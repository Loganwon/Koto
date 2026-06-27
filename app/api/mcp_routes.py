# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
MCP routes for Koto.

Supports three transports for external coding agents:
  - Streamable HTTP (POST JSON-RPC, preferred)
  - SSE transport   (GET SSE stream + POST JSON-RPC)
  - REST diagnostics for Koto's configured outbound MCP servers
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict

from flask import Blueprint, Response, jsonify, request, stream_with_context

from app.core.agent.koto_supervision import (
    agent_tool_inventory,
    recent_tasks,
    read_file_snippet,
    recent_events,
    recent_file_changes,
    route_map,
    run_tests,
    search_code,
    task_progress_history,
    task_status,
    test_status,
    project_root,
    resolve_project_path,
)
from app.core.agent.frontend_observability import (
    complete_frontend_action,
    enqueue_frontend_action,
    frontend_action_status,
    frontend_events,
    frontend_snapshot,
    frontend_surface_inventory,
    next_frontend_action,
    record_frontend_event,
)
from app.core.agent.mcp_manager import get_mcp_status, reload_mcp_runtime

logger = logging.getLogger(__name__)

mcp_bp = Blueprint("mcp", __name__, url_prefix="/api/mcp")

# ── SSE session store ──────────────────────────────────────────────────
_sse_sessions: Dict[str, Dict[str, Any]] = {}
_SESSION_TTL = 300  # 5 min idle timeout


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
    data = dict(get_mcp_status() or {})
    data["exposed_tool_count"] = len(_MCP_TOOLS)
    return data


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


def _koto_write_file(path: str = "", content: str = "", **_: Any) -> Dict[str, Any]:
    try:
        resolved = resolve_project_path(path)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return {"success": True, "path": str(resolved), "written": len(content)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _koto_read_file(path: str = "", max_chars: int = 50000, **_: Any) -> Dict[str, Any]:
    try:
        resolved = resolve_project_path(path)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    try:
        text = resolved.read_text(encoding="utf-8", errors="replace")
        limit = max(200, min(int(max_chars or 50000), 100000))
        result = text[:limit]
        return {
            "success": True,
            "path": str(resolved),
            "content": result,
            "truncated": len(text) > limit,
            "total_chars": len(text),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _koto_run_shell(
    command: str = "",
    timeout: int = 30,
    workdir: str = "",
    **_: Any,
) -> Dict[str, Any]:
    import subprocess as _sp
    root = project_root()
    cwd = root / workdir if workdir else root
    if not cwd.exists():
        cwd = root
    try:
        proc = _sp.run(
            command,
            shell=True,  # nosec B602 — MCP server commands come from vetted configuration
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=max(5, min(int(timeout or 30), 120)),
        )
        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[:20000],
            "stderr": (proc.stderr or "")[:5000],
        }
    except _sp.TimeoutExpired:
        return {"success": False, "error": f"Command timed out after {timeout}s"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _koto_task_logs(tail: int = 20, **_: Any) -> Dict[str, Any]:
    import glob as _glob
    root = project_root()
    log_dir = root / "logs"
    entries = []
    try:
        for log_path in sorted(_glob.glob(str(log_dir / "*.log")), reverse=True)[:3]:
            try:
                lines = []
                with open(log_path, encoding="utf-8", errors="replace") as fh:
                    lines = [line.rstrip("\n") for line in fh][-int(tail):]
                entries.append({"file": str(Path(log_path).name), "lines": lines})
            except Exception:
                pass
    except Exception:
        pass
    return {"success": True, "log_dir": str(log_dir), "entries": entries}


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
    "koto_recent_tasks": (
        _tool_schema(
            "koto_recent_tasks",
            "Return recent persistent Koto tasks from the task ledger.",
            {
                "session_id": {"type": "string"},
                "source": {"type": "string"},
                "status": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "include_steps": {"type": "boolean"},
            },
        ),
        recent_tasks,
    ),
    "koto_task_status": (
        _tool_schema(
            "koto_task_status",
            "Return one task's ledger status, steps, and latest progress event.",
            {
                "task_id": {"type": "string"},
                "include_steps": {"type": "boolean"},
            },
            required=["task_id"],
        ),
        task_status,
    ),
    "koto_task_progress_history": (
        _tool_schema(
            "koto_task_progress_history",
            "Return recent ProgressBus events for one Koto task.",
            {"task_id": {"type": "string"}},
            required=["task_id"],
        ),
        task_progress_history,
    ),
    "koto_frontend_events": (
        _tool_schema(
            "koto_frontend_events",
            "Return recent frontend observer events from the Koto browser UI.",
            {
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                "type": {"type": "string"},
                "session_id": {"type": "string"},
            },
        ),
        frontend_events,
    ),
    "koto_frontend_snapshot": (
        _tool_schema(
            "koto_frontend_snapshot",
            "Return frontend snapshot, recent events, and recent UI problems.",
            {
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                "session_id": {"type": "string"},
            },
        ),
        frontend_snapshot,
    ),
    "koto_frontend_surface_inventory": (
        _tool_schema(
            "koto_frontend_surface_inventory",
            "Return known frontend browser sessions and user-visible surfaces.",
            {
                "session_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
        ),
        frontend_surface_inventory,
    ),
    "koto_frontend_action": (
        _tool_schema(
            "koto_frontend_action",
            "Queue an action for the Koto frontend observer to execute.",
            {
                "action": {"type": "string"},
                "session_id": {"type": "string"},
                "selector": {"type": "string"},
                "value": {},
                "path": {"type": "string"},
                "panel": {"type": "string"},
                "options": {"type": "object"},
                "wait_ms": {"type": "integer", "minimum": 0, "maximum": 60000},
            },
            required=["action"],
            read_only=False,
        ),
        enqueue_frontend_action,
    ),
    "koto_frontend_action_status": (
        _tool_schema(
            "koto_frontend_action_status",
            "Return queued/dispatched/completed status for a frontend action.",
            {"action_id": {"type": "string"}},
            required=["action_id"],
        ),
        frontend_action_status,
    ),
    "koto_frontend_action_result": (
        _tool_schema(
            "koto_frontend_action_result",
            "Complete a frontend action with a result payload.",
            {
                "action_id": {"type": "string"},
                "ok": {"type": "boolean"},
                "result": {"type": "object"},
                "error": {"type": "string"},
            },
            required=["action_id"],
            read_only=False,
        ),
        complete_frontend_action,
    ),
    "koto_write_file": (
        _tool_schema(
            "koto_write_file",
            "Write content to a file inside the Koto project. The path must be relative to the project root.",
            {
                "path": {
                    "type": "string",
                    "description": "Project-relative file path to write.",
                },
                "content": {
                    "type": "string",
                    "description": "File content to write (UTF-8).",
                },
            },
            required=["path", "content"],
            read_only=False,
        ),
        _koto_write_file,
    ),
    "koto_read_file": (
        _tool_schema(
            "koto_read_file",
            "Read a file inside the Koto project, up to 100000 chars.",
            {
                "path": {
                    "type": "string",
                    "description": "Project-relative file path to read.",
                },
                "max_chars": {
                    "type": "integer",
                    "minimum": 200,
                    "maximum": 100000,
                    "description": "Maximum characters to return.",
                },
            },
            required=["path"],
        ),
        _koto_read_file,
    ),
    "koto_run_shell": (
        _tool_schema(
            "koto_run_shell",
            "Run a shell command in the Koto project root. Use this to run tests, lint, build, or git operations.",
            {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute.",
                },
                "timeout": {
                    "type": "integer",
                    "minimum": 5,
                    "maximum": 120,
                    "description": "Timeout in seconds.",
                },
                "workdir": {
                    "type": "string",
                    "description": "Project-relative working directory for the command.",
                },
            },
            required=["command"],
            read_only=False,
        ),
        _koto_run_shell,
    ),
    "koto_task_logs": (
        _tool_schema(
            "koto_task_logs",
            "Return recent Koto log tails to inspect agent task execution and errors.",
            {
                "tail": {
                    "type": "integer",
                    "minimum": 5,
                    "maximum": 200,
                    "description": "Number of lines to fetch from the end of each log file.",
                }
            },
        ),
        _koto_task_logs,
    ),
}


# ── CORS helpers ────────────────────────────────────────────────────────


def _cors_headers(origin: str | None = None) -> Dict[str, str]:
    origin = origin or request.headers.get("Origin", "")
    if not origin:
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization, Mcp-Session-Id, X-Request-ID",
        "Access-Control-Expose-Headers": "Mcp-Session-Id, X-Request-ID",
        "Access-Control-Allow-Credentials": "true",
    }


@mcp_bp.route("", methods=["OPTIONS"])
@mcp_bp.route("/tools", methods=["OPTIONS"])
@mcp_bp.route("/reload", methods=["OPTIONS"])
@mcp_bp.route("/status", methods=["OPTIONS"])
def _mcp_options(**_kw: Any) -> Response:
    origin = request.headers.get("Origin", "")
    resp = Response("", 204)
    for k, v in _cors_headers(origin).items():
        resp.headers[k] = v
    return resp


# ── SSE endpoint (GET /api/mcp) ────────────────────────────────────────


@mcp_bp.route("", methods=["GET"])
def mcp_sse():
    """SSE endpoint for MCP transport (opencode SSE fallback)."""
    session_id = request.headers.get("Mcp-Session-Id") or str(uuid.uuid4())
    origin = request.headers.get("Origin", "")
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    host = request.headers.get("X-Forwarded-Host", request.host)
    post_url = f"{scheme}://{host}/api/mcp"

    def _sse_event(event: str, data: str) -> str:
        return f"event: {event}\ndata: {data}\n\n"

    def generate():
        yield _sse_event("endpoint", post_url)
        yield _sse_event("session", session_id)
        last_seen = time.time()
        while True:
            elapsed = time.time() - last_seen
            if elapsed > _SESSION_TTL:
                break
            yield f": keepalive\n\n"
            time.sleep(15)

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
        **_cors_headers(origin),
    }
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers=headers,
    )


# ── REST status (GET /api/mcp/status) ──────────────────────────────────


@mcp_bp.route("/status", methods=["GET"])
def mcp_status():
    """REST status entry for Koto MCP integration."""
    origin = request.headers.get("Origin", "")
    try:
        from web.mcp_ws import get_mcp_ws_status

        websocket = get_mcp_ws_status()
    except Exception as exc:
        websocket = {"success": False, "error": str(exc)}
    data = {
        "success": True,
        "endpoint": "/api/mcp",
        "json_rpc": True,
        "tools_endpoint": "/api/mcp/tools",
        "reload_endpoint": "/api/mcp/reload",
        "websocket_endpoint": "/ws/mcp",
        "exposed_tool_count": len(_MCP_TOOLS),
        "websocket": websocket,
        "status": get_mcp_status(),
    }
    headers = _cors_headers(origin)
    resp = jsonify(data)
    for k, v in headers.items():
        resp.headers[k] = v
    return resp


@mcp_bp.route("/frontend-event", methods=["POST"])
def mcp_frontend_event():
    payload = request.get_json(silent=True) or {}
    if isinstance(payload, list):
        accepted = 0
        last = None
        for item in payload:
            if isinstance(item, dict):
                last = record_frontend_event(item)
                accepted += 1
        resp = jsonify({"success": True, "accepted": accepted, "last": last})
    else:
        data = record_frontend_event(payload)
        resp = jsonify({"success": True, "accepted": 1, "event": data})
    return resp


@mcp_bp.route("/frontend-events", methods=["GET"])
def mcp_frontend_events():
    data = frontend_events(
        limit=request.args.get("limit", 50),
        type=request.args.get("type", ""),
        session_id=request.args.get("session_id", ""),
    )
    return jsonify(data)


@mcp_bp.route("/frontend-action", methods=["GET"])
def mcp_frontend_action_next():
    data = next_frontend_action(session_id=request.args.get("session_id", ""))
    return jsonify(data)


@mcp_bp.route("/frontend-action-result", methods=["POST"])
def mcp_frontend_action_result():
    payload = request.get_json(silent=True) or {}
    data = complete_frontend_action(**payload)
    status = 200 if data.get("success") else 404
    return jsonify(data), status


# ── Tool listing (GET /api/mcp/tools) ──────────────────────────────────


@mcp_bp.route("/tools", methods=["GET"])
def mcp_tools():
    """List the read-only tools exposed by Koto's MCP supervision endpoint."""
    origin = request.headers.get("Origin", "")
    tools = [tool for tool, _handler in _MCP_TOOLS.values()]
    headers = _cors_headers(origin)
    resp = jsonify({"success": True, "count": len(tools), "tools": tools})
    for k, v in headers.items():
        resp.headers[k] = v
    return resp


# ── Reload MCP runtime (POST /api/mcp/reload) ──────────────────────────


@mcp_bp.route("/reload", methods=["POST"])
def mcp_reload():
    """Reload outbound MCP server configuration from user_settings.json."""
    origin = request.headers.get("Origin", "")
    headers = _cors_headers(origin)
    try:
        resp = jsonify({"success": True, "status": reload_mcp_runtime()})
    except Exception as exc:
        logger.warning("[MCPRoutes] reload failed: %s", exc, exc_info=True)
        resp = jsonify({"success": False, "error": str(exc)})
        resp.status_code = 500
    for k, v in headers.items():
        resp.headers[k] = v
    return resp


# ── JSON-RPC handler (POST /api/mcp) ───────────────────────────────────


@mcp_bp.route("", methods=["POST"])
def mcp_json_rpc():
    """HTTP JSON-RPC MCP endpoint for external coding agents.

    Supports Streamable HTTP and SSE transports.
    """
    origin = request.headers.get("Origin", "")
    session_id = request.headers.get("Mcp-Session-Id")
    payload = request.get_json(silent=True) or {}
    req_id = payload.get("id")
    method = payload.get("method", "")
    params = payload.get("params") or {}

    # ── notifications (no req_id) ──────────────────────────────
    if not req_id and method.startswith("notifications/"):
        resp = Response("", 202)
        for k, v in _cors_headers(origin).items():
            resp.headers[k] = v
        return resp

    try:
        if method == "initialize":
            if not session_id:
                session_id = str(uuid.uuid4())
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "koto-supervisor", "version": _read_version()},
                "_meta": {"sessionId": session_id},
            }
        elif method == "tools/list":
            result = {"tools": [tool for tool, _handler in _MCP_TOOLS.values()]}
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments") or {}
            if tool_name not in _MCP_TOOLS:
                resp = _rpc_error(req_id, -32602, f"Unknown tool: {tool_name}")
                resp.status_code = 400
                for k, v in _cors_headers(origin).items():
                    resp.headers[k] = v
                return resp
            _tool, handler = _MCP_TOOLS[tool_name]
            data = handler(**arguments)
            result = {
                "content": [{"type": "text", "text": _json_text(data)}],
                "isError": False,
            }
        else:
            resp = _rpc_error(req_id, -32601, f"Method not found: {method}")
            resp.status_code = 404
            for k, v in _cors_headers(origin).items():
                resp.headers[k] = v
            return resp

        resp = jsonify({"jsonrpc": "2.0", "id": req_id, "result": result})
        if session_id:
            resp.headers["Mcp-Session-Id"] = session_id
        for k, v in _cors_headers(origin).items():
            resp.headers[k] = v
        return resp
    except Exception as exc:
        logger.warning("[MCPRoutes] JSON-RPC failed: %s", exc, exc_info=True)
        resp = _rpc_error(req_id, -32603, str(exc))
        resp.status_code = 500
        for k, v in _cors_headers(origin).items():
            resp.headers[k] = v
        return resp


def _rpc_error(req_id: Any, code: int, message: str) -> Response:
    return jsonify(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }
    )
