# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Provider-neutral LLM gateway for the application runtime.

Unlike the retired SDK compatibility client, this boundary exposes generation
operations directly.  It selects the configured cloud or local provider once
and keeps request/response normalization out of ``web.app``.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Iterable

from app.core.llm.model_selection import (
    get_configured_cloud_model,
    get_configured_cloud_provider,
)
from app.core.llm.provider_factory import (
    get_llm_provider,
    get_local_model_tag,
    is_local_mode,
)


@dataclass(frozen=True)
class LLMGatewayResponse:
    text: str
    usage_metadata: Any = None


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _part_text(part: Any) -> str:
    if isinstance(part, str):
        return part
    text = _value(part, "text", None)
    if text is not None:
        return str(text)
    data = _value(part, "data", None) or _value(part, "inline_data", None)
    if data is not None or _value(part, "file_data", None) is not None:
        raise RuntimeError(
            "当前模型网关不接受 SDK 二进制 Part；请使用对应的图像或文件能力。"
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
        if isinstance(item, dict) and "content" in item and "parts" not in item:
            messages.append(
                {
                    "role": str(item.get("role") or "user"),
                    "content": str(item.get("content") or ""),
                }
            )
            continue
        role = str(_value(item, "role", "user") or "user").lower()
        parts = _value(item, "parts", None)
        if parts is None:
            parts = [item]
        elif not isinstance(parts, (list, tuple)):
            parts = [parts]
        text = "\n".join(filter(None, (_part_text(part) for part in parts))).strip()
        if not text:
            continue
        normalized_role = (
            "assistant"
            if role in {"model", "assistant"}
            else "system" if role in {"system", "developer"} else "user"
        )
        messages.append({"role": normalized_role, "content": text})
    if loose_text:
        messages.append({"role": "user", "content": "\n".join(loose_text)})
    return messages or ""


def _config_kwargs(config: Any) -> dict[str, Any]:
    if config is None:
        return {}
    tools = _value(config, "tools", None)
    if tools:
        raise RuntimeError(
            "SDK 工具声明不能通过通用模型网关执行；请使用 Koto 工具运行时。"
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
    if str(_value(config, "response_mime_type", "") or "") == "application/json":
        kwargs["response_format"] = {"type": "json_object"}
    return kwargs


def _response_text(response: Any) -> str:
    if isinstance(response, dict):
        return str(response.get("content") or response.get("text") or "")
    return str(getattr(response, "text", response) or "")


def _response_usage(response: Any) -> Any:
    if isinstance(response, dict):
        return response.get("usage") or response.get("usage_metadata")
    return getattr(response, "usage_metadata", None) or getattr(response, "usage", None)


class LLMRuntimeGateway:
    """Direct generation boundary over a configured :class:`LLMProvider`."""

    def __init__(self, provider: Any, model_id: str) -> None:
        self._provider = provider
        self.model_id = str(model_id or "").strip()

    def _model(self, requested: Any) -> str:
        value = str(requested or "").strip()
        return value or self.model_id

    def generate_content(
        self,
        model: Any = None,
        contents: Any = "",
        config: Any = None,
        **kwargs: Any,
    ) -> LLMGatewayResponse:
        request_kwargs = _config_kwargs(config)
        request_kwargs.update(kwargs)
        request_kwargs.pop("stream", None)
        response = self._provider.generate_content(
            prompt=_normalize_prompt(contents),
            model=self._model(model),
            stream=False,
            **request_kwargs,
        )
        return LLMGatewayResponse(
            text=_response_text(response),
            usage_metadata=_response_usage(response),
        )

    def generate_content_stream(
        self,
        model: Any = None,
        contents: Any = "",
        config: Any = None,
        **kwargs: Any,
    ) -> Iterable[LLMGatewayResponse]:
        request_kwargs = _config_kwargs(config)
        request_kwargs.update(kwargs)
        request_kwargs.pop("stream", None)
        chunks = self._provider.generate_content(
            prompt=_normalize_prompt(contents),
            model=self._model(model),
            stream=True,
            **request_kwargs,
        )
        for chunk in chunks:
            text = (
                str(chunk.get("delta") or "")
                if isinstance(chunk, dict) and "delta" in chunk
                else _response_text(chunk)
            )
            if text:
                yield LLMGatewayResponse(text, _response_usage(chunk))

    def list_models(self) -> list[Any]:
        """Return configured generation models without an SDK discovery call."""
        return (
            [
                SimpleNamespace(
                    name=self.model_id,
                    supported_actions=["generate_content", "generate_content_stream"],
                )
            ]
            if self.model_id
            else []
        )

    def generate_images(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("图片生成提供商未配置，请使用独立图像生成能力。")


def create_runtime_llm_gateway() -> LLMRuntimeGateway:
    if is_local_mode():
        model_id = get_local_model_tag()
        provider = get_llm_provider(provider="ollama", model=model_id)
        return LLMRuntimeGateway(provider, model_id)
    provider_name = get_configured_cloud_provider()
    model_id = get_configured_cloud_model(provider=provider_name)
    provider = get_llm_provider(provider=provider_name, model=model_id)
    return LLMRuntimeGateway(provider, model_id)
