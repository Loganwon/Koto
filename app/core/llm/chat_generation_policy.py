# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Pure policy helpers for regular chat generation."""

from __future__ import annotations

from collections.abc import Mapping

DEFAULT_CHAT_MODEL = "deepseek-chat"
CODER_FIRST_TOKEN_TIMEOUT_SECONDS = 60
DEFAULT_FIRST_TOKEN_TIMEOUT_SECONDS = 120


def select_regular_model(
    task_type: str,
    model_map: Mapping[str, str] | None,
    *,
    default_model: str = DEFAULT_CHAT_MODEL,
) -> str:
    model_map = model_map or {}
    return model_map.get(task_type) or model_map.get("CHAT") or default_model


def should_try_local_chat_fast_path(
    *,
    task_type: str,
    locked_model: str,
    local_chat_override: bool,
    simple_query: bool,
) -> bool:
    if task_type != "CHAT":
        return False
    if locked_model == "local":
        return False
    return bool(local_chat_override or simple_query)


def first_token_timeout_seconds(task_type: str) -> int:
    if task_type == "CODER":
        return CODER_FIRST_TOKEN_TIMEOUT_SECONDS
    return DEFAULT_FIRST_TOKEN_TIMEOUT_SECONDS


__all__ = [
    "CODER_FIRST_TOKEN_TIMEOUT_SECONDS",
    "DEFAULT_CHAT_MODEL",
    "DEFAULT_FIRST_TOKEN_TIMEOUT_SECONDS",
    "first_token_timeout_seconds",
    "select_regular_model",
    "should_try_local_chat_fast_path",
]
