# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Koto Anthropic Provider
=======================
Implements LLMProvider for Anthropic Claude (claude-3-7-sonnet, claude-3-5-haiku, etc.).
Returns the same response dict format as GeminiProvider:

    {
        "content":    str,
        "tool_calls": [{"name": str, "args": dict}, ...],
        "usage":      {"prompt_tokens": int, "completion_tokens": int},
    }

Requires:  pip install anthropic>=0.30
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Generator, List, Optional, Union

from .base import LLMProvider

logger = logging.getLogger(__name__)

try:
    import anthropic as _anthropic  # type: ignore
    from anthropic import (  # type: ignore
        Anthropic,
        APIConnectionError,
        APIStatusError,
        APITimeoutError,
    )

    _anthropic_available = True
except ImportError:
    _anthropic_available = False
    Anthropic = None  # type: ignore


class AnthropicProvider(LLMProvider):
    """Anthropic Claude LLM provider."""

    MAX_RETRIES = 3
    RETRY_BASE_DELAY = 2.0
    CALL_TIMEOUT: int = int(os.getenv("ANTHROPIC_CALL_TIMEOUT", "60"))
    # Claude's max output tokens cap
    MAX_OUTPUT_TOKENS: int = 16000

    def __init__(self, api_key: str | None = None):
        self.api_key = (
            api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
        )
        self.client = None

        if not _anthropic_available:
            logger.warning(
                "[AnthropicProvider] anthropic package not installed (pip install anthropic)"
            )
            return
        if not self.api_key:
            logger.warning("[AnthropicProvider] No ANTHROPIC_API_KEY found")
            return

        try:
            self.client = Anthropic(
                api_key=self.api_key,
                timeout=float(self.CALL_TIMEOUT),
            )
        except Exception as exc:
            logger.error(f"[AnthropicProvider] Client init failed: {exc}")

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_content(
        self,
        prompt: Union[str, List[Dict[str, Any]]],
        model: str = "claude-3-7-sonnet-20250219",
        system_instruction: Optional[str] = None,
        tools: Optional[List[Any]] = None,
        stream: bool = False,
        **kwargs,
    ) -> Union[Dict[str, Any], Generator[Dict[str, Any], None, None]]:
        if not self.client:
            raise ImportError("[AnthropicProvider] client not initialised")

        messages = self._build_messages(prompt)
        claude_tools = self._format_tools(tools)

        call_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": min(kwargs.get("max_tokens", 8192), self.MAX_OUTPUT_TOKENS),
        }
        if system_instruction:
            call_kwargs["system"] = system_instruction
        if claude_tools:
            call_kwargs["tools"] = claude_tools

        # Claude extended thinking (budget_tokens kwarg)
        thinking_budget = kwargs.get("thinking_budget") or kwargs.get("budget_tokens")
        if thinking_budget and int(thinking_budget) > 0:
            call_kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": int(thinking_budget),
            }
            # Extended thinking requires temperature=1
            call_kwargs["temperature"] = 1
        else:
            call_kwargs["temperature"] = kwargs.get("temperature", 0.7)

        for attempt in range(self.MAX_RETRIES):
            try:
                if stream:
                    return self._stream_generator(
                        model,
                        call_kwargs,
                        skill_id=kwargs.get("skill_id"),
                        session_id=kwargs.get("session_id"),
                    )
                resp = self.client.messages.create(**call_kwargs)
                result = self._format_response(resp)
                self._track_usage(
                    model,
                    result.get("usage"),
                    skill_id=kwargs.get("skill_id"),
                    session_id=kwargs.get("session_id"),
                )
                return result
            except Exception as exc:
                retryable = _anthropic_available and isinstance(
                    exc, (APIStatusError, APITimeoutError, APIConnectionError)
                )
                status = getattr(exc, "status_code", None)
                if (
                    retryable
                    and status in (429, 500, 529)
                    and attempt < self.MAX_RETRIES - 1
                ):
                    delay = self.RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        f"[AnthropicProvider] Retryable error, retry {attempt+1} in {delay}s: {exc}"
                    )
                    time.sleep(delay)
                    continue
                raise

    def get_token_count(
        self, prompt: Union[str, List[Dict[str, Any]]], model: str
    ) -> int:
        if not self.client:
            text = prompt if isinstance(prompt, str) else str(prompt)
            return max(1, len(text) // 3)
        try:
            messages = self._build_messages(prompt)
            resp = self.client.messages.count_tokens(
                model=model,
                messages=messages,
            )
            return int(getattr(resp, "input_tokens", 0))
        except Exception:
            text = prompt if isinstance(prompt, str) else str(prompt)
            return max(1, len(text) // 3)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_messages(
        self, prompt: Union[str, List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """Convert Koto contents format → Anthropic messages list."""
        if isinstance(prompt, str):
            return [{"role": "user", "content": prompt}]

        messages: List[Dict[str, Any]] = []
        for turn in prompt:
            role = turn.get("role", "user")
            # Map Gemini/Koto role names → Anthropic (user / assistant)
            if role in ("model", "assistant"):
                role = "assistant"
            elif role == "function":
                # Tool result → wrap in tool_result block
                name = turn.get("name", "tool")
                content_text = turn.get("content") or ""
                if isinstance(content_text, list):
                    content_text = " ".join(
                        p if isinstance(p, str) else str(p) for p in content_text
                    )
                # Anthropic tool results must follow the assistant tool_use block
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": f"toolu_{len(messages)}",
                                "content": str(content_text),
                            }
                        ],
                    }
                )
                continue
            else:
                role = "user"

            content = turn.get("content") or turn.get("parts", "")
            if isinstance(content, list):
                content = " ".join(
                    p if isinstance(p, str) else (p.get("text") or str(p))
                    for p in content
                )

            tool_calls_raw = turn.get("tool_calls")
            if role == "assistant" and tool_calls_raw:
                # Emit tool_use content blocks
                content_blocks: List[Dict] = []
                if content:
                    content_blocks.append({"type": "text", "text": str(content)})
                for i, tc in enumerate(tool_calls_raw):
                    content_blocks.append(
                        {
                            "type": "tool_use",
                            "id": f"toolu_{len(messages)}_{i}",
                            "name": tc.get("name", ""),
                            "input": tc.get("args", {}),
                        }
                    )
                messages.append({"role": "assistant", "content": content_blocks})
            else:
                messages.append({"role": role, "content": str(content)})

        return messages

    def _format_tools(self, tools: Optional[List[Any]]) -> Optional[List[Dict]]:
        if not tools:
            return None
        claude_tools = []
        for t in tools:
            if not isinstance(t, dict) or not t.get("name"):
                continue
            params = t.get("parameters") or {"type": "object", "properties": {}}
            claude_tools.append(
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "input_schema": params,
                }
            )
        return claude_tools or None

    def _format_response(self, resp: Any) -> Dict[str, Any]:
        content_text = ""
        tool_calls: List[Dict[str, Any]] = []

        for block in resp.content or []:
            btype = getattr(block, "type", "")
            if btype == "text":
                content_text += getattr(block, "text", "")
            elif btype == "tool_use":
                tool_calls.append(
                    {
                        "name": getattr(block, "name", ""),
                        "args": dict(getattr(block, "input", {}) or {}),
                    }
                )
            # Extended thinking blocks (type="thinking") are intentionally skipped
            # so the agent sees only the final answer, not raw CoT

        usage = {}
        if resp.usage:
            usage = {
                "prompt_tokens": getattr(resp.usage, "input_tokens", 0),
                "completion_tokens": getattr(resp.usage, "output_tokens", 0),
            }

        return {"content": content_text, "tool_calls": tool_calls, "usage": usage}

    def _stream_generator(
        self,
        model: str,
        call_kwargs: Dict[str, Any],
        skill_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        accumulated = ""
        with self.client.messages.stream(**call_kwargs) as s:
            for text in s.text_stream:
                accumulated += text
                yield {
                    "content": accumulated,
                    "tool_calls": [],
                    "usage": {},
                    "delta": text,
                }
            try:
                message = s.get_message()
                if hasattr(message, "usage") and message.usage:
                    self._track_usage(
                        model,
                        message.usage,
                        skill_id=skill_id,
                        session_id=session_id,
                    )
            except Exception as e:
                logger.debug(f"[Anthropic] Could not retrieve stream usage: {e}")
