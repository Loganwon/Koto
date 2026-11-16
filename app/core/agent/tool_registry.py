# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
import inspect
import json
import logging
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, get_type_hints

from app.core.agent.base import AgentPlugin
from app.core.agent.kernel import (
    ToolCall,
    ToolCatalog,
    ToolErrorCode,
    ToolExecutionPolicy,
    ToolExecutor,
    ToolResult,
    ToolSpec,
)

logger = logging.getLogger(__name__)

# 单个工具调用的最大允许执行秒数（超时后返回错误，不挂死 agent 循环）
_TOOL_TIMEOUT: int = 60
_TOOL_TIMEOUT_OVERRIDES: Dict[str, int] = {
    # Office writes can legitimately take longer on large files. If the generic
    # 60s timeout fires while python-docx is still saving, the background worker
    # may finish anyway and a model retry can duplicate the write.
    "insert_excel_as_docx_table": 180,
    "insert_image_into_docx": 120,
    "design_pptx_theme_layout": 120,
}

_ARG_ALIASES = {
    "path": (
        "file_path",
        "filepath",
        "xlsx_path",
        "docx_path",
        "pptx_path",
        "pdf_path",
    ),
    "target_path": (
        "target",
        "target_file",
        "destination",
        "destination_path",
        "dest",
        "dst",
        "dst_path",
        "output_path",
        "docx_path",
        "pptx_path",
    ),
    "source_path": (
        "source",
        "source_file",
        "src",
        "src_path",
        "input_path",
        "xlsx_path",
        "pdf_path",
    ),
    "destination": (
        "destination_path",
        "dest",
        "dst",
        "dst_path",
        "target_path",
        "output_path",
    ),
    "source": ("source_path", "source_file", "src", "src_path", "input_path"),
    "file_paths": ("paths", "path_list"),
}

_INTEGER_TEXT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_TEXT_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")


def _coerce_scalar_tool_args(
    func: Callable, normalized: Dict[str, Any]
) -> Dict[str, Any]:
    """Coerce only unambiguous numeric text emitted by model tool calls.

    Several hot-path tools are Cython-compiled and enforce annotations before
    their own defensive normalizers execute.  JSON producers occasionally emit
    `"2"` for an INTEGER parameter, so normalize that narrow, lossless case
    at the common registry boundary.
    """
    try:
        type_hints = get_type_hints(func)
    except Exception:
        type_hints = {}

    for name, value in list(normalized.items()):
        if not isinstance(value, str):
            continue
        text = value.strip()
        expected = type_hints.get(name)
        if expected is int and _INTEGER_TEXT_RE.fullmatch(text):
            normalized[name] = int(text)
        elif expected is float and _FLOAT_TEXT_RE.fullmatch(text):
            normalized[name] = float(text)
    return normalized


def _normalize_tool_args(func: Callable, tool_args: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(tool_args or {})
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return normalized

    parameters = signature.parameters
    accepts_var_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    for canonical_name, aliases in _ARG_ALIASES.items():
        if canonical_name not in parameters or canonical_name in normalized:
            continue
        for alias in aliases:
            if alias in normalized:
                normalized[canonical_name] = normalized.pop(alias)
                break
    if accepts_var_kwargs:
        return _coerce_scalar_tool_args(func, normalized)
    known = {name: value for name, value in normalized.items() if name in parameters}
    dropped = [name for name in normalized if name not in parameters]
    if dropped:
        logger.debug(
            "_normalize_tool_args: dropped unknown kwargs for %s: %s",
            getattr(func, "__name__", func),
            dropped,
        )
    return _coerce_scalar_tool_args(func, known)


def _coerce_structured_tool_args(
    input_schema: Dict[str, Any], normalized: Dict[str, Any]
) -> Dict[str, Any]:
    """Accept legacy JSON strings for fields whose canonical schema is structured.

    Older Koto prompts serialized arrays and objects into strings. New tool
    contracts expose native JSON to models, while this boundary keeps stored
    workflows and third-party callers compatible during migration.
    """
    properties = input_schema.get("properties")
    if not isinstance(properties, dict):
        return normalized
    for name, value in list(normalized.items()):
        if not isinstance(value, str):
            continue
        property_schema = properties.get(name)
        if not isinstance(property_schema, dict):
            continue
        expected_type = str(property_schema.get("type") or "").lower()
        if expected_type not in {"array", "object"}:
            continue
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            continue
        if expected_type == "array" and isinstance(parsed, list):
            normalized[name] = parsed
        elif expected_type == "object" and isinstance(parsed, dict):
            normalized[name] = parsed
    return normalized


def normalize_tool_args_for_spec(
    spec: ToolSpec, tool_args: Dict[str, Any]
) -> Dict[str, Any]:
    normalized = _normalize_tool_args(spec.handler, tool_args)
    normalized = _coerce_structured_tool_args(dict(spec.input_schema), normalized)
    if spec.name == "write_docx_content" and isinstance(
        normalized.get("paragraphs"), str
    ):
        # Historical plans often supplied a plain paragraph or a loose
        # Python/JSON-ish list. Preserve that input surface while publishing a
        # precise native-array schema to new model/tool callers.
        from app.core.agent.toolkits.foundation.docx_minimal import (
            _coerce_docx_paragraphs_for_write,
        )

        normalized["paragraphs"] = _coerce_docx_paragraphs_for_write(
            normalized["paragraphs"]
        )
    return normalized


class ToolRegistry:
    """
    Manages tools and plugins for the agent.
    Provides tool definitions for LLMs and executes tool calls.
    """

    def __init__(self):
        self._catalog = ToolCatalog()
        # Kept as compatibility views for older integrations.  The catalog is
        # authoritative and these views are refreshed after every registration.
        self._tools: Dict[str, Callable] = {}
        self._tool_definitions: List[Dict[str, Any]] = []
        self._plugins: Dict[str, AgentPlugin] = {}

    @property
    def catalog(self) -> ToolCatalog:
        """Return the canonical catalog used by the Kernel Runtime.

        The property is intentionally read-only: callers may select and execute
        registered tools, but replacing the catalog would invalidate the
        registry's compatibility views.
        """

        return self._catalog

    def register_tool(
        self,
        name: str,
        func: Callable,
        description: Optional[str] = None,
        parameters: Optional[Dict] = None,
        *,
        source: str = "core",
        capabilities: Iterable[str] = (),
        read_only: Optional[bool] = None,
        timeout_seconds: Optional[float] = None,
    ):
        """
        Register a single tool function.
        """
        if name in self._catalog:
            logger.warning(f"Tool {name} is already registered. Updating definition.")

        spec = ToolSpec(
            name=name,
            description=description or func.__doc__ or "No description provided.",
            input_schema=parameters or self._generate_schema(func),
            handler=func,
            source=source,
            capabilities=tuple(capabilities),
            read_only=read_only,
            timeout_seconds=timeout_seconds,
        )
        self._catalog.register(spec, replace=True)
        self._refresh_compatibility_views()
        logger.debug(f"Registered tool: {name}")

    def register_specs(
        self,
        specs: Iterable[ToolSpec],
        *,
        replace: bool = False,
    ) -> None:
        """Atomically register canonical tool specs from a trusted runtime.

        This is the composition seam used by the Add-on runtime.  It preserves
        protocol-owned metadata and avoids adapting Add-ons to the legacy
        ``AgentPlugin`` shape.
        """

        self._catalog.register_many(tuple(specs), replace=replace)
        self._refresh_compatibility_views()

    def register_plugin(
        self,
        plugin: AgentPlugin,
        *,
        tool_allowlist: Optional[Iterable[str]] = None,
    ):
        """
        Register a set of tools via a Plugin.
        """
        tools = plugin.get_tools()
        allowed = (
            {str(name).strip() for name in tool_allowlist}
            if tool_allowlist is not None
            else None
        )
        if allowed is not None:
            available = {
                str(tool.get("name") or "").strip()
                for tool in tools
                if isinstance(tool, dict)
            }
            missing = sorted(allowed - available)
            if missing:
                raise ValueError(
                    f"Plugin {plugin.name} is missing allowlisted tools: "
                    f"{', '.join(missing)}"
                )
            tools = [tool for tool in tools if tool.get("name") in allowed]
        pending_specs: List[ToolSpec] = []
        contributor_source = str(
            getattr(plugin, "toolkit_source", "") or f"plugin:{plugin.name}"
        ).strip()
        contributor_version = str(
            getattr(plugin, "toolkit_version", "") or "1.0.0"
        ).strip()

        for tool_def in tools:
            name = tool_def.get("name")
            func = tool_def.get("func")

            if not name or not func:
                logger.warning(
                    f"Plugin {plugin.name} provided invalid tool definition: {tool_def}"
                )
                continue

            pending_specs.append(
                ToolSpec(
                    name=name,
                    handler=func,
                    description=(
                        tool_def.get("description")
                        or func.__doc__
                        or "No description provided."
                    ),
                    input_schema=(
                        tool_def.get("parameters") or self._generate_schema(func)
                    ),
                    source=contributor_source,
                    version=contributor_version,
                    capabilities=tuple(tool_def.get("capabilities") or ()),
                    read_only=tool_def.get("read_only"),
                    timeout_seconds=tool_def.get("timeout_seconds"),
                    requires_invocation_context=bool(
                        tool_def.get("requires_invocation_context", False)
                    ),
                )
            )

        # One plugin is one atomic catalog update.  A malformed spec cannot
        # leave half of a future plugin installed.
        self._catalog.register_many(pending_specs, replace=True)
        self._plugins[plugin.name] = plugin
        self._refresh_compatibility_views()
        logger.info(f"Registered plugin: {plugin.name} with {len(tools)} tools")

    def get_definitions(self) -> List[Dict[str, Any]]:
        """
        Returns JSON schemas for all registered tools, compatible with LLM function calling.
        """
        return self._catalog.definitions()

    def execute(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        *,
        invocation_context: Any = None,
    ) -> Any:
        """
        Execute a tool by name with provided arguments.
        Per-tool timeout: _TOOL_TIMEOUT seconds (prevents hung tools from stalling the agent loop).
        """
        spec = self._catalog.get(tool_name)
        if not spec:
            raise ValueError(f"Tool '{tool_name}' not found.")

        try:
            normalized_args = normalize_tool_args_for_spec(spec, tool_args)
        except Exception as exc:
            raise ValueError(
                f"Argument mismatch for tool '{tool_name}': {exc}"
            ) from exc

        executor = ToolExecutor(
            self._catalog,
            ToolExecutionPolicy(
                default_timeout_seconds=_TOOL_TIMEOUT,
                timeout_overrides=_TOOL_TIMEOUT_OVERRIDES,
            ),
        )
        outcome = executor.invoke(
            ToolCall(name=tool_name, arguments=normalized_args),
            invocation_context=invocation_context,
        )
        if outcome.ok:
            return outcome.value
        if outcome.error_code is ToolErrorCode.INVALID_ARGUMENTS:
            message = str(outcome.error_message or "")
            if not message.startswith("Argument mismatch"):
                message = f"Argument mismatch for tool '{tool_name}': {message}"
            raise ValueError(message)
        if outcome.error_code is ToolErrorCode.NOT_FOUND:
            raise ValueError(outcome.error_message)
        if outcome.error_code is ToolErrorCode.EXECUTION_ERROR:
            logger.error(outcome.error_message)
        raise RuntimeError(outcome.error_message)

    def execute_result(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        *,
        call_id: str = "",
        invocation_context: Any = None,
    ) -> ToolResult:
        """Execute through the new kernel and keep the structured outcome.

        New runtimes and plugins should use this method.  ``execute`` remains
        the exception-based compatibility API for current callers.
        """
        spec = self._catalog.get(tool_name)
        if spec is None:
            executor = ToolExecutor(self._catalog)
            return executor.invoke(
                ToolCall(name=tool_name, arguments=tool_args, call_id=call_id),
                invocation_context=invocation_context,
            )
        try:
            normalized_args = normalize_tool_args_for_spec(spec, tool_args)
        except Exception as exc:
            return ToolResult(
                call_id=call_id,
                tool_name=tool_name,
                ok=False,
                error_code=ToolErrorCode.INVALID_ARGUMENTS,
                error_message=f"Argument mismatch for tool '{tool_name}': {exc}",
            )
        executor = ToolExecutor(
            self._catalog,
            ToolExecutionPolicy(
                default_timeout_seconds=_TOOL_TIMEOUT,
                timeout_overrides=_TOOL_TIMEOUT_OVERRIDES,
            ),
        )
        return executor.invoke(
            ToolCall(name=tool_name, arguments=normalized_args, call_id=call_id),
            invocation_context=invocation_context,
        )

    def _refresh_compatibility_views(self) -> None:
        self._tools = {
            name: self._catalog.require(name).handler for name in self._catalog.names()
        }
        self._tool_definitions = self._catalog.definitions()

    def _generate_schema(self, func: Callable) -> Dict[str, Any]:
        """
        Generates a JSON schema for a function based on its signature and type hints.
        Basic implementation - sufficient for primary types.
        """
        sig = inspect.signature(func)
        try:
            type_hints = get_type_hints(func)
        except Exception:
            type_hints = {}

        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue
            if param.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue

            # Untyped Python parameters accept any JSON value. Guessing
            # ``string`` here made valid numeric/object calls fail once the
            # Kernel began enforcing schemas.
            json_type = None

            # Map Python types to JSON schema types
            hint = type_hints.get(param_name)
            if hint:
                if hint is int:
                    json_type = "integer"
                elif hint is float:
                    json_type = "number"
                elif hint is bool:
                    json_type = "boolean"
                elif hint is list or getattr(hint, "__origin__", None) is list:
                    json_type = "array"
                elif hint is dict or getattr(hint, "__origin__", None) is dict:
                    json_type = "object"
                elif hint is str:
                    json_type = "string"

            properties[param_name] = (
                {"type": json_type} if json_type is not None else {}
            )

            if param.default == inspect.Parameter.empty:
                required.append(param_name)

        return {"type": "object", "properties": properties, "required": required}
