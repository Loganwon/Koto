"""Lifecycle surface exposed to admitted plugins by the Koto host."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

from app.core.agent.kernel import ToolSpec

from .contracts import (
    DataClassification,
    PluginManifestV1,
    PluginPermission,
    PluginProtocolError,
)
from .retrieval import RetrieverSpec


class PluginHealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class PluginHealth:
    status: PluginHealthStatus
    message: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", PluginHealthStatus(self.status))
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


@dataclass(frozen=True)
class AddonInvocationContext:
    """Trusted per-call context injected by the host, never by the model."""

    request_id: str = ""
    task_id: str = ""
    session_id: str = ""
    tenant_id: str = ""
    principal_id: str = ""
    role_ids: tuple[str, ...] = ()
    organization_scope: tuple[str, ...] = ()
    purpose_code: str = ""
    data_classification: DataClassification = DataClassification.INTERNAL
    correlation_id: str = ""
    requested_at: str = ""

    def __post_init__(self) -> None:
        for name in (
            "request_id",
            "task_id",
            "session_id",
            "tenant_id",
            "principal_id",
            "purpose_code",
            "correlation_id",
            "requested_at",
        ):
            object.__setattr__(self, name, str(getattr(self, name) or "").strip())
        object.__setattr__(
            self,
            "role_ids",
            tuple(
                dict.fromkeys(
                    str(item).strip() for item in self.role_ids if str(item).strip()
                )
            ),
        )
        object.__setattr__(
            self,
            "organization_scope",
            tuple(
                dict.fromkeys(
                    str(item).strip()
                    for item in self.organization_scope
                    if str(item).strip()
                )
            ),
        )
        object.__setattr__(
            self, "data_classification", DataClassification(self.data_classification)
        )

    def require_identity(self) -> None:
        if (
            not str(self.tenant_id or "").strip()
            or not str(self.principal_id or "").strip()
        ):
            raise PluginProtocolError(
                "trusted Addon invocation requires tenant_id and principal_id"
            )
        if not str(self.purpose_code or "").strip():
            raise PluginProtocolError("trusted Addon invocation requires purpose_code")


@dataclass(frozen=True)
class PluginHostContext:
    """Narrow host surface; never exposes Flask or the global service locator."""

    plugin_id: str
    granted_permissions: frozenset[PluginPermission]
    config: Mapping[str, Any]
    declared_secret_names: frozenset[str]
    secret_resolver: Callable[[str], str] = field(repr=False, compare=False)
    emit_audit: Callable[[Mapping[str, Any]], None]

    def __post_init__(self) -> None:
        if not str(self.plugin_id or "").strip():
            raise PluginProtocolError("plugin host context requires plugin_id")
        object.__setattr__(self, "config", MappingProxyType(dict(self.config)))
        object.__setattr__(
            self,
            "granted_permissions",
            frozenset(PluginPermission(item) for item in self.granted_permissions),
        )
        object.__setattr__(
            self,
            "declared_secret_names",
            frozenset(str(item) for item in self.declared_secret_names),
        )
        if self.declared_secret_names and (
            PluginPermission.SECRETS_USE not in self.granted_permissions
        ):
            raise PluginProtocolError(
                "declared secret bindings require secrets.use permission"
            )
        if not callable(self.secret_resolver) or not callable(self.emit_audit):
            raise PluginProtocolError(
                "plugin host secret_resolver and emit_audit must be callable"
            )

    def get_secret(self, name: str) -> str:
        """Resolve only a manifest-declared binding; never enumerate the store."""

        normalized = str(name or "").strip()
        if normalized not in self.declared_secret_names:
            raise PluginProtocolError(f"secret binding is not declared: {normalized}")
        return self.secret_resolver(normalized)


@runtime_checkable
class KotoPlugin(Protocol):
    """Host-owned lifecycle contract; plugins do not own an Agent loop."""

    @property
    def manifest(self) -> PluginManifestV1: ...

    def tool_specs(self) -> Sequence[ToolSpec]: ...

    def retriever_specs(self) -> Sequence[RetrieverSpec]: ...

    def initialize(self, context: PluginHostContext) -> None: ...

    def health(self) -> PluginHealth: ...

    def shutdown(self) -> None: ...


__all__ = [
    "AddonInvocationContext",
    "KotoPlugin",
    "PluginHealth",
    "PluginHealthStatus",
    "PluginHostContext",
]
