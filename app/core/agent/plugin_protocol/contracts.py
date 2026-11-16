"""Versioned, transport-neutral contracts for Koto plugin admission.

This package defines how a plugin may contribute capabilities to the Agent
Kernel.  It deliberately does not discover, install, import, or implement any
business plugin.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Tuple
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from app.core.agent.kernel import KERNEL_API_VERSION, PluginManifest

PLUGIN_PROTOCOL_VERSION = "1.0"

_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_ENTRYPOINT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_.]*$")


class PluginProtocolError(ValueError):
    """Raised when a plugin package violates the public admission protocol."""


class PluginTransport(str, Enum):
    IN_PROCESS = "in_process"
    HTTP = "http"
    MCP = "mcp"


class ContributionKind(str, Enum):
    TOOL = "tool"
    RETRIEVER = "retriever"


class PluginPermission(str, Enum):
    WORKSPACE_READ = "workspace.read"
    WORKSPACE_WRITE = "workspace.write"
    NETWORK_EGRESS = "network.egress"
    DATABASE_READ = "database.read"
    DATABASE_WRITE = "database.write"
    MODEL_INVOKE = "model.invoke"
    PROCESS_EXECUTE = "process.execute"
    SECRETS_USE = "secrets.use"
    USER_NOTIFY = "user.notify"


class DataClassification(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class PersistenceMode(str, Enum):
    NONE = "none"
    SESSION = "session"
    DURABLE = "durable"


def _unique_text(values: Any) -> Tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(value).strip() for value in (values or ()) if str(value).strip()
        )
    )


def _validate_schema(schema: Mapping[str, Any], *, label: str) -> Mapping[str, Any]:
    if not isinstance(schema, Mapping):
        raise PluginProtocolError(f"{label} must be a JSON Schema object")
    normalized = copy.deepcopy(dict(schema))
    try:
        Draft202012Validator.check_schema(normalized)
    except SchemaError as exc:
        raise PluginProtocolError(
            f"{label} is not valid JSON Schema: {exc.message}"
        ) from exc
    return normalized


@dataclass(frozen=True)
class PluginRuntimeSpec:
    transport: PluginTransport
    entrypoint: str

    def __post_init__(self) -> None:
        transport = PluginTransport(self.transport)
        entrypoint = str(self.entrypoint or "").strip()
        if not entrypoint:
            raise PluginProtocolError("plugin runtime requires an entrypoint")
        if transport is PluginTransport.IN_PROCESS and not _ENTRYPOINT_RE.fullmatch(
            entrypoint
        ):
            raise PluginProtocolError(
                "in-process entrypoint must use 'python.module:object' syntax"
            )
        if transport is PluginTransport.HTTP:
            parsed = urlsplit(entrypoint)
            if parsed.scheme != "https" or not parsed.netloc:
                raise PluginProtocolError("HTTP plugin entrypoint must be an HTTPS URL")
            if parsed.username or parsed.password:
                raise PluginProtocolError(
                    "HTTP plugin entrypoint must not contain credentials"
                )
        if transport is PluginTransport.MCP and not _ID_RE.fullmatch(entrypoint):
            raise PluginProtocolError(
                "MCP entrypoint must be a stable lowercase server id"
            )
        object.__setattr__(self, "transport", transport)
        object.__setattr__(self, "entrypoint", entrypoint)


@dataclass(frozen=True)
class PluginDependency:
    plugin_id: str
    min_version: str = ""
    max_version: str = ""
    optional: bool = False

    def __post_init__(self) -> None:
        plugin_id = str(self.plugin_id or "").strip()
        if not _ID_RE.fullmatch(plugin_id):
            raise PluginProtocolError(f"invalid dependency plugin id: {plugin_id!r}")
        for label, version in (
            ("min_version", self.min_version),
            ("max_version", self.max_version),
        ):
            if version and not _SEMVER_RE.fullmatch(str(version)):
                raise PluginProtocolError(
                    f"dependency {label} must be semantic version"
                )
        object.__setattr__(self, "plugin_id", plugin_id)


@dataclass(frozen=True)
class PluginLimits:
    max_timeout_seconds: float = 60.0
    max_result_bytes: int = 2_000_000
    max_concurrency: int = 4
    max_rag_chunks: int = 20

    def __post_init__(self) -> None:
        if not 0 < float(self.max_timeout_seconds) <= 600:
            raise PluginProtocolError("max_timeout_seconds must be in (0, 600]")
        if not 1_024 <= int(self.max_result_bytes) <= 50_000_000:
            raise PluginProtocolError(
                "max_result_bytes must be between 1 KiB and 50 MB"
            )
        if not 1 <= int(self.max_concurrency) <= 32:
            raise PluginProtocolError("max_concurrency must be between 1 and 32")
        if not 1 <= int(self.max_rag_chunks) <= 100:
            raise PluginProtocolError("max_rag_chunks must be between 1 and 100")


@dataclass(frozen=True)
class PluginDataPolicy:
    accepts: Tuple[DataClassification, ...] = (DataClassification.INTERNAL,)
    emits: Tuple[DataClassification, ...] = (DataClassification.INTERNAL,)
    persistence: PersistenceMode = PersistenceMode.NONE
    retention_days: int = 0
    tenant_isolation: bool = True
    sends_data_external: bool = False

    def __post_init__(self) -> None:
        accepts = tuple(DataClassification(value) for value in self.accepts)
        emits = tuple(DataClassification(value) for value in self.emits)
        persistence = PersistenceMode(self.persistence)
        if not accepts or not emits:
            raise PluginProtocolError(
                "data policy must declare accepted and emitted classes"
            )
        if int(self.retention_days) < 0 or int(self.retention_days) > 3650:
            raise PluginProtocolError("retention_days must be between 0 and 3650")
        if persistence is PersistenceMode.DURABLE and int(self.retention_days) <= 0:
            raise PluginProtocolError(
                "durable persistence requires a positive retention_days"
            )
        if persistence is not PersistenceMode.DURABLE and int(self.retention_days) != 0:
            raise PluginProtocolError(
                "retention_days must be zero unless persistence is durable"
            )
        object.__setattr__(self, "accepts", tuple(dict.fromkeys(accepts)))
        object.__setattr__(self, "emits", tuple(dict.fromkeys(emits)))
        object.__setattr__(self, "persistence", persistence)


@dataclass(frozen=True)
class PluginContribution:
    contribution_id: str
    kind: ContributionKind
    name: str
    description: str
    capabilities: Tuple[str, ...]
    permissions: Tuple[PluginPermission, ...] = ()
    read_only: bool = True
    input_schema: Mapping[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )
    output_schema: Mapping[str, Any] = field(default_factory=dict)
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        contribution_id = str(self.contribution_id or "").strip()
        name = str(self.name or "").strip()
        description = str(self.description or "").strip()
        kind = ContributionKind(self.kind)
        if not _ID_RE.fullmatch(contribution_id):
            raise PluginProtocolError(f"invalid contribution id: {contribution_id!r}")
        if not _ID_RE.fullmatch(name):
            raise PluginProtocolError(f"invalid contribution name: {name!r}")
        if not description:
            raise PluginProtocolError(
                f"contribution '{contribution_id}' needs a description"
            )
        capabilities = _unique_text(self.capabilities)
        if not capabilities or any(not _ID_RE.fullmatch(item) for item in capabilities):
            raise PluginProtocolError(
                f"contribution '{contribution_id}' needs valid capability ids"
            )
        permissions = tuple(
            dict.fromkeys(PluginPermission(item) for item in self.permissions)
        )
        input_schema = _validate_schema(
            self.input_schema, label=f"contribution '{contribution_id}' input_schema"
        )
        output_schema = _validate_schema(
            self.output_schema, label=f"contribution '{contribution_id}' output_schema"
        )
        if str(input_schema.get("type") or "object").lower() != "object":
            raise PluginProtocolError(
                f"contribution '{contribution_id}' input_schema must describe an object"
            )
        if not any(
            key in output_schema for key in ("type", "$ref", "oneOf", "anyOf", "allOf")
        ):
            raise PluginProtocolError(
                f"contribution '{contribution_id}' output_schema needs a root constraint"
            )
        if self.timeout_seconds is not None and float(self.timeout_seconds) <= 0:
            raise PluginProtocolError("contribution timeout_seconds must be positive")
        if kind is ContributionKind.RETRIEVER and not self.read_only:
            raise PluginProtocolError(f"{kind.value} contributions must be read-only")
        object.__setattr__(self, "contribution_id", contribution_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "permissions", permissions)
        object.__setattr__(self, "input_schema", input_schema)
        object.__setattr__(self, "output_schema", output_schema)


@dataclass(frozen=True)
class PluginManifestV1(PluginManifest):
    """The complete admission manifest; contains no executable plugin code."""

    schema_version: str = PLUGIN_PROTOCOL_VERSION
    name: str = ""
    publisher: str = ""
    runtime: PluginRuntimeSpec = field(
        default_factory=lambda: PluginRuntimeSpec(
            PluginTransport.IN_PROCESS, "plugin:Plugin"
        )
    )
    permissions: Tuple[PluginPermission, ...] = ()
    contributions: Tuple[PluginContribution, ...] = ()
    dependencies: Tuple[PluginDependency, ...] = ()
    limits: PluginLimits = field(default_factory=PluginLimits)
    data_policy: PluginDataPolicy = field(default_factory=PluginDataPolicy)
    config_schema: Mapping[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
    )
    secret_names: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if str(self.schema_version) != PLUGIN_PROTOCOL_VERSION:
            raise PluginProtocolError(
                f"unsupported plugin schema {self.schema_version!r}; "
                f"expected {PLUGIN_PROTOCOL_VERSION}"
            )
        if not _SEMVER_RE.fullmatch(str(self.version or "")):
            raise PluginProtocolError("plugin version must use semantic versioning")
        if not str(self.name or "").strip():
            raise PluginProtocolError("plugin manifest requires a display name")
        if not str(self.description or "").strip():
            raise PluginProtocolError("plugin manifest requires a description")
        if not str(self.publisher or "").strip():
            raise PluginProtocolError("plugin manifest requires a publisher")
        if not isinstance(self.runtime, PluginRuntimeSpec):
            raise PluginProtocolError("plugin runtime must be PluginRuntimeSpec")
        if not isinstance(self.limits, PluginLimits):
            raise PluginProtocolError("plugin limits must be PluginLimits")
        if not isinstance(self.data_policy, PluginDataPolicy):
            raise PluginProtocolError("plugin data_policy must be PluginDataPolicy")
        permissions = tuple(
            dict.fromkeys(PluginPermission(item) for item in self.permissions)
        )
        contributions = tuple(self.contributions)
        if not contributions:
            raise PluginProtocolError(
                "plugin manifest requires at least one contribution"
            )
        if not all(isinstance(item, PluginContribution) for item in contributions):
            raise PluginProtocolError(
                "plugin contributions must be PluginContribution instances"
            )
        if not all(isinstance(item, PluginDependency) for item in self.dependencies):
            raise PluginProtocolError(
                "plugin dependencies must be PluginDependency instances"
            )
        contribution_ids = [item.contribution_id for item in contributions]
        contribution_names = [item.name for item in contributions]
        if len(contribution_ids) != len(set(contribution_ids)):
            raise PluginProtocolError("plugin contribution ids must be unique")
        if len(contribution_names) != len(set(contribution_names)):
            raise PluginProtocolError("plugin contribution names must be unique")
        undeclared = sorted(
            {
                permission.value
                for item in contributions
                for permission in item.permissions
                if permission not in permissions
            }
        )
        if undeclared:
            raise PluginProtocolError(
                "contribution permissions are absent from manifest: "
                + ", ".join(undeclared)
            )
        if any(
            item.timeout_seconds is not None
            and float(item.timeout_seconds) > float(self.limits.max_timeout_seconds)
            for item in contributions
        ):
            raise PluginProtocolError("contribution timeout exceeds plugin limit")
        config_schema = _validate_schema(self.config_schema, label="config_schema")
        if str(config_schema.get("type") or "object").lower() != "object":
            raise PluginProtocolError("config_schema must describe an object")
        secret_names = _unique_text(self.secret_names)
        if any(not _ID_RE.fullmatch(item) for item in secret_names):
            raise PluginProtocolError("secret names must be stable lowercase ids")
        if secret_names and PluginPermission.SECRETS_USE not in permissions:
            raise PluginProtocolError("secret_names require the secrets.use permission")
        object.__setattr__(self, "name", str(self.name).strip())
        object.__setattr__(self, "publisher", str(self.publisher).strip())
        object.__setattr__(self, "permissions", permissions)
        object.__setattr__(self, "contributions", contributions)
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        object.__setattr__(self, "config_schema", config_schema)
        object.__setattr__(self, "secret_names", secret_names)


__all__ = [
    "ContributionKind",
    "DataClassification",
    "PersistenceMode",
    "PLUGIN_PROTOCOL_VERSION",
    "PluginContribution",
    "PluginDataPolicy",
    "PluginDependency",
    "PluginLimits",
    "PluginManifestV1",
    "PluginPermission",
    "PluginProtocolError",
    "PluginRuntimeSpec",
    "PluginTransport",
]
