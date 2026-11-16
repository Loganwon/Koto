# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""MCP Server — Koto as an MCP server exposing tools/resources to external clients.

Implements the server-side MCP protocol:
  - initialize: handshake with client
  - tools/list: list available tools
  - tools/call: execute a tool
  - resources/list: list available resources
  - resources/read: read a resource
  - prompts/list, prompts/get: prompt management
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional

from app.core.mcp.protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    SERVER_NOT_INITIALIZED,
    MCPError,
    MCPRequest,
    MCPResponse,
    MCPTool,
)
from app.core.mcp.resource_registry import MCPResourceRegistry
from app.core.mcp.tool_registry import MCPToolRegistry

logger = logging.getLogger(__name__)

DEFAULT_PROTOCOL_VERSION = "2024-11-05"


class MCPServer:
    """Koto MCP Server — exposes tools and resources to external MCP clients.

    Handles the full MCP JSON-RPC lifecycle:
      1. initialize → capabilities exchange
      2. tools/list, tools/call → tool execution
      3. resources/list, resources/read → resource access

    Usage:
        server = MCPServer(
            name="koto-supervisor",
            version="1.0.0",
        )
        server.tool_registry.register("hello", "Say hello", handler=lambda name: f"Hello {name}")
        response = server.handle_request(request)
    """

    def __init__(
        self,
        name: str = "koto-mcp-server",
        version: str = "unknown",
        protocol_version: str = DEFAULT_PROTOCOL_VERSION,
        instructions: Optional[str] = None,
    ):
        self.name = name
        self.version = version
        self.protocol_version = protocol_version
        self.instructions = instructions

        # Registries
        self.tool_registry = MCPToolRegistry()
        self.resource_registry = MCPResourceRegistry()

        # Per-session initialization state
        self._initialized_sessions: Dict[str, Dict[str, Any]] = {}

        # Additional capabilities
        self._capabilities: Dict[str, Any] = {
            "tools": {},
            "resources": {},
            "prompts": {},
        }

    # ── Capability Configuration ────────────────────────────────────────────

    def enable_tools(self, list_changed: bool = True) -> None:
        self._capabilities["tools"] = {"listChanged": list_changed}

    def enable_resources(
        self, subscribe: bool = False, list_changed: bool = False
    ) -> None:
        self._capabilities["resources"] = {
            "subscribe": subscribe,
            "listChanged": list_changed,
        }

    def enable_prompts(self, list_changed: bool = False) -> None:
        self._capabilities["prompts"] = {"listChanged": list_changed}

    def disable_capability(self, name: str) -> None:
        self._capabilities.pop(name, None)

    @property
    def capabilities(self) -> Dict[str, Any]:
        return dict(self._capabilities)

    # ── Request Handling ────────────────────────────────────────────────────

    def handle_request(self, raw_request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle a raw JSON-RPC request dict and return a response dict."""
        try:
            req = MCPRequest.from_dict(raw_request)
        except Exception as e:
            return MCPResponse.error_response(None, PARSE_ERROR, str(e)).to_dict()

        # Notifications (no id) — no response expected
        if req.is_notification():
            self._handle_notification(req)
            return {}

        response = self._dispatch(req)
        return response.to_dict()

    def handle_request_json(self, raw_json: str) -> str:
        """Handle a JSON-RPC request string and return a response JSON string."""
        try:
            raw = json.loads(raw_json)
        except json.JSONDecodeError as e:
            return MCPResponse.error_response(None, PARSE_ERROR, str(e)).to_json()
        result = self.handle_request(raw)
        return json.dumps(result, ensure_ascii=False) if result else ""

    def _dispatch(self, req: MCPRequest) -> MCPResponse:
        """Route a request to the appropriate handler method."""
        method = req.method
        req_id = req.id

        try:
            if method == "initialize":
                return self._handle_initialize(req_id, req.params)
            elif method == "initialized":
                return self._handle_initialized(req_id, req.params)
            elif method == "tools/list":
                return self._handle_tools_list(req_id)
            elif method == "tools/call":
                return self._handle_tools_call(req_id, req.params)
            elif method == "resources/list":
                return self._handle_resources_list(req_id)
            elif method == "resources/read":
                return self._handle_resources_read(req_id, req.params)
            elif method == "resources/templates/list":
                return self._handle_resources_templates_list(req_id)
            elif method == "prompts/list":
                return self._handle_prompts_list(req_id)
            elif method == "prompts/get":
                return self._handle_prompts_get(req_id, req.params)
            elif method == "ping":
                return MCPResponse.success(req_id, {})
            else:
                return MCPResponse.error_response(
                    req_id, METHOD_NOT_FOUND, f"Method not found: {method}"
                )
        except Exception as e:
            logger.exception("[MCPServer] error handling method %s: %s", method, e)
            return MCPResponse.error_response(req_id, INTERNAL_ERROR, str(e))

    # ── initialize ──────────────────────────────────────────────────────────

    def _handle_initialize(self, req_id: Any, params: Dict[str, Any]) -> MCPResponse:
        client_info = params.get("clientInfo") or {}
        session_id = params.get("_meta", {}).get("sessionId", "")
        client_protocol = params.get("protocolVersion", self.protocol_version)

        if session_id:
            self._initialized_sessions[session_id] = {
                "client_info": client_info,
                "protocol_version": client_protocol,
                "initialized_at": __import__("time").time(),
            }

        result = {
            "protocolVersion": self.protocol_version,
            "capabilities": self._capabilities,
            "serverInfo": {
                "name": self.name,
                "version": self.version,
            },
        }
        if self.instructions:
            result["instructions"] = self.instructions
        if session_id:
            result["_meta"] = {"sessionId": session_id}

        return MCPResponse.success(req_id, result)

    def _handle_initialized(self, req_id: Any, params: Dict[str, Any]) -> MCPResponse:
        # Acknowledgment notification — client confirms init complete
        return MCPResponse.success(req_id, {})

    # ── tools/* ─────────────────────────────────────────────────────────────

    def _handle_tools_list(self, req_id: Any) -> MCPResponse:
        tools = self.tool_registry.list_tools()
        return MCPResponse.success(req_id, {"tools": tools})

    def _handle_tools_call(self, req_id: Any, params: Dict[str, Any]) -> MCPResponse:
        tool_name = params.get("name", "")
        arguments = params.get("arguments") or {}

        if not tool_name:
            return MCPResponse.error_response(
                req_id, INVALID_PARAMS, "Missing required parameter: name"
            )

        try:
            result = self.tool_registry.call_tool(tool_name, arguments)
            # Format result as MCP content
            if isinstance(result, (dict, list)):
                text = json.dumps(result, ensure_ascii=False, indent=2)
            else:
                text = str(result)

            return MCPResponse.success(
                req_id,
                {
                    "content": [{"type": "text", "text": text}],
                    "isError": False,
                },
            )
        except KeyError as e:
            return MCPResponse.error_response(
                req_id, INVALID_PARAMS, f"Unknown tool: {e}"
            )
        except Exception as e:
            logger.exception("[MCPServer] tool call failed: %s", tool_name)
            return MCPResponse.success(
                req_id,
                {
                    "content": [{"type": "text", "text": str(e)}],
                    "isError": True,
                },
            )

    # ── resources/* ─────────────────────────────────────────────────────────

    def _handle_resources_list(self, req_id: Any) -> MCPResponse:
        resources = self.resource_registry.list_resources()
        return MCPResponse.success(req_id, {"resources": resources})

    def _handle_resources_read(
        self, req_id: Any, params: Dict[str, Any]
    ) -> MCPResponse:
        uri = params.get("uri", "")
        if not uri:
            return MCPResponse.error_response(
                req_id, INVALID_PARAMS, "Missing required parameter: uri"
            )
        try:
            content = self.resource_registry.read_resource(uri)
            return MCPResponse.success(
                req_id, {"contents": [{"uri": uri, "text": content}]}
            )
        except KeyError:
            return MCPResponse.error_response(
                req_id, INVALID_PARAMS, f"Resource not found: {uri}"
            )

    def _handle_resources_templates_list(self, req_id: Any) -> MCPResponse:
        templates = self.resource_registry.list_templates()
        return MCPResponse.success(req_id, {"resourceTemplates": templates})

    # ── prompts/* ───────────────────────────────────────────────────────────

    def _handle_prompts_list(self, req_id: Any) -> MCPResponse:
        return MCPResponse.success(req_id, {"prompts": []})

    def _handle_prompts_get(self, req_id: Any, params: Dict[str, Any]) -> MCPResponse:
        return MCPResponse.success(req_id, {"messages": []})

    # ── Notifications ───────────────────────────────────────────────────────

    def _handle_notification(self, req: MCPRequest) -> None:
        method = req.method
        if method == "notifications/initialized":
            logger.debug("[MCPServer] client initialized notification received")
        elif method == "notifications/cancelled":
            logger.debug("[MCPServer] cancellation notification: %s", req.params)
        else:
            logger.debug("[MCPServer] unhandled notification: %s", method)

    # ── Diagnostics ─────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "protocol_version": self.protocol_version,
            "capabilities": self._capabilities,
            "tools": self.tool_registry.status(),
            "resources": self.resource_registry.status(),
            "initialized_sessions": len(self._initialized_sessions),
        }

    # ── Koto Tool Bootstrap ─────────────────────────────────────────────────

    def bootstrap_koto_tools(self) -> int:
        """Register all Koto built-in tools in this MCP server.

        Imports tools from the UnifiedToolRegistry and registers them
        with the MCP tool_registry so external MCP clients can discover
        and call Koto's built-in capabilities.

        Returns the number of tools registered.
        """
        try:
            from app.core.toolkits import get_unified_tool_registry

            unified = get_unified_tool_registry()
        except Exception as exc:
            logger.warning("[MCPServer] unified registry unavailable: %s", exc)
            return 0

        count = 0
        for record in unified.list_tools():
            try:
                self.tool_registry.register(
                    name=record.name,
                    description=record.description,
                    input_schema=record.parameters
                    or {"type": "object", "properties": {}},
                    handler=record.handler,
                    annotations={"readOnlyHint": bool(record.read_only)},
                    source_prefix=record.source.value,
                )
                count += 1
            except Exception as exc:
                logger.debug("[MCPServer] skip tool %s: %s", record.name, exc)

        logger.info("[MCPServer] bootstrapped %d Koto tools", count)
        self.enable_tools()
        return count


__all__ = ["MCPServer", "DEFAULT_PROTOCOL_VERSION"]
