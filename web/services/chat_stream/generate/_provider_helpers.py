# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

import json
import time
import os
import re

from app.core.llm.chat_generation_policy import (
    first_token_timeout_seconds,
    select_regular_model,
    should_try_local_chat_fast_path,
)
from web.sse.sanitizer import safe_sse as _safe_sse


def _convert_history_to_messages(
    formatted_history: list,
    rag_input: str,
) -> list:
    """Convert compatibility history plus RAG text into provider messages."""
    messages = []
    for item in formatted_history:
        if hasattr(item, "role") and hasattr(item, "parts"):
            role = "assistant" if item.role == "model" else item.role
            text = "".join(
                (p.text if hasattr(p, "text") else str(p)) for p in (item.parts or [])
            )
            if text.strip():
                messages.append({"role": role, "content": text})
        elif isinstance(item, dict):
            messages.append(item)
    messages.append({"role": "user", "content": rag_input})
    return messages


class _StreamChunk:
    """Minimal adapter so downstream streaming sees a stable .text contract."""
    __slots__ = ("text",)
    def __init__(self, text: str = ""):
        self.text = text


def _stream_from_provider(
    provider,
    candidate_model: str,
    messages: list,
    use_instruction: str,
):
    """Call provider.generate_content(stream=True) and yield _StreamChunk objects."""
    stream = provider.generate_content(
        prompt=messages,
        model=candidate_model,
        system_instruction=use_instruction,
        stream=True,
    )
    for chunk in stream:
        if isinstance(chunk, dict):
            choices = chunk.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                content = delta.get("content", "")
            else:
                content = chunk.get("content", "")
        else:
            content = getattr(chunk, "content", "") or str(chunk)
        yield _StreamChunk(text=content)
