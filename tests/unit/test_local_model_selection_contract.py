# -*- coding: utf-8 -*-
"""Regression guards for the one configured local-model contract."""

from __future__ import annotations

from unittest.mock import MagicMock


def test_ollama_llm_provider_prefers_configured_model_over_auto_cache(monkeypatch):
    from app.core.llm import local_model_runtime
    from app.core.llm.ollama_llm_provider import OllamaLLMProvider

    monkeypatch.setattr(
        local_model_runtime, "get_configured_local_model_tag", lambda: "chosen:latest"
    )
    monkeypatch.setattr(OllamaLLMProvider, "_auto_model", "stale:auto")
    monkeypatch.setattr(OllamaLLMProvider, "_auto_model_ts", 1e20)

    assert OllamaLLMProvider(model=None)._resolve_model() == "chosen:latest"


def test_shared_local_provider_uses_configured_model_before_tag_heuristic(monkeypatch):
    from app.core.llm import local_model_runtime
    from app.core.shared.llm_helpers import get_local_provider

    monkeypatch.setattr(
        local_model_runtime, "get_configured_local_model_tag", lambda: "chosen:latest"
    )
    provider = get_local_provider()

    assert provider.model == "chosen:latest"


def test_router_response_model_uses_configured_tag(monkeypatch):
    from app.core.llm import local_model_runtime
    from app.core.routing.local_model_router import LocalModelRouter

    monkeypatch.setattr(LocalModelRouter, "_response_model", None)
    monkeypatch.setattr(LocalModelRouter, "_response_model_inited", False)
    monkeypatch.setattr(
        local_model_runtime, "get_configured_local_model_tag", lambda: "chosen:latest"
    )
    monkeypatch.setattr(LocalModelRouter, "is_ollama_available", lambda: True)
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "models": [{"name": "chosen:latest"}, {"name": "qwen3:8b"}]
    }
    monkeypatch.setattr(
        "app.core.routing.local_model_router.requests.get",
        lambda *args, **kwargs: response,
    )

    assert LocalModelRouter._init_response_model() is True
    assert LocalModelRouter._response_model == "chosen:latest"


def test_router_plan_uses_configured_tag(monkeypatch):
    from app.core.llm import local_model_runtime
    from app.core.routing.local_model_router import LocalModelRouter

    monkeypatch.setattr(
        local_model_runtime, "get_configured_local_model_tag", lambda: "chosen:latest"
    )
    monkeypatch.setattr(LocalModelRouter, "_initialized", True)
    monkeypatch.setattr(LocalModelRouter, "_model_name", "router:auto")
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"message": {"content": '{"steps":["one"]}'}}
    post = MagicMock(return_value=response)
    monkeypatch.setattr("app.core.routing.local_model_router.requests.post", post)

    assert LocalModelRouter.generate_plan("plan", "CHAT") == ["one"]
    assert post.call_args.kwargs["json"]["model"] == "chosen:latest"


def test_ollama_provider_no_longer_reads_user_settings_file_directly():
    from pathlib import Path

    source = Path("app/core/llm/ollama_provider.py").read_text(encoding="utf-8")
    resolver = source[
        source.index("def _resolve_model_from_settings") : source.index(
            "def get_local_model_info"
        )
    ]

    assert "get_configured_local_model_tag" in resolver
    assert '"config" / "user_settings.json"' not in resolver


def test_ollama_provider_disables_qwen_thinking_only_when_requested(monkeypatch):
    import app.core.llm.ollama_llm_provider as provider_module

    captured = {}

    def fake_post(_url, payload, **_kwargs):
        captured["payload"] = payload
        return {"message": {"content": "ok"}}

    monkeypatch.setattr(provider_module, "_raw_post", fake_post)
    provider_module.OllamaLLMProvider(model="qwen3.5:9b").generate_content(
        "hello", think=False
    )
    assert captured["payload"]["think"] is False

    provider_module.OllamaLLMProvider(model="gemma3:1b").generate_content(
        "hello", think=False
    )
    assert "think" not in captured["payload"]


def test_file_task_local_call_uses_longer_budget_disables_thinking_and_checks_tools(
    monkeypatch,
):
    import app.core.agent.file_task_model as file_task_model
    import app.core.llm.local_model_capabilities as capabilities
    import app.core.llm.ollama_llm_provider as provider_module
    from app.core.agent.file_task_contract import FileTaskRequest

    captured = {}
    monkeypatch.setattr(
        file_task_model.FileTaskModelClient, "_is_local_available", lambda _self: True
    )
    monkeypatch.setattr(capabilities, "local_model_supports_tools", lambda _model: True)

    class FakeProvider:
        def __init__(self, model):
            captured["model"] = model

        def generate_content(self, **kwargs):
            captured.update(kwargs)
            return {"content": "ok"}

    monkeypatch.setattr(provider_module, "OllamaLLMProvider", FakeProvider)
    request = FileTaskRequest.from_mapping(
        {
            "task": "总结选区",
            "model_mode": "local",
            "options": {"local_model": "qwen3.5:9b"},
        }
    )
    result = file_task_model.FileTaskModelClient().call(
        request=request,
        messages=[{"role": "user", "content": "hi"}],
        system="system",
        tools=[{"name": "echo"}],
    )

    assert result == {"content": "ok"}
    assert captured["model"] == "qwen3.5:9b"
    assert captured["call_timeout"] == file_task_model._LOCAL_FILE_TASK_LLM_CALL_TIMEOUT
    assert captured["think"] is False
    assert captured["num_predict"] == file_task_model._LOCAL_FILE_TASK_MAX_OUTPUT_TOKENS


def test_file_task_rejects_known_model_without_tool_support(monkeypatch):
    import app.core.agent.file_task_model as file_task_model
    import app.core.llm.local_model_capabilities as capabilities

    monkeypatch.setattr(
        capabilities, "local_model_supports_tools", lambda _model: False
    )

    try:
        file_task_model.FileTaskModelClient._ensure_local_tool_support(
            "gemma3:1b", [{"name": "echo"}]
        )
    except RuntimeError as exc:
        assert "gemma3:1b" in str(exc)
        assert "qwen3.5:9b" in str(exc)
    else:
        raise AssertionError(
            "a tool-less model must be rejected before file-task execution"
        )
