from __future__ import annotations

from app.core.agent.lifecycle import AgentRequest, evt_task_complete
from app.core.agent.session_queue import SessionQueue


def test_editor_facade_runs_legacy_loop(monkeypatch):
    from app.core.agent import legacy_loop_facade as facade

    captured = {}

    class FakeEditorExecutor:
        def iter_events(self, request):
            captured["request"] = request
            yield evt_task_complete(result=f"ok:{request.prompt}")

    monkeypatch.setattr(facade, "EditorLoopExecutor", FakeEditorExecutor)

    request = AgentRequest(prompt="polish this")
    events = list(facade.iter_editor_agent_events(request))

    assert captured["request"] is request
    assert events[0].data["result"] == "ok:polish this"


def test_doc_facade_builds_request_and_runs_with_hooks(monkeypatch):
    from app.core.agent import legacy_loop_facade as facade

    captured = {}

    class FakeDocExecutor:
        def iter_events(self, request, session_queue):
            captured["request"] = request
            captured["session_queue"] = session_queue
            yield evt_task_complete(result=f"done:{request.session_id}")

    monkeypatch.setattr(facade, "DocWebSocketLoopExecutor", FakeDocExecutor)

    queue = SessionQueue()

    events = list(
        facade.iter_doc_agent_events(
            "sid-1",
            {
                "prompt": "summarize",
                "file_type": "docx",
                "file_name": "notes.docx",
                "context": "full text",
                "selection": "selected text",
                "has_selection": True,
                "history": [{"role": "user", "content": "hi"}],
                "output_mode": "chat",
                "model_mode": "local",
                "language": "python",
                "csv_data": "a,b\n1,2",
                "_action_type": "summary",
                "_action_system_prompt": "system prompt",
                "live_doc": True,
                "live_mode": "append",
            },
            queue,
        )
    )

    request = captured["request"]
    assert request.session_id == "sid-1"
    assert request.prompt == "summarize"
    assert request.file_type == "docx"
    assert request.file_name == "notes.docx"
    assert request.context == "full text"
    assert request.selection == "selected text"
    assert request.has_selection is True
    assert request.history == [{"role": "user", "content": "hi"}]
    assert request.output_mode == "chat"
    assert request.model_mode == "local"
    assert request.language == "python"
    assert request.csv_data == "a,b\n1,2"
    assert request.action_type == "summary"
    assert request.action_system_prompt == "system prompt"
    assert request.live_doc is True
    assert request.live_mode == "append"
    assert captured["session_queue"] is queue
    assert events[0].data["result"] == "done:sid-1"


def test_doc_facade_chat_request_uses_doc_agent_not_legacy_loop(monkeypatch):
    from app.core.agent import llm_provider_helpers
    from app.core.agent.legacy_loop_facade import iter_doc_agent_events

    class FakeProvider:
        def generate_content(self, **kwargs):
            return iter([{"content": "chat"}, {"content": " ok"}])

    monkeypatch.setattr(llm_provider_helpers, "get_provider", lambda **kwargs: FakeProvider())
    monkeypatch.setattr(llm_provider_helpers, "pick_online_model", lambda: "gemini-test")

    events = list(
        iter_doc_agent_events(
            "sid-chat",
            {
                "prompt": "总结这段内容",
                "context": "文档内容",
                "output_mode": "chat",
                "model_mode": "cloud",
            },
            SessionQueue(),
        )
    )

    complete = [event for event in events if event.type.value == "task_complete"][-1]
    assert complete.data["result"] == "chat ok"


def test_doc_facade_inline_no_selection_request_uses_doc_agent_not_legacy_loop(monkeypatch):
    from app.core.agent import llm_provider_helpers
    from app.core.agent.legacy_loop_facade import iter_doc_agent_events

    class FakeProvider:
        def generate_content(self, **kwargs):
            return iter([
                {"content": '已生成<TOOL>{"type":"set_html","value":"<p>新内容</p>"}</TOOL>'}
            ])

    monkeypatch.setattr(llm_provider_helpers, "get_provider", lambda **kwargs: FakeProvider())
    monkeypatch.setattr(llm_provider_helpers, "pick_online_model", lambda: "gemini-test")

    events = list(
        iter_doc_agent_events(
            "sid-inline-tool",
            {
                "prompt": "写一段内容",
                "file_type": "docx",
                "output_mode": "inline",
                "model_mode": "cloud",
            },
            SessionQueue(),
        )
    )

    tool_events = [event for event in events if event.type.value == "doc_tool_call"]
    assert tool_events
    assert tool_events[0].data == {"type": "set_html", "value": "<p>新内容</p>"}


def test_doc_facade_inline_selected_request_uses_doc_agent_not_legacy_loop(monkeypatch):
    from app.core.agent import llm_provider_helpers
    from app.core.agent.legacy_loop_facade import iter_doc_agent_events

    class FakeProvider:
        def generate_content(self, **kwargs):
            return iter([
                {
                    "content": (
                        '润色说明<TOOL>{"type":"set_html",'
                        '"value":"润色后的文字"}</TOOL>'
                    )
                }
            ])

    monkeypatch.setattr(llm_provider_helpers, "get_provider", lambda **kwargs: FakeProvider())
    monkeypatch.setattr(llm_provider_helpers, "pick_online_model", lambda: "gemini-test")

    events = list(
        iter_doc_agent_events(
            "sid-inline-proposal",
            {
                "prompt": "润色",
                "file_type": "docx",
                "output_mode": "inline",
                "model_mode": "cloud",
                "selection": "原始文字",
                "has_selection": True,
            },
            SessionQueue(),
        )
    )

    proposal_events = [event for event in events if event.type.value == "proposal"]
    assert proposal_events
    assert proposal_events[0].data["proposals"][0]["proposed_text"] == "润色后的文字"


def test_doc_facade_live_doc_request_uses_doc_agent_not_legacy_loop(monkeypatch):
    from app.core.agent import llm_provider_helpers
    from app.core.agent.legacy_loop_facade import iter_doc_agent_events

    class FakeProvider:
        def generate_content(self, **kwargs):
            return iter([{"content": "实时"}, {"content": "写入"}])

    monkeypatch.setattr(llm_provider_helpers, "get_provider", lambda **kwargs: FakeProvider())
    monkeypatch.setattr(llm_provider_helpers, "pick_online_model", lambda: "gemini-test")

    events = list(
        iter_doc_agent_events(
            "sid-live",
            {
                "prompt": "续写",
                "file_type": "docx",
                "output_mode": "inline",
                "model_mode": "cloud",
                "selection": "原文",
                "has_selection": True,
                "live_doc": True,
                "live_mode": "append",
            },
            SessionQueue(),
        )
    )

    commit_events = [event for event in events if event.type.value == "live_doc_commit"]
    assert commit_events
    assert commit_events[0].data["full_text"] == "实时写入"
    assert commit_events[0].data["live_mode"] == "append"
    assert commit_events[0].data["original_selection"] == "原文"


def test_doc_facade_python_request_emits_code_result(monkeypatch):
    from app.core.agent import llm_provider_helpers
    from app.core.agent.legacy_loop_facade import iter_doc_agent_events
    from app.core import sandbox

    monkeypatch.setattr(
        llm_provider_helpers,
        "call_llm_sync",
        lambda prompt, use_local_only=False: "```python\nprint('chart')\n```",
    )
    monkeypatch.setattr(
        sandbox,
        "run_python",
        lambda code: {"stdout": "chart", "stderr": "", "files": {"chart.png": "ZmFrZQ=="}, "error": ""},
    )

    events = list(
        iter_doc_agent_events(
            "sid-python",
            {
                "prompt": "生成图表",
                "file_type": "docx",
                "output_mode": "inline",
                "language": "python",
                "csv_data": "类别,值\nA,10",
                "model_mode": "cloud",
            },
            SessionQueue(),
        )
    )

    code_results = [event for event in events if event.type.value == "code_result"]
    assert code_results
    assert code_results[-1].data["files"] == {"chart.png": "ZmFrZQ=="}
