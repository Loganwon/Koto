# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Runtime manager for Koto's MCP integration.

This module keeps the MCP client side lazy and process-wide:
- Agent factories can inject configured MCP tools into each ToolRegistry.
- API routes can inspect or reload MCP server connections.
- Missing or broken MCP configuration never prevents Koto from starting.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

from app.core.agent.mcp_adapter import MCPRegistry

logger = logging.getLogger(__name__)


class MCPRuntime:
    """Small lifecycle wrapper around MCPRegistry."""

    def __init__(self):
        self.registry = MCPRegistry.from_koto_settings()
        self.connect_results: Dict[str, bool] = {}
        self.injected_tool_count = 0
        self._connected = False

    def connect(self) -> Dict[str, bool]:
        if not self._connected:
            self.connect_results = self.registry.connect_all()
            self._connected = True
        return dict(self.connect_results)

    def inject_into(self, tool_registry) -> int:
        self.connect()
        self.injected_tool_count = self.registry.inject_into(tool_registry)
        return self.injected_tool_count

    def status(self) -> Dict[str, Any]:
        self.connect()
        status = self.registry.status()
        status["connect_results"] = dict(self.connect_results)
        status["injected_tool_count"] = self.injected_tool_count
        return status

    def close(self) -> None:
        self.registry.disconnect_all()
        self._connected = False


_runtime: Optional[MCPRuntime] = None
_runtime_lock = threading.Lock()


def get_mcp_runtime(force_reload: bool = False) -> MCPRuntime:
    """Return the process-wide MCP runtime, optionally reloading settings."""

    global _runtime
    with _runtime_lock:
        if force_reload and _runtime is not None:
            _runtime.close()
            _runtime = None
        if _runtime is None:
            _runtime = MCPRuntime()
        return _runtime


def inject_configured_mcp_tools(tool_registry) -> int:
    """
    Inject configured MCP tools into a Koto ToolRegistry.

    Returns the number of injected tools. Any failure is logged and converted to
    zero so the main agent path remains available even if an external MCP server
    is offline.
    """

    try:
        return get_mcp_runtime().inject_into(tool_registry)
    except Exception as exc:
        logger.warning("[MCPManager] MCP 工具注入失败: %s", exc, exc_info=True)
        return 0


def get_mcp_status() -> Dict[str, Any]:
    try:
        return get_mcp_runtime().status()
    except Exception as exc:
        logger.warning("[MCPManager] MCP 状态读取失败: %s", exc, exc_info=True)
        return {
            "server_count": 0,
            "tool_count": 0,
            "servers": {},
            "connect_results": {},
            "injected_tool_count": 0,
            "error": str(exc),
        }


def reload_mcp_runtime() -> Dict[str, Any]:
    runtime = get_mcp_runtime(force_reload=True)
    return runtime.status()


def reset_mcp_runtime_for_tests() -> None:
    global _runtime
    with _runtime_lock:
        if _runtime is not None:
            _runtime.close()
        _runtime = None
