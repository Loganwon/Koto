from __future__ import annotations

from types import SimpleNamespace


def test_doc_annotate_bridge_uses_deepseek_provider_client(monkeypatch):
    from app.core.agent.file_task_contract import FileTaskRequest
    import app.core.agent.file_task_doc_annotate_bridge as bridge
    import app.core.llm.model_selection as model_selection
    import app.core.llm.provider_factory as provider_factory
    import web.document_feedback as feedback_module

    captured = {}

    monkeypatch.setattr(
        model_selection,
        "get_provider_for_model_mode",
        lambda mode: "deepseek",
    )
    monkeypatch.setattr(
        model_selection,
        "get_configured_cloud_model",
        lambda **kwargs: "deepseek-v4-pro",
    )

    class FakeProvider:
        def generate_content(self, **kwargs):
            captured["provider_call"] = kwargs
            return {"content": "ok"}

    def fake_get_llm_provider(**kwargs):
        captured["provider_kwargs"] = kwargs
        return FakeProvider()

    monkeypatch.setattr(provider_factory, "get_llm_provider", fake_get_llm_provider)

    class FakeFeedback:
        def __init__(self, gemini_client=None, default_model_id=""):
            captured["feedback_client"] = gemini_client
            captured["default_model_id"] = default_model_id

    monkeypatch.setattr(feedback_module, "DocumentFeedbackSystem", FakeFeedback)

    request = FileTaskRequest.from_mapping(
        {
            "task": "审阅这份 DOCX",
            "model_mode": "deepseek",
            "model_id": "",
        }
    )

    bridge._build_feedback_system(request, gemini_client="gemini-client")

    assert captured["default_model_id"] == "deepseek-v4-pro"
    assert captured["provider_kwargs"]["provider"] == "deepseek"
    assert captured["provider_kwargs"]["model"] == "deepseek-v4-pro"
    assert captured["feedback_client"] != "gemini-client"

    response = captured["feedback_client"].models.generate_content(
        model="deepseek-v4-pro",
        contents="ping",
        config=SimpleNamespace(temperature=0.1, max_output_tokens=12),
    )

    assert response.text == "ok"
    assert captured["provider_call"]["model"] == "deepseek-v4-pro"
    assert captured["provider_call"]["prompt"] == "ping"
    assert captured["provider_call"]["temperature"] == 0.1
    assert captured["provider_call"]["max_tokens"] == 12
    assert captured["provider_call"]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_file_task_model_client_deepseek_mode_uses_deepseek_provider(monkeypatch):
    from app.core.agent.file_task_contract import FileTaskRequest
    import app.core.agent.file_task_model as file_task_model
    import app.core.llm.model_fallback as model_fallback
    import app.core.llm.provider_factory as provider_factory

    captured = {}

    monkeypatch.setattr(
        file_task_model,
        "get_provider_for_model_mode",
        lambda mode: "deepseek",
    )
    monkeypatch.setattr(
        file_task_model,
        "get_configured_cloud_model",
        lambda **kwargs: "deepseek-v4-pro",
    )

    class FakeProvider:
        pass

    def fake_get_llm_provider(**kwargs):
        captured["provider_kwargs"] = kwargs
        return FakeProvider()

    class FakeFallbackExecutor:
        def generate_with_fallback(self, **kwargs):
            captured["fallback_kwargs"] = kwargs
            return {"content": "done", "model": kwargs.get("preferred_model")}

    monkeypatch.setattr(provider_factory, "get_llm_provider", fake_get_llm_provider)
    monkeypatch.setattr(
        model_fallback,
        "get_fallback_executor",
        lambda: FakeFallbackExecutor(),
    )

    request = FileTaskRequest.from_mapping(
        {
            "task": "处理这个文件",
            "model_mode": "deepseek",
            "model_id": "",
        }
    )

    result = file_task_model.FileTaskModelClient().call(
        request=request,
        messages=[{"role": "user", "content": "hi"}],
        system="system",
        tools=[],
    )

    assert result["model"] == "deepseek-v4-pro"
    assert captured["provider_kwargs"]["provider"] == "deepseek"
    assert captured["provider_kwargs"]["model"] == "deepseek-v4-pro"
    assert captured["fallback_kwargs"]["preferred_model"] == "deepseek-v4-pro"
    assert captured["fallback_kwargs"]["task_type"] == "FILE_TASK"


def test_file_task_request_defaults_to_deepseek_when_mode_omitted(monkeypatch):
    from app.core.agent.file_task_contract import FileTaskRequest
    import app.core.agent.file_task_model as file_task_model

    request = FileTaskRequest.from_mapping({"task": "整理这个文件"})

    assert request.model_mode == "deepseek"
    assert file_task_model.FileTaskModelClient()._cloud_model_id(request) == "deepseek-v4-pro"


def test_doc_annotate_bridge_local_mode_builds_ollama_client(monkeypatch):
    from app.core.agent.file_task_contract import FileTaskRequest
    import app.core.agent.file_task_doc_annotate_bridge as bridge
    import app.core.llm.ollama_provider as ollama_provider

    captured = {}

    class FakeOllamaClientProxy:
        def __init__(self, model_tag=None):
            captured["model_tag"] = model_tag
            self._model_tag = model_tag
            self.models = object()

    monkeypatch.setattr(ollama_provider, "OllamaClientProxy", FakeOllamaClientProxy)

    request = FileTaskRequest.from_mapping(
        {
            "task": "审阅这份 DOCX",
            "model_mode": "local",
            "model_id": "local",
            "options": {"local_model": "qwen3.5:9b"},
        }
    )

    feedback_client = bridge._build_feedback_client(
        request,
        gemini_client="gemini-client",
    )

    assert feedback_client != "gemini-client"
    assert captured["model_tag"] == "qwen3.5:9b"
    assert feedback_client._model_tag == "qwen3.5:9b"
