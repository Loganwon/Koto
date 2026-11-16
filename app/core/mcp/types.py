# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Type definitions for MCP (Model Context Protocol) JSON-RPC 2.0 messages.

Protocol spec: https://modelcontextprotocol.io/specification
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict, Union

# ── JSON-RPC 2.0 Base ────────────────────────────────────────────────────────


class JSONRPCRequest(TypedDict, total=False):
    jsonrpc: str  # "2.0"
    id: Union[int, str]
    method: str
    params: Optional[Dict[str, Any]]


class JSONRPCError(TypedDict):
    code: int
    message: str
    data: Optional[Any]


class JSONRPCResponse(TypedDict, total=False):
    jsonrpc: str
    id: Union[int, str]
    result: Optional[Any]
    error: Optional[JSONRPCError]


# ── MCP Protocol Types ──────────────────────────────────────────────────────


class ClientInfo(TypedDict, total=False):
    name: str
    version: str


class ServerInfo(TypedDict, total=False):
    name: str
    version: str


class InitializeParams(TypedDict, total=False):
    protocolVersion: str
    capabilities: Dict[str, Any]
    clientInfo: Optional[ClientInfo]


class InitializeResult(TypedDict, total=False):
    protocolVersion: str
    capabilities: Dict[str, Any]
    serverInfo: ServerInfo
    instructions: Optional[str]


class ToolInputSchema(TypedDict, total=False):
    type: str  # "object"
    properties: Dict[str, Any]
    required: Optional[List[str]]


class ToolAnnotations(TypedDict, total=False):
    readOnlyHint: bool
    destructiveHint: bool
    idempotentHint: bool
    openWorldHint: bool


class Tool(TypedDict, total=False):
    name: str
    description: str
    inputSchema: ToolInputSchema
    annotations: Optional[ToolAnnotations]


class CallToolParams(TypedDict, total=False):
    name: str
    arguments: Optional[Dict[str, Any]]


class TextContent(TypedDict):
    type: Literal["text"]
    text: str


class ImageContent(TypedDict):
    type: Literal["image"]
    data: str
    mimeType: str


class ResourceContent(TypedDict):
    type: Literal["resource"]
    resource: Dict[str, Any]


ContentBlock = Union[TextContent, ImageContent, ResourceContent]


class CallToolResult(TypedDict, total=False):
    content: List[ContentBlock]
    isError: bool


# ── Resource Types ──────────────────────────────────────────────────────────


class Resource(TypedDict, total=False):
    uri: str
    name: str
    description: str
    mimeType: Optional[str]


class ResourceTemplate(TypedDict, total=False):
    uriTemplate: str
    name: str
    description: str
    mimeType: Optional[str]


class ReadResourceParams(TypedDict):
    uri: str


class ReadResourceResult(TypedDict, total=False):
    contents: List[Dict[str, Any]]


# ── Prompt Types ────────────────────────────────────────────────────────────


class Prompt(TypedDict, total=False):
    name: str
    description: str
    arguments: Optional[List[Dict[str, Any]]]


class GetPromptParams(TypedDict, total=False):
    name: str
    arguments: Optional[Dict[str, str]]


# ── Transport Types ─────────────────────────────────────────────────────────

TransportKind = Literal["stdio", "websocket", "sse"]


class StdioTransportConfig(TypedDict, total=False):
    command: str
    args: List[str]
    env: Optional[Dict[str, str]]
    cwd: Optional[str]


class WebSocketTransportConfig(TypedDict, total=False):
    url: str
    headers: Optional[Dict[str, str]]


class SSETransportConfig(TypedDict, total=False):
    url: str
    headers: Optional[Dict[str, str]]


# ── Session Types ───────────────────────────────────────────────────────────


class SessionInfo(TypedDict, total=False):
    session_id: str
    connected_at: float
    last_seen_at: float
    initialized: bool
    client_info: Dict[str, Any]
    server_info: Optional[ServerInfo]
    protocol_version: str
    transport_kind: TransportKind


# ── Capability Types ────────────────────────────────────────────────────────


class ServerCapabilities(TypedDict, total=False):
    tools: Optional[Dict[str, Any]]
    resources: Optional[Dict[str, Any]]
    prompts: Optional[Dict[str, Any]]
    logging: Optional[Dict[str, Any]]


class ClientCapabilities(TypedDict, total=False):
    roots: Optional[Dict[str, Any]]
    sampling: Optional[Dict[str, Any]]


# ── Error Codes ─────────────────────────────────────────────────────────────

# Standard JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# MCP-specific error codes (server errors range: -32000 to -32099)
SERVER_NOT_INITIALIZED = -32002
UNKNOWN_ERROR = -32001


__all__ = [
    # Base
    "JSONRPCRequest",
    "JSONRPCError",
    "JSONRPCResponse",
    # MCP Protocol
    "ClientInfo",
    "ServerInfo",
    "InitializeParams",
    "InitializeResult",
    "ToolInputSchema",
    "ToolAnnotations",
    "Tool",
    "CallToolParams",
    "TextContent",
    "ImageContent",
    "ResourceContent",
    "ContentBlock",
    "CallToolResult",
    # Resources
    "Resource",
    "ResourceTemplate",
    "ReadResourceParams",
    "ReadResourceResult",
    # Prompts
    "Prompt",
    "GetPromptParams",
    # Transport
    "TransportKind",
    "StdioTransportConfig",
    "WebSocketTransportConfig",
    "SSETransportConfig",
    # Session
    "SessionInfo",
    # Capabilities
    "ServerCapabilities",
    "ClientCapabilities",
    # Error codes
    "PARSE_ERROR",
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "INVALID_PARAMS",
    "INTERNAL_ERROR",
    "SERVER_NOT_INITIALIZED",
    "UNKNOWN_ERROR",
]
