# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import pytest

from web.llm_client_compat import ProviderClientCompat


class _Provider:
    def __init__(self):
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return iter([{"content": "A"}, {"content": "B"}])
        return {"content": "answer", "usage": {"prompt_tokens": 2}}


def test_legacy_text_call_delegates_to_configured_provider():
    provider = _Provider()
    client = ProviderClientCompat(provider, "deepseek-chat")
    config = SimpleNamespace(
        system_instruction="system",
        temperature=0.2,
        max_output_tokens=128,
        response_mime_type="application/json",
        tools=None,
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents="hello",
        config=config,
    )

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


def test_legacy_stream_yields_text_chunks():
    provider = _Provider()
    client = ProviderClientCompat(provider, "deepseek-chat")

    chunks = list(
        client.models.generate_content_stream(
            model="gemini-3-flash-preview", contents="hello"
        )
    )

    assert [chunk.text for chunk in chunks] == ["A", "B"]
    assert provider.calls[0]["model"] == "deepseek-chat"


def test_google_tools_are_rejected_instead_of_silently_ignored():
    client = ProviderClientCompat(_Provider(), "deepseek-chat")
    config = SimpleNamespace(tools=[object()])

    with pytest.raises(RuntimeError, match="联网搜索服务"):
        client.models.generate_content(contents="weather", config=config)


def test_binary_parts_are_rejected_with_clear_error():
    client = ProviderClientCompat(_Provider(), "deepseek-chat")
    content = SimpleNamespace(
        role="user",
        parts=[SimpleNamespace(text=None, inline_data=object())],
    )

    with pytest.raises(RuntimeError, match="只支持文本输入"):
        client.models.generate_content(contents=[content])
