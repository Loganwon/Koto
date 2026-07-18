from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AnswerOnlyRound:
    enabled: bool
    tool_defs: list[dict[str, Any]]


@dataclass(frozen=True)
class AnswerOnlyToolCalls:
    tool_calls: list[dict[str, Any]]
    discarded_count: int = 0


READONLY_DUPLICATE_GUARD_SUMMARY = (
    "检测到重复读取/重复工具调用，已要求模型停止读取并直接输出分析结果。"
)
READONLY_DUPLICATE_FALLBACK_SUMMARY = "已读取上下文，但模型未生成可见分析结果。"
READONLY_ANSWER_GUARD_PENDING_SUMMARY = "已读取内容，正在生成可见分析结果。"
WRITE_DUPLICATE_SUPERVISOR_SUMMARY = (
    "检测到重复读取/重复工具调用，监管层已要求模型回到计划主线继续执行。"
)
WRITE_DUPLICATE_STOP_SUMMARY = "检测到重复工具调用，已自动停止以避免重复写入。"


def answer_only_round(
    *,
    write_intent: bool,
    readonly_answer_guard_injected: bool,
    readonly_duplicate_guard_injected: bool,
    has_context: bool,
    tool_defs: list[dict[str, Any]],
) -> AnswerOnlyRound:
    # Context is read by FileTaskContextReadPhase before the model loop. Once
    # an answer-only task already has grounded context, exposing file tools is
    # unnecessary and excludes otherwise capable local chat models that do not
    # implement Ollama tool calling. Write tasks and context-missing reads keep
    # the full tool catalog.
    enabled = not write_intent and has_context
    return AnswerOnlyRound(
        enabled=enabled,
        tool_defs=[] if enabled else tool_defs,
    )


def discard_answer_only_tool_calls(
    *,
    answer_only: bool,
    tool_calls: list[dict[str, Any]],
) -> AnswerOnlyToolCalls:
    if not answer_only or not tool_calls:
        return AnswerOnlyToolCalls(tool_calls=tool_calls, discarded_count=0)
    return AnswerOnlyToolCalls(tool_calls=[], discarded_count=len(tool_calls))


def should_retry_readonly_duplicate_guard(
    *,
    readonly_duplicate_guard_injected: bool,
    round_index: int,
    max_rounds: int,
) -> bool:
    return (not readonly_duplicate_guard_injected) and round_index < max_rounds


def should_retry_readonly_answer_guard(
    *,
    content_text: str,
    has_context: bool,
    readonly_answer_guard_injected: bool,
    round_index: int,
    max_rounds: int,
) -> bool:
    return (
        not str(content_text or "").strip()
        and has_context
        and not readonly_answer_guard_injected
        and round_index < max_rounds
    )


def readonly_duplicate_guard_reminder(
    *,
    task: str,
    source_lines: list[str],
) -> str:
    reminder_lines = [
        "你正在重复调用只读工具。不要再次调用任何工具；请直接基于已读取内容输出分析结果。",
        f"用户任务：{task}",
    ]
    if source_lines:
        reminder_lines.append("已读取内容摘录：")
        reminder_lines.extend(source_lines)
    return "\n".join(reminder_lines)


def readonly_duplicate_final_summary(
    *,
    context_summary: str,
    content_text: str,
) -> str:
    return (
        str(context_summary or "").strip()
        or str(content_text or "").strip()
        or READONLY_DUPLICATE_FALLBACK_SUMMARY
    )


def should_retry_write_duplicate_guard(
    *,
    write_intent: bool,
    has_file_changes: bool,
    duplicate_supervisor_guard_injected: bool,
    round_index: int,
    max_rounds: int,
) -> bool:
    return (
        write_intent
        and not has_file_changes
        and not duplicate_supervisor_guard_injected
        and round_index < max_rounds
    )


def supervisor_guard_tool_payload(reminder: str) -> dict[str, Any]:
    return {
        "tool_name": "supervisor_guard",
        "success": False,
        "skipped": True,
        "result_preview": reminder,
    }


def duplicate_guard_tool_payload(summary: str) -> dict[str, Any]:
    return {
        "tool_name": "duplicate_guard",
        "success": True,
        "skipped": True,
        "result_preview": summary,
    }
