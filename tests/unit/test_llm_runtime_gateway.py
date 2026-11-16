from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.llm.runtime_gateway import LLMRuntimeGateway


class _Provider:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return iter([{"content": "A"}, {"content": "B"}])
        return {"content": "answer", "usage": {"prompt_tokens": 2}}


def test_direct_text_generation_delegates_to_provider() -> None:
    provider = _Provider()
    gateway = LLMRuntimeGateway(provider, "deepseek-chat")
    config = SimpleNamespace(
        system_instruction="system",
        temperature=0.2,
        max_output_tokens=128,
        response_mime_type="application/json",
        tools=None,
    )

    response = gateway.generate_content(contents="hello", config=config)

    assert response.text == "answer"
    assert response.usage_metadata == {"prompt_tokens": 2}
    assert provider.calls == [
        {
            "prompt": "hello",
            "model": "deepseek-chat",
            "stream": False,
            "system_instruction": "system",
            "temperature": 0.2,
            "max_tokens": 128,
            "response_format": {"type": "json_object"},
        }
    ]


def test_direct_stream_yields_normalized_chunks() -> None:
    provider = _Provider()
    gateway = LLMRuntimeGateway(provider, "deepseek-chat")

    chunks = list(gateway.generate_content_stream(contents="hello"))

    assert [chunk.text for chunk in chunks] == ["A", "B"]
    assert provider.calls[0]["model"] == "deepseek-chat"


def test_sdk_tool_declarations_fail_at_gateway_boundary() -> None:
    gateway = LLMRuntimeGateway(_Provider(), "deepseek-chat")

    with pytest.raises(RuntimeError, match="Koto 工具运行时"):
        gateway.generate_content(
            contents="weather", config=SimpleNamespace(tools=[object()])
        )


def test_binary_parts_fail_at_gateway_boundary() -> None:
    gateway = LLMRuntimeGateway(_Provider(), "deepseek-chat")
    content = SimpleNamespace(
        role="user",
        parts=[SimpleNamespace(text=None, inline_data=object())],
    )

    with pytest.raises(RuntimeError, match="不接受 SDK 二进制"):
        gateway.generate_content(contents=[content])


def test_model_listing_is_provider_neutral() -> None:
    gateway = LLMRuntimeGateway(_Provider(), "deepseek-chat")

    assert [model.name for model in gateway.list_models()] == ["deepseek-chat"]
