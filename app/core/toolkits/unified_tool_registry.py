# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Unified Tool Registry — outward-facing projection of all tool sources.

Combines tools from:
  - Koto built-in tools (app/core/agent/toolkits/builtin/)
  - Foundation tools (app/core/agent/toolkits/foundation/)
  - MCP server tools (app/core/mcp/tool_registry.py)
  - Plugin contributions (app/core/plugin_protocol/registry.py)

All tools are registered with a namespace prefix indicating their source:
  - builtin__{name}    — Koto built-in tools
  - foundation__{name} — Foundation office tools
  - mcp__{server}__{name} — External MCP server tools
  - plugin__{plugin}__{name} — Plugin-contributed tools

The Kernel ``ToolCatalog`` remains authoritative for Agent execution. This
registry provides one namespaced projection for MCP and provider bridges.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_JSON_SCHEMA_TYPE_NAMES = {
    "STRING": "string",
    "INTEGER": "integer",
    "NUMBER": "number",
    "BOOLEAN": "boolean",
    "ARRAY": "array",
    "OBJECT": "object",
    "NULL": "null",
}


def _normalize_json_schema(value: Any) -> Any:
    """Return a JSON-Schema-compatible copy of a Koto tool schema."""
    if isinstance(value, list):
        return [_normalize_json_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    normalized = {key: _normalize_json_schema(item) for key, item in value.items()}
    schema_type = normalized.get("type")
    if isinstance(schema_type, str):
        normalized["type"] = _JSON_SCHEMA_TYPE_NAMES.get(
            schema_type.upper(), schema_type.lower()
        )
    elif isinstance(schema_type, list):
        normalized["type"] = [
            _JSON_SCHEMA_TYPE_NAMES.get(str(item).upper(), str(item).lower())
            for item in schema_type
        ]
    return normalized


class ToolSource(str, Enum):
    """Identifies the origin of a registered tool."""

    BUILTIN = "builtin"
    FOUNDATION = "foundation"
    MCP = "mcp"
    PLUGIN = "plugin"
    CUSTOM = "custom"


class ToolRecord:
    """Read-only-facing record projected from an executable tool owner."""

    __slots__ = (
        "name",
        "description",
        "source",
        "source_name",
        "handler",
        "parameters",
        "read_only",
        "timeout_seconds",
        "metadata",
    )

    def __init__(
        self,
        name: str,
        description: str,
        source: ToolSource,
        source_name: str = "",
        handler: Optional[Callable] = None,
        parameters: Optional[Dict[str, Any]] = None,
        read_only: bool = True,
        timeout_seconds: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.description = description
        self.source = source
        self.source_name = source_name
        self.handler = handler
        self.parameters = _normalize_json_schema(
            parameters or {"type": "object", "properties": {}}
        )
        self.read_only = read_only
        self.timeout_seconds = timeout_seconds
        self.metadata = metadata or {}

    def to_tool_def(self) -> Dict[str, Any]:
        """Convert to LLM function-calling format."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def to_mcp_tool_def(self) -> Dict[str, Any]:
        """Convert to MCP tool listing format."""
        result: Dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.parameters,
        }
        if self.read_only is not None:
            result.setdefault("annotations", {})["readOnlyHint"] = self.read_only
        return result


class UnifiedToolRegistry:
    """Namespaced publication projection aggregating tools from all sources.

    Usage:
        registry = UnifiedToolRegistry()

        # Register built-in tools
        registry.register_builtin("read_file", description="...", handler=read_file)

        # Import from MCP tool registry
        registry.merge_from_mcp(mcp_tool_registry)

        # List all tools for LLM
        tools = registry.list_tools_for_llm()
    """

    def __init__(self):
        self._tools: Dict[str, ToolRecord] = {}
        self._by_source: Dict[ToolSource, Dict[str, ToolRecord]] = {
            src: {} for src in ToolSource
        }
        self._sealed = False

    # ── Registration ────────────────────────────────────────────────────────

    def register(
        self,
        name: str,
        description: str,
        source: ToolSource,
        source_name: str = "",
        handler: Optional[Callable] = None,
        parameters: Optional[Dict[str, Any]] = None,
        read_only: bool = True,
        timeout_seconds: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ToolRecord:
        """Register a tool in the unified registry."""
        if self._sealed:
            raise RuntimeError("unified tool projection is sealed")
        if name in self._tools:
            existing = self._tools[name]
            logger.warning(
                "[UnifiedToolRegistry] tool %r already registered (source=%s), overwriting",
                name,
                existing.source.value,
            )
            self._by_source[existing.source].pop(name, None)

        record = ToolRecord(
            name=name,
            description=description,
            source=source,
            source_name=source_name,
            handler=handler,
            parameters=parameters,
            read_only=read_only,
            timeout_seconds=timeout_seconds,
            metadata=metadata,
        )
        self._tools[name] = record
        self._by_source[source][name] = record
        logger.debug("[UnifiedToolRegistry] registered %s tool: %s", source.value, name)
        return record

    def register_builtin(
        self,
        name: str,
        description: str,
        handler: Optional[Callable] = None,
        parameters: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ToolRecord:
        """Register a built-in Koto tool."""
        return self.register(
            name=f"builtin__{name}",
            description=description,
            source=ToolSource.BUILTIN,
            source_name="koto",
            handler=handler,
            parameters=parameters,
            **kwargs,
        )

    def register_foundation(
        self,
        name: str,
        description: str,
        handler: Optional[Callable] = None,
        parameters: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ToolRecord:
        """Register a foundation (office) tool."""
        return self.register(
            name=f"foundation__{name}",
            description=description,
            source=ToolSource.FOUNDATION,
            source_name="foundation",
            handler=handler,
            parameters=parameters,
            **kwargs,
        )

    def unregister(self, name: str) -> None:
        """Remove a tool by full name."""
        if self._sealed:
            raise RuntimeError("unified tool projection is sealed")
        record = self._tools.pop(name, None)
        if record:
            self._by_source.get(record.source, {}).pop(name, None)

    def unregister_by_source(self, source: ToolSource, source_name: str = "") -> int:
        """Remove all tools from a source. Returns count removed."""
        if self._sealed:
            raise RuntimeError("unified tool projection is sealed")
        source_tools = self._by_source.get(source, {})
        if source_name:
            names = [
                name for name, r in source_tools.items() if r.source_name == source_name
            ]
        else:
            names = list(source_tools.keys())

        count = 0
        for name in names:
            record = self._tools.pop(name, None)
            if record:
                source_tools.pop(name, None)
                count += 1

        if count:
            logger.info(
                "[UnifiedToolRegistry] removed %d tools from source %s",
                count,
                source.value,
            )
        return count

    # ── Bulk Import ─────────────────────────────────────────────────────────

    def merge_from_mcp(self, mcp_tool_registry: Any) -> int:
        """Import tools from an MCPToolRegistry."""
        count = 0
        for tool_def in mcp_tool_registry.list_tools():
            name = tool_def["name"]
            # MCP tools already have namespace prefix
            handler = mcp_tool_registry.get(name)
            self.register(
                name=name,
                description=tool_def.get("description", ""),
                source=ToolSource.MCP,
                source_name=tool_def.get("_mcp_server", name),
                handler=handler.handler if handler else None,
                parameters=tool_def.get("inputSchema"),
                read_only=tool_def.get("annotations", {}).get("readOnlyHint", True),
            )
            count += 1
        logger.info("[UnifiedToolRegistry] imported %d tools from MCP registry", count)
        return count

    def merge_from_builtin_plugins(self, builtin_plugins: List[Any]) -> int:
        """Import tools from Koto built-in plugin instances."""
        count = 0
        for plugin in builtin_plugins:
            try:
                tool_specs = plugin.tool_specs()
            except (AttributeError, Exception):
                continue
            for spec in tool_specs:
                name = f"builtin__{spec.name}"
                self.register(
                    name=name,
                    description=getattr(spec, "description", ""),
                    source=ToolSource.BUILTIN,
                    source_name=getattr(plugin, "toolkit_id", "builtin"),
                    handler=getattr(spec, "handler", None),
                    parameters=getattr(spec, "parameters", None),
                    read_only=getattr(spec, "read_only", True),
                )
                count += 1
        logger.info(
            "[UnifiedToolRegistry] imported %d tools from builtin plugins", count
        )
        return count

    # ── Query ───────────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[ToolRecord]:
        """Get a tool by full name."""
        return self._tools.get(name)

    def list_tools(self) -> List[ToolRecord]:
        """List all registered tools."""
        return list(self._tools.values())

    def list_tools_for_llm(self) -> List[Dict[str, Any]]:
        """List all tools in LLM function-calling format."""
        return [record.to_tool_def() for record in self._tools.values()]

    def list_tools_for_mcp(self) -> List[Dict[str, Any]]:
        """List all tools in MCP format."""
        return [record.to_mcp_tool_def() for record in self._tools.values()]

    def list_by_source(self, source: ToolSource) -> List[ToolRecord]:
        """List tools from a specific source."""
        return list(self._by_source.get(source, {}).values())

    def tool_count(self) -> int:
        return len(self._tools)

    def tool_names(self) -> List[str]:
        return sorted(self._tools.keys())

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def seal(self) -> None:
        """Prevent runtime mutation after composition is complete."""
        self._sealed = True

    @property
    def is_sealed(self) -> bool:
        return self._sealed

    # ── Clear ───────────────────────────────────────────────────────────────

    def clear(self) -> None:
        """Remove all tools."""
        self._tools.clear()
        for src in ToolSource:
            self._by_source[src].clear()
        self._sealed = False

    # ── Diagnostics ─────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Return comprehensive registry status."""
        by_source = {src.value: len(self._by_source[src]) for src in ToolSource}
        return {
            "total_tools": len(self._tools),
            "by_source": by_source,
            "tool_names": sorted(self._tools.keys()),
        }


# ── Module-level singleton ──────────────────────────────────────────────────

import threading

_registry: Optional[UnifiedToolRegistry] = None
_registry_lock = threading.Lock()


def get_unified_tool_registry() -> UnifiedToolRegistry:
    """Get or create the global unified tool registry.

    On first access, auto-bootstraps builtin tools from Koto plugins.
    """
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = UnifiedToolRegistry()
            try:
                from app.core.toolkits.bootstrap import (
                    _load_builtin_plugins,
                    _load_foundation_tools,
                )

                _load_builtin_plugins(_registry)
                _load_foundation_tools(_registry)
                _registry.seal()
            except Exception:
                logger.exception("[UnifiedToolRegistry] bootstrap failed")
        return _registry


def reset_unified_tool_registry() -> None:
    """Reset the global unified registry (for testing)."""
    global _registry
    with _registry_lock:
        if _registry is not None:
            _registry.clear()
        _registry = None


__all__ = [
    "ToolSource",
    "ToolRecord",
    "UnifiedToolRegistry",
    "get_unified_tool_registry",
    "reset_unified_tool_registry",
]
