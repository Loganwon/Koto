"""Content-free measurements for actual model calls, separate from estimates."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from typing import Any, Callable

from .lifecycle import AgentEvent, EventType


def _count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= 2**63 - 1 else None
    if (
        not math.isfinite(value)
        or value < 0
        or value > 2**63 - 1
        or int(value) != value
    ):
        return None
    return int(value)


def reported_usage(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Only numeric provider facts; never infer billing from generated text."""
    source = metadata if isinstance(metadata, Mapping) else {}
    raw = (
        source.get("usage")
        or source.get("usage_metadata")
        or source.get("usageMetadata")
    )
    raw = raw if isinstance(raw, Mapping) else {}

    def first(*keys):
        return next(
            (number for key in keys if (number := _count(raw.get(key))) is not None),
            None,
        )

    details = raw.get("prompt_tokens_details") or raw.get("input_tokens_details") or {}
    details = details if isinstance(details, Mapping) else {}
    result = {
        "input_tokens": first(
            "prompt_tokens", "input_tokens", "prompt_token_count", "promptTokenCount"
        ),
        "output_tokens": first(
            "completion_tokens",
            "output_tokens",
            "candidates_token_count",
            "candidatesTokenCount",
        ),
        "total_tokens": first("total_tokens", "total_token_count", "totalTokenCount"),
        "cached_input_tokens": first(
            "prompt_cache_hit_tokens", "cached_input_tokens", "cachedContentTokenCount"
        ),
    }
    if result["cached_input_tokens"] is None:
        result["cached_input_tokens"] = _count(details.get("cached_tokens"))
    return {
        "provider_reported": any(value is not None for value in result.values()),
        **result,
    }


class ModelTurnMetrics:
    """One measurement per actual call; replayed model responses create none."""

    def __init__(
        self,
        *,
        run_id: str,
        message_id: str,
        model: str = "",
        estimated_input_tokens: int | None = None,
        input_budget: int | None = None,
        compacted: bool = False,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._clock = clock or time.perf_counter
        self._started = self._clock()
        self._first_text: float | None = None
        self.run_id = run_id
        self.message_id = message_id
        self.model = model
        self.estimated_input_tokens = estimated_input_tokens
        self.input_budget = input_budget
        self.compacted = compacted

    def start_call(self) -> None:
        """Exclude time spent delivering message.started to a slow consumer."""
        self._started = self._clock()
        self._first_text = None

    def first_text(self) -> None:
        if self._first_text is None:
            self._first_text = self._clock()

    def event(self, *, status: str, response=None, error_type: str = "") -> AgentEvent:
        elapsed = max(0.0, self._clock() - self._started)
        first = (
            None
            if self._first_text is None
            else round(max(0.0, self._first_text - self._started) * 1000, 3)
        )
        return AgentEvent(
            EventType.STATUS_MESSAGE,
            {
                "event_type": "model.metrics",
                "run_id": self.run_id,
                "message_id": self.message_id,
                "model": str(getattr(response, "model", "") or self.model)[:160],
                "status": status,
                "duration_ms": round(elapsed * 1000, 3),
                "first_text_ms": first,
                "usage": reported_usage(getattr(response, "metadata", None)),
                "context_estimate": {
                    "estimated_input_tokens": self.estimated_input_tokens,
                    "input_budget": self.input_budget,
                    "compacted": self.compacted,
                    "billing_usage": False,
                },
                "error_type": str(error_type)[:100],
            },
        )


__all__ = ["ModelTurnMetrics", "reported_usage"]
