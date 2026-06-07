# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
MCP routes for Koto.

Two purposes:
- REST diagnostics for Koto's configured outbound MCP servers.
- A small HTTP JSON-RPC MCP endpoint that external coding agents can use to
  inspect Koto without needing to know Koto's internal Python modules.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict

from flask import Blueprint, jsonify, request

from app.core.agent.koto_supervision import (
    agent_tool_inventory,
    read_file_snippet,
    recent_events,
    recent_file_changes,
    route_map,
    run_tests,
    search_code,
    test_status,
)
from app.core.agent.mcp_manager import get_mcp_status, reload_mcp_runtime

logger = logging.getLogger(__name__)

mcp_bp = Blueprint("mcp", __name__, url_prefix="/api/mcp")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_version() -> str:
    try:
        return (_project_root() / "VERSION").read_text(encoding="utf-8").strip()
    except Exception:
        return "unknown"


def _json_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _tool_schema(
    name: str,
    description: str,
    properties: Dict | None = None,
    required: list[str] | None = None,
    read_only: bool = True,
) -> Dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
        },
        "annotations": {
            "readOnlyHint": read_only,
            "openWorldHint": False,
        },
    }


def _koto_health(**_: Any) -> Dict[str, Any]:
    root = _project_root()
    return {
        "name": "Koto",
        "version": _read_version(),
        "root": str(root),
        "workspace": os.environ.get("KOTO_WORKSPACE", str(root / "workspace")),
        "mcp": get_mcp_status(),
    }


def _koto_mcp_status(**_: Any) -> Dict[str, Any]:
    return get_mcp_status()


def _koto_skill_inventory(limit: int = 50, **_: Any) -> Dict[str, Any]:
    from app.core.skills.skill_manager import SkillManager

    skills = SkillManager.list_skills()
    visible = skills[: max(1, min(int(limit or 50), 200))]
    return {
        "count": len(skills),
        "returned": len(visible),
        "skills": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "category": item.get("category"),
                "enabled": item.get("enabled"),
                "description": item.get("description", ""),
            }
            for item in visible
        ],
    }


def _koto_project_overview(**_: Any) -> Dict[str, Any]:
    root = _project_root()
    top_level = []
    for path in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if path.name in {".git", ".venv", ".nodeenv", "__pycache__"}:
            continue
        top_level.append(
            {
                "name": path.name,
                "type": "dir" if path.is_dir() else "file",
                "size": path.stat().st_size if path.is_file() else None,
            }
        )
    return {
        "root": str(root),
        "top_level": top_level[:100],
        "important_paths": [
            "app/core/agent",
            "app/api",
            "web/app_blueprints.py",
            "config/user_settings.json",
            "tests",
        ],
    }


_MCP_TOOLS: Dict[str, tuple[Dict[str, Any], Callable[..., Any]]] = {
    "koto_health": (
        _tool_schema("koto_health", "Return Koto version, workspace, and MCP health."),
        _koto_health,
    ),
    "koto_mcp_status": (
        _tool_schema("koto_mcp_status", "Return configured MCP server status."),
        _koto_mcp_status,
    ),
    "koto_skill_inventory": (
        _tool_schema(
            "koto_skill_inventory",
            "List Koto skills for supervision and routing diagnostics.",
            {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "description": "Maximum number of skills to return.",
                }
            },
        ),
        _koto_skill_inventory,
    ),
    "koto_project_overview": (
        _tool_schema(
            "koto_project_overview",
            "Return top-level project structure and important Koto paths.",
        ),
        _koto_project_overview,
    ),
    "koto_recent_file_changes": (
        _tool_schema(
            "koto_recent_file_changes",
            "Return current git status so an agent can attribute recent file changes.",
            {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "description": "Maximum number of changed files to return.",
                }
            },
        ),
        recent_file_changes,
    ),
    "koto_recent_events": (
        _tool_schema(
            "koto_recent_events",
            "Return recent tails from Koto log files.",
            {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum number of log entries to return.",
                }
            },
        ),
        recent_events,
    ),
    "koto_read_file_snippet": (
        _tool_schema(
            "koto_read_file_snippet",
            "Read a bounded snippet from a text file inside the Koto project.",
            {
                "path": {
                    "type": "string",
                    "description": "Project-relative file path.",
                },
                "start_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "First 1-based line number to read.",
                },
                "max_chars": {
                    "type": "integer",
                    "minimum": 200,
                    "maximum": 20000,
                    "description": "Maximum snippet size in characters.",
                },
            },
            required=["path"],
        ),
        read_file_snippet,
    ),
    "koto_search_code": (
        _tool_schema(
            "koto_search_code",
            "Search Koto source code with ripgrep, constrained to the project root.",
            {
                "pattern": {
                    "type": "string",
                    "description": "Search pattern passed to ripgrep.",
                },
                "path": {
                    "type": "string",
                    "description": "Project-relative directory or file to search.",
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "description": "Maximum number of matches to return.",
                },
            },
            required=["pattern"],
        ),
        search_code,
    ),
    "koto_route_map": (
        _tool_schema(
            "koto_route_map",
            "Return Flask routes registered in the current Koto app.",
            {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000,
                    "description": "Maximum routes to return.",
                }
            },
        ),
        route_map,
    ),
    "koto_agent_tool_inventory": (
        _tool_schema(
            "koto_agent_tool_inventory",
            "Build a Koto agent tool registry and return available tools.",
            {
                "full": {
                    "type": "boolean",
                    "description": "Whether to include the full UnifiedAgent tool set.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000,
                    "description": "Maximum tools to return.",
                },
            },
        ),
        agent_tool_inventory,
    ),
    "koto_run_tests": (
        _tool_schema(
            "koto_run_tests",
            "Run a constrained pytest command against targets under tests/.",
            {
                "targets": {
                    "type": ["string", "array"],
                    "description": "A test path or list of test paths/node ids under tests/.",
                },
                "timeout": {
                    "type": "integer",
                    "minimum": 5,
                    "maximum": 300,
                    "description": "Timeout in seconds.",
                },
            },
            read_only=False,
        ),
        run_tests,
    ),
    "koto_test_status": (
        _tool_schema(
            "koto_test_status",
            "Return the latest pytest result triggered through koto_run_tests.",
        ),
        test_status,
    ),
}


@mcp_bp.route("", methods=["GET"])
def mcp_status():
    """REST status entry for Koto MCP integration."""
    return jsonify(
        {
            "success": True,
            "endpoint": "/api/mcp",
            "json_rpc": True,
            "tools_endpoint": "/api/mcp/tools",
            "reload_endpoint": "/api/mcp/reload",
            "status": get_mcp_status(),
        }
    )


@mcp_bp.route("/tools", methods=["GET"])
def mcp_tools():
    """List the read-only tools exposed by Koto's MCP supervision endpoint."""
    tools = [tool for tool, _handler in _MCP_TOOLS.values()]
    return jsonify({"success": True, "count": len(tools), "tools": tools})


@mcp_bp.route("/reload", methods=["POST"])
def mcp_reload():
    """Reload outbound MCP server configuration from user_settings.json."""
    try:
        return jsonify({"success": True, "status": reload_mcp_runtime()})
    except Exception as exc:
        logger.warning("[MCPRoutes] reload failed: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500


@mcp_bp.route("", methods=["POST"])
def mcp_json_rpc():
    """Minimal HTTP JSON-RPC MCP endpoint for external coding agents."""
    payload = request.get_json(silent=True) or {}
    req_id = payload.get("id")
    method = payload.get("method", "")
    params = payload.get("params") or {}

    if not req_id and method.startswith("notifications/"):
        return ("", 204)

    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "koto-supervisor", "version": _read_version()},
            }
        elif method == "tools/list":
            result = {"tools": [tool for tool, _handler in _MCP_TOOLS.values()]}
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments") or {}
            if tool_name not in _MCP_TOOLS:
                return _rpc_error(req_id, -32602, f"Unknown tool: {tool_name}"), 400
            _tool, handler = _MCP_TOOLS[tool_name]
            data = handler(**arguments)
            result = {
                "content": [{"type": "text", "text": _json_text(data)}],
                "isError": False,
            }
        else:
            return _rpc_error(req_id, -32601, f"Method not found: {method}"), 404

        return jsonify({"jsonrpc": "2.0", "id": req_id, "result": result})
    except Exception as exc:
        logger.warning("[MCPRoutes] JSON-RPC failed: %s", exc, exc_info=True)
        return _rpc_error(req_id, -32603, str(exc)), 500


def _rpc_error(req_id: Any, code: int, message: str):
    return jsonify(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }
    )
