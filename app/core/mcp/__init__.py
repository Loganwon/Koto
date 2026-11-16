# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""MCP (Model Context Protocol) support modules.

Protocol spec: https://modelcontextprotocol.io/specification

Package structure:
  protocol.py      — JSON-RPC 2.0 message dataclasses
  types.py         — TypedDict type definitions
  transport.py     — Transport abstraction (stdio/WebSocket/SSE)
  server.py        — MCP Server (Koto exposes tools to external clients)
  client.py        — MCP Client (Koto connects to external MCP servers)
  tool_registry.py     — MCP tool registration and execution
  resource_registry.py — MCP resource registration and serving
  session_manager.py   — Session lifecycle management
  session_store.py     — Low-level session storage (legacy)
"""

from app.core.mcp.client import MCPClient
from app.core.mcp.protocol import (
    MCPError,
    MCPRequest,
    MCPResource,
    MCPResponse,
    MCPTool,
)
from app.core.mcp.resource_registry import MCPResourceRegistry
from app.core.mcp.server import DEFAULT_PROTOCOL_VERSION, MCPServer
from app.core.mcp.session_manager import (
    MCPSessionManager,
    get_session_manager,
    reset_session_manager,
)
from app.core.mcp.session_store import (
    get_mcp_ws_status,
    mark_initialized,
    register_session,
    unregister_session,
)
from app.core.mcp.tool_registry import (
    MCPToolRegistry,
    get_global_tool_registry,
    reset_global_tool_registry,
)
from app.core.mcp.transport import (
    AsyncTransport,
    SSETransport,
    StdioTransport,
    Transport,
    WebSocketTransport,
    create_transport,
)
from app.core.mcp.types import (  # Base; MCP Protocol; Resources; Transport; Session; Error codes
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    SERVER_NOT_INITIALIZED,
    UNKNOWN_ERROR,
    CallToolParams,
    CallToolResult,
    ClientInfo,
    InitializeParams,
    InitializeResult,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    ReadResourceParams,
    ReadResourceResult,
    Resource,
    ResourceTemplate,
    ServerInfo,
    SessionInfo,
    SSETransportConfig,
    StdioTransportConfig,
    Tool,
    ToolInputSchema,
    TransportKind,
    WebSocketTransportConfig,
)

__all__ = [
    # Protocol
    "MCPError",
    "MCPRequest",
    "MCPResponse",
    "MCPTool",
    "MCPResource",
    # Server
    "MCPServer",
    "DEFAULT_PROTOCOL_VERSION",
    # Client
    "MCPClient",
    # Registries
    "MCPToolRegistry",
    "MCPResourceRegistry",
    "get_global_tool_registry",
    "reset_global_tool_registry",
    # Session
    "MCPSessionManager",
    "get_session_manager",
    "reset_session_manager",
    "register_session",
    "unregister_session",
    "mark_initialized",
    "get_mcp_ws_status",
    # Transport
    "Transport",
    "AsyncTransport",
    "StdioTransport",
    "WebSocketTransport",
    "SSETransport",
    "create_transport",
    # Types
    "JSONRPCRequest",
    "JSONRPCError",
    "JSONRPCResponse",
    "ClientInfo",
    "ServerInfo",
    "InitializeParams",
    "InitializeResult",
    "ToolInputSchema",
    "Tool",
    "CallToolParams",
    "CallToolResult",
    "Resource",
    "ResourceTemplate",
    "ReadResourceParams",
    "ReadResourceResult",
    "TransportKind",
    "StdioTransportConfig",
    "WebSocketTransportConfig",
    "SSETransportConfig",
    "SessionInfo",
    # Error codes
    "PARSE_ERROR",
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "INVALID_PARAMS",
    "INTERNAL_ERROR",
    "SERVER_NOT_INITIALIZED",
    "UNKNOWN_ERROR",
]
