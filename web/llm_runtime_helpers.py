# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

from collections.abc import Iterable

from app.core.llm.model_capabilities import (
    DEFAULT_INTERACTIONS_ONLY_MODELS,
    is_interactions_only_model,
    normalize_model_id,
)


def normalize_proxy_url(proxy_value: str) -> str:
    """Normalize proxy value to a URL with scheme."""
    if not proxy_value:
        return ""
    value = str(proxy_value).strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"http://{value}"
    return value


class FakeGenerateContentResponse:
    """
    Lightweight response wrapper used when an alternate runtime returns text
    but callers expect the Gemini response shape.
    """

    __slots__ = ("text", "candidates", "usage_metadata")

    def __init__(self, text: str):
        self.text = text
        self.candidates = []
        self.usage_metadata = None


def extract_prompt_text(contents, config=None) -> tuple[str, str | None]:
    """
    Extract prompt text and system_instruction from generate_content inputs.
    Returns (prompt_text, system_instruction).
    """
    sys_instr = None
    if config is not None:
        sys_instr = getattr(config, "system_instruction", None)
        if sys_instr is not None:
            sys_instr = str(sys_instr)

    if contents is None:
        return "", sys_instr
    if isinstance(contents, str):
        return contents, sys_instr
    if isinstance(contents, list):
        parts = []
        for item in contents:
            if isinstance(item, str):
                parts.append(item)
            elif hasattr(item, "text") and item.text:
                parts.append(str(item.text))
            elif hasattr(item, "parts"):
                for part in item.parts or []:
                    if hasattr(part, "text") and part.text:
                        parts.append(str(part.text))
            else:
                value = str(item)
                if value:
                    parts.append(value)
        return "\n".join(parts), sys_instr
    return str(contents), sys_instr


def is_interactions_only(
    model_id: str,
    interactions_only_models: Iterable[str] | None = None,
) -> bool:
    models = interactions_only_models or DEFAULT_INTERACTIONS_ONLY_MODELS
    return is_interactions_only_model(normalize_model_id(model_id), models)
