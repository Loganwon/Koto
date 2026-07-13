from __future__ import annotations

from app.core.agent.lifecycle import (
    RunState,
    evt_code_result,
    evt_error,
    evt_lifecycle_end,
    evt_lifecycle_start,
    evt_live_doc_commit,
    evt_plan,
    evt_proposal,
    evt_rag_info,
    evt_status_message,
    evt_step_done,
    evt_step_error,
    evt_step_progress,
    evt_step_start,
    evt_stream_block,
    evt_stream_chunk,
    evt_task_complete,
    evt_tool_call,
    evt_tool_result,
)


def test_editor_sse_agent_event_payload_contract() -> None:
    from app.core.agent.lifecycle import AgentEvent, EventType
    from web.blueprints.editor_ai import _agent_event_payload

    assert _agent_event_payload(evt_stream_chunk("hello")) == {
        "type": "token",
        "content": "hello",
        "text": "hello",
    }
    assert _agent_event_payload(evt_stream_block("block")) == {
        "type": "token",
        "content": "block",
        "text": "block",
    }
    assert _agent_event_payload(evt_task_complete(result="done")) == {
        "type": "done",
        "result": "done",
        "has_proposals": False,
        "can_insert": True,
        "action_type": "",
    }
    assert _agent_event_payload(
        AgentEvent(EventType.TASK_COMPLETE, {"text": "fallback text"})
    ) == {
        "type": "done",
        "text": "fallback text",
        "result": "fallback text",
        "can_insert": True,
        "action_type": "",
    }
    assert _agent_event_payload(evt_error("bad")) == {"type": "error", "text": "bad"}
    assert _agent_event_payload(evt_status_message("working")) == {
        "type": "info",
        "text": "working",
        "is_error": False,
    }
    assert _agent_event_payload(evt_code_result({"stdout": "ok"})) == {
        "type": "code_result",
        "stdout": "ok",
    }
    assert _agent_event_payload(evt_step_start("s1", "start")) == {
        "type": "step_start",
        "step_id": "s1",
        "text": "start",
    }


class _FakeSocketIO:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict, str | None, str | None]] = []

    def emit(self, event: str, payload: dict, namespace=None, to=None) -> None:
        self.emitted.append((event, payload, namespace, to))


def _emit(event):
    from app.core.agent.doc_websocket_event_mapper import emit_agent_event

    socketio = _FakeSocketIO()
    emit_agent_event(socketio, "sid-1", event)
    return socketio.emitted


def test_socket_handler_emit_wrapper_delegates_to_doc_websocket_mapper(
    monkeypatch,
) -> None:
    import app.core.socket_handler as socket_handler

    captured = {}

    def fake_emit_agent_event(socketio, sid, event):
        captured["socketio"] = socketio
        captured["sid"] = sid
        captured["event"] = event

    monkeypatch.setattr(
        "app.core.agent.doc_websocket_event_mapper.emit_agent_event",
        fake_emit_agent_event,
    )

    socketio = _FakeSocketIO()
    event = evt_stream_chunk("hello")
    socket_handler._emit_agent_event(socketio, "sid-1", event)

    assert captured == {"socketio": socketio, "sid": "sid-1", "event": event}


def test_doc_websocket_stream_and_completion_contract() -> None:
    emitted = _emit(
        evt_stream_chunk(
            "hello",
            live_doc=True,
            live_mode="append",
            request_id="req-1",
        )
    )

    assert emitted == [
        ("agent_stream_chunk", {"chunk": "hello"}, "/doc", "sid-1"),
        (
            "doc_live_chunk",
            {"chunk": "hello", "mode": "append", "request_id": "req-1"},
            "/doc",
            "sid-1",
        ),
    ]

    assert _emit(
        evt_live_doc_commit(
            "full",
            live_mode="replace",
            original_selection="old",
            request_id="req-2",
        )
    ) == [
        (
            "doc_live_commit",
            {
                "full_text": "full",
                "mode": "replace",
                "original_selection": "old",
                "request_id": "req-2",
            },
            "/doc",
            "sid-1",
        )
    ]

    assert _emit(
        evt_live_doc_commit(
            "实时写入内容",
            live_mode="append",
            original_selection="原文",
            request_id="run-live",
        )
    ) == [
        (
            "doc_live_commit",
            {
                "full_text": "实时写入内容",
                "mode": "append",
                "original_selection": "原文",
                "request_id": "run-live",
            },
            "/doc",
            "sid-1",
        )
    ]

    assert _emit(evt_task_complete(result="done", has_proposals=True)) == [
        (
            "agent_task_complete",
            {"result": "done", "has_proposals": True, "error": ""},
            "/doc",
            "sid-1",
        )
    ]


def test_doc_websocket_structured_progress_contract() -> None:
    assert _emit(evt_plan([{"id": "s1", "description": "first"}])) == [
        (
            "agent_event",
            {"type": "plan", "steps": [{"id": "s1", "description": "first"}]},
            "/doc",
            "sid-1",
        )
    ]
    assert _emit(evt_step_start("s1", "start")) == [
        (
            "agent_event",
            {"type": "step_start", "step_id": "s1", "text": "start"},
            "/doc",
            "sid-1",
        )
    ]
    assert _emit(evt_step_progress("s1", "half")) == [
        (
            "agent_event",
            {"type": "step_progress", "step_id": "s1", "detail": "half"},
            "/doc",
            "sid-1",
        )
    ]
    assert _emit(evt_step_done("s1", "done")) == [
        (
            "agent_event",
            {"type": "step_done", "step_id": "s1", "text": "done"},
            "/doc",
            "sid-1",
        )
    ]
    assert _emit(evt_step_error("s1", "bad")) == [
        (
            "agent_event",
            {"type": "step_error", "step_id": "s1", "error": "bad"},
            "/doc",
            "sid-1",
        )
    ]


def test_doc_websocket_tool_status_and_lifecycle_contract() -> None:
    assert _emit(evt_tool_call({"name": "search", "args": {"q": "gold"}})) == [
        (
            "agent_event",
            {"type": "tool_call", "tool_name": "search", "tool_args": {"q": "gold"}},
            "/doc",
            "sid-1",
        )
    ]
    assert _emit(evt_tool_result("search", "found")) == [
        (
            "agent_event",
            {"type": "tool_result", "tool_name": "search", "result_preview": "found"},
            "/doc",
            "sid-1",
        )
    ]
    assert _emit(evt_status_message("working")) == [
        (
            "agent_progress",
            {"step": "status", "detail": "working"},
            "/doc",
            "sid-1",
        )
    ]
    assert _emit(evt_status_message("failed", is_error=True)) == [
        (
            "agent_execute_command",
            {"action": "show_message", "text": "failed", "is_error": True},
            "/doc",
            "sid-1",
        )
    ]
    assert _emit(evt_lifecycle_start("run-1", "sid-1")) == [
        (
            "agent_lifecycle",
            {
                "type": "lifecycle_start",
                "run_id": "run-1",
                "session_id": "sid-1",
                "state": "running",
            },
            "/doc",
            "sid-1",
        )
    ]
    assert _emit(evt_lifecycle_end("run-1", RunState.SUCCEEDED)) == [
        (
            "agent_lifecycle",
            {"type": "lifecycle_end", "run_id": "run-1", "state": "succeeded"},
            "/doc",
            "sid-1",
        )
    ]


def test_doc_websocket_secondary_event_contracts() -> None:
    assert _emit(evt_proposal([{"op": "replace"}], summary="summary")) == [
        (
            "agent_proposals",
            {"proposals": [{"op": "replace"}], "summary": "summary"},
            "/doc",
            "sid-1",
        )
    ]
    assert _emit(
        evt_proposal([{"original_text": "原文", "new_text": "新文"}], summary="润色")
    ) == [
        (
            "agent_proposals",
            {
                "proposals": [{"original_text": "原文", "new_text": "新文"}],
                "summary": "润色",
            },
            "/doc",
            "sid-1",
        )
    ]
    from app.core.agent.lifecycle import evt_doc_tool_call

    assert _emit(evt_doc_tool_call({"type": "set_html", "value": "<p>新内容</p>"})) == [
        (
            "doc_tool_call",
            {"type": "set_html", "value": "<p>新内容</p>"},
            "/doc",
            "sid-1",
        )
    ]
    assert _emit(evt_rag_info(total_chunks=5, retrieved_chunks=2)) == [
        (
            "rag_info",
            {"total_chunks": 5, "retrieved_chunks": 2},
            "/doc",
            "sid-1",
        ),
        (
            "agent_event",
            {"type": "rag_info", "total_chunks": 5, "retrieved_chunks": 2},
            "/doc",
            "sid-1",
        ),
    ]
    assert _emit(evt_code_result({"stdout": "ok"})) == [
        ("code_result", {"stdout": "ok"}, "/doc", "sid-1")
    ]
    assert _emit(evt_error("bad")) == [
        (
            "agent_task_complete",
            {"full_text": "", "error": "bad"},
            "/doc",
            "sid-1",
        )
    ]
