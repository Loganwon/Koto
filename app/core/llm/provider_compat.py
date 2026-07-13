"""Provider-neutral compatibility surface for legacy SDK-shaped callers.

New code should call ``get_llm_provider`` directly.  This module exists only
while older services are migrated away from ``client.models.generate_content``.
It never loads a vendor SDK and always resolves the active DeepSeek provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from .provider_factory import get_llm_provider


class _DataObject:
    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


class GenerateContentConfig(_DataObject):
    pass


class GenerateImagesConfig(_DataObject):
    pass


class ThinkingConfig(_DataObject):
    pass


class FunctionDeclaration(_DataObject):
    pass


class Tool(_DataObject):
    pass


class GoogleSearch(_DataObject):
    pass


@dataclass
class Part:
    text: str | None = None
    data: bytes | None = None
    mime_type: str | None = None

    @classmethod
    def from_text(cls, *, text: str) -> "Part":
        return cls(text=text)

    @classmethod
    def from_bytes(cls, *, data: bytes, mime_type: str) -> "Part":
        return cls(data=data, mime_type=mime_type)


@dataclass
class Content:
    role: str
    parts: list[Part]


class Candidate(_DataObject):
    pass


class UsageMetadata(_DataObject):
    pass


types = SimpleNamespace(
    GenerateContentConfig=GenerateContentConfig,
    GenerateImagesConfig=GenerateImagesConfig,
    ThinkingConfig=ThinkingConfig,
    FunctionDeclaration=FunctionDeclaration,
    Tool=Tool,
    GoogleSearch=GoogleSearch,
    Part=Part,
    Content=Content,
    Candidate=Candidate,
    UsageMetadata=UsageMetadata,
)


def _config_kwargs(config: Any) -> dict[str, Any]:
    if config is None:
        return {}
    values = dict(vars(config)) if hasattr(config, "__dict__") else dict(config or {})
    mapped: dict[str, Any] = {}
    if values.get("system_instruction"):
        mapped["system_instruction"] = values["system_instruction"]
    if values.get("temperature") is not None:
        mapped["temperature"] = values["temperature"]
    if values.get("max_output_tokens") is not None:
        mapped["max_tokens"] = values["max_output_tokens"]
    if values.get("tools") is not None:
        mapped["tools"] = _normalize_tools(values["tools"])
    if values.get("response_mime_type") == "application/json":
        mapped["response_format"] = {"type": "json_object"}
    return mapped


def _normalize_tools(tools: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for tool in tools or []:
        declarations = getattr(tool, "function_declarations", None) or []
        for declaration in declarations:
            values = (
                vars(declaration) if hasattr(declaration, "__dict__") else declaration
            )
            if not isinstance(values, dict) or not values.get("name"):
                continue
            normalized.append(
                {
                    "name": values["name"],
                    "description": values.get("description", ""),
                    "parameters": values.get("parameters")
                    or {"type": "object", "properties": {}},
                }
            )
        if isinstance(tool, dict) and tool.get("name"):
            normalized.append(tool)
    return normalized


def _normalize_contents(contents: Any) -> Any:
    if isinstance(contents, list):
        normalized = []
        for item in contents:
            parts = getattr(item, "parts", None)
            if parts and any(getattr(part, "data", None) for part in parts):
                raise RuntimeError(
                    "The active DeepSeek provider does not support binary media input."
                )
            if parts is not None:
                normalized.append(
                    {
                        "role": getattr(item, "role", "user"),
                        "content": " ".join(
                            str(getattr(part, "text", "") or "") for part in parts
                        ),
                    }
                )
            elif isinstance(item, dict):
                normalized.append(item)
            else:
                normalized.append({"role": "user", "content": str(item)})
        return normalized
    return contents


class _Response:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.text = (
            str(payload.get("content") or payload.get("text") or "")
            if isinstance(payload, dict)
            else str(getattr(payload, "text", payload) or "")
        )
        self.usage_metadata = (
            payload.get("usage") if isinstance(payload, dict) else None
        )


class _ModelsProxy:
    def generate_content(
        self,
        *,
        model: str | None = None,
        contents: Any = None,
        config: Any = None,
        **kwargs: Any,
    ) -> _Response:
        provider = get_llm_provider(provider="deepseek", allow_local_fallback=False)
        request_kwargs = _config_kwargs(config)
        request_kwargs.update(kwargs)
        payload = provider.generate_content(
            prompt=_normalize_contents(contents),
            model=(
                model if str(model or "").startswith("deepseek") else "deepseek-chat"
            ),
            **request_kwargs,
        )
        return _Response(payload)

    def generate_content_stream(self, **kwargs: Any):
        provider = get_llm_provider(provider="deepseek", allow_local_fallback=False)
        config = kwargs.pop("config", None)
        model = kwargs.pop("model", None)
        contents = kwargs.pop("contents", None)
        request_kwargs = _config_kwargs(config)
        request_kwargs.update(kwargs)
        return provider.generate_content(
            prompt=_normalize_contents(contents),
            model=(
                model if str(model or "").startswith("deepseek") else "deepseek-chat"
            ),
            stream=True,
            **request_kwargs,
        )


class Client:
    def __init__(self, *_: Any, **__: Any) -> None:
        self.models = _ModelsProxy()


def create_provider_client() -> Client:
    return Client()
