"""Sanitized public projections for editor and file-task SSE events."""

from __future__ import annotations

import json
import logging

from app.core.security.output_validator import sanitize_user_visible_text

logger = logging.getLogger("koto.app")


def sanitize_sse_text_field(
    payload: dict,
    field_name: str,
    *,
    fallback: str,
    treat_as_error: bool = False,
    skip_empty: bool = False,
) -> None:
    if field_name not in payload:
        return
    raw_value = payload.get(field_name, "")
    if skip_empty:
        raw_value = str(raw_value or "").strip()
        if not raw_value:
            return
    payload[field_name] = sanitize_user_visible_text(
        raw_value,
        fallback=fallback,
        treat_as_error=treat_as_error,
    )


def safe_editor_sse(payload: dict) -> str:
    safe_payload = dict(payload or {})
    event_type = str(safe_payload.get("type") or "").strip().lower()

    if event_type == "tool_result":
        sanitize_sse_text_field(
            safe_payload,
            "result_preview",
            fallback="工具已执行。",
        )
    elif event_type == "step_error":
        sanitize_sse_text_field(
            safe_payload,
            "error",
            fallback="处理失败，请稍后重试。",
            treat_as_error=True,
        )
    elif event_type == "error":
        sanitize_sse_text_field(
            safe_payload,
            "text",
            fallback="AI 处理失败，请稍后重试。",
            treat_as_error=True,
        )
    elif event_type == "info":
        sanitize_sse_text_field(
            safe_payload,
            "text",
            fallback="处理中…",
        )

    return f"data: {json.dumps(safe_payload, ensure_ascii=False)}\n\n"


def coerce_file_task_event_dict(event) -> dict:
    payload = event.to_dict() if hasattr(event, "to_dict") else dict(event or {})
    if not isinstance(payload.get("payload"), dict):
        payload["payload"] = {}
    return payload


def safe_file_task_event_dict(event) -> dict:
    payload = coerce_file_task_event_dict(event)
    event_type = str(payload.get("type") or "").strip()
    event_payload = (
        payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    )

    safe_event_payload = dict(event_payload)
    if event_type == "run.finished" and not bool(
        safe_event_payload.get("completed_task")
    ):
        sanitize_sse_text_field(
            safe_event_payload,
            "text",
            fallback="任务执行失败，请稍后重试。",
            treat_as_error=True,
        )
    elif (
        event_type == "tool.finished"
        and str(safe_event_payload.get("tool_name") or "").strip()
        in {"provided_file_context", "selection_context", "parse_file_to_text"}
        and "result_preview" in safe_event_payload
    ):
        tool_name = str(safe_event_payload.get("tool_name") or "").strip()
        if (
            tool_name == "parse_file_to_text"
            and safe_event_payload.get("success") is False
        ):
            sanitize_sse_text_field(
                safe_event_payload,
                "result_preview",
                fallback="文件读取失败，请调整任务或文件后重试。",
                treat_as_error=True,
                skip_empty=True,
            )
        else:
            preview_text = str(safe_event_payload.get("result_preview") or "")
            safe_event_payload["result_preview"] = (
                f"已读取上下文片段（约 {len(preview_text)} 字），正文已隐藏。"
                if preview_text
                else "已读取上下文片段，正文已隐藏。"
            )
    elif event_type == "tool.finished" and "result_preview" in safe_event_payload:
        blocked = bool(safe_event_payload.get("blocked"))
        success = safe_event_payload.get("success")
        fallback = (
            "当前调用已被拦截，请调整方案后重试。"
            if blocked
            else (
                "工具执行失败，请调整方案后重试。"
                if success is False
                else "工具已执行。"
            )
        )
        sanitize_sse_text_field(
            safe_event_payload,
            "result_preview",
            fallback=fallback,
            treat_as_error=(success is False and not blocked),
            skip_empty=True,
        )

    payload["payload"] = safe_event_payload
    try:
        from app.core.agent.file_task_ui_stream import normalize_ui_state

        ui_state = normalize_ui_state(payload)
        if ui_state is not None:
            payload["ui_state"] = ui_state.to_payload()
    except Exception as exc:
        logger.debug("[FileTaskRuntime] ui_state normalization skipped: %s", exc)
    return payload


__all__ = [
    "coerce_file_task_event_dict",
    "safe_editor_sse",
    "safe_file_task_event_dict",
]
