from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

_TOOL_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
KERNEL_API_VERSION = "1"
TRUSTED_CONTEXT_ARGUMENT = "invocation_context"

_JSON_SCHEMA_TYPES = {
    "array",
    "boolean",
    "integer",
    "null",
    "number",
    "object",
    "string",
}


def _normalize_json_schema(value: Any, *, key: str = "") -> Any:
    """Normalize legacy upper-case JSON Schema type names recursively."""

    if isinstance(value, Mapping):
        return {
            str(item_key): _normalize_json_schema(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalize_json_schema(item, key=key) for item in value]
    if key == "type" and isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _JSON_SCHEMA_TYPES:
            return normalized
    return copy.deepcopy(value)


class ToolContractError(ValueError):
    """Raised when a tool or plugin violates the kernel contract."""


class ToolErrorCode(str, Enum):
    NOT_FOUND = "not_found"
    INVALID_ARGUMENTS = "invalid_arguments"
    TIMEOUT = "timeout"
    EXECUTION_ERROR = "execution_error"
    POLICY_DENIED = "policy_denied"


@dataclass(frozen=True)
class ToolSpec:
    """Canonical description and handler for exactly one model-callable tool."""

    name: str
    description: str
    input_schema: Mapping[str, Any]
    handler: Callable[..., Any] = field(repr=False, compare=False)
    source: str = "core"
    version: str = "1.0.0"
    capabilities: Tuple[str, ...] = ()
    read_only: Optional[bool] = None
    timeout_seconds: Optional[float] = None
    requires_invocation_context: bool = False
    policy_denied_handler: Optional[Callable[[str, Any], None]] = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        name = str(self.name or "").strip()
        if not _TOOL_NAME_RE.fullmatch(name):
            raise ToolContractError(
                "tool name must start with a letter and contain only letters, "
                "numbers, '_', '-', or '.' (max 128 characters)"
            )
        if not callable(self.handler):
            raise ToolContractError(f"tool '{name}' handler must be callable")
        if not str(self.description or "").strip():
            raise ToolContractError(f"tool '{name}' requires a description")
        if not isinstance(self.input_schema, Mapping):
            raise ToolContractError(f"tool '{name}' input_schema must be an object")
        normalized_schema = _normalize_json_schema(dict(self.input_schema))
        schema_type = str(normalized_schema.get("type") or "object").lower()
        if schema_type != "object":
            raise ToolContractError(f"tool '{name}' input_schema type must be object")
        normalized_schema.setdefault("type", "object")
        properties = normalized_schema.get("properties") or {}
        if isinstance(properties, Mapping) and TRUSTED_CONTEXT_ARGUMENT in properties:
            raise ToolContractError(
                f"tool '{name}' cannot expose reserved argument "
                f"'{TRUSTED_CONTEXT_ARGUMENT}' to the model"
            )
        try:
            Draft202012Validator.check_schema(normalized_schema)
        except SchemaError as exc:
            raise ToolContractError(
                f"tool '{name}' input_schema is not valid JSON Schema: {exc.message}"
            ) from exc
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ToolContractError(f"tool '{name}' timeout_seconds must be positive")
        if self.policy_denied_handler is not None and not callable(
            self.policy_denied_handler
        ):
            raise ToolContractError(
                f"tool '{name}' policy_denied_handler must be callable"
            )

        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", str(self.description).strip())
        object.__setattr__(self, "input_schema", normalized_schema)
        object.__setattr__(self, "source", str(self.source or "core").strip() or "core")
        object.__setattr__(
            self,
            "capabilities",
            tuple(
                dict.fromkeys(
                    str(item).strip() for item in self.capabilities if str(item).strip()
                )
            ),
        )
        object.__setattr__(
            self,
            "requires_invocation_context",
            bool(self.requires_invocation_context),
        )

    def llm_definition(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": copy.deepcopy(dict(self.input_schema)),
        }


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    call_id: str = ""

    def __post_init__(self) -> None:
        if not str(self.name or "").strip():
            raise ToolContractError("tool call requires a name")
        if not isinstance(self.arguments, Mapping):
            raise ToolContractError("tool call arguments must be an object")
        object.__setattr__(self, "name", str(self.name).strip())
        object.__setattr__(self, "arguments", copy.deepcopy(dict(self.arguments)))


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    tool_name: str
    ok: bool
    value: Any = None
    error_code: Optional[ToolErrorCode] = None
    error_message: str = ""
    duration_ms: int = 0

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "ok": self.ok,
            "duration_ms": max(0, int(self.duration_ms)),
        }
        if self.ok:
            payload["value"] = self.value
        else:
            payload["error"] = {
                "code": (self.error_code or ToolErrorCode.EXECUTION_ERROR).value,
                "message": self.error_message,
            }
        return payload


@dataclass(frozen=True)
class PluginManifest:
    """Compatibility boundary implemented by future in-process or remote plugins."""

    plugin_id: str
    version: str
    api_version: str = KERNEL_API_VERSION
    description: str = ""

    def __post_init__(self) -> None:
        plugin_id = str(self.plugin_id or "").strip()
        if not _TOOL_NAME_RE.fullmatch(plugin_id):
            raise ToolContractError(f"invalid plugin id: {plugin_id!r}")
        if str(self.api_version) != KERNEL_API_VERSION:
            raise ToolContractError(
                f"plugin '{plugin_id}' targets kernel API {self.api_version}; "
                f"expected {KERNEL_API_VERSION}"
            )
        object.__setattr__(self, "plugin_id", plugin_id)


@dataclass(frozen=True)
class AgentRunLimits:
    max_steps: int = 15
    max_tool_calls: int = 32
    max_repeated_batches: int = 1
    max_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.max_steps < 1 or self.max_tool_calls < 1:
            raise ToolContractError("agent step and tool-call limits must be positive")
        if self.max_repeated_batches < 0 or self.max_seconds <= 0:
            raise ToolContractError("agent repeat and time limits must be non-negative")
