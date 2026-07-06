# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Minimal WebSocket-side MCP session support for Koto supervision tools."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, Dict

from app.core.mcp.session_store import (
    get_mcp_ws_status,
    mark_initialized,
    register_session,
    unregister_session,
)

from flask import request

# Backward-compatible aliases for internal use
_register_session = register_session
_unregister_session = unregister_session
_mark_initialized = mark_initialized


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
        raw = str(raw).lstrip("\ufeff")
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


def _authorized_ws_request() -> bool:
    required_key = os.environ.get("KOTO_MCP_API_KEY", "").strip()
    if not required_key:
        return True
    bearer = request.headers.get("Authorization", "")
    provided = (
        request.headers.get("X-Koto-MCP-Key")
        or request.args.get("key")
        or (bearer.removeprefix("Bearer ").strip() if bearer.startswith("Bearer ") else "")
    )
    return provided == required_key


def register_mcp_ws(sock: Any) -> None:
    """Register Koto's external MCP WebSocket endpoint on a Flask-Sock instance."""

    @sock.route("/ws/mcp")
    def ws_mcp(ws):
        if not _authorized_ws_request():
            ws.close()
            return
        session = MCPWebSocketSession(f"mcp-ws-{uuid.uuid4().hex}")
        try:
            while True:
                raw = ws.receive()
                if raw is None:
                    break
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                ws.send(session.handle_message(str(raw)))
        finally:
            session.close()
