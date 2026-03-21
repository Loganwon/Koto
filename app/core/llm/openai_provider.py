# -*- coding: utf-8 -*-
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
    from openai import OpenAI, APIStatusError, APITimeoutError, APIConnectionError  # type: ignore
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
        self.api_key = (
            api_key
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("OPENAI_KEY")
        )
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")  # for Azure / local
        self.client = None

        if not _openai_available:
            logger.warning("[OpenAIProvider] openai package not installed (pip install openai)")
            return
        if not self.api_key:
            logger.warning("[OpenAIProvider] No OPENAI_API_KEY found")
            return

        try:
            kwargs: Dict[str, Any] = {"api_key": self.api_key, "timeout": self.CALL_TIMEOUT}
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
        if oai_tools:
            call_kwargs["tools"] = oai_tools
            call_kwargs["tool_choice"] = "auto"

        for attempt in range(self.MAX_RETRIES):
            try:
                if stream:
                    return self._stream_generator(
                        self.client.chat.completions.create(**call_kwargs)
                    )
                resp = self.client.chat.completions.create(**call_kwargs)
                return self._format_response(resp)
            except Exception as exc:
                retryable = _openai_available and isinstance(
                    exc, (APIStatusError, APITimeoutError, APIConnectionError)
                )
                status = getattr(exc, "status_code", None)
                if retryable and status in (429, 500, 502, 503) and attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(f"[OpenAIProvider] Retryable error, retry {attempt+1} in {delay}s: {exc}")
                    time.sleep(delay)
                    continue
                raise

    def get_token_count(
        self, prompt: Union[str, List[Dict[str, Any]]], model: str
    ) -> int:
        try:
            import tiktoken  # type: ignore
            enc = tiktoken.encoding_for_model(model.replace("gpt-4o", "gpt-4").replace("-preview", ""))
            text = prompt if isinstance(prompt, str) else json.dumps(prompt, ensure_ascii=False)
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
                    oai_tool_calls.append({
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": json.dumps(tc.get("args", {}), ensure_ascii=False),
                        },
                    })
                messages.append({"role": "assistant", "content": content or None, "tool_calls": oai_tool_calls})
            elif role == "tool":
                # function result
                name = turn.get("name", "tool")
                messages.append({"role": "tool", "tool_call_id": f"call_0", "name": name, "content": str(content)})
            else:
                messages.append({"role": role, "content": str(content)})

        return messages

    def _format_tools(self, tools: Optional[List[Any]]) -> Optional[List[Dict]]:
        if not tools:
            return None
        oai_tools = []
        for t in tools:
            if not isinstance(t, dict) or not t.get("name"):
                continue
            oai_tools.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters") or {"type": "object", "properties": {}},
                },
            })
        return oai_tools or None

    def _format_response(self, resp: Any) -> Dict[str, Any]:
        choice = resp.choices[0] if resp.choices else None
        content = ""
        tool_calls: List[Dict[str, Any]] = []

        if choice:
            msg = choice.message
            content = msg.content or ""
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    tool_calls.append({"name": tc.function.name, "args": args})

        usage = {}
        if resp.usage:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens or 0,
                "completion_tokens": resp.usage.completion_tokens or 0,
            }

        return {"content": content, "tool_calls": tool_calls, "usage": usage}

    def _stream_generator(self, stream_resp: Any) -> Generator[Dict[str, Any], None, None]:
        accumulated = ""
        for chunk in stream_resp:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue
            piece = delta.content or ""
            accumulated += piece
            yield {"content": accumulated, "tool_calls": [], "usage": {}, "delta": piece}
