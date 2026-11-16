"""Lifecycle, admission and task selection for Koto Addons."""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable, Mapping, Sequence

from app.core.agent.kernel import ToolCatalog, ToolSpec
from app.core.agent.plugin_protocol import (
    ContributionKind,
    KotoPlugin,
    PluginAdmissionController,
    PluginAdmissionPolicy,
    PluginHealthStatus,
    PluginHostContext,
    PluginProtocolError,
    RetrievalBatch,
    RetrievalRequest,
    RetrieverSpec,
)

from .contracts import AddonBinding, AddonExecutionPlan, AddonTaskRequest


@dataclass
class _AddonRecord:
    plugin: KotoPlugin
    bindings: tuple[AddonBinding, ...]
    tool_names: tuple[str, ...]
    retriever_specs: tuple[RetrieverSpec, ...]
    enabled: bool = True
    stopped: bool = False
    health_status: PluginHealthStatus = PluginHealthStatus.HEALTHY
    failure_count: int = 0
    last_error: str = ""


class AddonRuntime:
    """In-memory runtime of explicitly admitted Addons.

    Discovery and installation remain separate concerns.  This runtime only
    accepts already constructed plugin objects and never imports them by name.
    """

    def __init__(
        self, *, audit_sink: Callable[[Mapping[str, Any]], None] | None = None
    ):
        self._catalog = ToolCatalog()
        self._records: dict[str, _AddonRecord] = {}
        self._audit_sink = audit_sink or (lambda _event: None)
        self._lock = RLock()

    @property
    def catalog(self) -> ToolCatalog:
        return self._catalog

    def admit(
        self,
        plugin: KotoPlugin,
        *,
        host_context: PluginHostContext,
        policy: PluginAdmissionPolicy,
        bindings: Sequence[AddonBinding],
    ):
        manifest = plugin.manifest
        if host_context.plugin_id != manifest.plugin_id:
            raise PluginProtocolError("host context plugin_id differs from manifest")
        normalized_bindings = tuple(bindings)
        declared = {item.name for item in manifest.contributions}
        unknown = sorted(
            binding.contribution_name
            for binding in normalized_bindings
            if binding.contribution_name not in declared
        )
        if unknown:
            raise PluginProtocolError(
                "addon bindings reference undeclared contributions: "
                + ", ".join(unknown)
            )
        with self._lock:
            if manifest.plugin_id in self._records:
                raise PluginProtocolError(
                    f"addon '{manifest.plugin_id}' is already admitted"
                )
            try:
                plugin.initialize(host_context)
                health = plugin.health()
                if health.status is PluginHealthStatus.UNAVAILABLE:
                    raise PluginProtocolError(
                        f"addon '{manifest.plugin_id}' is unavailable: {health.message}"
                    )
                controller = PluginAdmissionController(
                    self._catalog,
                    policy,
                    audit_sink=self._audit_sink,
                )
                tool_specs = tuple(plugin.tool_specs())
                retriever_specs = tuple(plugin.retriever_specs())
                existing_retrievers = {
                    item.name
                    for record in self._records.values()
                    for item in record.retriever_specs
                }
                duplicate_retrievers = sorted(
                    existing_retrievers.intersection(
                        item.name for item in retriever_specs
                    )
                )
                if duplicate_retrievers:
                    raise PluginProtocolError(
                        "retriever name collision: " + ", ".join(duplicate_retrievers)
                    )
                admitted = controller.admit(
                    manifest,
                    tool_specs=tool_specs,
                    retriever_specs=retriever_specs,
                    config=host_context.config,
                )
                self._records[manifest.plugin_id] = _AddonRecord(
                    plugin=plugin,
                    bindings=normalized_bindings,
                    tool_names=admitted.report.tool_names,
                    retriever_specs=admitted.retriever_specs,
                    health_status=health.status,
                )
                return admitted.report
            except Exception:
                try:
                    plugin.shutdown()
                except Exception:
                    pass
                raise

    def set_enabled(self, addon_id: str, enabled: bool) -> None:
        with self._lock:
            record = self._records.get(str(addon_id))
            if record is None:
                raise KeyError(str(addon_id))
            if enabled and record.stopped:
                raise PluginProtocolError(
                    f"addon '{addon_id}' was shut down and must be admitted again"
                )
            record.enabled = bool(enabled)

    def shutdown(self, addon_id: str) -> None:
        with self._lock:
            record = self._records.get(str(addon_id))
            if record is None:
                raise KeyError(str(addon_id))
            if record.stopped:
                return
            record.enabled = False
            record.stopped = True
        record.plugin.shutdown()

    def plan(self, request: AddonTaskRequest) -> AddonExecutionPlan:
        candidates: list[tuple[int, str, str, ContributionKind, tuple[str, ...]]] = []
        rejected: dict[str, str] = {}
        text = request.user_input.casefold()
        required_caps = set(request.required_capabilities)
        request_files = set(request.file_types)

        with self._lock:
            records = list(self._records.items())
        for addon_id, record in records:
            if not record.enabled:
                rejected[addon_id] = "disabled"
                continue
            if record.health_status is PluginHealthStatus.UNAVAILABLE:
                rejected[addon_id] = "unavailable"
                continue
            manifest = record.plugin.manifest
            if request.data_classification not in manifest.data_policy.accepts:
                rejected[addon_id] = "data_classification_not_accepted"
                continue
            contribution_map = {item.name: item for item in manifest.contributions}
            for binding in record.bindings:
                contribution = contribution_map[binding.contribution_name]
                if binding.task_types and request.task_type not in binding.task_types:
                    continue
                if binding.file_types and not (set(binding.file_types) & request_files):
                    continue
                matched_patterns = sum(
                    pattern in text for pattern in binding.intent_patterns
                )
                if binding.intent_patterns and not matched_patterns:
                    continue
                capabilities = set(contribution.capabilities)
                if required_caps and not required_caps.issubset(capabilities):
                    continue
                if request.read_only is True and not contribution.read_only:
                    continue
                score = (
                    binding.priority * 100
                    + matched_patterns * 10
                    + len(required_caps & capabilities)
                )
                candidates.append(
                    (
                        score,
                        addon_id,
                        contribution.name,
                        contribution.kind,
                        tuple(contribution.capabilities),
                    )
                )

        candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
        selected = []
        selected_keys: set[tuple[str, str]] = set()
        for item in candidates:
            key = (item[1], item[2])
            if key in selected_keys:
                continue
            selected.append(item)
            selected_keys.add(key)
            if len(selected) >= request.max_contributions:
                break
        return AddonExecutionPlan(
            task_type=request.task_type,
            data_classification=request.data_classification,
            addon_ids=tuple(dict.fromkeys(item[1] for item in selected)),
            tool_names=tuple(
                item[2] for item in selected if item[3] is ContributionKind.TOOL
            ),
            retriever_names=tuple(
                item[2] for item in selected if item[3] is ContributionKind.RETRIEVER
            ),
            capabilities=tuple(
                dict.fromkeys(cap for item in selected for cap in item[4])
            ),
            matched_bindings=tuple(f"{item[1]}:{item[2]}" for item in selected),
            rejected=rejected,
        )

    def tool_specs(self, names: Sequence[str] | None = None) -> tuple[ToolSpec, ...]:
        with self._lock:
            active_names = {
                name
                for record in self._records.values()
                if record.enabled and not record.stopped
                for name in record.tool_names
            }
        selected = set(names) if names is not None else active_names
        selected &= active_names
        return tuple(
            spec
            for name in self._catalog.names()
            if name in selected and (spec := self._catalog.get(name)) is not None
        )

    def retriever_specs(
        self, names: Sequence[str] | None = None
    ) -> tuple[RetrieverSpec, ...]:
        selected = set(names) if names is not None else None
        with self._lock:
            specs = [
                spec
                for record in self._records.values()
                if record.enabled and not record.stopped
                for spec in record.retriever_specs
            ]
        return tuple(
            spec for spec in specs if selected is None or spec.name in selected
        )

    def retrieve(
        self,
        plan: AddonExecutionPlan,
        *,
        query: str,
        tenant_id: str,
        principal_id: str,
        correlation_id: str,
        top_k: int = 8,
        filters: Mapping[str, Any] | None = None,
    ) -> tuple[RetrievalBatch, ...]:
        """Execute only retrievers selected in an Add-on plan.

        Tenant and principal identity are mandatory.  The chat layer must not
        invent these values from user text, so identity-aware bootstrap code
        owns the call to this method.
        """

        if not str(tenant_id or "").strip() or not str(principal_id or "").strip():
            raise PluginProtocolError(
                "addon retrieval requires tenant_id and principal_id"
            )
        request = RetrievalRequest(
            query=query,
            top_k=top_k,
            tenant_id=tenant_id,
            principal_id=principal_id,
            filters=dict(filters or {}),
            correlation_id=correlation_id,
        )
        specs = {item.name: item for item in self.retriever_specs(plan.retriever_names)}
        batches: list[RetrievalBatch] = []
        for name in plan.retriever_names:
            spec = specs.get(name)
            if spec is not None:
                executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix=f"koto-addon-retriever-{name[:24]}",
                )
                future = executor.submit(spec.handler, request)
                timed_out = False
                try:
                    batch = future.result(timeout=float(spec.timeout_seconds))
                except concurrent.futures.TimeoutError as exc:
                    timed_out = True
                    future.cancel()
                    self._record_retriever_failure(name, "timeout")
                    raise PluginProtocolError(
                        f"retriever '{name}' timed out after "
                        f"{float(spec.timeout_seconds):g}s"
                    ) from exc
                except Exception as exc:
                    self._record_retriever_failure(name, str(exc))
                    raise
                finally:
                    # Retriever contributions are required to be read-only.
                    # A late in-process result can be discarded, while the
                    # admission guard retains its capacity until it really
                    # exits and prevents timeout storms from growing forever.
                    executor.shutdown(
                        wait=not timed_out,
                        cancel_futures=timed_out,
                    )
                if not isinstance(batch, RetrievalBatch):
                    self._record_retriever_failure(name, "invalid_batch")
                    raise PluginProtocolError(
                        f"retriever '{name}' returned an invalid batch"
                    )
                self._record_retriever_success(name)
                batches.append(batch)
        return tuple(batches)

    def _record_retriever_failure(self, name: str, error: str) -> None:
        with self._lock:
            for record in self._records.values():
                if any(spec.name == name for spec in record.retriever_specs):
                    record.failure_count += 1
                    record.last_error = str(error or "")[:500]
                    record.health_status = PluginHealthStatus.DEGRADED
                    return

    def _record_retriever_success(self, name: str) -> None:
        with self._lock:
            for record in self._records.values():
                if any(spec.name == name for spec in record.retriever_specs):
                    record.failure_count = 0
                    record.last_error = ""
                    record.health_status = PluginHealthStatus.HEALTHY
                    return

    def catalog_snapshot(self) -> dict[str, Any]:
        with self._lock:
            records = list(self._records.items())
        addons = []
        for addon_id, record in records:
            manifest = record.plugin.manifest
            addons.append(
                {
                    "addon_id": addon_id,
                    "name": manifest.name,
                    "version": manifest.version,
                    "publisher": manifest.publisher,
                    "enabled": record.enabled,
                    "stopped": record.stopped,
                    "health": record.health_status.value,
                    "failure_count": record.failure_count,
                    "last_error": record.last_error,
                    "plugin_id": addon_id,
                    "tools": list(record.tool_names),
                    "retrievers": [item.name for item in record.retriever_specs],
                    "bindings": [
                        {
                            "contribution_name": item.contribution_name,
                            "task_types": list(item.task_types),
                            "intent_patterns": list(item.intent_patterns),
                            "file_types": list(item.file_types),
                            "priority": item.priority,
                        }
                        for item in record.bindings
                    ],
                }
            )
        return {"addons": addons, "total": len(addons)}


_runtime: AddonRuntime | None = None
_runtime_revision = -1
_runtime_lock = RLock()


def get_addon_runtime(*, sync: bool = True) -> AddonRuntime:
    """Return the runtime, refreshing when another worker changed the store."""
    global _runtime
    if sync:
        from .store import get_addon_store

        persisted_revision = get_addon_store().revision()
        with _runtime_lock:
            stale = _runtime is None or _runtime_revision != persisted_revision
        if stale:
            # Lazy import avoids a bootstrap/runtime import cycle.  The
            # bootstrap lock coalesces concurrent refreshes in one worker.
            from .bootstrap import refresh_addon_runtime

            refresh_addon_runtime()
    with _runtime_lock:
        if _runtime is None:
            _runtime = AddonRuntime()
        return _runtime


def set_addon_runtime(
    runtime: AddonRuntime | None,
    *,
    revision: int | None = None,
) -> None:
    """Explicit composition seam used by bootstrap code and tests."""

    global _runtime, _runtime_revision
    if runtime is not None and revision is None:
        try:
            from .store import get_addon_store

            revision = get_addon_store().revision()
        except Exception:
            revision = -1
    with _runtime_lock:
        _runtime = runtime
        _runtime_revision = -1 if revision is None else int(revision)


__all__ = ["AddonRuntime", "get_addon_runtime", "set_addon_runtime"]
