"""Bound model input while retaining current instructions and tool pairing.

This is a request projection, not another memory store. Complete messages and
tool receipts remain with the run owner; only the model-facing copy is reduced.
Capacity comes from explicit model options, with a configurable conservative
fallback when the provider does not publish a context window.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


class ContextBudgetExceeded(ValueError):
    """Protected instructions and tool arguments do not fit the chosen model."""


@dataclass(frozen=True)
class BudgetedMessages:
    messages: list[dict[str, Any]]
    estimated_tokens: int
    input_budget: int
    compacted: bool = False
    removed_history_messages: int = 0
    reduced_tool_results: int = 0


def estimate_tokens(value: Any) -> int:
    """Conservative mixed-language estimate without a provider tokenizer.

    ASCII is estimated at three characters per token and non-ASCII at two
    tokens per character. This is a budget estimate, never reported as billing
    usage. Provider-reported usage remains authoritative.
    """
    text = (
        value
        if isinstance(value, str)
        else json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
    )
    non_ascii = sum(ord(char) > 127 for char in text)
    return max(1, math.ceil((len(text) - non_ascii) / 3) + 2 * non_ascii)


def _positive_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def input_token_budget(options: Mapping[str, Any] | None = None) -> int:
    opts = dict(options or {})
    nested = opts.get("options")
    nested = nested if isinstance(nested, Mapping) else {}
    capacity = next(
        (
            number
            for number in (
                _positive_int(opts.get("context_window_tokens")),
                _positive_int(opts.get("context_window")),
                _positive_int(opts.get("num_ctx")),
                _positive_int(nested.get("num_ctx")),
                _positive_int(os.environ.get("KOTO_CONTEXT_WINDOW_TOKENS")),
            )
            if number
        ),
        32768,
    )
    reserved = next(
        (
            number
            for number in (
                _positive_int(opts.get("reserved_output_tokens")),
                _positive_int(opts.get("max_output_tokens")),
                _positive_int(opts.get("max_tokens")),
                _positive_int(nested.get("num_predict")),
            )
            if number
        ),
        min(4096, max(128, capacity // 4)),
    )
    # Protocol framing and estimation error get a separate small margin.
    budget = capacity - reserved - min(512, max(32, capacity // 20))
    if budget < 128:
        raise ContextBudgetExceeded(
            "模型上下文容量不足：请减少输出预留或选择上下文容量更大的模型。"
        )
    return budget


def _request_cost(
    system: str, tools: Sequence[Mapping[str, Any]], messages: list
) -> int:
    return (
        estimate_tokens(system)
        + estimate_tokens(tools)
        + sum(estimate_tokens(message) + 12 for message in messages)
    )


def _protected_start(messages: list[dict[str, Any]], prompt: str) -> int:
    candidates = [
        index for index, message in enumerate(messages) if message.get("role") == "user"
    ]
    matches = [
        index
        for index in candidates
        if prompt and messages[index].get("content") == prompt
    ]
    start = matches[-1] if matches else candidates[-1] if candidates else 0
    # Kernel places explicit per-request context directly before the prompt.
    if (
        start
        and messages[start - 1].get("role") == "user"
        and str(messages[start - 1].get("content") or "").startswith("Context:\n")
    ):
        start -= 1
    return start


def _history_groups(messages: list[dict[str, Any]], stop: int) -> list[list[int]]:
    groups: list[list[int]] = []
    current: list[int] = []
    for index in range(stop):
        message = messages[index]
        if message.get("role") in {"system", "developer"}:
            if current:
                groups.append(current)
                current = []
            continue
        if message.get("role") == "user" and current:
            groups.append(current)
            current = []
        current.append(index)
    if current:
        groups.append(current)
    return groups


def _short_tool_content(content: str, max_preview_chars: int) -> str:
    original = str(content)
    details: dict[str, Any] = {
        "context_truncated": True,
        "original_characters": len(original),
        "sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
        "preview": original[:max_preview_chars],
        "notice": "完整结果保留在工具执行记录中；需要细节时按目标和范围重新读取。",
    }
    try:
        payload = json.loads(original)
    except (ValueError, TypeError):
        payload = None
    if isinstance(payload, dict) and "ok" in payload:
        preserved = {
            key: payload[key]
            for key in ("call_id", "tool_name", "ok", "duration_ms")
            if key in payload
        }
        target = "value" if payload.get("ok") else "error"
        value = payload.get(target)
        if isinstance(value, dict):
            # Small facts about writes/errors survive compaction verbatim.
            for key in (
                "code",
                "status",
                "saved",
                "verified",
                "committed",
                "success",
                "path",
                "file_path",
                "document_id",
                "revision",
                "new_revision",
                "persisted",
                "error_code",
            ):
                item = value.get(key)
                if key in value and isinstance(
                    item, (str, int, float, bool, type(None))
                ):
                    details[key] = item[:500] if isinstance(item, str) else item
        preserved[target] = details
        return json.dumps(preserved, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(details, ensure_ascii=False, separators=(",", ":"))


def prepare_model_messages(
    messages: Sequence[Mapping[str, Any]],
    *,
    system: str,
    tools: Sequence[Mapping[str, Any]],
    options: Mapping[str, Any] | None = None,
    prompt: str = "",
) -> BudgetedMessages:
    """Reduce old whole turns and oversized tool results on a private copy.

    The current request and all subsequent assistant tool calls/results are
    preserved as protocol items. Their arguments and the user's instruction
    are never truncated. If that irreducible input cannot fit, fail explicitly
    before a network request rather than silently dropping the task.
    """
    projected = copy.deepcopy([dict(message) for message in messages])
    budget = input_token_budget(options)
    # Count immutable history once. Re-tokenizing the entire remaining history
    # after each discarded turn made long conversations quadratic in size.
    message_costs = [estimate_tokens(message) + 12 for message in projected]
    initial = estimate_tokens(system) + estimate_tokens(tools) + sum(message_costs)
    if initial <= budget:
        return BudgetedMessages(projected, initial, budget)

    protected = _protected_start(projected, prompt)
    removed: set[int] = set()
    remaining_cost = initial
    for group in _history_groups(projected, protected):
        removed.update(group)
        remaining_cost -= sum(message_costs[index] for index in group)
        if remaining_cost <= budget:
            candidate = [
                message
                for index, message in enumerate(projected)
                if index not in removed
            ]
            return BudgetedMessages(
                candidate, remaining_cost, budget, True, len(removed)
            )
    projected = [
        message for index, message in enumerate(projected) if index not in removed
    ]
    tool_indices = [
        index
        for index, message in enumerate(projected)
        if message.get("role") == "tool" and isinstance(message.get("content"), str)
    ]
    originals = {index: projected[index]["content"] for index in tool_indices}
    reduced: set[int] = set()
    for preview_limit in (4096, 2048, 1024, 512, 128, 0):
        for index, original in originals.items():
            if len(original) > preview_limit + 512:
                projected[index]["content"] = _short_tool_content(
                    original, preview_limit
                )
                reduced.add(index)
        cost = _request_cost(system, tools, projected)
        if cost <= budget:
            return BudgetedMessages(
                projected, cost, budget, True, len(removed), len(reduced)
            )
    raise ContextBudgetExceeded(
        "当前指令、文件上下文或工具参数超过模型输入预算。"
        "请缩小材料/选区范围，或提高所选模型的上下文容量设置；当前操作尚未继续执行。"
    )


__all__ = [
    "BudgetedMessages",
    "ContextBudgetExceeded",
    "estimate_tokens",
    "input_token_budget",
    "prepare_model_messages",
]
