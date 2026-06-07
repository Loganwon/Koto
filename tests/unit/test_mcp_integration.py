# -*- coding: utf-8 -*-
from __future__ import annotations

from flask import Flask


def test_mcp_registry_accepts_claude_style_stdio_config():
    from app.core.agent.mcp_adapter import MCPRegistry

    registry = MCPRegistry().from_config(
        {
            "filesystem": {
                "command": "node",
                "args": ["server.js", "C:/workspace"],
                "env": {"TOKEN": "secret"},
                "cwd": "C:/workspace",
                "timeout": 7,
            }
        }
    )

    entry = registry._servers["filesystem"]
    assert entry.server_type == "stdio"
    assert entry.client.command == ["node", "server.js", "C:/workspace"]
    assert entry.client.env == {"TOKEN": "secret"}
    assert entry.client.cwd == "C:/workspace"
    assert entry.client.timeout == 7


def test_factory_injects_configured_mcp_tools(monkeypatch):
    from app.core.agent import factory

    called = {"count": 0}

    def fake_inject(registry):
        called["count"] += 1
        registry.register_tool(
            "mcp__fake__ping",
            lambda: "pong",
            description="fake mcp tool",
            parameters={"type": "object", "properties": {}, "required": []},
        )
        return 1

    monkeypatch.setattr(
        "app.core.agent.mcp_manager.inject_configured_mcp_tools",
        fake_inject,
    )

    registry = factory._build_registry(api_key=None, full=False)
    names = [tool["name"] for tool in registry.get_definitions()]
    assert called["count"] == 1
    assert "mcp__fake__ping" in names


def test_mcp_routes_list_and_call_status_tool(monkeypatch):
    from app.api import mcp_routes
    from app.api.mcp_routes import mcp_bp

    monkeypatch.setattr(
        mcp_routes,
        "get_mcp_status",
        lambda: {
            "server_count": 0,
            "tool_count": 0,
            "servers": {},
            "connect_results": {},
            "injected_tool_count": 0,
        },
    )

    app = Flask(__name__)
    app.register_blueprint(mcp_bp)
    client = app.test_client()

    listed = client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert listed.status_code == 200
    tool_names = [tool["name"] for tool in listed.get_json()["result"]["tools"]]
    assert "koto_mcp_status" in tool_names

    called = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "koto_mcp_status", "arguments": {}},
        },
    )
    assert called.status_code == 200
    body = called.get_json()
    assert body["result"]["isError"] is False
    assert '"server_count": 0' in body["result"]["content"][0]["text"]


def test_supervision_read_file_snippet_is_project_scoped():
    from app.core.agent.koto_supervision import read_file_snippet, resolve_project_path

    result = read_file_snippet("app/api/mcp_routes.py", start_line=1, max_chars=500)
    assert result["path"] == "app\\api\\mcp_routes.py" or result["path"] == "app/api/mcp_routes.py"
    assert "MCP routes for Koto" in result["snippet"]

    try:
        resolve_project_path("../outside.txt")
    except ValueError as exc:
        assert "outside project root" in str(exc)
    else:
        raise AssertionError("expected path escape to be rejected")


def test_supervision_run_tests_is_limited_to_pytest_under_tests(monkeypatch):
    import subprocess

    from app.core.agent import koto_supervision

    calls = []

    def fake_run(command, timeout=20):
        calls.append((command, timeout))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="1 passed\n",
            stderr="",
        )

    monkeypatch.setattr(koto_supervision, "_run", fake_run)
    result = koto_supervision.run_tests(
        targets="tests/unit/test_mcp_integration.py",
        timeout=15,
    )
    assert result["success"] is True
    assert calls[0][0][:3] == [koto_supervision.sys.executable, "-m", "pytest"]
    assert any(
        item.replace("\\", "/") == "tests/unit/test_mcp_integration.py"
        for item in calls[0][0]
    )

    try:
        koto_supervision.run_tests(targets="app/api/mcp_routes.py")
    except ValueError as exc:
        assert "under tests/" in str(exc)
    else:
        raise AssertionError("expected non-test pytest target to be rejected")


def test_mcp_routes_expose_supervision_tools(monkeypatch):
    from app.api import mcp_routes
    from app.api.mcp_routes import mcp_bp

    monkeypatch.setattr(mcp_routes, "get_mcp_status", lambda: {})

    app = Flask(__name__)
    app.register_blueprint(mcp_bp)
    client = app.test_client()

    listed = client.get("/api/mcp/tools")
    assert listed.status_code == 200
    tool_names = [tool["name"] for tool in listed.get_json()["tools"]]
    assert "koto_recent_file_changes" in tool_names
    assert "koto_search_code" in tool_names
    assert "koto_run_tests" in tool_names

    called = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "koto_read_file_snippet",
                "arguments": {"path": "app/api/mcp_routes.py", "max_chars": 500},
            },
        },
    )
    assert called.status_code == 200
    text = called.get_json()["result"]["content"][0]["text"]
    assert "MCP routes for Koto" in text
