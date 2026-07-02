from __future__ import annotations

from app.core.agent.lifecycle import (
    AgentRequest,
    EventType,
    evt_doc_tool_call,
    evt_live_doc_commit,
    evt_proposal,
    evt_task_complete,
)
from app.core.agent.session_queue import SessionQueue


def test_doc_websocket_executor_uses_queue_for_code_requests(monkeypatch):
    from app.core.agent import doc_websocket_loop_executor as executor

    captured = {}

    class FakeDocAgent:
        def iter_events(self, request):
            captured["request"] = request
            captured["queue_depth_during_run"] = queue.queue_depth(request.session_id)
            yield evt_task_complete(result=request.session_id)

    monkeypatch.setattr(executor, "DocWebSocketAgentExecutor", FakeDocAgent)

    queue = SessionQueue()
    request = AgentRequest(
        prompt="summarize",
        session_id="sid-1",
        output_mode="inline",
        language="python",
    )
    events = list(executor.DocWebSocketLoopExecutor().iter_events(request, queue))

    assert captured["request"] is request
    assert captured["queue_depth_during_run"] == 1
    assert queue.queue_depth("sid-1") == 0
    assert events[0].data["result"] == "sid-1"


def test_doc_websocket_executor_delegates_chat_requests_to_doc_agent(monkeypatch):
    from app.core.agent import doc_websocket_loop_executor as executor

    captured = {}

    class FakeDocAgent:
        def iter_events(self, request):
            captured["request"] = request
            captured["queue_depth_during_run"] = queue.queue_depth(request.session_id)
            yield evt_task_complete(result=f"doc:{request.session_id}")

    monkeypatch.setattr(executor, "DocWebSocketAgentExecutor", FakeDocAgent)

    queue = SessionQueue()
    request = AgentRequest(prompt="summarize", session_id="sid-2", output_mode="chat")
    events = list(executor.DocWebSocketLoopExecutor().iter_events(request, queue))

    assert captured["request"] is request
    assert captured["queue_depth_during_run"] == 1
    assert queue.queue_depth("sid-2") == 0
    assert events[0].data["result"] == "doc:sid-2"


def test_doc_websocket_executor_delegates_inline_proposal_path_to_doc_agent(monkeypatch):
    from app.core.agent import doc_websocket_loop_executor as executor

    captured = {}
    proposal = {
        "id": "p1",
        "type": "replace",
        "original_text": "原始文字",
        "new_text": "润色后的文字",
        "rationale": "润色建议",
    }

    class FakeDocAgent:
        def iter_events(self, request):
            captured["request"] = request
            captured["queue_depth_during_run"] = queue.queue_depth(request.session_id)
            yield evt_proposal([proposal], "润色建议")
            yield evt_task_complete(result="已润色", has_proposals=True)

    monkeypatch.setattr(executor, "DocWebSocketAgentExecutor", FakeDocAgent)

    queue = SessionQueue()
    request = AgentRequest(
        prompt="润色",
        session_id="sid-inline",
        output_mode="inline",
        selection="原始文字",
        has_selection=True,
    )
    events = list(executor.DocWebSocketLoopExecutor().iter_events(request, queue))

    assert captured["request"] is request
    assert captured["queue_depth_during_run"] == 1
    assert queue.queue_depth("sid-inline") == 0
    assert any(event.type == EventType.PROPOSAL for event in events)
    complete = [event for event in events if event.type == EventType.TASK_COMPLETE][-1]
    assert complete.data["has_proposals"] is True


def test_doc_websocket_executor_delegates_inline_doc_tool_path_to_doc_agent(monkeypatch):
    from app.core.agent import doc_websocket_loop_executor as executor

    captured = {}
    tool_call = {"type": "set_html", "value": "<p>新内容</p>"}

    class FakeDocAgent:
        def iter_events(self, request):
            captured["request"] = request
            captured["queue_depth_during_run"] = queue.queue_depth(request.session_id)
            yield evt_doc_tool_call(tool_call)
            yield evt_task_complete(result="已生成", has_proposals=False)

    monkeypatch.setattr(executor, "DocWebSocketAgentExecutor", FakeDocAgent)

    queue = SessionQueue()
    request = AgentRequest(prompt="写一段话", session_id="sid-tool", output_mode="inline")
    events = list(executor.DocWebSocketLoopExecutor().iter_events(request, queue))

    assert captured["request"] is request
    assert captured["queue_depth_during_run"] == 1
    assert queue.queue_depth("sid-tool") == 0
    tool_events = [event for event in events if event.type == EventType.DOC_TOOL_CALL]
    assert tool_events and tool_events[0].data == tool_call
    complete = [event for event in events if event.type == EventType.TASK_COMPLETE][-1]
    assert complete.data["has_proposals"] is False


def test_doc_websocket_executor_delegates_live_doc_commit_path_to_doc_agent(monkeypatch):
    from app.core.agent import doc_websocket_loop_executor as executor

    captured = {}

    class FakeDocAgent:
        def iter_events(self, request):
            captured["request"] = request
            captured["queue_depth_during_run"] = queue.queue_depth(request.session_id)
            yield evt_live_doc_commit(
                full_text="实时写入内容",
                live_mode=request.live_mode,
                original_selection=request.selection,
                request_id="run-1",
            )
            yield evt_task_complete(result="实时写入内容", has_proposals=False)

    monkeypatch.setattr(executor, "DocWebSocketAgentExecutor", FakeDocAgent)

    queue = SessionQueue()
    request = AgentRequest(
        prompt="续写",
        session_id="sid-live",
        output_mode="inline",
        selection="原文",
        live_doc=True,
        live_mode="replace",
    )
    events = list(executor.DocWebSocketLoopExecutor().iter_events(request, queue))

    assert captured["request"] is request
    assert captured["queue_depth_during_run"] == 1
    assert queue.queue_depth("sid-live") == 0
    live_events = [event for event in events if event.type == EventType.LIVE_DOC_COMMIT]
    assert live_events
    assert live_events[0].data["full_text"] == "实时写入内容"
