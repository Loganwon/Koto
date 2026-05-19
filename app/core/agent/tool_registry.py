# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
import inspect
import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FuturesTimeout
from typing import Any, Callable, Dict, List, Optional, get_type_hints

from app.core.agent.base import AgentPlugin

logger = logging.getLogger(__name__)

# 单个工具调用的最大允许执行秒数（超时后返回错误，不挂死 agent 循环）
_TOOL_TIMEOUT: int = 60

_ARG_ALIASES = {
    "path": ("file_path", "filepath", "xlsx_path", "docx_path", "pptx_path", "pdf_path"),
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
    "source_path": ("source", "source_file", "src", "src_path", "input_path", "xlsx_path", "pdf_path"),
    "destination": ("destination_path", "dest", "dst", "dst_path", "target_path", "output_path"),
    "source": ("source_path", "source_file", "src", "src_path", "input_path"),
    "file_paths": ("paths", "path_list"),
}


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
        return normalized
    known = {name: value for name, value in normalized.items() if name in parameters}
    dropped = [name for name in normalized if name not in parameters]
    if dropped:
        logger.debug(
            "_normalize_tool_args: dropped unknown kwargs for %s: %s",
            getattr(func, "__name__", func),
            dropped,
        )
    return known


class ToolRegistry:
    """
    Manages tools and plugins for the agent.
    Provides tool definitions for LLMs and executes tool calls.
    """

    def __init__(self):
        self._tools: Dict[str, Callable] = {}
        self._tool_definitions: List[Dict[str, Any]] = []
        self._plugins: Dict[str, AgentPlugin] = {}

    def register_tool(
        self,
        name: str,
        func: Callable,
        description: Optional[str] = None,
        parameters: Optional[Dict] = None,
    ):
        """
        Register a single tool function.
        """
        # Avoid duplicate registration
        if name in self._tools:
            logger.warning(f"Tool {name} is already registered. Updating definition.")

        self._tools[name] = func

        definition = {
            "name": name,
            "description": description or func.__doc__ or "No description provided.",
        }

        if parameters:
            definition["parameters"] = parameters
        else:
            definition["parameters"] = self._generate_schema(func)

        # Update definition in list
        self._tool_definitions = [
            t for t in self._tool_definitions if t["name"] != name
        ]
        self._tool_definitions.append(definition)
        logger.debug(f"Registered tool: {name}")

    def register_plugin(self, plugin: AgentPlugin):
        """
        Register a set of tools via a Plugin.
        """
        self._plugins[plugin.name] = plugin
        tools = plugin.get_tools()

        for tool_def in tools:
            name = tool_def.get("name")
            func = tool_def.get("func")

            if not name or not func:
                logger.warning(
                    f"Plugin {plugin.name} provided invalid tool definition: {tool_def}"
                )
                continue

            self.register_tool(
                name=name,
                func=func,
                description=tool_def.get("description"),
                parameters=tool_def.get("parameters"),
            )
        logger.info(f"Registered plugin: {plugin.name} with {len(tools)} tools")

    def get_definitions(self) -> List[Dict[str, Any]]:
        """
        Returns JSON schemas for all registered tools, compatible with LLM function calling.
        """
        return self._tool_definitions

    def execute(self, tool_name: str, tool_args: Dict[str, Any]) -> Any:
        """
        Execute a tool by name with provided arguments.
        Per-tool timeout: _TOOL_TIMEOUT seconds (prevents hung tools from stalling the agent loop).
        """
        func = self._tools.get(tool_name)
        if not func:
            raise ValueError(f"Tool '{tool_name}' not found.")

        try:
            normalized_args = _normalize_tool_args(func, tool_args)
            with ThreadPoolExecutor(max_workers=1) as _pool:
                _future = _pool.submit(func, **normalized_args)
                try:
                    return _future.result(timeout=_TOOL_TIMEOUT)
                except _FuturesTimeout:
                    raise RuntimeError(
                        f"Tool '{tool_name}' timed out after {_TOOL_TIMEOUT}s"
                    )
        except (ValueError, RuntimeError):
            raise
        except TypeError as e:
            raise ValueError(f"Argument mismatch for tool '{tool_name}': {e}")
        except Exception as e:
            logger.error(f"Error executing tool '{tool_name}': {e}", exc_info=True)
            raise RuntimeError(f"Error executing tool '{tool_name}': {str(e)}")

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

            # Start with default type string
            json_type = "STRING"

            # Map Python types to JSON schema types
            hint = type_hints.get(param_name)
            if hint:
                if hint is int:
                    json_type = "INTEGER"
                elif hint is float:
                    json_type = "NUMBER"
                elif hint is bool:
                    json_type = "BOOLEAN"
                elif hint is list or getattr(hint, "__origin__", None) is list:
                    json_type = "ARRAY"
                elif hint is dict or getattr(hint, "__origin__", None) is dict:
                    json_type = "OBJECT"

            properties[param_name] = {"type": json_type}

            if param.default == inspect.Parameter.empty:
                required.append(param_name)

        return {"type": "OBJECT", "properties": properties, "required": required}
