# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""MCP Tool Registry — register, list, and execute MCP tools."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from app.core.mcp.protocol import MCPTool

logger = logging.getLogger(__name__)


class MCPToolRegistry:
    """Registry for MCP tools.

    Tools can be registered from multiple sources:
      - Koto built-in tools
      - MCP servers connected as clients
      - Plugin contributions

    Each tool has a unique name, description, JSON Schema input specification,
    and a callable handler.
    """

    def __init__(self):
        self._tools: Dict[str, MCPTool] = {}
        self._name_prefixes: Dict[str, str] = {}  # name → source prefix

    # ── Registration ────────────────────────────────────────────────────────

    def register(
        self,
        name: str,
        description: str,
        input_schema: Optional[Dict[str, Any]] = None,
        handler: Optional[Callable] = None,
        annotations: Optional[Dict[str, Any]] = None,
        source_prefix: str = "",
    ) -> MCPTool:
        """Register a tool in the registry."""
        if name in self._tools:
            raise ValueError(f"Tool {name!r} is already registered")

        tool = MCPTool(
            name=name,
            description=description,
            inputSchema=input_schema or {"type": "object", "properties": {}},
            handler=handler,
            annotations=annotations,
        )
        self._tools[name] = tool
        if source_prefix:
            self._name_prefixes[name] = source_prefix

        logger.debug("[MCPToolRegistry] registered tool: %s", name)
        return tool

    def register_tool(self, tool: MCPTool, source_prefix: str = "") -> None:
        """Register an existing MCPTool instance."""
        if tool.name in self._tools:
            raise ValueError(f"Tool {tool.name!r} is already registered")
        self._tools[tool.name] = tool
        if source_prefix:
            self._name_prefixes[tool.name] = source_prefix
        logger.debug("[MCPToolRegistry] registered tool: %s", tool.name)

    def unregister(self, name: str) -> None:
        """Remove a tool from the registry."""
        self._tools.pop(name, None)
        self._name_prefixes.pop(name, None)
        logger.debug("[MCPToolRegistry] unregistered tool: %s", name)

    def unregister_by_prefix(self, source_prefix: str) -> int:
        """Remove all tools registered under a given source prefix. Returns count."""
        names = [
            name
            for name, prefix in self._name_prefixes.items()
            if prefix == source_prefix
        ]
        for name in names:
            self._tools.pop(name, None)
            self._name_prefixes.pop(name, None)
        if names:
            logger.debug(
                "[MCPToolRegistry] unregistered %d tools from prefix %r",
                len(names),
                source_prefix,
            )
        return len(names)

    # ── Query ───────────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[MCPTool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[Dict[str, Any]]:
        """List all tools in MCP-compatible format."""
        return [tool.to_tool_def() for tool in self._tools.values()]

    def tool_names(self) -> List[str]:
        """List all registered tool names."""
        return sorted(self._tools.keys())

    def tool_count(self) -> int:
        """Number of registered tools."""
        return len(self._tools)

    # ── Execution ───────────────────────────────────────────────────────────

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Execute a tool by name with given arguments."""
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"Tool {name!r} not found in registry")
        return tool.execute(arguments)

    def has_tool(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    # ── Bulk Operations ─────────────────────────────────────────────────────

    def merge_from(self, other: "MCPToolRegistry", prefix: str = "") -> int:
        """Import all tools from another registry, optionally with a name prefix."""
        count = 0
        for tool in other._tools.values():
            new_name = f"{prefix}__{tool.name}" if prefix else tool.name
            new_tool = MCPTool(
                name=new_name,
                description=(
                    f"[{prefix}] {tool.description}" if prefix else tool.description
                ),
                inputSchema=tool.inputSchema,
                handler=tool.handler,
                annotations=tool.annotations,
            )
            try:
                self.register_tool(
                    new_tool, source_prefix=other._name_prefixes.get(tool.name, prefix)
                )
                count += 1
            except ValueError:
                logger.warning(
                    "[MCPToolRegistry] skipping duplicate tool: %s", new_name
                )
        return count

    def clear(self) -> None:
        """Remove all tools from the registry."""
        self._tools.clear()
        self._name_prefixes.clear()

    # ── Diagnostics ─────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Return registry status for diagnostics."""
        by_source: Dict[str, int] = {}
        for name, prefix in self._name_prefixes.items():
            by_source[prefix] = by_source.get(prefix, 0) + 1
        return {
            "total_tools": len(self._tools),
            "by_source": by_source,
            "tool_names": sorted(self._tools.keys()),
        }


# ── Module-level singleton ──────────────────────────────────────────────────

_global_tool_registry: Optional[MCPToolRegistry] = None


def get_global_tool_registry() -> MCPToolRegistry:
    """Get or create the global MCP tool registry singleton."""
    global _global_tool_registry
    if _global_tool_registry is None:
        _global_tool_registry = MCPToolRegistry()
    return _global_tool_registry


def reset_global_tool_registry() -> None:
    """Reset the global registry (for testing)."""
    global _global_tool_registry
    if _global_tool_registry is not None:
        _global_tool_registry.clear()
    _global_tool_registry = None


__all__ = [
    "MCPToolRegistry",
    "get_global_tool_registry",
    "reset_global_tool_registry",
]
