from __future__ import annotations

from unittest.mock import MagicMock


def test_task_agent_call_llm_uses_extended_file_task_timeout(monkeypatch):
    from app.core.agent import task_agent as task_agent_module
    from app.core.agent.task_agent import TaskAgent

    captured = {}

    class FakeExecutor:
        def generate_with_fallback(self, **kwargs):
            captured.update(kwargs)
            return {"content": "ok", "tool_calls": []}

    monkeypatch.setattr(
        "app.core.llm.model_fallback.get_fallback_executor",
        lambda: FakeExecutor(),
    )

    agent = TaskAgent(model_id="gemini-3-pro-preview")
    result = agent._call_llm(
        provider=object(),
        messages=[{"role": "user", "content": "hi"}],
        system="system",
        tool_defs=[],
    )

    assert result == {"content": "ok", "tool_calls": []}
    assert captured["task_type"] == "FILE_TASK"
    assert captured["call_timeout"] == task_agent_module._FILE_TASK_LLM_CALL_TIMEOUT


def test_task_agent_get_provider_uses_ollama_for_local_mode(monkeypatch):
    import app.core.llm.ollama_llm_provider as ollama_llm_provider
    from app.core.agent.task_agent import TaskAgent

    captured = {}

    class FakeOllamaProvider:
        def __init__(self, model=None):
            captured["model"] = model

    monkeypatch.setattr(ollama_llm_provider, "OllamaLLMProvider", FakeOllamaProvider)

    agent = TaskAgent(model_id="gemini-3-pro-preview")
    provider = agent._get_provider({"model_mode": "local"})

    assert isinstance(provider, FakeOllamaProvider)
    assert captured["model"] is None


def test_task_agent_call_llm_local_mode_bypasses_cloud_fallback():
    from app.core.agent import task_agent as task_agent_module
    from app.core.agent.task_agent import TaskAgent

    provider = MagicMock()
    provider.generate_content.return_value = {"content": "本地结果", "tool_calls": []}

    agent = TaskAgent(model_id="gemini-3-pro-preview")
    result = agent._call_llm(
        provider=provider,
        messages=[{"role": "user", "content": "hi"}],
        system="system",
        tool_defs=[],
        options={"model_mode": "local"},
    )

    assert result == {"content": "本地结果", "tool_calls": []}
    provider.generate_content.assert_called_once_with(
        prompt=[{"role": "user", "content": "hi"}],
        model=None,
        system_instruction="system",
        tools=None,
        stream=False,
        call_timeout=task_agent_module._FILE_TASK_LLM_CALL_TIMEOUT,
    )
