"""Internal helpers: number normalization."""

from __future__ import annotations

from typing import Any

from ..task_tools_common import _TEXT_LIMIT_MAX, _TEXT_LIMIT_MIN


def _normalize_text_limit(max_chars: Any, default: int) -> int:
    try:
        value = int(max_chars)
    except (TypeError, ValueError):
        value = default
    return min(max(_TEXT_LIMIT_MIN, value), _TEXT_LIMIT_MAX)


def _normalize_positive_int(value: Any, *, default: int, upper: int) -> int:
    try:
        if isinstance(value, str):
            value = value.strip()
        parsed = int(float(value))
    except (TypeError, ValueError):
        parsed = default
    if parsed < 1:
        parsed = default
    return min(parsed, upper)


def _normalize_positive_float(value: Any, *, default: float, upper: float) -> float:
    try:
        if isinstance(value, str):
            value = value.strip()
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed <= 0:
        parsed = default
    return min(parsed, upper)
