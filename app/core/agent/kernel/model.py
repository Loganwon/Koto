"""Canonical model gateway and response contract for all Agent loops."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import (
    Any,
    Dict,
    Iterator,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    runtime_checkable,
)


class ModelProtocolError(ValueError):
    """A provider response cannot be represented by the Kernel contract."""


@dataclass(frozen=True)
class ModelToolCall:
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    call_id: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ModelToolCall":
        function = value.get("function")
        function = function if isinstance(function, Mapping) else {}
        name = str(
            value.get("name") or value.get("tool_name") or function.get("name") or ""
        ).strip()
        if not name:
            raise ModelProtocolError("model tool call requires a name")

        arguments = value.get("arguments")
        if arguments is None:
            arguments = value.get("args")
        if arguments is None:
            arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except Exception as exc:
                raise ModelProtocolError(
                    f"tool '{name}' arguments are not valid JSON"
                ) from exc
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, Mapping):
            raise ModelProtocolError(f"tool '{name}' arguments must be an object")

        return cls(
            name=name,
            arguments=copy.deepcopy(dict(arguments)),
            call_id=str(value.get("id") or value.get("call_id") or "").strip(),
        )

    def legacy_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "name": self.name,
            "args": copy.deepcopy(dict(self.arguments)),
        }
        if self.call_id:
            payload["id"] = self.call_id
        return payload


@dataclass(frozen=True)
class ModelResponse:
    content: str = ""
    tool_calls: tuple[ModelToolCall, ...] = ()
    reasoning: str = ""
    model: str = ""
    raw_parts: tuple[Any, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, value: Any, *, strict: bool = True) -> "ModelResponse":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(content=value)
        if not isinstance(value, Mapping):
            raise ModelProtocolError("model response must be an object or string")

        raw_calls = value.get("tool_calls") or []
        if not isinstance(raw_calls, Sequence) or isinstance(
            raw_calls, (str, bytes, bytearray)
        ):
            raise ModelProtocolError("model response tool_calls must be an array")

        calls: List[ModelToolCall] = []
        ignored_errors: List[str] = []
        for index, item in enumerate(raw_calls):
            if not isinstance(item, Mapping):
                error = f"tool call {index} must be an object"
                if strict:
                    raise ModelProtocolError(error)
                ignored_errors.append(error)
                continue
            try:
                calls.append(ModelToolCall.from_mapping(item))
            except ModelProtocolError as exc:
                if strict:
                    raise
                ignored_errors.append(str(exc))

        known = {
            "content",
            "tool_calls",
            "reasoning_content",
            "reasoning",
            "model",
            "_raw_parts",
            "parts",
        }
        metadata = {
            str(key): copy.deepcopy(item)
            for key, item in value.items()
            if key not in known
        }
        if ignored_errors:
            metadata["protocol_warnings"] = ignored_errors

        raw_parts = value.get("_raw_parts")
        if raw_parts is None:
            raw_parts = value.get("parts")
        if not isinstance(raw_parts, Sequence) or isinstance(
            raw_parts, (str, bytes, bytearray)
        ):
            raw_parts = []

        return cls(
            content=str(value.get("content") or ""),
            tool_calls=tuple(calls),
            reasoning=str(
                value.get("reasoning_content") or value.get("reasoning") or ""
            ),
            model=str(value.get("model") or ""),
            raw_parts=tuple(copy.deepcopy(list(raw_parts))),
            metadata=metadata,
        )

    def legacy_tool_calls(self) -> List[Dict[str, Any]]:
        return [call.legacy_dict() for call in self.tool_calls]

    def to_mapping(self) -> Dict[str, Any]:
        """Return the normalized provider-neutral response as a plain mapping."""

        payload: Dict[str, Any] = {
            "content": self.content,
            "tool_calls": self.legacy_tool_calls(),
        }
        if self.reasoning:
            payload["reasoning_content"] = self.reasoning
        if self.model:
            payload["model"] = self.model
        if self.raw_parts:
            payload["_raw_parts"] = copy.deepcopy(list(self.raw_parts))
        payload.update(copy.deepcopy(dict(self.metadata)))
        return payload


@dataclass(frozen=True)
class ModelStreamChunk:
    """Text is provisional until the final, fully assembled response arrives."""

    delta: str = ""
    response: Optional[ModelResponse] = None


def iter_model_stream(value: Any) -> Iterator[ModelStreamChunk]:
    """Normalize native delta streams and older non-streaming test providers.

    A provider must explicitly mark cumulative text with ``delta`` (possibly
    empty); unmarked ``content`` is an incremental chunk for legacy adapters.
    Tool calls are never exposed to the executor before this iterator finishes.
    """
    if isinstance(value, (Mapping, str, ModelResponse)):
        yield ModelStreamChunk(response=ModelResponse.from_raw(value))
        return
    content = ""
    final: Dict[str, Any] = {}
    finished = False
    try:
        for raw in value:
            if isinstance(raw, ModelStreamChunk):
                if raw.delta:
                    content += raw.delta
                    yield raw
                if raw.response is not None:
                    final = raw.response.to_mapping()
                    finished = True
                continue
            if isinstance(raw, str):
                piece = raw
                item: Mapping[str, Any] = {}
            elif isinstance(raw, Mapping):
                item = raw
                piece = str(item.get("delta", item.get("content", "")) or "")
                if item.get("stream_final"):
                    piece = str(item.get("delta") or "")
                    final = dict(item)
                    finished = True
                elif item.get("tool_calls"):
                    final["tool_calls"] = item["tool_calls"]
                if item.get("reasoning_content"):
                    final["reasoning_content"] = item["reasoning_content"]
            else:
                raise ModelProtocolError(
                    "model stream chunk must be an object or string"
                )
            if piece:
                if finished and not item.get("stream_final"):
                    raise ModelProtocolError(
                        "model emitted text after its final response"
                    )
                content += piece
                yield ModelStreamChunk(delta=piece)
        final.setdefault("content", content)
        yield ModelStreamChunk(response=ModelResponse.from_raw(final))
    finally:
        close = getattr(value, "close", None)
        if callable(close):
            close()


@runtime_checkable
class ModelGateway(Protocol):
    """The only model interface the future Kernel Runtime may depend on."""

    def generate(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        system: str,
        tools: Sequence[Mapping[str, Any]],
        model_id: str = "",
        options: Optional[Mapping[str, Any]] = None,
    ) -> ModelResponse: ...


__all__ = [
    "ModelGateway",
    "ModelProtocolError",
    "ModelResponse",
    "ModelToolCall",
    "ModelStreamChunk",
    "iter_model_stream",
]
