# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

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


def test_mcp_status_reports_exposed_tools_and_websocket_sessions(monkeypatch):
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

    response = client.get("/api/mcp/status")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert data["exposed_tool_count"] >= 1
    assert data["websocket_endpoint"] == "/ws/mcp"
    assert "active_external_session_count" in data["websocket"]


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


def test_mcp_task_status_tools_surface_task_ledger(tmp_path, monkeypatch):
    from app.api import mcp_routes
    from app.api.mcp_routes import mcp_bp
    from app.core.agent import koto_supervision
    from app.core.tasks.progress_bus import ProgressBus, ProgressEvent
    from app.core.tasks.task_ledger import TaskLedger

    monkeypatch.setattr(mcp_routes, "get_mcp_status", lambda: {})
    ledger = TaskLedger(str(tmp_path / "task_ledger.sqlite"))
    bus = ProgressBus()
    monkeypatch.setattr(koto_supervision, "_task_ledger", lambda: ledger)
    monkeypatch.setattr(koto_supervision, "_progress_bus", lambda: bus)

    task = ledger.create(
        session_id="session-1",
        user_input="inspect progress",
        task_type="file_task",
        source="file_task",
        metadata={"run_id": "run-1"},
    )
    ledger.mark_running(task.task_id)
    ledger.update_metadata(task.task_id, {"last_event_type": "tool.finished"})
    ledger.add_step(
        task.task_id,
        step_type="ACTION",
        content="read file",
        tool_name="read_file",
        tool_args={"path": "demo.docx"},
        observation="ok",
    )
    bus.publish(
        ProgressEvent(
            task_id=task.task_id,
            session_id="session-1",
            event_type="file_task_event",
            status="running",
            message="read file",
            progress=42,
            step_type="ACTION",
            tool_name="read_file",
        )
    )

    app = Flask(__name__)
    app.register_blueprint(mcp_bp)
    client = app.test_client()

    listed = client.get("/api/mcp/tools")
    tool_names = [tool["name"] for tool in listed.get_json()["tools"]]
    assert "koto_recent_tasks" in tool_names
    assert "koto_task_status" in tool_names
    assert "koto_task_progress_history" in tool_names

    recent = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 18,
            "method": "tools/call",
            "params": {
                "name": "koto_recent_tasks",
                "arguments": {"source": "file_task", "include_steps": True},
            },
        },
    )
    assert recent.status_code == 200
    recent_text = recent.get_json()["result"]["content"][0]["text"]
    assert task.task_id in recent_text
    assert "last_event_type" in recent_text
    assert "read_file" in recent_text

    status = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 19,
            "method": "tools/call",
            "params": {
                "name": "koto_task_status",
                "arguments": {"task_id": task.task_id},
            },
        },
    )
    assert status.status_code == 200
    status_text = status.get_json()["result"]["content"][0]["text"]
    assert '"progress": 42' in status_text
    assert '"step_type": "ACTION"' in status_text


def test_mcp_frontend_observability_routes_and_tools(tmp_path, monkeypatch):
    from app.api import mcp_routes
    from app.api.mcp_routes import mcp_bp
    from app.core.agent import frontend_observability

    monkeypatch.setattr(mcp_routes, "get_mcp_status", lambda: {})
    monkeypatch.setattr(
        frontend_observability,
        "_event_log_path",
        lambda: tmp_path / "frontend_observability.jsonl",
    )
    frontend_observability.clear_frontend_events()

    app = Flask(__name__)
    app.register_blueprint(mcp_bp)
    client = app.test_client()

    posted = client.post(
        "/api/mcp/frontend-event",
        json={
            "type": "runtime_error",
            "level": "error",
            "message": "Cannot read properties of undefined",
            "details": {"filename": "workspace-bundle.js", "lineno": 42},
        },
    )
    assert posted.status_code == 200
    assert posted.get_json()["accepted"] == 1

    listed = client.get("/api/mcp/frontend-events?limit=5")
    assert listed.status_code == 200
    events = listed.get_json()["events"]
    assert events[0]["type"] == "runtime_error"
    assert "undefined" in events[0]["message"]

    called = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "koto_frontend_snapshot",
                "arguments": {"limit": 10},
            },
        },
    )
    assert called.status_code == 200
    text = called.get_json()["result"]["content"][0]["text"]
    assert "recent_problems" in text
    assert "runtime_error" in text


def test_frontend_observer_redacts_sensitive_control_values():
    source = Path("web/src/mcp/frontend-observer.ts").read_text(encoding="utf-8")

    assert "function _isSensitiveControl(" in source
    assert "function _summarizeControlValue(" in source
    assert "value_redacted" in source
    assert "[redacted]" in source
    for keyword in ["password", "token", "secret", "api[_-]?key", "authorization"]:
        assert keyword in source


def test_mcp_frontend_action_queue_round_trip(tmp_path, monkeypatch):
    from app.api import mcp_routes
    from app.api.mcp_routes import mcp_bp
    from app.core.agent import frontend_observability

    monkeypatch.setattr(mcp_routes, "get_mcp_status", lambda: {})
    monkeypatch.setattr(
        frontend_observability,
        "_event_log_path",
        lambda: tmp_path / "frontend_observability.jsonl",
    )
    frontend_observability.clear_frontend_events()

    app = Flask(__name__)
    app.register_blueprint(mcp_bp)
    client = app.test_client()

    queued = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "koto_frontend_action",
                "arguments": {
                    "action": "click",
                    "selector": "#navSettingsBtn",
                    "wait_ms": 0,
                },
            },
        },
    )
    assert queued.status_code == 200
    queued_payload = queued.get_json()["result"]["content"][0]["text"]
    assert "navSettingsBtn" in queued_payload

    next_action = client.get("/api/mcp/frontend-action?session_id=test-session")
    assert next_action.status_code == 200
    action = next_action.get_json()["action"]
    assert action["action"] == "click"
    assert action["selector"] == "#navSettingsBtn"

    completed = client.post(
        "/api/mcp/frontend-action-result",
        json={
            "id": action["id"],
            "ok": True,
            "result": {"clicked": True, "target": {"id": "navSettingsBtn"}},
        },
    )
    assert completed.status_code == 200
    assert completed.get_json()["action"]["status"] == "completed"

    status = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "koto_frontend_action_status",
                "arguments": {"action_id": action["id"]},
            },
        },
    )
    assert status.status_code == 200
    status_text = status.get_json()["result"]["content"][0]["text"]
    assert "completed" in status_text
    assert "navSettingsBtn" in status_text

    panel_queued = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "koto_frontend_action",
                "arguments": {
                    "action": "open_panel",
                    "panel": "settings",
                    "wait_ms": 0,
                },
            },
        },
    )
    assert panel_queued.status_code == 200
    panel_action = client.get("/api/mcp/frontend-action?session_id=test-session")
    assert panel_action.status_code == 200
    panel_payload = panel_action.get_json()["action"]
    assert panel_payload["action"] == "open_panel"
    assert panel_payload["panel"] == "settings"

    file_queued = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "koto_frontend_action",
                "arguments": {
                    "action": "open_workspace_file",
                    "path": "demo/notes.txt",
                    "wait_ms": 0,
                },
            },
        },
    )
    assert file_queued.status_code == 200
    file_action = client.get("/api/mcp/frontend-action?session_id=test-session")
    assert file_action.status_code == 200
    file_payload = file_action.get_json()["action"]
    assert file_payload["action"] == "open_workspace_file"
    assert file_payload["path"] == "demo/notes.txt"

    read_queued = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "koto_frontend_action",
                "arguments": {
                    "action": "read_editor_content",
                    "options": {"maxChars": 1000},
                    "wait_ms": 0,
                },
            },
        },
    )
    assert read_queued.status_code == 200
    read_action = client.get("/api/mcp/frontend-action?session_id=test-session")
    assert read_action.status_code == 200
    read_payload = read_action.get_json()["action"]
    assert read_payload["action"] == "read_editor_content"
    assert read_payload["options"]["maxChars"] == 1000

    selection_queued = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "koto_frontend_action",
                "arguments": {
                    "action": "current_selection",
                    "wait_ms": 0,
                },
            },
        },
    )
    assert selection_queued.status_code == 200
    selection_action = client.get("/api/mcp/frontend-action?session_id=test-session")
    assert selection_action.status_code == 200
    selection_payload = selection_action.get_json()["action"]
    assert selection_payload["action"] == "current_selection"

    range_queued = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "koto_frontend_action",
                "arguments": {
                    "action": "select_text_range",
                    "options": {"start": 0, "end": 10},
                    "wait_ms": 0,
                },
            },
        },
    )
    assert range_queued.status_code == 200
    range_action = client.get("/api/mcp/frontend-action?session_id=test-session")
    assert range_action.status_code == 200
    range_payload = range_action.get_json()["action"]
    assert range_payload["action"] == "select_text_range"
    assert range_payload["options"]["end"] == 10

    replace_queued = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {
                "name": "koto_frontend_action",
                "arguments": {
                    "action": "replace_text_selection",
                    "value": "patched",
                    "wait_ms": 0,
                },
            },
        },
    )
    assert replace_queued.status_code == 200
    replace_action = client.get("/api/mcp/frontend-action?session_id=test-session")
    assert replace_action.status_code == 200
    replace_payload = replace_action.get_json()["action"]
    assert replace_payload["action"] == "replace_text_selection"
    assert replace_payload["value"] == "patched"

    set_queued = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 13,
            "method": "tools/call",
            "params": {
                "name": "koto_frontend_action",
                "arguments": {
                    "action": "set_editor_content",
                    "value": "full content",
                    "wait_ms": 0,
                },
            },
        },
    )
    assert set_queued.status_code == 200
    set_action = client.get("/api/mcp/frontend-action?session_id=test-session")
    assert set_action.status_code == 200
    set_payload = set_action.get_json()["action"]
    assert set_payload["action"] == "set_editor_content"
    assert set_payload["value"] == "full content"

    save_queued = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 14,
            "method": "tools/call",
            "params": {
                "name": "koto_frontend_action",
                "arguments": {
                    "action": "save_current_file",
                    "wait_ms": 0,
                },
            },
        },
    )
    assert save_queued.status_code == 200
    save_action = client.get("/api/mcp/frontend-action?session_id=test-session")
    assert save_action.status_code == 200
    save_payload = save_action.get_json()["action"]
    assert save_payload["action"] == "save_current_file"

    context_queued = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 15,
            "method": "tools/call",
            "params": {
                "name": "koto_frontend_action",
                "arguments": {
                    "action": "document_context",
                    "options": {"maxChars": 2000, "shapeLimit": 20},
                    "wait_ms": 0,
                },
            },
        },
    )
    assert context_queued.status_code == 200
    context_action = client.get("/api/mcp/frontend-action?session_id=test-session")
    assert context_action.status_code == 200
    context_payload = context_action.get_json()["action"]
    assert context_payload["action"] == "document_context"
    assert context_payload["options"]["shapeLimit"] == 20

    pptx_queued = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 16,
            "method": "tools/call",
            "params": {
                "name": "koto_frontend_action",
                "arguments": {
                    "action": "set_pptx_shape_text",
                    "value": "Updated title",
                    "options": {"slideIndex": 0, "shapeId": 2},
                    "wait_ms": 0,
                },
            },
        },
    )
    assert pptx_queued.status_code == 200
    pptx_action = client.get("/api/mcp/frontend-action?session_id=test-session")
    assert pptx_action.status_code == 200
    pptx_payload = pptx_action.get_json()["action"]
    assert pptx_payload["action"] == "set_pptx_shape_text"
    assert pptx_payload["value"] == "Updated title"
    assert pptx_payload["options"]["shapeId"] == 2

    docx_queued = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 17,
            "method": "tools/call",
            "params": {
                "name": "koto_frontend_action",
                "arguments": {
                    "action": "replace_docx_anchor_text",
                    "value": "Updated heading",
                    "options": {"anchorText": "Original heading", "anchorOccurrence": 0},
                    "wait_ms": 0,
                },
            },
        },
    )
    assert docx_queued.status_code == 200
    docx_action = client.get("/api/mcp/frontend-action?session_id=test-session")
    assert docx_action.status_code == 200
    docx_payload = docx_action.get_json()["action"]
    assert docx_payload["action"] == "replace_docx_anchor_text"
    assert docx_payload["value"] == "Updated heading"
    assert docx_payload["options"]["anchorText"] == "Original heading"
    assert docx_payload["options"]["anchorOccurrence"] == 0


def test_mcp_frontend_action_targets_latest_visible_session(tmp_path, monkeypatch):
    from app.core.agent import frontend_observability

    monkeypatch.setattr(
        frontend_observability,
        "_event_log_path",
        lambda: tmp_path / "frontend_observability.jsonl",
    )
    frontend_observability.clear_frontend_events()
    frontend_observability.record_frontend_event(
        {
            "type": "snapshot",
            "session_id": "older-visible",
            "details": {"visibilityState": "visible"},
        }
    )
    frontend_observability.record_frontend_event(
        {
            "type": "snapshot",
            "session_id": "newer-hidden",
            "details": {"visibilityState": "hidden"},
        }
    )
    frontend_observability.record_frontend_event(
        {
            "type": "snapshot",
            "session_id": "newer-visible",
            "details": {"visibilityState": "visible"},
        }
    )

    queued = frontend_observability.enqueue_frontend_action(action="current_file_state")
    action = queued["action"]

    assert action["target_session_id"] == "newer-visible"
    assert frontend_observability.next_frontend_action(session_id="older-visible")["action"] is None
    delivered = frontend_observability.next_frontend_action(session_id="newer-visible")["action"]
    assert delivered["id"] == action["id"]


def test_mcp_frontend_action_sticks_to_recent_action_session(tmp_path, monkeypatch):
    from app.core.agent import frontend_observability

    monkeypatch.setattr(
        frontend_observability,
        "_event_log_path",
        lambda: tmp_path / "frontend_observability.jsonl",
    )
    frontend_observability.clear_frontend_events()
    frontend_observability.record_frontend_event(
        {
            "type": "snapshot",
            "session_id": "first-visible",
            "details": {"visibilityState": "visible"},
        }
    )
    first = frontend_observability.enqueue_frontend_action(action="open_workspace_file")
    frontend_observability.next_frontend_action(session_id="first-visible")
    frontend_observability.complete_frontend_action(
        action_id=first["action"]["id"],
        ok=True,
        result={"opened": True},
    )
    frontend_observability.record_frontend_event(
        {
            "type": "snapshot",
            "session_id": "second-visible",
            "details": {"visibilityState": "visible"},
        }
    )

    second = frontend_observability.enqueue_frontend_action(action="current_file_state")

    assert second["action"]["target_session_id"] == "first-visible"
    assert frontend_observability.next_frontend_action(session_id="second-visible")["action"] is None


def test_mcp_frontend_action_long_poll_waits_until_action(tmp_path, monkeypatch):
    import threading
    import time

    from app.core.agent import frontend_observability

    monkeypatch.setattr(
        frontend_observability,
        "_event_log_path",
        lambda: tmp_path / "frontend_observability.jsonl",
    )
    frontend_observability.clear_frontend_events()

    def enqueue_later():
        time.sleep(0.05)
        frontend_observability.enqueue_frontend_action(
            action="snapshot",
            target_session_id="long-poll-session",
        )

    thread = threading.Thread(target=enqueue_later)
    thread.start()
    started = time.monotonic()
    delivered = frontend_observability.next_frontend_action(
        session_id="long-poll-session",
        timeout_ms=1000,
    )
    thread.join(timeout=1)

    assert delivered["action"]["action"] == "snapshot"
    assert delivered["action"]["status"] == "delivered"
    assert time.monotonic() - started < 0.8


def test_mcp_frontend_action_wait_ms_returns_completed_action(tmp_path, monkeypatch):
    import threading

    from app.core.agent import frontend_observability

    monkeypatch.setattr(
        frontend_observability,
        "_event_log_path",
        lambda: tmp_path / "frontend_observability.jsonl",
    )
    frontend_observability.clear_frontend_events()

    def frontend_worker():
        delivered = frontend_observability.next_frontend_action(
            session_id="wait-session",
            timeout_ms=1000,
        )
        action = delivered.get("action") or {}
        if action.get("id"):
            frontend_observability.complete_frontend_action(
                action_id=action["id"],
                ok=True,
                result={"title": "Koto", "readyState": "complete"},
            )

    thread = threading.Thread(target=frontend_worker)
    thread.start()
    waited = frontend_observability.enqueue_frontend_action(
        action="snapshot",
        target_session_id="wait-session",
        wait_ms=1000,
    )
    thread.join(timeout=1)

    assert waited["success"] is True
    assert waited["action"]["status"] == "completed"
    assert waited["action"]["ok"] is True
    assert waited["action"]["result"]["readyState"] == "complete"
    assert waited["queued_action"]["id"] == waited["action"]["id"]


def test_websocket_mcp_exposes_koto_supervision_tools():
    from web.mcp_ws import MCPWebSocketSession

    session = MCPWebSocketSession("test", tool_registry=None)
    session.initialized = True

    listed = session._handle_tools_list()
    tool_names = [tool["name"] for tool in listed["tools"]]
    assert "koto_frontend_events" in tool_names
    assert "koto_project_overview" in tool_names
    assert "koto_frontend_action" in tool_names

    called = session._handle_tools_call(
        {"name": "koto_frontend_snapshot", "arguments": {"limit": 1}}
    )
    assert called["isError"] is False
    assert "recent_problems" in called["content"][0]["text"]


def test_websocket_status_tracks_external_sessions_only():
    from web.mcp_ws import (
        _mark_initialized,
        _register_session,
        _unregister_session,
        get_mcp_ws_status,
    )

    _register_session("ui-test")
    _register_session("external-test")
    try:
        _mark_initialized("ui-test", {"name": "koto-ui", "version": "2.0.0"})
        _mark_initialized("external-test", {"name": "codex", "version": "1.0.0"})

        status = get_mcp_ws_status()
        assert status["active_session_count"] >= 2
        assert status["active_external_session_count"] >= 1
        names = [item["client_name"] for item in status["external_sessions"]]
        assert "codex" in names
        assert "koto-ui" not in names
    finally:
        _unregister_session("ui-test")
        _unregister_session("external-test")


def test_stdio_mcp_bridge_handles_fast_websocket_response(monkeypatch):
    import io
    import json
    import sys

    from scripts.koto_mcp_cli import StdioMCPBridge

    bridge = StdioMCPBridge("ws://127.0.0.1:5000/ws/mcp", timeout=0.2)

    class FastWebSocket:
        def send(self, raw):
            msg = json.loads(raw)
            response = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": msg["id"],
                    "result": {"ok": True},
                }
            )
            with bridge._lock:
                bridge._responses[msg["id"]] = response
                event = bridge._pending.pop(msg["id"], None)
            if event:
                event.set()

    bridge._ws = FastWebSocket()
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {},
                }
            )
            + "\n"
        ),
    )
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)

    bridge._read_stdin()

    payload = json.loads(stdout.getvalue().strip())
    assert payload["id"] == 1
    assert payload["result"]["ok"] is True
