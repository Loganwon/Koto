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


def test_ollama_runtime_response_model_uses_configured_tag(monkeypatch):
    from app.core.llm import local_model_runtime
    from app.core.llm.local_model_runtime import OllamaRuntime

    monkeypatch.setattr(OllamaRuntime, "_response_model", None)
    monkeypatch.setattr(OllamaRuntime, "_response_model_inited", False)
    monkeypatch.setattr(
        local_model_runtime, "get_configured_local_model_tag", lambda: "chosen:latest"
    )
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "models": [{"name": "chosen:latest"}, {"name": "qwen3:8b"}]
    }
    monkeypatch.setattr(
        OllamaRuntime,
        "_installed_models",
        classmethod(lambda cls: ["chosen:latest", "qwen3:8b"]),
    )

    assert OllamaRuntime._init_response_model() is True
    assert OllamaRuntime._response_model == "chosen:latest"


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


def test_ollama_provider_does_not_report_unloadable_model_as_running(monkeypatch):
    from app.core.llm import local_model_runtime, ollama_provider, ollama_runtime_compat

    monkeypatch.setattr(
        local_model_runtime, "get_configured_model_mode", lambda: "local"
    )
    monkeypatch.setattr(
        local_model_runtime,
        "get_configured_local_model_tag",
        lambda: "broken:latest",
    )
    monkeypatch.setattr(ollama_provider, "_is_ollama_running", lambda: True)
    monkeypatch.setattr(
        "app.core.llm.local_model_capabilities.get_ollama_model_capabilities",
        lambda _model: {"chat"},
    )
    monkeypatch.setattr(
        ollama_runtime_compat,
        "inspect_ollama_model_compatibility",
        lambda _model: {
            "model_id": "broken:latest",
            "compatible": None,
            "reason": "model_load_failed",
        },
    )

    info = ollama_provider.get_local_model_info()

    assert info["ollama_reachable"] is True
    assert info["running"] is False
    assert info["runtime_error"] == "model_load_failed"


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
