# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""DeepSeek provider built on the OpenAI-compatible chat API."""

from __future__ import annotations

import os
from typing import Any, Dict, Generator, List, Optional, Union

from .deepseek_config import (
    DEEPSEEK_DEFAULT_BASE_URL,
    DEEPSEEK_DEFAULT_MODEL,
    get_deepseek_api_key,
)
from .openai_provider import OpenAIProvider


class DeepSeekProvider(OpenAIProvider):
    """DeepSeek cloud provider using OpenAI-compatible chat completions."""

    CALL_TIMEOUT: int = int(os.getenv("DEEPSEEK_CALL_TIMEOUT", "120"))
    _COUNT_MODEL = DEEPSEEK_DEFAULT_MODEL

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        super().__init__(
            api_key=get_deepseek_api_key(api_key),
            base_url=(
                base_url
                or os.getenv("DEEPSEEK_BASE_URL")
                or os.getenv("DEEPSEEK_API_BASE")
                or DEEPSEEK_DEFAULT_BASE_URL
            ),
        )

    def generate_content(
        self,
        prompt: Union[str, List[Dict[str, Any]]],
        model: str = DEEPSEEK_DEFAULT_MODEL,
        system_instruction: Optional[str] = None,
        tools: Optional[List[Any]] = None,
        stream: bool = False,
        **kwargs,
    ) -> Union[Dict[str, Any], Generator[Dict[str, Any], None, None]]:
        kwargs.setdefault("max_tokens", int(os.getenv("DEEPSEEK_MAX_TOKENS", "8192")))
        has_assistant_turn = False
        if isinstance(prompt, list):
            has_assistant_turn = any(
                str(turn.get("role", "")).lower() in {"assistant", "model"}
                and not turn.get("reasoning_content")
                for turn in prompt
                if isinstance(turn, dict)
            )
            has_assistant_turn = has_assistant_turn or any(
                str(turn.get("role", "")).lower() in {"assistant", "model"}
                for turn in prompt
                if isinstance(turn, dict)
            )
        thinking_allowed = (
            os.getenv("DEEPSEEK_ENABLE_THINKING", "true").lower()
            not in {"0", "false", "no"}
            and not tools
            and not has_assistant_turn
        )
        if thinking_allowed:
            extra_body = dict(kwargs.get("extra_body") or {})
            extra_body.setdefault("thinking", {"type": "enabled"})
            extra_body.setdefault(
                "reasoning_effort", os.getenv("DEEPSEEK_REASONING_EFFORT", "high")
            )
            kwargs["extra_body"] = extra_body
        return super().generate_content(
            prompt=prompt,
            model=model or DEEPSEEK_DEFAULT_MODEL,
            system_instruction=system_instruction,
            tools=tools,
            stream=stream,
            **kwargs,
        )
