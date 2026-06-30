# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Koto OpenAI Provider
====================
Implements LLMProvider for OpenAI-compatible APIs (gpt-4o, gpt-4.1, etc.).
Returns the same response dict format as GeminiProvider so UnifiedAgent
and all other consumers work without modification:

    {
        "content":    str,                      # assistant text
        "tool_calls": [{"name": str, "args": dict}, ...],
        "usage":      {"prompt_tokens": int, "completion_tokens": int},
    }

Streaming yields the same keys with partial content accumulated.

Requires:  pip install openai>=1.0
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Generator, List, Optional, Union

from .base import LLMProvider

logger = logging.getLogger(__name__)

try:
    from openai import (  # type: ignore
        APIConnectionError,
        APIStatusError,
        APITimeoutError,
        OpenAI,
    )

    _openai_available = True
except ImportError:
    _openai_available = False
    OpenAI = None  # type: ignore


class OpenAIProvider(LLMProvider):
    """OpenAI / Azure-OpenAI compatible LLM provider."""

    MAX_RETRIES = 3
    RETRY_BASE_DELAY = 2.0
    CALL_TIMEOUT: int = int(os.getenv("OPENAI_CALL_TIMEOUT", "60"))

    # Cheap fast model used for token counting (not the full model)
    _COUNT_MODEL = "gpt-4o-mini"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")  # for Azure / local
        self.client = None

        if not _openai_available:
            logger.warning(
                "[OpenAIProvider] openai package not installed (pip install openai)"
            )
            return
        if not self.api_key:
            logger.warning("[OpenAIProvider] No OPENAI_API_KEY found")
            return

        try:
            kwargs: Dict[str, Any] = {
                "api_key": self.api_key,
                "timeout": self.CALL_TIMEOUT,
            }
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self.client = OpenAI(**kwargs)
        except Exception as exc:
            logger.error(f"[OpenAIProvider] Client init failed: {exc}")

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_content(
        self,
        prompt: Union[str, List[Dict[str, Any]]],
        model: str = "gpt-4o",
        system_instruction: Optional[str] = None,
        tools: Optional[List[Any]] = None,
        stream: bool = False,
        **kwargs,
    ) -> Union[Dict[str, Any], Generator[Dict[str, Any], None, None]]:
        if not self.client:
            raise ImportError("[OpenAIProvider] client not initialised")

        messages = self._build_messages(prompt, system_instruction)
        oai_tools = self._format_tools(tools)

        call_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 8192),
            "stream": stream,
        }
        for passthrough_key in (
            "extra_body",
            "extra_headers",
            "response_format",
            "timeout",
        ):
            if kwargs.get(passthrough_key) is not None:
                call_kwargs[passthrough_key] = kwargs[passthrough_key]
        if oai_tools:
            call_kwargs["tools"] = oai_tools
            call_kwargs["tool_choice"] = "auto"

        for attempt in range(self.MAX_RETRIES):
            try:
                if stream:
                    # 只在官方 OpenAI 下安全包含 include_usage
                    # 以防第三方兼容 API (如 ollama, deepseek) 报错 "Unknown parameter"
                    if "api.openai.com" in str(self.client.base_url):
                        call_kwargs["stream_options"] = {"include_usage": True}
                    elif "stream_options" in call_kwargs:
                        del call_kwargs["stream_options"]

                    return self._stream_generator(
                        self.client.chat.completions.create(**call_kwargs),
                        model=model,
                        skill_id=kwargs.get("skill_id"),
                        session_id=kwargs.get("session_id"),
                    )
                resp = self.client.chat.completions.create(**call_kwargs)
                result = self._format_response(resp)
                self._track_usage(
                    model,
                    result.get("usage"),
                    skill_id=kwargs.get("skill_id"),
                    session_id=kwargs.get("session_id"),
                )
                return result
            except Exception as exc:
                retryable = _openai_available and isinstance(
                    exc, (APIStatusError, APITimeoutError, APIConnectionError)
                )
                status = getattr(exc, "status_code", None)
                if (
                    retryable
                    and status in (429, 500, 502, 503)
                    and attempt < self.MAX_RETRIES - 1
                ):
                    delay = self.RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        f"[OpenAIProvider] Retryable error, retry {attempt+1} in {delay}s: {exc}"
                    )
                    time.sleep(delay)
                    continue
                raise

    def get_token_count(
        self, prompt: Union[str, List[Dict[str, Any]]], model: str
    ) -> int:
        try:
            import tiktoken  # type: ignore

            enc = tiktoken.encoding_for_model(
                model.replace("gpt-4o", "gpt-4").replace("-preview", "")
            )
            text = (
                prompt
                if isinstance(prompt, str)
                else json.dumps(prompt, ensure_ascii=False)
            )
            return len(enc.encode(text))
        except Exception:
            text = prompt if isinstance(prompt, str) else str(prompt)
            return max(1, len(text) // 3)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_messages(
        self,
        prompt: Union[str, List[Dict[str, Any]]],
        system_instruction: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Convert Koto contents format → OpenAI messages list."""
        messages: List[Dict[str, Any]] = []

        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})

        if isinstance(prompt, str):
            messages.append({"role": "user", "content": prompt})
            return messages

        # Multi-turn history (Koto format: [{role, content/parts}, ...])
        for turn in prompt:
            role = turn.get("role", "user")
            # Map Gemini role names → OpenAI
            if role == "model":
                role = "assistant"
            elif role == "function":
                role = "tool"

            # content can be a string or list of parts
            content = turn.get("content") or turn.get("parts", "")
            if isinstance(content, list):
                # Flatten parts list to string
                content = " ".join(
                    p if isinstance(p, str) else (p.get("text") or str(p))
                    for p in content
                )

            tool_calls_raw = turn.get("tool_calls")

            if role == "assistant" and tool_calls_raw:
                # model turn with tool calls
                oai_tool_calls = []
                for i, tc in enumerate(tool_calls_raw):
                    tool_call_id = (
                        str(tc.get("id") or f"call_{i}").strip() or f"call_{i}"
                    )
                    oai_tool_calls.append(
                        {
                            "id": tool_call_id,
                            "type": "function",
                            "function": {
                                "name": tc.get("name", ""),
                                "arguments": json.dumps(
                                    tc.get("args", {}), ensure_ascii=False
                                ),
                            },
                        }
                    )
                assistant_message = {
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": oai_tool_calls,
                }
                if turn.get("reasoning_content"):
                    assistant_message["reasoning_content"] = str(
                        turn.get("reasoning_content")
                    )
                messages.append(assistant_message)
            elif role == "tool":
                # function result
                name = turn.get("name", "tool")
                tool_call_id = str(turn.get("tool_call_id") or "").strip()
                if not tool_call_id:
                    tool_call_id = str(turn.get("id") or "call_0").strip() or "call_0"
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": name,
                        "content": str(content),
                    }
                )
            else:
                message = {"role": role, "content": str(content)}
                if role == "assistant" and turn.get("reasoning_content"):
                    message["reasoning_content"] = str(turn.get("reasoning_content"))
                messages.append(message)

        return self._sanitize_tool_call_messages(messages)

    def _sanitize_tool_call_messages(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        sanitized: List[Dict[str, Any]] = []
        index = 0
        while index < len(messages):
            message = messages[index]
            if message.get("role") == "assistant" and message.get("tool_calls"):
                expected_ids = {
                    str(tool_call.get("id") or "").strip()
                    for tool_call in (message.get("tool_calls") or [])
                    if str(tool_call.get("id") or "").strip()
                }
                tool_messages: List[Dict[str, Any]] = []
                next_index = index + 1
                while (
                    next_index < len(messages)
                    and messages[next_index].get("role") == "tool"
                ):
                    tool_messages.append(messages[next_index])
                    next_index += 1

                matched: List[Dict[str, Any]] = []
                extra: List[Dict[str, Any]] = []
                seen_ids: set[str] = set()
                for tool_message in tool_messages:
                    tool_call_id = str(tool_message.get("tool_call_id") or "").strip()
                    if tool_call_id in expected_ids and tool_call_id not in seen_ids:
                        matched.append(tool_message)
                        seen_ids.add(tool_call_id)
                    else:
                        extra.append(tool_message)

                if expected_ids and seen_ids == expected_ids:
                    sanitized.append(message)
                    sanitized.extend(matched)
                    sanitized.extend(
                        self._tool_message_as_context(item) for item in extra
                    )
                else:
                    sanitized.append(
                        self._assistant_message_without_tool_calls(message)
                    )
                    sanitized.extend(
                        self._tool_message_as_context(item) for item in tool_messages
                    )
                index = next_index
                continue

            if message.get("role") == "tool":
                sanitized.append(self._tool_message_as_context(message))
            else:
                sanitized.append(message)
            index += 1

        return sanitized

    def _assistant_message_without_tool_calls(
        self, message: Dict[str, Any]
    ) -> Dict[str, Any]:
        content = str(message.get("content") or "").strip()
        if not content:
            names: List[str] = []
            for tool_call in message.get("tool_calls") or []:
                function = (
                    tool_call.get("function") if isinstance(tool_call, dict) else None
                )
                if isinstance(function, dict):
                    name = str(function.get("name") or "").strip()
                elif isinstance(tool_call, dict):
                    name = str(tool_call.get("name") or "").strip()
                else:
                    name = ""
                if name:
                    names.append(name)
            content = "工具调用记录已省略"
            if names:
                content += "：" + "、".join(names)

        sanitized = {"role": "assistant", "content": content}
        if message.get("reasoning_content"):
            sanitized["reasoning_content"] = str(message.get("reasoning_content"))
        return sanitized

    def _tool_message_as_context(self, message: Dict[str, Any]) -> Dict[str, str]:
        name = str(message.get("name") or "tool").strip() or "tool"
        content = str(message.get("content") or "")
        return {"role": "user", "content": f"工具结果（{name}）：{content}"}

    def _format_tools(self, tools: Optional[List[Any]]) -> Optional[List[Dict]]:
        if not tools:
            return None
        oai_tools = []
        for t in tools:
            if not isinstance(t, dict) or not t.get("name"):
                continue
            parameters = self._normalize_json_schema(
                t.get("parameters") or {"type": "object", "properties": {}}
            )
            oai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": parameters,
                    },
                }
            )
        return oai_tools or None

    def _normalize_json_schema(self, schema: Any) -> Any:
        """Normalize Koto/Gemini-flavored schemas for OpenAI-compatible APIs."""
        if isinstance(schema, list):
            return [self._normalize_json_schema(item) for item in schema]
        if not isinstance(schema, dict):
            return schema

        normalized: Dict[str, Any] = {}
        for key, value in schema.items():
            if key == "type" and isinstance(value, str):
                normalized[key] = value.lower()
            elif key == "anyOf" and isinstance(value, list):
                normalized[key] = [self._normalize_json_schema(item) for item in value]
            else:
                normalized[key] = self._normalize_json_schema(value)

        if normalized.get("type") == "object":
            normalized.setdefault("properties", {})
        if normalized.get("type") == "array":
            normalized.setdefault("items", {})
        return normalized

    def _format_response(self, resp: Any) -> Dict[str, Any]:
        choice = resp.choices[0] if resp.choices else None
        content = ""
        reasoning_content = ""
        tool_calls: List[Dict[str, Any]] = []

        if choice:
            msg = choice.message
            content = msg.content or ""
            reasoning_content = getattr(msg, "reasoning_content", None) or ""
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    tool_calls.append(
                        {
                            "id": str(getattr(tc, "id", "") or ""),
                            "name": tc.function.name,
                            "args": args,
                        }
                    )

        usage = {}
        if resp.usage:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens or 0,
                "completion_tokens": resp.usage.completion_tokens or 0,
            }

        result = {"content": content, "tool_calls": tool_calls, "usage": usage}
        if reasoning_content:
            result["reasoning_content"] = reasoning_content
        return result

    def _stream_generator(
        self,
        stream_resp: Any,
        model: str,
        skill_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        accumulated = ""
        for chunk in stream_resp:
            usage = getattr(chunk, "usage", None)
            if usage:
                self._track_usage(
                    model,
                    usage,
                    skill_id=skill_id,
                    session_id=session_id,
                )

            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue
            piece = delta.content or ""
            accumulated += piece
            yield {
                "content": accumulated,
                "tool_calls": [],
                "usage": usage.model_dump() if usage else {},
                "delta": piece,
            }
