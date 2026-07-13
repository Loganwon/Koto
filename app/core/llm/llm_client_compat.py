# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Compatibility client for legacy ``client.models`` text call sites.

The active cloud runtime uses :class:`LLMProvider`, while a number of older
web features still expect the Google-style ``client.models.generate_content``
shape.  This adapter keeps those text-only features operational without
reviving the archived Gemini client.  Provider-specific capabilities such as
Google Search tools, image generation, and binary/multimodal input are rejected
explicitly instead of silently pretending that DeepSeek supports them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.core.llm.model_selection import (
    get_configured_cloud_model,
    get_configured_cloud_provider,
)
from app.core.llm.provider_factory import get_llm_provider


@dataclass
class CompatGenerateContentResponse:
    text: str
    usage_metadata: Any = None


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _part_text(part: Any) -> str:
    text = _value(part, "text", None)
    if text is not None:
        return str(text)
    if any(
        _value(part, name, None) is not None
        for name in ("inline_data", "file_data", "function_call", "function_response")
    ):
        raise RuntimeError(
            "当前云模型兼容层只支持文本输入；二进制、图像和函数调用内容需要专用处理路径。"
        )
    return ""


def _normalize_prompt(contents: Any) -> str | list[dict[str, str]]:
    if isinstance(contents, str):
        return contents
    if not isinstance(contents, (list, tuple)):
        text = _part_text(contents)
        return text or str(contents or "")

    messages: list[dict[str, str]] = []
    loose_text: list[str] = []
    for item in contents:
        if isinstance(item, str):
            loose_text.append(item)
            continue
        role = str(_value(item, "role", "") or "").strip().lower()
        parts = _value(item, "parts", None)
        if parts is None and isinstance(item, dict):
            direct = item.get("content") or item.get("text")
            if direct is not None:
                parts = [direct]
        if parts is None:
            parts = [item]
        if not isinstance(parts, (list, tuple)):
            parts = [parts]
        text = "\n".join(filter(None, (_part_text(part) for part in parts))).strip()
        if not text:
            continue
        if role in {"model", "assistant"}:
            messages.append({"role": "assistant", "content": text})
        elif role in {"system", "developer"}:
            messages.append({"role": "system", "content": text})
        else:
            messages.append({"role": "user", "content": text})

    if loose_text:
        messages.append({"role": "user", "content": "\n".join(loose_text)})
    if not messages:
        return ""
    return messages


def _extract_text(response: Any) -> str:
    if isinstance(response, dict):
        return str(response.get("content") or response.get("text") or "")
    return str(getattr(response, "text", response) or "")


def _extract_usage(response: Any) -> Any:
    if isinstance(response, dict):
        return response.get("usage") or response.get("usage_metadata")
    return getattr(response, "usage_metadata", None) or getattr(response, "usage", None)


class ProviderModelsCompat:
    def __init__(self, provider: Any, model_id: str):
        self._provider = provider
        self._model_id = model_id

    def _request_kwargs(self, config: Any) -> dict[str, Any]:
        if config is None:
            return {}
        tools = _value(config, "tools", None)
        if tools:
            raise RuntimeError(
                "当前云模型不支持 Google Search/GenerateContent 工具；请使用 Koto 联网搜索服务。"
            )
        kwargs: dict[str, Any] = {}
        system_instruction = _value(config, "system_instruction", None)
        if system_instruction:
            kwargs["system_instruction"] = str(system_instruction)
        temperature = _value(config, "temperature", None)
        if temperature is not None:
            kwargs["temperature"] = temperature
        max_tokens = _value(config, "max_output_tokens", None)
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        response_mime_type = str(_value(config, "response_mime_type", "") or "")
        if response_mime_type == "application/json":
            kwargs["response_format"] = {"type": "json_object"}
        return kwargs

    def _model(self, requested: Any) -> str:
        model = str(requested or "").strip()
        if not model or not model.lower().startswith("deepseek"):
            return self._model_id
        return model

    def generate_content(
        self,
        model: Any = None,
        contents: Any = "",
        config: Any = None,
        **kwargs: Any,
    ) -> CompatGenerateContentResponse:
        request_kwargs = self._request_kwargs(config)
        request_kwargs.update(kwargs)
        request_kwargs.pop("stream", None)
        response = self._provider.generate_content(
            prompt=_normalize_prompt(contents),
            model=self._model(model),
            stream=False,
            **request_kwargs,
        )
        return CompatGenerateContentResponse(
            text=_extract_text(response), usage_metadata=_extract_usage(response)
        )

    def generate_content_stream(
        self,
        model: Any = None,
        contents: Any = "",
        config: Any = None,
        **kwargs: Any,
    ) -> Iterable[CompatGenerateContentResponse]:
        request_kwargs = self._request_kwargs(config)
        request_kwargs.update(kwargs)
        request_kwargs.pop("stream", None)
        stream = self._provider.generate_content(
            prompt=_normalize_prompt(contents),
            model=self._model(model),
            stream=True,
            **request_kwargs,
        )
        for chunk in stream:
            text = _extract_text(chunk)
            if text:
                yield CompatGenerateContentResponse(
                    text=text, usage_metadata=_extract_usage(chunk)
                )

    def generate_images(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(
            "当前 DeepSeek 云模型不支持图像生成，请使用独立图像生成能力。"
        )


class ProviderClientCompat:
    def __init__(self, provider: Any, model_id: str):
        self.models = ProviderModelsCompat(provider, model_id)


def create_cloud_client_compat() -> ProviderClientCompat:
    provider_name = get_configured_cloud_provider()
    model_id = get_configured_cloud_model(provider=provider_name)
    provider = get_llm_provider(provider=provider_name, model=model_id)
    return ProviderClientCompat(provider, model_id)
