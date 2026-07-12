from __future__ import annotations

from types import SimpleNamespace


def test_pick_online_model_prefers_request_model() -> None:
    from app.core.agent.llm_provider_helpers import pick_online_model

    request = SimpleNamespace(extra={"preferred_model": "gemini-custom"})

    assert pick_online_model(request) == "gemini-custom"


def test_pick_online_model_uses_core_configuration_selector(monkeypatch) -> None:
    from app.core.agent import llm_provider_helpers

    monkeypatch.setattr(
        llm_provider_helpers,
        "get_configured_cloud_model",
        lambda **_kwargs: "configured-model",
    )

    assert llm_provider_helpers.pick_online_model() == "configured-model"


def test_call_llm_sync_uses_local_only_provider(monkeypatch) -> None:
    from app.core.agent import llm_provider_helpers

    class FakeLocalProvider:
        def generate_content(self, **kwargs):
            return {"content": f"local:{kwargs['prompt']}"}

    monkeypatch.setattr(llm_provider_helpers, "is_ollama_alive", lambda: True)
    monkeypatch.setattr(llm_provider_helpers, "get_local_provider", lambda: FakeLocalProvider())

    assert llm_provider_helpers.call_llm_sync("prompt", use_local_only=True) == "local:prompt"


def test_call_llm_sync_falls_back_to_local_when_cloud_fails(monkeypatch) -> None:
    from app.core.agent import llm_provider_helpers

    class FakeLocalProvider:
        def generate_content(self, **kwargs):
            return {"content": "fallback"}

    def fail_cloud(**kwargs):
        raise RuntimeError("cloud failed")

    monkeypatch.setattr(llm_provider_helpers, "pick_online_model", lambda: "gemini-test")
    monkeypatch.setattr(llm_provider_helpers, "get_provider", fail_cloud)
    monkeypatch.setattr(llm_provider_helpers, "is_ollama_alive", lambda: True)
    monkeypatch.setattr(llm_provider_helpers, "get_local_provider", lambda: FakeLocalProvider())

    assert llm_provider_helpers.call_llm_sync("prompt") == "fallback"


def test_online_failure_detection_covers_model_availability_errors() -> None:
    from app.core.agent import llm_provider_helpers

    assert llm_provider_helpers.is_online_failure(
        RuntimeError("404 model not found: gemini-2.5-flash")
    )
    assert llm_provider_helpers.is_online_failure(
        RuntimeError("Permission denied: Project does not have access to model")
    )
