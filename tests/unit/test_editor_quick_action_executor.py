from __future__ import annotations

from app.core.agent.editor_quick_action_executor import EditorQuickActionExecutor
from app.core.agent.lifecycle import AgentRequest


class _FakeProvider:
    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return iter(self.chunks)


def _event_types(events):
    return [event.type.value for event in events]


def test_editor_quick_action_executor_streams_cloud_response(monkeypatch):
    from app.core.agent import llm_provider_helpers

    provider = _FakeProvider([{"content": "云端"}, {"content": "响应"}])
    monkeypatch.setattr(llm_provider_helpers, "get_provider", lambda **kwargs: provider)
    monkeypatch.setattr(llm_provider_helpers, "pick_online_model", lambda: "gemini-test")

    request = AgentRequest(
        prompt="润色这句话",
        action_type="polish",
        action_system_prompt="只输出润色后的文本。",
        model_mode="cloud",
        extra={"preferred_model": "gemini-2.5-pro"},
    )

    events = list(EditorQuickActionExecutor().iter_events(request))

    assert "lifecycle_start" in _event_types(events)
    assert "stream_chunk" in _event_types(events)
    assert events[-1].type.value == "lifecycle_end"
    complete = [event for event in events if event.type.value == "task_complete"][-1]
    assert complete.data["result"] == "云端响应"
    assert provider.calls[0]["model"] == "gemini-2.5-pro"
    assert provider.calls[0]["system_instruction"] == "只输出润色后的文本。"


def test_editor_quick_action_executor_uses_local_when_requested(monkeypatch):
    from app.core.agent import llm_provider_helpers

    provider = _FakeProvider([{"content": "本地"}, {"content": "响应"}])
    monkeypatch.setattr(llm_provider_helpers, "is_ollama_alive", lambda: True)
    monkeypatch.setattr(llm_provider_helpers, "get_local_provider", lambda model="": provider)

    request = AgentRequest(
        prompt="润色这句话",
        model_mode="local",
        extra={"local_model": "qwen3.5:9b"},
    )

    events = list(EditorQuickActionExecutor().iter_events(request))

    complete = [event for event in events if event.type.value == "task_complete"][-1]
    assert complete.data["result"] == "本地响应"
    assert "[系统指令]" in provider.calls[0]["prompt"]
    assert provider.calls[0]["stream"] is True


def test_editor_quick_action_executor_falls_back_to_local_on_online_failure(monkeypatch):
    from app.core.agent import llm_provider_helpers

    local_provider = _FakeProvider([{"content": "fallback"}])

    def fail_cloud(**kwargs):
        raise RuntimeError("503 unavailable")

    monkeypatch.setattr(llm_provider_helpers, "get_provider", fail_cloud)
    monkeypatch.setattr(llm_provider_helpers, "is_online_failure", lambda exc: True)
    monkeypatch.setattr(llm_provider_helpers, "is_ollama_alive", lambda: True)
    monkeypatch.setattr(llm_provider_helpers, "get_local_provider", lambda model="": local_provider)

    request = AgentRequest(prompt="润色", model_mode="cloud")
    events = list(EditorQuickActionExecutor().iter_events(request))

    status_texts = [
        event.data.get("text", "")
        for event in events
        if event.type.value == "status_message"
    ]
    complete = [event for event in events if event.type.value == "task_complete"][-1]
    assert any("自动切换到本地模型" in text for text in status_texts)
    assert complete.data["result"] == "fallback"


def test_editor_quick_action_executor_returns_error_when_local_unavailable(monkeypatch):
    from app.core.agent import llm_provider_helpers

    monkeypatch.setattr(llm_provider_helpers, "is_ollama_alive", lambda: False)

    request = AgentRequest(
        prompt="润色",
        model_mode="local",
        extra={"local_model": "qwen3.5:9b"},
    )
    events = list(EditorQuickActionExecutor().iter_events(request))

    errors = [event for event in events if event.type.value == "error"]
    assert errors
    assert "Ollama 未运行" in errors[-1].data["text"]
    assert not [event for event in events if event.type.value == "task_complete"]


def test_editor_quick_action_executor_does_not_claim_code_mode() -> None:
    assert EditorQuickActionExecutor.supports(AgentRequest(prompt="x")) is True
    assert EditorQuickActionExecutor.supports(AgentRequest(prompt="x", language="python")) is False
    assert EditorQuickActionExecutor.supports(AgentRequest(prompt="x", language="r")) is False
