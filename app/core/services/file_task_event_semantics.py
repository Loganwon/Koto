"""Pure projections from runtime file-task events to persistence semantics."""

from __future__ import annotations

import re


def trim_file_task_text(value, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def file_task_message(event_type: str, event_payload: dict) -> str:
    failure = (
        event_payload.get("failure")
        if isinstance(event_payload.get("failure"), dict)
        else {}
    )
    for key in ("summary", "detail"):
        text = trim_file_task_text(failure.get(key), 320)
        if text:
            return text
    for key in ("summary", "detail", "text", "title", "message", "status"):
        text = trim_file_task_text(event_payload.get(key), 320)
        if text:
            return text
    tool_name = trim_file_task_text(
        event_payload.get("tool_name") or event_payload.get("tool"), 120
    )
    if tool_name:
        return f"{event_type}: {tool_name}"
    return event_type or "file_task_event"


def file_task_terminal_status(event_type: str, event_payload: dict) -> str:
    runtime = (
        event_payload.get("runtime")
        if isinstance(event_payload.get("runtime"), dict)
        else {}
    )
    raw_status = (
        str(
            runtime.get("terminal_status")
            or event_payload.get("terminal_status")
            or event_payload.get("status")
            or ""
        )
        .strip()
        .lower()
    )
    if raw_status == "needs_attention":
        raw_status = "needs_review"
    if raw_status in {
        "awaiting_confirmation",
        "context_summary_fallback",
        "needs_review",
        "waiting",
    } or event_payload.get("awaiting_confirmation"):
        return "waiting"
    if event_type == "run.started":
        return "running"
    if event_type == "run.cancelled":
        return "cancelled"
    if event_type == "run.finished":
        if raw_status in {"cancelled", "canceled"}:
            return "cancelled"
        if bool(event_payload.get("completed_task")):
            return "completed"
        return "failed"
    return ""


def file_task_step_type(event_type: str) -> str:
    if event_type == "tool.started":
        return "ACTION"
    if event_type.startswith("tool."):
        return "OBSERVATION"
    if event_type.endswith(".error"):
        return "ERROR"
    if event_type in {"run.finished", "check.finished", "step.result"}:
        return "ANSWER"
    return "OBSERVATION"


__all__ = [
    "file_task_message",
    "file_task_step_type",
    "file_task_terminal_status",
    "trim_file_task_text",
]
