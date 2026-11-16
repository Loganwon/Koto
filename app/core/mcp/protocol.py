# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""MCP JSON-RPC 2.0 protocol message types as dataclasses.

Provides structured, serializable message types for MCP communication
that are easier to work with than raw TypedDicts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union


@dataclass
class MCPError:
    code: int
    message: str
    data: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            result["data"] = self.data
        return result


@dataclass
class MCPRequest:
    jsonrpc: str = "2.0"
    id: Optional[Union[int, str]] = None
    method: str = ""
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"jsonrpc": self.jsonrpc, "method": self.method}
        if self.id is not None:
            result["id"] = self.id
        if self.params:
            result["params"] = self.params
        return result

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def is_notification(self) -> bool:
        return self.id is None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPRequest":
        return cls(
            jsonrpc=data.get("jsonrpc", "2.0"),
            id=data.get("id"),
            method=data.get("method", ""),
            params=data.get("params") or {},
        )


@dataclass
class MCPResponse:
    jsonrpc: str = "2.0"
    id: Optional[Union[int, str]] = None
    result: Any = None
    error: Optional[MCPError] = None

    @property
    def is_error(self) -> bool:
        return self.error is not None

    @property
    def is_success(self) -> bool:
        return self.error is None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"jsonrpc": self.jsonrpc, "id": self.id}
        if self.error is not None:
            result["error"] = self.error.to_dict()
        else:
            result["result"] = self.result
        return result

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPResponse":
        error_data = data.get("error")
        return cls(
            jsonrpc=data.get("jsonrpc", "2.0"),
            id=data.get("id"),
            result=data.get("result"),
            error=MCPError(**error_data) if error_data else None,
        )

    @classmethod
    def success(cls, req_id: Optional[Union[int, str]], result: Any) -> "MCPResponse":
        return cls(jsonrpc="2.0", id=req_id, result=result)

    @classmethod
    def error_response(
        cls,
        req_id: Optional[Union[int, str]],
        code: int,
        message: str,
        data: Any = None,
    ) -> "MCPResponse":
        return cls(jsonrpc="2.0", id=req_id, error=MCPError(code, message, data))


@dataclass
class MCPTool:
    """Represents a tool exposed through the MCP protocol."""

    name: str
    description: str
    inputSchema: Dict[str, Any] = field(default_factory=dict)
    handler: Optional[Callable] = field(default=None, repr=False)
    annotations: Optional[Dict[str, Any]] = None

    def to_tool_def(self) -> Dict[str, Any]:
        """Convert to MCP tool listing format."""
        result: Dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.inputSchema
            or {
                "type": "object",
                "properties": {},
            },
        }
        if self.annotations:
            result["annotations"] = self.annotations
        return result

    def execute(self, arguments: Dict[str, Any]) -> Any:
        """Execute the tool handler with given arguments."""
        if self.handler is None:
            raise RuntimeError(f"Tool {self.name!r} has no handler registered")
        return self.handler(**arguments)


@dataclass
class MCPResource:
    """Represents a resource exposed through the MCP protocol."""

    uri: str
    name: str
    description: str = ""
    mimeType: Optional[str] = None
    handler: Optional[Callable[[], str]] = field(default=None, repr=False)

    def to_resource_def(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "uri": self.uri,
            "name": self.name,
        }
        if self.description:
            result["description"] = self.description
        if self.mimeType:
            result["mimeType"] = self.mimeType
        return result

    def read(self) -> str:
        if self.handler is None:
            raise RuntimeError(f"Resource {self.uri!r} has no handler registered")
        return self.handler()


@dataclass
class MCPPrompt:
    """Represents a prompt template exposed through the MCP protocol."""

    name: str
    description: str = ""
    arguments: List[Dict[str, Any]] = field(default_factory=list)
    handler: Optional[Callable[[Dict[str, Any]], List[Dict[str, Any]]]] = field(
        default=None, repr=False
    )

    def to_prompt_def(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"name": self.name}
        if self.description:
            result["description"] = self.description
        if self.arguments:
            result["arguments"] = self.arguments
        return result


# ── Re-export TypedDicts for convenience ────────────────────────────────────

from app.core.mcp.types import (  # noqa: E402
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    SERVER_NOT_INITIALIZED,
    UNKNOWN_ERROR,
)

__all__ = [
    "MCPError",
    "MCPRequest",
    "MCPResponse",
    "MCPTool",
    "MCPResource",
    "MCPPrompt",
    # Error codes
    "PARSE_ERROR",
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "INVALID_PARAMS",
    "INTERNAL_ERROR",
    "SERVER_NOT_INITIALIZED",
    "UNKNOWN_ERROR",
]
