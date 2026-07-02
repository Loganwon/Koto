from __future__ import annotations

from app.core.agent.doc_websocket_agent_executor import DocWebSocketAgentExecutor
from app.core.agent.lifecycle import AgentRequest


class _FakeProvider:
    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return iter(self.chunks)


def test_doc_websocket_agent_executor_streams_chat_response(monkeypatch):
    from app.core.agent import llm_provider_helpers

    provider = _FakeProvider([{"content": "doc"}, {"content": " chat"}])
    monkeypatch.setattr(llm_provider_helpers, "get_provider", lambda **kwargs: provider)
    monkeypatch.setattr(llm_provider_helpers, "pick_online_model", lambda: "gemini-test")

    request = AgentRequest(
        prompt="总结一下",
        output_mode="chat",
        context="文档内容",
        file_type="docx",
        model_mode="cloud",
    )
    events = list(DocWebSocketAgentExecutor().iter_events(request))

    assert any(event.type.value == "plan" for event in events)
    assert any(event.type.value == "stream_chunk" for event in events)
    complete = [event for event in events if event.type.value == "task_complete"][-1]
    assert complete.data["result"] == "doc chat"
    assert "文档内容" in provider.calls[0]["prompt"]
    assert provider.calls[0]["stream"] is True


def test_doc_websocket_agent_executor_local_unavailable_returns_task_error(monkeypatch):
    from app.core.agent import llm_provider_helpers

    monkeypatch.setattr(llm_provider_helpers, "is_ollama_alive", lambda: False)

    events = list(
        DocWebSocketAgentExecutor().iter_events(
            AgentRequest(prompt="总结", output_mode="chat", model_mode="local")
        )
    )

    errors = [event for event in events if event.type.value == "task_complete"]
    assert errors
    assert "Ollama 未运行" in errors[-1].data["error"]


def test_doc_websocket_agent_executor_delegates_python_requests_to_code_executor(monkeypatch):
    from app.core.agent import doc_websocket_agent_executor as executor

    captured = {}

    class FakeCodeExecutor:
        @staticmethod
        def supports(request):
            captured["supports_request"] = request
            return request.language == "python"

        def iter_events(self, request):
            captured["request"] = request
            yield from ()

    monkeypatch.setattr(executor, "EditorCodeActionExecutor", FakeCodeExecutor)

    request = AgentRequest(prompt="生成图表", language="python", csv_data="a,b\n1,2")
    events = list(executor.DocWebSocketAgentExecutor().iter_events(request))

    assert events == []
    assert captured["supports_request"] is request
    assert captured["request"] is request


def test_doc_websocket_agent_executor_runs_python_code_request(monkeypatch):
    from app.core.agent import llm_provider_helpers
    from app.core import sandbox

    captured = {}

    def fake_call_llm_sync(prompt, use_local_only=False):
        captured["prompt"] = prompt
        captured["use_local_only"] = use_local_only
        return "```python\nprint('chart')\n```"

    def fake_run_python(code):
        captured["code"] = code
        return {"stdout": "chart", "stderr": "", "files": {"chart.png": "ZmFrZQ=="}, "error": ""}

    monkeypatch.setattr(llm_provider_helpers, "call_llm_sync", fake_call_llm_sync)
    monkeypatch.setattr(sandbox, "run_python", fake_run_python)

    events = list(
        DocWebSocketAgentExecutor().iter_events(
            AgentRequest(
                prompt="生成图表",
                output_mode="inline",
                language="python",
                csv_data="类别,值\nA,10",
                model_mode="cloud",
            )
        )
    )

    assert captured["use_local_only"] is False
    assert "表格数据（CSV 格式）" in captured["prompt"]
    assert captured["code"] == "print('chart')"
    code_result = [event for event in events if event.type.value == "code_result"][-1]
    assert code_result.data["files"] == {"chart.png": "ZmFrZQ=="}


def test_doc_websocket_agent_executor_emits_doc_tool_calls_for_inline_request(monkeypatch):
    from app.core.agent import llm_provider_helpers

    provider = _FakeProvider([
        {"content": '已生成<TOOL>{"type":"set_html","value":"<p>新内容</p>"}</TOOL>'}
    ])
    monkeypatch.setattr(llm_provider_helpers, "get_provider", lambda **kwargs: provider)
    monkeypatch.setattr(llm_provider_helpers, "pick_online_model", lambda: "gemini-test")

    request = AgentRequest(
        prompt="写一段话",
        output_mode="inline",
        file_type="docx",
        model_mode="cloud",
    )
    events = list(DocWebSocketAgentExecutor().iter_events(request))

    tool_events = [event for event in events if event.type.value == "doc_tool_call"]
    assert tool_events
    assert tool_events[0].data == {"type": "set_html", "value": "<p>新内容</p>"}
    complete = [event for event in events if event.type.value == "task_complete"][-1]
    assert complete.data["result"] == "已生成"
    assert complete.data["has_proposals"] is False


def test_doc_websocket_agent_executor_emits_proposals_for_selected_inline_request(monkeypatch):
    from app.core.agent import llm_provider_helpers

    provider = _FakeProvider([
        {
            "content": (
                '建议改得更自然<TOOL>{"type":"set_html",'
                '"value":"润色后的文字"}</TOOL>'
            )
        }
    ])
    monkeypatch.setattr(llm_provider_helpers, "get_provider", lambda **kwargs: provider)
    monkeypatch.setattr(llm_provider_helpers, "pick_online_model", lambda: "gemini-test")

    request = AgentRequest(
        prompt="润色",
        output_mode="inline",
        file_type="docx",
        model_mode="cloud",
        selection="原始文字",
        has_selection=True,
    )
    events = list(DocWebSocketAgentExecutor().iter_events(request))

    proposal_events = [event for event in events if event.type.value == "proposal"]
    assert proposal_events
    proposal = proposal_events[0].data["proposals"][0]
    assert proposal["original_text"] == "原始文字"
    assert proposal["proposed_text"] == "润色后的文字"
    assert proposal["rationale"] == "建议改得更自然"
    complete = [event for event in events if event.type.value == "task_complete"][-1]
    assert complete.data["result"] == "建议改得更自然"
    assert complete.data["has_proposals"] is True


def test_doc_websocket_agent_executor_emits_live_doc_commit(monkeypatch):
    from app.core.agent import llm_provider_helpers

    provider = _FakeProvider([{"content": "实时"}, {"content": "写入"}])
    monkeypatch.setattr(llm_provider_helpers, "get_provider", lambda **kwargs: provider)
    monkeypatch.setattr(llm_provider_helpers, "pick_online_model", lambda: "gemini-test")

    request = AgentRequest(
        prompt="续写",
        output_mode="inline",
        file_type="docx",
        model_mode="cloud",
        selection="原文",
        has_selection=True,
        live_doc=True,
        live_mode="replace",
    )
    events = list(DocWebSocketAgentExecutor().iter_events(request))

    start_event = [event for event in events if event.type.value == "lifecycle_start"][0]
    stream_events = [event for event in events if event.type.value == "stream_chunk"]
    assert stream_events
    assert stream_events[0].data["live_doc"] is True
    assert stream_events[0].data["live_mode"] == "replace"

    commit_events = [event for event in events if event.type.value == "live_doc_commit"]
    assert commit_events
    assert commit_events[0].data["full_text"] == "实时写入"
    assert commit_events[0].data["live_mode"] == "replace"
    assert commit_events[0].data["original_selection"] == "原文"
    assert commit_events[0].data["request_id"] == start_event.data["run_id"]
    complete = [event for event in events if event.type.value == "task_complete"][-1]
    assert complete.data["result"] == "实时写入"
    assert complete.data["has_proposals"] is False


def test_doc_websocket_agent_executor_synthesizes_insert_doc_tool_call(monkeypatch):
    from app.core.agent import llm_provider_helpers

    provider = _FakeProvider([{"content": "好的，我会插入。"}])
    monkeypatch.setattr(llm_provider_helpers, "get_provider", lambda **kwargs: provider)
    monkeypatch.setattr(llm_provider_helpers, "pick_online_model", lambda: "gemini-test")

    request = AgentRequest(
        prompt="请插入",
        output_mode="inline",
        file_type="docx",
        model_mode="cloud",
        history=[{"role": "assistant", "content": "第一段内容比较完整\n第二段内容也完整"}],
    )
    events = list(DocWebSocketAgentExecutor().iter_events(request))

    tool_events = [event for event in events if event.type.value == "doc_tool_call"]
    assert tool_events
    assert tool_events[0].data == {
        "type": "set_html",
        "value": "<p>第一段内容比较完整</p><p>第二段内容也完整</p>",
    }


def test_doc_websocket_agent_executor_supports_chat_and_no_selection_inline_requests() -> None:
    assert DocWebSocketAgentExecutor.supports(
        AgentRequest(prompt="x", output_mode="chat")
    )
    assert DocWebSocketAgentExecutor.supports(
        AgentRequest(prompt="x", output_mode="inline")
    )
    assert DocWebSocketAgentExecutor.supports(
        AgentRequest(prompt="x", output_mode="inline", selection="text", has_selection=True)
    )
    assert DocWebSocketAgentExecutor.supports(
        AgentRequest(prompt="x", output_mode="inline", live_doc=True)
    )
    assert DocWebSocketAgentExecutor.supports(
        AgentRequest(prompt="x", output_mode="chat", language="python")
    )
