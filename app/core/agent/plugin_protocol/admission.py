"""Fail-closed admission gate for future Koto plugins."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence, Tuple

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from app.core.agent.kernel import (
    TRUSTED_CONTEXT_ARGUMENT,
    ToolCatalog,
    ToolRegistrationError,
    ToolSpec,
)

from .contracts import (
    ContributionKind,
    DataClassification,
    PluginContribution,
    PluginManifestV1,
    PluginPermission,
    PluginProtocolError,
    PluginTransport,
)
from .retrieval import (
    RETRIEVAL_BATCH_JSON_SCHEMA,
    RETRIEVAL_REQUEST_JSON_SCHEMA,
    RetrievalBatch,
    RetrievalRequest,
    RetrieverSpec,
)
from .schema import manifest_digest

_MUTATION_PERMISSIONS = frozenset(
    {
        PluginPermission.WORKSPACE_WRITE,
        PluginPermission.DATABASE_WRITE,
        PluginPermission.NETWORK_EGRESS,
        PluginPermission.PROCESS_EXECUTE,
        PluginPermission.USER_NOTIFY,
    }
)
_RETRIEVAL_PERMISSIONS = frozenset(
    {
        PluginPermission.WORKSPACE_READ,
        PluginPermission.DATABASE_READ,
        PluginPermission.NETWORK_EGRESS,
    }
)


class _ContributionGuard:
    """Per-contribution concurrency budget and local circuit breaker."""

    def __init__(self, capacity: int, *, failure_threshold: int = 3) -> None:
        self._semaphore = threading.BoundedSemaphore(max(1, int(capacity)))
        self._lock = threading.Lock()
        self._failures = 0
        self._open_until = 0.0
        self._failure_threshold = max(1, int(failure_threshold))

    def enter(self, timeout: float) -> None:
        with self._lock:
            if time.monotonic() < self._open_until:
                raise PluginProtocolError("contribution circuit breaker is open")
        if not self._semaphore.acquire(timeout=max(0.001, float(timeout))):
            raise PluginProtocolError("contribution concurrency limit exceeded")

    def leave(self) -> None:
        self._semaphore.release()

    def succeeded(self) -> None:
        with self._lock:
            self._failures = 0
            self._open_until = 0.0

    def failed(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._failure_threshold:
                self._open_until = time.monotonic() + 30.0


def _semver_key(version: str) -> tuple[Any, ...]:
    without_build = str(version).split("+", 1)[0]
    main, _, prerelease = without_build.partition("-")
    major, minor, patch = (int(item) for item in main.split("."))
    # A release has higher precedence than a prerelease with the same core.
    prerelease_key = tuple(
        (0, int(item)) if item.isdigit() else (1, item)
        for item in prerelease.split(".")
        if item
    )
    return major, minor, patch, 1 if not prerelease else 0, prerelease_key


@dataclass(frozen=True)
class PluginAdmissionPolicy:
    granted_permissions: frozenset[PluginPermission] = frozenset()
    allowed_transports: frozenset[PluginTransport] = frozenset(
        {PluginTransport.IN_PROCESS}
    )
    available_plugins: Mapping[str, str] = field(default_factory=dict)
    available_secret_names: frozenset[str] = frozenset()
    max_timeout_seconds: float = 120.0
    max_result_bytes: int = 5_000_000
    max_concurrency: int = 8
    max_rag_chunks: int = 30
    allow_external_restricted_data: bool = False
    allow_tool_replacement: bool = False
    require_audit_sink: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "granted_permissions",
            frozenset(PluginPermission(item) for item in self.granted_permissions),
        )
        object.__setattr__(
            self,
            "allowed_transports",
            frozenset(PluginTransport(item) for item in self.allowed_transports),
        )
        object.__setattr__(self, "available_plugins", dict(self.available_plugins))
        object.__setattr__(
            self,
            "available_secret_names",
            frozenset(str(item) for item in self.available_secret_names),
        )
        if not self.allowed_transports:
            raise PluginProtocolError("host policy must allow at least one transport")
        if float(self.max_timeout_seconds) <= 0:
            raise PluginProtocolError("host max_timeout_seconds must be positive")
        if int(self.max_result_bytes) < 1024:
            raise PluginProtocolError("host max_result_bytes must be at least 1 KiB")
        if int(self.max_concurrency) < 1 or int(self.max_rag_chunks) < 1:
            raise PluginProtocolError(
                "host concurrency and RAG limits must be positive"
            )
        for plugin_id, version in self.available_plugins.items():
            try:
                _semver_key(version)
            except (TypeError, ValueError) as exc:
                raise PluginProtocolError(
                    f"available plugin '{plugin_id}' has invalid semantic version"
                ) from exc


@dataclass(frozen=True)
class PluginAdmissionReport:
    plugin_id: str
    accepted: bool
    manifest_sha256: str
    errors: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()
    tool_names: Tuple[str, ...] = ()
    retriever_names: Tuple[str, ...] = ()

    def require_accepted(self) -> None:
        if not self.accepted:
            raise PluginProtocolError(
                f"plugin '{self.plugin_id}' was rejected: " + "; ".join(self.errors)
            )


@dataclass(frozen=True)
class AdmittedPluginContributions:
    report: PluginAdmissionReport
    retriever_specs: Tuple[RetrieverSpec, ...] = ()


class PluginAdmissionController:
    """Validates a plugin package before any contribution becomes visible."""

    def __init__(
        self,
        catalog: ToolCatalog,
        policy: PluginAdmissionPolicy,
        *,
        audit_sink: Callable[[Mapping[str, Any]], None] | None = None,
    ):
        self._catalog = catalog
        self._policy = policy
        if audit_sink is not None and not callable(audit_sink):
            raise PluginProtocolError("audit_sink must be callable")
        self._audit_sink = audit_sink
        self._guards: dict[str, _ContributionGuard] = {}

    def _guard_for(
        self, manifest: PluginManifestV1, contribution_name: str
    ) -> _ContributionGuard:
        guard = self._guards.get(contribution_name)
        if guard is None:
            capacity = min(
                int(manifest.limits.max_concurrency),
                int(self._policy.max_concurrency),
            )
            guard = _ContributionGuard(capacity)
            self._guards[contribution_name] = guard
        return guard

    def evaluate(
        self,
        manifest: PluginManifestV1,
        *,
        tool_specs: Sequence[ToolSpec] = (),
        retriever_specs: Sequence[RetrieverSpec] = (),
        config: Mapping[str, Any] | None = None,
    ) -> PluginAdmissionReport:
        errors: list[str] = []
        warnings: list[str] = []
        tools = tuple(tool_specs)
        retrievers = tuple(retriever_specs)

        if self._policy.require_audit_sink and self._audit_sink is None:
            errors.append("host policy requires an audit sink")
        if manifest.runtime.transport not in self._policy.allowed_transports:
            errors.append(
                f"transport '{manifest.runtime.transport.value}' is not allowed by host policy"
            )
        missing_permissions = sorted(
            permission.value
            for permission in manifest.permissions
            if permission not in self._policy.granted_permissions
        )
        if missing_permissions:
            errors.append("permissions not granted: " + ", ".join(missing_permissions))
        missing_secrets = sorted(
            name
            for name in manifest.secret_names
            if name not in self._policy.available_secret_names
        )
        if missing_secrets:
            errors.append("secret bindings unavailable: " + ", ".join(missing_secrets))
        if manifest.runtime.transport is PluginTransport.HTTP and (
            PluginPermission.NETWORK_EGRESS not in manifest.permissions
        ):
            errors.append("HTTP transport requires network.egress permission")
        if (
            PluginPermission.DATABASE_READ in manifest.permissions
            or PluginPermission.DATABASE_WRITE in manifest.permissions
        ) and not manifest.data_policy.tenant_isolation:
            errors.append("database plugins must declare tenant_isolation=true")
        if (
            manifest.data_policy.sends_data_external
            and DataClassification.RESTRICTED in manifest.data_policy.accepts
            and not self._policy.allow_external_restricted_data
        ):
            errors.append("host policy forbids sending restricted data externally")

        self._check_limits(manifest, errors)
        self._check_dependencies(manifest, errors, warnings)
        try:
            Draft202012Validator(manifest.config_schema).validate(dict(config or {}))
        except ValidationError as exc:
            errors.append(f"plugin config does not match config_schema: {exc.message}")

        contributions = {item.name: item for item in manifest.contributions}
        declared_tools = {
            item.name: item
            for item in manifest.contributions
            if item.kind is ContributionKind.TOOL
        }
        declared_retrievers = {
            item.name: item
            for item in manifest.contributions
            if item.kind is ContributionKind.RETRIEVER
        }
        actual_tools = {item.name: item for item in tools}
        actual_retrievers = {item.name: item for item in retrievers}
        if len(actual_tools) != len(tools):
            errors.append("tool_specs contain duplicate names")
        if len(actual_retrievers) != len(retrievers):
            errors.append("retriever_specs contain duplicate names")
        self._check_exact_names("tools", declared_tools, actual_tools, errors)
        self._check_exact_names(
            "retrievers", declared_retrievers, actual_retrievers, errors
        )

        for name, spec in actual_tools.items():
            contribution = contributions.get(name)
            if contribution is not None:
                self._check_tool(manifest, contribution, spec, errors)
            if name in self._catalog and not self._policy.allow_tool_replacement:
                errors.append(f"tool name collision: {name}")
        for name, spec in actual_retrievers.items():
            contribution = contributions.get(name)
            if contribution is not None:
                self._check_retriever(manifest, contribution, spec, errors)

        return PluginAdmissionReport(
            plugin_id=manifest.plugin_id,
            accepted=not errors,
            manifest_sha256=manifest_digest(manifest),
            errors=tuple(dict.fromkeys(errors)),
            warnings=tuple(dict.fromkeys(warnings)),
            tool_names=tuple(actual_tools),
            retriever_names=tuple(actual_retrievers),
        )

    def register_tools(
        self,
        manifest: PluginManifestV1,
        *,
        tool_specs: Sequence[ToolSpec],
        config: Mapping[str, Any] | None = None,
    ) -> PluginAdmissionReport:
        return self.admit(
            manifest,
            tool_specs=tool_specs,
            config=config,
        ).report

    def admit(
        self,
        manifest: PluginManifestV1,
        *,
        tool_specs: Sequence[ToolSpec] = (),
        retriever_specs: Sequence[RetrieverSpec] = (),
        config: Mapping[str, Any] | None = None,
    ) -> AdmittedPluginContributions:
        report = self.evaluate(
            manifest,
            tool_specs=tool_specs,
            retriever_specs=retriever_specs,
            config=config,
        )
        report.require_accepted()
        contributions = {item.name: item for item in manifest.contributions}
        wrapped = [
            self._wrap_tool(manifest, contributions[spec.name], spec)
            for spec in tool_specs
        ]
        wrapped_retrievers = tuple(
            self._wrap_retriever(manifest, spec) for spec in retriever_specs
        )
        try:
            if wrapped:
                self._catalog.register_many(
                    wrapped, replace=self._policy.allow_tool_replacement
                )
        except ToolRegistrationError as exc:
            raise PluginProtocolError(
                f"plugin '{manifest.plugin_id}' registration failed atomically: {exc}"
            ) from exc
        return AdmittedPluginContributions(
            report=report,
            retriever_specs=wrapped_retrievers,
        )

    def _wrap_retriever(
        self,
        manifest: PluginManifestV1,
        spec: RetrieverSpec,
    ) -> RetrieverSpec:
        contribution = next(
            (
                item
                for item in manifest.contributions
                if item.kind is ContributionKind.RETRIEVER and item.name == spec.name
            ),
            None,
        )
        if contribution is None:
            raise PluginProtocolError(f"undeclared retriever: {spec.name}")

        def handler(request: RetrievalRequest) -> RetrievalBatch:
            self._emit_audit(
                manifest,
                contribution,
                "plugin.retriever.started",
                correlation_id=request.correlation_id,
            )
            guard = self._guard_for(manifest, contribution.name)
            timeout = float(spec.timeout_seconds or manifest.limits.max_timeout_seconds)
            guard.enter(timeout)
            try:
                if request.top_k > manifest.limits.max_rag_chunks:
                    raise PluginProtocolError(
                        "retrieval top_k exceeds plugin limit "
                        f"{manifest.limits.max_rag_chunks}"
                    )
                if manifest.data_policy.tenant_isolation and (
                    not request.tenant_id or not request.principal_id
                ):
                    raise PluginProtocolError(
                        "tenant-isolated retrieval requires tenant_id and principal_id"
                    )
                batch = spec.handler(request)
                if not isinstance(batch, RetrievalBatch):
                    raise PluginProtocolError("retriever must return RetrievalBatch")
                if batch.provider_id != spec.name:
                    raise PluginProtocolError(
                        "retrieval provider_id must match retriever name"
                    )
                if (
                    request.correlation_id
                    and batch.correlation_id != request.correlation_id
                ):
                    raise PluginProtocolError(
                        "retrieval correlation_id was not preserved"
                    )
                if len(batch.chunks) > manifest.limits.max_rag_chunks:
                    raise PluginProtocolError(
                        "retriever returned too many evidence chunks"
                    )
                sensitive = {
                    DataClassification.CONFIDENTIAL,
                    DataClassification.RESTRICTED,
                }.intersection(manifest.data_policy.accepts)
                if sensitive and any(not chunk.acl_tags for chunk in batch.chunks):
                    raise PluginProtocolError(
                        "sensitive evidence chunks require non-empty acl_tags"
                    )
            except Exception as exc:
                guard.failed()
                self._emit_audit(
                    manifest,
                    contribution,
                    "plugin.retriever.failed",
                    correlation_id=request.correlation_id,
                    error_type=type(exc).__name__,
                )
                raise
            finally:
                guard.leave()
            guard.succeeded()
            self._emit_audit(
                manifest,
                contribution,
                "plugin.retriever.succeeded",
                correlation_id=request.correlation_id,
                result_items=len(batch.chunks),
            )
            return batch

        return RetrieverSpec(
            name=spec.name,
            description=spec.description,
            handler=handler,
            source=spec.source,
            version=spec.version,
            capabilities=spec.capabilities,
            timeout_seconds=spec.timeout_seconds,
        )

    def _check_limits(self, manifest: PluginManifestV1, errors: list[str]) -> None:
        pairs = (
            (
                "max_timeout_seconds",
                manifest.limits.max_timeout_seconds,
                self._policy.max_timeout_seconds,
            ),
            (
                "max_result_bytes",
                manifest.limits.max_result_bytes,
                self._policy.max_result_bytes,
            ),
            (
                "max_concurrency",
                manifest.limits.max_concurrency,
                self._policy.max_concurrency,
            ),
            (
                "max_rag_chunks",
                manifest.limits.max_rag_chunks,
                self._policy.max_rag_chunks,
            ),
        )
        for name, requested, allowed in pairs:
            if requested > allowed:
                errors.append(f"{name} requests {requested}; host allows {allowed}")

    def _check_dependencies(
        self,
        manifest: PluginManifestV1,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        for dependency in manifest.dependencies:
            installed = self._policy.available_plugins.get(dependency.plugin_id)
            if not installed:
                message = f"dependency '{dependency.plugin_id}' is not available"
                (warnings if dependency.optional else errors).append(message)
                continue
            current = _semver_key(installed)
            if dependency.min_version and current < _semver_key(dependency.min_version):
                errors.append(
                    f"dependency '{dependency.plugin_id}' is below {dependency.min_version}"
                )
            if dependency.max_version and current > _semver_key(dependency.max_version):
                errors.append(
                    f"dependency '{dependency.plugin_id}' is above {dependency.max_version}"
                )

    @staticmethod
    def _check_exact_names(
        label: str,
        declared: Mapping[str, Any],
        actual: Mapping[str, Any],
        errors: list[str],
    ) -> None:
        missing = sorted(set(declared) - set(actual))
        undeclared = sorted(set(actual) - set(declared))
        if missing:
            errors.append(f"declared {label} not supplied: {', '.join(missing)}")
        if undeclared:
            errors.append(f"undeclared {label} supplied: {', '.join(undeclared)}")

    @staticmethod
    def _check_tool(
        manifest: PluginManifestV1,
        contribution: PluginContribution,
        spec: ToolSpec,
        errors: list[str],
    ) -> None:
        expected_source = f"plugin:{manifest.plugin_id}"
        if spec.source != expected_source:
            errors.append(f"tool '{spec.name}' source must be '{expected_source}'")
        if spec.version != manifest.version:
            errors.append(f"tool '{spec.name}' version must match plugin version")
        if dict(spec.input_schema) != dict(contribution.input_schema):
            errors.append(f"tool '{spec.name}' input schema differs from manifest")
        if tuple(spec.capabilities) != tuple(contribution.capabilities):
            errors.append(f"tool '{spec.name}' capabilities differ from manifest")
        if spec.read_only is not contribution.read_only:
            errors.append(f"tool '{spec.name}' read_only differs from manifest")
        database_permissions = {
            PluginPermission.DATABASE_READ,
            PluginPermission.DATABASE_WRITE,
        }.intersection(contribution.permissions)
        if database_permissions and not spec.requires_invocation_context:
            errors.append(
                f"database tool '{spec.name}' requires trusted invocation context"
            )
        timeout = spec.timeout_seconds or manifest.limits.max_timeout_seconds
        if float(timeout) > float(manifest.limits.max_timeout_seconds):
            errors.append(f"tool '{spec.name}' timeout exceeds manifest limit")
        if not contribution.read_only and not (
            set(contribution.permissions) & _MUTATION_PERMISSIONS
        ):
            errors.append(f"mutating tool '{spec.name}' lacks a mutation permission")
        if not contribution.read_only:
            properties = contribution.input_schema.get("properties") or {}
            required = set(contribution.input_schema.get("required") or ())
            key_schema = (
                properties.get("idempotency_key")
                if isinstance(properties, Mapping)
                else None
            )
            if not isinstance(key_schema, Mapping) or "idempotency_key" not in required:
                errors.append(
                    f"mutating tool '{spec.name}' must require idempotency_key"
                )

    @staticmethod
    def _check_retriever(
        manifest: PluginManifestV1,
        contribution: PluginContribution,
        spec: RetrieverSpec,
        errors: list[str],
    ) -> None:
        expected_source = f"plugin:{manifest.plugin_id}"
        if spec.source != expected_source:
            errors.append(f"retriever '{spec.name}' source must be '{expected_source}'")
        if spec.version != manifest.version:
            errors.append(f"retriever '{spec.name}' version must match plugin version")
        if tuple(spec.capabilities) != tuple(contribution.capabilities):
            errors.append(f"retriever '{spec.name}' capabilities differ from manifest")
        if dict(contribution.input_schema) != dict(RETRIEVAL_REQUEST_JSON_SCHEMA):
            errors.append(
                f"retriever '{spec.name}' must use the canonical retrieval input schema"
            )
        if dict(contribution.output_schema) != dict(RETRIEVAL_BATCH_JSON_SCHEMA):
            errors.append(
                f"retriever '{spec.name}' must use the canonical evidence batch schema"
            )
        if not (set(contribution.permissions) & _RETRIEVAL_PERMISSIONS):
            errors.append(f"retriever '{spec.name}' lacks a read permission")

    def _wrap_tool(
        self,
        manifest: PluginManifestV1,
        contribution: PluginContribution,
        spec: ToolSpec,
    ) -> ToolSpec:
        validator = Draft202012Validator(contribution.output_schema)

        def identity_details(context: Any) -> dict[str, str]:
            if context is None:
                return {}
            return {
                "tenant_id": str(getattr(context, "tenant_id", "") or ""),
                "principal_id": str(getattr(context, "principal_id", "") or ""),
                "purpose_code": str(getattr(context, "purpose_code", "") or ""),
                "request_id": str(getattr(context, "request_id", "") or ""),
                "task_id": str(getattr(context, "task_id", "") or ""),
            }

        def policy_denied(reason: str, invocation_context: Any) -> None:
            self._emit_audit(
                manifest,
                contribution,
                "plugin.tool.denied",
                correlation_id=str(
                    getattr(invocation_context, "correlation_id", "") or ""
                ),
                reason=str(reason or "policy_denied"),
                **identity_details(invocation_context),
            )

        def handler(**kwargs: Any) -> Any:
            invocation_context = kwargs.pop(TRUSTED_CONTEXT_ARGUMENT, None)
            if spec.requires_invocation_context:
                require_identity = getattr(invocation_context, "require_identity", None)
                if not callable(require_identity):
                    raise PluginProtocolError(
                        f"plugin tool '{spec.name}' requires trusted host identity"
                    )
                require_identity()
            try:
                input_bytes = len(
                    json.dumps(
                        kwargs, ensure_ascii=False, separators=(",", ":")
                    ).encode("utf-8")
                )
            except (TypeError, ValueError):
                input_bytes = -1
            correlation_id = str(
                getattr(invocation_context, "correlation_id", "") or ""
            )
            identity_audit = identity_details(invocation_context)
            self._emit_audit(
                manifest,
                contribution,
                "plugin.tool.started",
                correlation_id=correlation_id,
                input_bytes=input_bytes,
                **identity_audit,
            )
            guard = self._guard_for(manifest, contribution.name)
            timeout = float(spec.timeout_seconds or manifest.limits.max_timeout_seconds)
            guard.enter(timeout)
            try:
                if spec.requires_invocation_context:
                    value = spec.handler(
                        **{
                            TRUSTED_CONTEXT_ARGUMENT: invocation_context,
                            **kwargs,
                        }
                    )
                else:
                    value = spec.handler(**kwargs)
                validator.validate(value)
                encoded = json.dumps(
                    value, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
                if len(encoded) > manifest.limits.max_result_bytes:
                    raise PluginProtocolError(
                        f"plugin tool '{spec.name}' output exceeds "
                        f"{manifest.limits.max_result_bytes} bytes"
                    )
            except ValidationError as exc:
                guard.failed()
                error = PluginProtocolError(
                    f"plugin tool '{spec.name}' returned invalid output: {exc.message}"
                )
                self._emit_audit(
                    manifest,
                    contribution,
                    "plugin.tool.failed",
                    correlation_id=correlation_id,
                    error_type=type(error).__name__,
                    **identity_audit,
                )
                raise error from exc
            except PluginProtocolError as exc:
                guard.failed()
                self._emit_audit(
                    manifest,
                    contribution,
                    "plugin.tool.failed",
                    correlation_id=correlation_id,
                    error_type=type(exc).__name__,
                    **identity_audit,
                )
                raise
            except (TypeError, ValueError) as exc:
                guard.failed()
                error = PluginProtocolError(
                    f"plugin tool '{spec.name}' output must be JSON serializable"
                )
                self._emit_audit(
                    manifest,
                    contribution,
                    "plugin.tool.failed",
                    correlation_id=correlation_id,
                    error_type=type(error).__name__,
                    **identity_audit,
                )
                raise error from exc
            except Exception as exc:
                guard.failed()
                self._emit_audit(
                    manifest,
                    contribution,
                    "plugin.tool.failed",
                    correlation_id=correlation_id,
                    error_type=type(exc).__name__,
                    **identity_audit,
                )
                raise
            finally:
                guard.leave()
            guard.succeeded()
            self._emit_audit(
                manifest,
                contribution,
                "plugin.tool.succeeded",
                correlation_id=correlation_id,
                output_bytes=len(encoded),
                **identity_audit,
            )
            return value

        return ToolSpec(
            name=spec.name,
            description=spec.description,
            input_schema=spec.input_schema,
            handler=handler,
            source=spec.source,
            version=spec.version,
            capabilities=spec.capabilities,
            read_only=spec.read_only,
            timeout_seconds=spec.timeout_seconds,
            requires_invocation_context=spec.requires_invocation_context,
            policy_denied_handler=policy_denied,
        )

    def _emit_audit(
        self,
        manifest: PluginManifestV1,
        contribution: PluginContribution,
        event: str,
        **details: Any,
    ) -> None:
        if self._audit_sink is None:
            return
        payload = {
            "event": event,
            "plugin_id": manifest.plugin_id,
            "plugin_version": manifest.version,
            "manifest_sha256": manifest_digest(manifest),
            "contribution": contribution.name,
            "permissions": [item.value for item in contribution.permissions],
            **details,
        }
        self._audit_sink(payload)


__all__ = [
    "AdmittedPluginContributions",
    "PluginAdmissionController",
    "PluginAdmissionPolicy",
    "PluginAdmissionReport",
]
