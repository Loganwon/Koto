"""The local input budget must match the capacity actually sent to Ollama."""

from app.core.agent.file_task_contract import FileTaskRequest
from app.core.agent.file_task_model import FileTaskModelClient
from app.core.agent.kernel import AgentRequest, EventType, KernelRuntime, ToolCatalog
from app.core.agent.provider_model_gateway import ProviderModelGateway
from app.core.llm import ollama_llm_provider as native


def test_unprobed_local_default_is_explicit_in_budget_and_native_request(monkeypatch):
    monkeypatch.delenv("KOTO_OLLAMA_NUM_CTX", raising=False)
    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
    provider = native.OllamaLLMProvider(model="arbitrary-model")
    calls = []
    monkeypatch.setattr(
        native,
        "_raw_post",
        lambda url, payload, **kw: calls.append(payload)
        or {"message": {"content": "ok"}},
    )
    limits = provider.context_options()
    provider.generate_content("hello")
    assert limits["num_ctx"] == limits["context_window_tokens"] == 8192
    assert calls[0]["options"]["num_ctx"] == 8192
    assert limits["reserved_output_tokens"] == calls[0]["options"]["num_predict"]


def test_actual_small_local_context_refuses_oversized_prompt_before_network(
    monkeypatch,
):
    provider = native.OllamaLLMProvider(
        model="arbitrary-model", num_ctx=1024, num_predict=128
    )
    calls = []
    monkeypatch.setattr(
        native,
        "_stream_deltas",
        lambda *a, **kw: calls.append(True) or iter(["must not generate"]),
    )
    runtime = KernelRuntime(
        gateway=ProviderModelGateway(provider, allow_fallback=False),
        catalog=ToolCatalog(),
    )
    events = list(runtime.iter_events(AgentRequest(prompt="很长的输入" * 600)))
    final = next(event for event in events if event.type is EventType.TASK_COMPLETE)
    assert final.data.get("error")
    assert calls == []
    assert events[-1].data["state"] == "failed"


def test_explicit_nested_local_limits_are_used_for_both_payload_and_budget(monkeypatch):
    provider = native.OllamaLLMProvider(model="arbitrary-model", num_ctx=8192)
    calls = []
    monkeypatch.setattr(
        native,
        "_raw_post",
        lambda url, payload, **kw: calls.append(payload)
        or {"message": {"content": "ok"}},
    )
    options = {"options": {"num_ctx": 2048, "num_predict": 256}}
    limits = ProviderModelGateway(provider).context_options(options)
    provider.generate_content("hello", **options)
    assert limits["context_window_tokens"] == calls[0]["options"]["num_ctx"] == 2048
    assert limits["reserved_output_tokens"] == calls[0]["options"]["num_predict"] == 256


def test_local_file_task_budget_reserves_actual_bounded_output(monkeypatch):
    monkeypatch.setenv("KOTO_OLLAMA_NUM_CTX", "4096")
    client = FileTaskModelClient()
    request = FileTaskRequest(task="read", model_mode="local")
    limits = client.context_options(request)
    assert limits["num_ctx"] == limits["context_window_tokens"] == 4096
    assert limits["reserved_output_tokens"] == limits["num_predict"]
    assert limits["num_predict"] == 1536
