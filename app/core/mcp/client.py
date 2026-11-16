# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""MCP Client — Koto as an MCP client connecting to external MCP servers.

Provides a clean client interface for:
  - Connecting to MCP servers via stdio/WebSocket/SSE transports
  - Calling tools on remote MCP servers
  - Listing tools and resources
  - Managing connection lifecycle

This is a higher-level abstraction over the transport layer. For lower-level
transport access, use app.core.mcp.transport directly.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from app.core.mcp.protocol import MCPRequest, MCPResponse, MCPTool
from app.core.mcp.transport import (
    SSETransport,
    StdioTransport,
    Transport,
    WebSocketTransport,
    create_transport,
)

logger = logging.getLogger(__name__)


class MCPClient:
    """Client for connecting to and interacting with an external MCP server.

    Usage:
        client = MCPClient("my-server", transport=StdioTransport(command=["npx", "..."]))
        client.connect()
        tools = client.list_tools()
        result = client.call_tool("read_file", {"path": "/tmp/test.txt"})
        client.disconnect()
    """

    def __init__(
        self,
        name: str,
        transport: Optional[Transport] = None,
        protocol_version: str = "2024-11-05",
        connect_timeout: float = 30.0,
        request_timeout: float = 30.0,
    ):
        self.name = name
        self.transport: Optional[Transport] = transport
        self.protocol_version = protocol_version
        self.connect_timeout = connect_timeout
        self.request_timeout = request_timeout

        self._server_info: Dict[str, Any] = {}
        self._server_capabilities: Dict[str, Any] = {}
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._connected = False
        self._initialized = False
        self._req_id = 0

    # ── Connection Lifecycle ────────────────────────────────────────────────

    def connect(self) -> bool:
        """Connect to the MCP server and perform initialization handshake."""
        if self._connected:
            return True
        if self.transport is None:
            raise RuntimeError("No transport configured for MCP client")

        try:
            self.transport.connect()
            self._connected = True
            logger.info(
                "[MCPClient] connected to %s via %s", self.name, self.transport.kind
            )

            # Initialize handshake
            init_result = self._initialize()
            if init_result:
                self._initialized = True
                logger.info(
                    "[MCPClient] initialized %s: %s", self.name, self._server_info
                )
                # Load tools
                self._load_tools()
            return self._initialized
        except Exception:
            self._connected = False
            logger.exception("[MCPClient] connection to %s failed", self.name)
            raise

    def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        self._connected = False
        self._initialized = False
        self._tools.clear()
        if self.transport is not None:
            try:
                self.transport.disconnect()
            except Exception:
                pass
        logger.info("[MCPClient] disconnected from %s", self.name)

    def _initialize(self) -> bool:
        """Perform the MCP initialize handshake."""
        params: Dict[str, Any] = {
            "protocolVersion": self.protocol_version,
            "capabilities": {
                "roots": {},
                "sampling": {},
            },
            "clientInfo": {
                "name": "koto",
                "version": "unknown",
            },
        }

        response = self._send_request("initialize", params)
        if response.error:
            logger.error("[MCPClient] initialize failed: %s", response.error)
            return False

        result = response.result or {}
        self._server_info = result.get("serverInfo", {})
        self._server_capabilities = result.get("capabilities", {})

        # Send initialized notification
        self._send_notification("notifications/initialized", {})
        return True

    # ── Tool Operations ─────────────────────────────────────────────────────

    def _load_tools(self) -> None:
        """Fetch the tool list from the server."""
        response = self._send_request("tools/list", {})
        if response.error:
            logger.warning("[MCPClient] tools/list failed: %s", response.error)
            return
        tools_data = (response.result or {}).get("tools", [])
        self._tools = {t["name"]: t for t in tools_data}
        logger.info("[MCPClient] loaded %d tools from %s", len(self._tools), self.name)

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return the cached list of tools (requires connect first)."""
        return list(self._tools.values())

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Call a tool on the remote MCP server."""
        if not self._initialized:
            raise RuntimeError(f"MCP client {self.name!r} not initialized")

        response = self._send_request(
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments,
            },
        )

        if response.error:
            raise RuntimeError(
                f"MCP tool call failed: {response.error.code} {response.error.message}"
            )

        result = response.result or {}
        if result.get("isError"):
            content = result.get("content", [])
            error_text = ""
            for item in content:
                if item.get("type") == "text":
                    error_text += item.get("text", "")
            raise RuntimeError(f"MCP tool {tool_name!r} returned error: {error_text}")

        return result

    # ── Resource Operations ─────────────────────────────────────────────────

    def list_resources(self) -> List[Dict[str, Any]]:
        """List resources from the server."""
        response = self._send_request("resources/list", {})
        if response.error:
            return []
        return (response.result or {}).get("resources", [])

    def read_resource(self, uri: str) -> Dict[str, Any]:
        """Read a resource by URI."""
        if not self._initialized:
            raise RuntimeError(f"MCP client {self.name!r} not initialized")
        response = self._send_request("resources/read", {"uri": uri})
        if response.error:
            raise RuntimeError(f"Resource read failed: {response.error.message}")
        return response.result or {}

    # ── JSON-RPC Communication ──────────────────────────────────────────────

    def _send_request(self, method: str, params: Dict[str, Any]) -> MCPResponse:
        """Send a JSON-RPC request and wait for the response."""
        self._req_id += 1
        req = MCPRequest(
            jsonrpc="2.0",
            id=self._req_id,
            method=method,
            params=params,
        )
        return self._send_and_receive(req)

    def _send_notification(self, method: str, params: Dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        req = MCPRequest(jsonrpc="2.0", method=method, params=params)
        self._send_raw(req.to_json().encode())

    def _send_and_receive(self, req: MCPRequest) -> MCPResponse:
        """Send a request and parse the response."""
        if self.transport is None:
            raise RuntimeError("No transport configured")

        payload = req.to_json().encode() + b"\n"
        self.transport.send(payload)

        raw = self.transport.receive(timeout=self.request_timeout)
        if raw is None:
            raise TimeoutError(
                f"MCP request {req.method!r} timed out after {self.request_timeout}s"
            )

        try:
            data = json.loads(raw.decode().strip())
            return MCPResponse.from_dict(data)
        except json.JSONDecodeError as e:
            logger.error("[MCPClient] invalid response: %s", e)
            raise RuntimeError(f"Invalid JSON response from MCP server: {e}") from e

    def _send_raw(self, payload: bytes) -> None:
        """Send raw bytes to the transport."""
        if self.transport is None:
            raise RuntimeError("No transport configured")
        self.transport.send(payload)

    # ── Properties ──────────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def initialized(self) -> bool:
        return self._initialized

    @property
    def server_info(self) -> Dict[str, Any]:
        return dict(self._server_info)

    @property
    def server_capabilities(self) -> Dict[str, Any]:
        return dict(self._server_capabilities)

    @property
    def tools(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._tools)

    # ── Diagnostics ─────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "connected": self._connected,
            "initialized": self._initialized,
            "transport_kind": self.transport.kind if self.transport else "none",
            "server_info": self._server_info,
            "tool_count": len(self._tools),
            "tool_names": sorted(self._tools.keys()),
        }


__all__ = ["MCPClient"]
