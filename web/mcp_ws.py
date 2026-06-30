# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Minimal WebSocket-side MCP session support for Koto supervision tools."""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict

_SESSIONS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.RLock()


def _register_session(session_id: str) -> None:
    with _LOCK:
        _SESSIONS[session_id] = {
            "session_id": session_id,
            "connected_at": time.time(),
            "last_seen_at": time.time(),
            "initialized": False,
            "client_info": {},
        }


def _unregister_session(session_id: str) -> None:
    with _LOCK:
        _SESSIONS.pop(session_id, None)


def _mark_initialized(session_id: str, client_info: Dict[str, Any] | None = None) -> None:
    with _LOCK:
        session = _SESSIONS.setdefault(
            session_id,
            {
                "session_id": session_id,
                "connected_at": time.time(),
                "last_seen_at": time.time(),
            },
        )
        session["initialized"] = True
        session["client_info"] = client_info or {}
        session["last_seen_at"] = time.time()


def _is_external_session(session: Dict[str, Any]) -> bool:
    client = session.get("client_info") or {}
    name = str(client.get("name") or "").lower()
    return name not in {"koto-ui", "koto", "koto-frontend"}


def get_mcp_ws_status() -> Dict[str, Any]:
    with _LOCK:
        sessions = [dict(item) for item in _SESSIONS.values()]
    external = [item for item in sessions if _is_external_session(item)]
    for item in sessions:
        client = item.get("client_info") or {}
        item["client_name"] = client.get("name", "")
    for item in external:
        client = item.get("client_info") or {}
        item["client_name"] = client.get("name", "")
    return {
        "success": True,
        "active_session_count": len(sessions),
        "active_external_session_count": len(external),
        "sessions": sessions,
        "external_sessions": external,
    }


class MCPWebSocketSession:
    """Small JSON-RPC MCP dispatcher shared by WebSocket and tests."""

    def __init__(self, session_id: str, tool_registry: Any = None) -> None:
        self.session_id = session_id
        self.tool_registry = tool_registry
        self.initialized = False
        _register_session(session_id)

    def close(self) -> None:
        _unregister_session(self.session_id)

    def _mcp_tools(self):
        from app.api.mcp_routes import _MCP_TOOLS

        return _MCP_TOOLS

    def _handle_initialize(self, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
        client_info = (params or {}).get("clientInfo") or {}
        self.initialized = True
        _mark_initialized(self.session_id, client_info)
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "koto-supervisor-ws", "version": "unknown"},
        }

    def _handle_tools_list(self) -> Dict[str, Any]:
        return {"tools": [tool for tool, _handler in self._mcp_tools().values()]}

    def _handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        from app.api.mcp_routes import _json_text

        name = params.get("name")
        arguments = params.get("arguments") or {}
        tools = self._mcp_tools()
        if name not in tools:
            return {
                "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                "isError": True,
            }
        _tool, handler = tools[name]
        data = handler(**arguments)
        return {"content": [{"type": "text", "text": _json_text(data)}], "isError": False}

    def handle_message(self, raw: str) -> str:
        payload = json.loads(raw)
        req_id = payload.get("id")
        method = payload.get("method", "")
        params = payload.get("params") or {}
        try:
            if method == "initialize":
                result = self._handle_initialize(params)
            elif method == "tools/list":
                result = self._handle_tools_list()
            elif method == "tools/call":
                result = self._handle_tools_call(params)
            else:
                return json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32601, "message": f"Method not found: {method}"},
                    },
                    ensure_ascii=False,
                )
            return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32603, "message": str(exc)},
                },
                ensure_ascii=False,
            )
