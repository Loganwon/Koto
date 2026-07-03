# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""SSE streaming helpers for file-assistant tasks.

This module owns the file-task streaming path used by the editor AI blueprint.
It keeps the route layer out of ``web.app`` while the larger app module is
gradually split into smaller services.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from types import SimpleNamespace
from typing import Any, Iterable

from app.core.llm.model_mode import normalize_model_mode
from app.core.security.output_validator import sanitize_user_visible_text

logger = logging.getLogger("koto.app")

_FILE_TASK_SOURCE = "file_task"
_FILE_TASK_CONTRACT = "file_task_v1"


def _sanitize_sse_text_field(
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
    from web.sse.protocol import sse

    safe_payload = dict(payload or {})
    event_type = str(safe_payload.get("type") or "").strip().lower()

    if event_type == "tool_result":
        _sanitize_sse_text_field(
            safe_payload,
            "result_preview",
            fallback="工具已执行。",
        )
    elif event_type == "step_error":
        _sanitize_sse_text_field(
            safe_payload,
            "error",
            fallback="处理失败，请稍后重试。",
            treat_as_error=True,
        )
    elif event_type == "error":
        _sanitize_sse_text_field(
            safe_payload,
            "text",
            fallback="AI 处理失败，请稍后重试。",
            treat_as_error=True,
        )
    elif event_type == "info":
        _sanitize_sse_text_field(
            safe_payload,
            "text",
            fallback="处理中…",
        )

    return sse.chunk(safe_payload)


def _normalize_file_task_payload(data: dict) -> dict:
    from web.runtime_context import get_configured_local_model_id

    payload = dict(data or {})
    model_mode = normalize_model_mode(payload.get("model_mode"), default="deepseek")
    payload["model_mode"] = model_mode
    raw_options = payload.get("options")
    options = dict(raw_options) if isinstance(raw_options, dict) else {}
    if "allow_local_fallback" not in options:
        options["allow_local_fallback"] = False
    payload["options"] = options
    if model_mode == "local":
        raw_model_id = str(payload.get("model_id") or "").strip()
        if raw_model_id.lower() in {"auto", "cloud", "local"} or raw_model_id.lower().startswith("gemini"):
            payload["model_id"] = ""
        configured_local_model = get_configured_local_model_id()
        if configured_local_model:
            options.setdefault("local_model", configured_local_model)
    history = payload.get("history")
    if not isinstance(history, list):
        history = []
    payload["history"] = history[-20:]
    return payload


def _inject_recent_file_task_summary_context(
    payload: dict,
    *,
    load_recent_summaries_fn,
    format_summaries_as_context_fn,
) -> dict:
    try:
        raw_files = payload.get("files") or []
        file_paths = [
            str(item.get("path") or item.get("name") or "")
            for item in raw_files
            if isinstance(item, dict)
        ]
        if payload.get("target_path"):
            file_paths.append(str(payload["target_path"]))
        file_paths = list(dict.fromkeys(path for path in file_paths if path))
        recent = load_recent_summaries_fn(file_paths, limit=5)
        if recent:
            ctx_text = format_summaries_as_context_fn(recent)
            raw_options = payload.get("options")
            options = dict(raw_options) if isinstance(raw_options, dict) else {}
            if ctx_text and not options.get("memory_context"):
                options["memory_context"] = ctx_text
                payload["options"] = options
    except Exception as exc:
        logger.debug("[FileTaskRuntime] recent summary context injection skipped: %s", exc)
    return payload


def _coerce_file_task_event_dict(event) -> dict:
    payload = event.to_dict() if hasattr(event, "to_dict") else dict(event or {})
    if not isinstance(payload.get("payload"), dict):
        payload["payload"] = {}
    return payload


def _safe_file_task_event_dict(event) -> dict:
    payload = _coerce_file_task_event_dict(event)
    event_type = str(payload.get("type") or "").strip()
    event_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}

    safe_event_payload = dict(event_payload)
    if event_type == "run.error":
        _sanitize_sse_text_field(
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
        if tool_name == "parse_file_to_text" and safe_event_payload.get("success") is False:
            _sanitize_sse_text_field(
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
        fallback = "当前调用已被拦截，请调整方案后重试。" if blocked else (
            "工具执行失败，请调整方案后重试。" if success is False else "工具已执行。"
        )
        _sanitize_sse_text_field(
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


def _trim_file_task_text(value, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _file_task_record_metadata(request_payload) -> dict:
    files = []
    for file_info in getattr(request_payload, "files", []) or []:
        if hasattr(file_info, "public_dict"):
            files.append(file_info.public_dict())
    metadata = {
        "task_contract": _FILE_TASK_CONTRACT,
        "task_mode": _FILE_TASK_CONTRACT,
        "run_id": str(getattr(request_payload, "run_id", "") or "").strip(),
        "target_path": str(getattr(request_payload, "target_path", "") or "").strip(),
        "model_mode": str(getattr(request_payload, "model_mode", "") or "").strip(),
        "model_id": str(getattr(request_payload, "model_id", "") or "").strip(),
        "selection_source": str(getattr(request_payload, "selection_source", "") or "").strip(),
        "has_selection": bool(getattr(request_payload, "selection", "")),
        "file_count": len(files),
        "files": files[:8],
    }
    task_context = getattr(request_payload, "task_context", None)
    if isinstance(task_context, dict) and task_context:
        metadata["task_context"] = task_context
    selection_context = None
    if hasattr(request_payload, "selection_context_file"):
        try:
            selection_context = request_payload.selection_context_file()
        except Exception:
            selection_context = None
    if selection_context is not None and hasattr(selection_context, "public_dict"):
        metadata["current_file"] = selection_context.public_dict()
    return metadata


def _ensure_file_task_record(request_payload) -> str:
    from app.core.tasks.task_ledger import get_ledger

    ledger = get_ledger()
    requested_task_id = str(getattr(request_payload, "task_id", "") or "").strip()
    if requested_task_id:
        existing = ledger.get(requested_task_id)
        if existing is not None:
            ledger.update_metadata(existing.task_id, _file_task_record_metadata(request_payload))
            request_payload.task_id = existing.task_id
            return existing.task_id

    record = ledger.create(
        session_id=str(
            getattr(request_payload, "session_id", "")
            or getattr(request_payload, "run_id", "")
            or "file_task_session"
        )[:96],
        user_input=str(getattr(request_payload, "task", "") or "")[:1000],
        task_type="file_task",
        source=_FILE_TASK_SOURCE,
        metadata=_file_task_record_metadata(request_payload),
    )
    request_payload.task_id = record.task_id
    return record.task_id


def _file_task_message(event_type: str, event_payload: dict) -> str:
    for key in ("summary", "detail", "text", "title", "message", "status"):
        text = _trim_file_task_text(event_payload.get(key), 320)
        if text:
            return text
    tool_name = _trim_file_task_text(event_payload.get("tool_name") or event_payload.get("tool"), 120)
    if tool_name:
        return f"{event_type}: {tool_name}"
    return event_type or "file_task_event"


def _file_task_progress(event_type: str) -> int:
    explicit = {
        "run.started": 5,
        "task.classified": 12,
        "plan.checked": 18,
        "plan.created": 24,
        "multi_target.started": 8,
        "multi_target.subrun.started": 28,
        "multi_target.subrun.finished": 72,
        "multi_target.finished": 100,
        "check.started": 84,
        "check.finished": 94,
        "run.finished": 100,
        "run.cancelled": 0,
        "run.error": 0,
    }
    if event_type in explicit:
        return explicit[event_type]
    if event_type.startswith("tool."):
        return 62 if event_type.endswith("finished") else 46
    if event_type.startswith("step."):
        return 36 if event_type.endswith("started") else 70
    return 40


def _file_task_terminal_status(event_type: str, event_payload: dict) -> str:
    runtime = event_payload.get("runtime") if isinstance(event_payload.get("runtime"), dict) else {}
    raw_status = str(
        runtime.get("terminal_status")
        or event_payload.get("terminal_status")
        or event_payload.get("status")
        or ""
    ).strip().lower()
    if raw_status in {
        "awaiting_confirmation",
        "waiting",
        "needs_attention",
        "context_summary_fallback",
    } or event_payload.get("awaiting_confirmation"):
        return "waiting"
    if event_type == "run.started" or event_type == "multi_target.started":
        return "running"
    if event_type == "run.cancelled":
        return "cancelled"
    if event_type == "run.error":
        return "failed"
    if event_type == "run.finished":
        if raw_status in {"cancelled", "canceled"}:
            return "cancelled"
        if bool(event_payload.get("completed_task")):
            return "completed"
        return "failed"
    if event_type == "multi_target.finished":
        return "completed" if str(event_payload.get("status") or "").strip().lower() == "succeeded" else "failed"
    return ""


def _file_task_step_type(event_type: str) -> str:
    if event_type.startswith("tool."):
        return "ACTION"
    if event_type == "run.error" or event_type.endswith(".error"):
        return "ERROR"
    if event_type in {"run.finished", "multi_target.finished", "check.finished", "step.result"}:
        return "ANSWER"
    return "OBSERVATION"


def _persist_file_task_progress_event(request_payload, event) -> None:
    task_id = str(getattr(request_payload, "task_id", "") or "").strip()
    if not task_id:
        return

    try:
        from app.core.tasks.progress_bus import ProgressEvent, get_progress_bus
        from app.core.tasks.task_ledger import get_ledger

        safe_event = _safe_file_task_event_dict(event)
        event_type = str(safe_event.get("type") or "").strip()
        event_payload = safe_event.get("payload") if isinstance(safe_event.get("payload"), dict) else {}
        message = _file_task_message(event_type, event_payload)
        terminal_status = _file_task_terminal_status(event_type, event_payload)
        step_type = _file_task_step_type(event_type)
        tool_name = _trim_file_task_text(event_payload.get("tool_name") or event_payload.get("tool"), 120) or None
        observation = _trim_file_task_text(
            event_payload.get("result_preview") or event_payload.get("summary"),
            800,
        ) or None

        ledger = get_ledger()
        task_record = ledger.get(task_id)
        current_status = task_record.status.value if task_record is not None else ""

        if terminal_status == "running":
            if current_status != "running":
                ledger.mark_running(task_id)
        elif terminal_status == "waiting":
            if current_status != "waiting":
                ledger.mark_waiting(task_id, reason=message or "awaiting_confirmation")
        elif terminal_status == "completed":
            if current_status != "completed":
                ledger.mark_completed(task_id, result_summary=str(event_payload.get("summary") or message or "")[:500])
        elif terminal_status == "failed":
            if current_status != "failed":
                ledger.mark_failed(task_id, message or "任务执行失败")
        elif terminal_status == "cancelled":
            if current_status != "cancelled":
                ledger.mark_cancelled(task_id)

        metadata_patch = {
            "run_id": str(getattr(request_payload, "run_id", "") or "").strip(),
            "last_event_type": event_type,
            "last_event_seq": safe_event.get("seq", 0),
            "last_event_step_id": str(safe_event.get("step_id") or "").strip(),
            "last_event_ts": safe_event.get("ts"),
            "last_message": message,
        }
        if terminal_status:
            metadata_patch["last_status"] = terminal_status
        if terminal_status in {"waiting", "completed", "failed", "cancelled"}:
            metadata_patch["terminal_event"] = safe_event
        if terminal_status == "waiting":
            metadata_patch["waiting_event"] = safe_event
        ledger.update_metadata(task_id, metadata_patch)

        if event_type not in {"run.started", "multi_target.started"}:
            ledger.add_step(
                task_id,
                step_type=step_type,
                content=message,
                tool_name=tool_name,
                observation=observation,
            )

        get_progress_bus().publish(
            ProgressEvent(
                task_id=task_id,
                session_id=str(getattr(request_payload, "session_id", "") or ""),
                event_type="file_task_event",
                status=terminal_status or (current_status or "running"),
                message=message,
                progress=_file_task_progress(event_type),
                step_type=step_type,
                tool_name=tool_name,
                detail={"event": safe_event},
            )
        )
    except Exception as exc:
        logger.debug("[FileTaskRuntime] progress persistence skipped: %s", exc)


def _persist_file_task_summary_event(
    request_payload,
    event,
    *,
    save_task_summary_fn,
) -> None:
    try:
        event_payload = _coerce_file_task_event_dict(event)
        event_type = str(event_payload.get("type") or "").strip()
        if event_type not in {"run.finished", "multi_target.subrun.finished"}:
            return
        payload = event_payload.get("payload") if isinstance(event_payload.get("payload"), dict) else {}
        event_summary = str(payload.get("summary") or "").strip()
        event_completed = bool(payload.get("completed_task"))
        event_target = str(payload.get("target") or request_payload.target_path or "").strip()
        if not event_summary or not event_target:
            return
        save_task_summary_fn(
            file_path=event_target,
            task=str(request_payload.task or "")[:500],
            outcome="completed" if event_completed else "needs_attention",
            summary=event_summary,
        )
    except Exception as exc:
        logger.debug("[FileTaskRuntime] task summary persistence skipped: %s", exc)


def _file_task_event_to_safe_sse(event) -> str:
    from app.core.agent.file_task_contract import event_to_sse

    return event_to_sse(_safe_file_task_event_dict(event))


def _file_task_change_path(change: dict) -> str:
    for key in ("path", "file_path", "output_path", "target_path", "destination", "revised_file"):
        value = str((change or {}).get(key) or "").strip()
        if value:
            return value.replace("\\", "/")
    return ""


def _append_file_task_artifact_changes(file_changes: list[dict], changes) -> None:
    seen = {
        (
            _file_task_change_path(item).lower(),
            str(item.get("operation") or "").strip().lower(),
            str(item.get("summary") or "").strip().lower(),
        )
        for item in file_changes
        if isinstance(item, dict)
    }
    for item in changes or []:
        if not isinstance(item, dict):
            continue
        path = _file_task_change_path(item)
        if not path:
            continue
        key = (
            path.lower(),
            str(item.get("operation") or "").strip().lower(),
            str(item.get("summary") or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        file_changes.append(dict(item))


def _artifact_result_file_changes(artifact_result: dict) -> list[dict]:
    if not isinstance(artifact_result, dict):
        return []
    changes: list[dict] = []
    for artifact in artifact_result.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        path = str(artifact.get("path") or artifact.get("file") or "").strip()
        if not path:
            continue
        changes.append(
            {
                "path": path,
                "operation": artifact.get("operation") or artifact.get("type") or "artifact",
                "summary": artifact.get("summary") or artifact.get("title") or f"已生成 {path}",
                "status": artifact.get("status") or "applied",
            }
        )
    for change in artifact_result.get("changes") or []:
        if not isinstance(change, dict):
            continue
        path = str(change.get("file") or change.get("path") or "").strip()
        if not path:
            continue
        item = dict(change)
        item.setdefault("path", path)
        item.setdefault("operation", item.get("kind") or "update")
        item.setdefault("summary", item.get("summary") or f"已更新 {path}")
        changes.append(item)
    return changes


def _collect_file_task_artifact_changes(event: dict, file_changes: list[dict]) -> None:
    event_type = str((event or {}).get("type") or "").strip()
    payload = event.get("payload") if isinstance((event or {}).get("payload"), dict) else {}
    if event_type == "file.changed":
        _append_file_task_artifact_changes(file_changes, [payload])
    if isinstance(payload.get("file_changes"), list):
        _append_file_task_artifact_changes(file_changes, payload.get("file_changes"))
    if isinstance(payload.get("artifact_result"), dict):
        _append_file_task_artifact_changes(
            file_changes,
            _artifact_result_file_changes(payload.get("artifact_result")),
        )


def _file_task_artifact_status(event_type: str, event_payload: dict) -> str:
    runtime = event_payload.get("runtime") if isinstance(event_payload.get("runtime"), dict) else {}
    raw_status = str(
        runtime.get("terminal_status")
        or event_payload.get("terminal_status")
        or event_payload.get("status")
        or ""
    ).strip().lower()
    if raw_status in {
        "awaiting_confirmation",
        "waiting",
        "needs_attention",
        "context_summary_fallback",
        "needs_review",
        "pending",
        "failed",
        "error",
        "write_blocked",
        "tool_gap",
    }:
        return raw_status
    terminal_status = _file_task_terminal_status(event_type, event_payload)
    if terminal_status:
        return terminal_status
    if event_type in {"run.error", "run.cancelled"}:
        return "failed"
    return "running"


def _should_attach_file_task_artifact_result(
    event_type: str,
    event_payload: dict,
    file_changes: list[dict],
) -> bool:
    if isinstance(event_payload.get("artifact_result"), dict):
        return False
    if event_type in {"run.finished", "multi_target.finished", "run.error", "run.cancelled"}:
        return True
    if event_type == "file.changed":
        return True
    if event_type in {"step.result", "check.finished"} and file_changes:
        return True
    if isinstance(event_payload.get("next_action_artifact"), dict):
        return True
    return False


def _merge_file_changes_into_artifact_result(artifact_result: dict, file_changes: list[dict]) -> dict:
    result = dict(artifact_result or {})
    existing_changes = [
        dict(item)
        for item in result.get("changes") or []
        if isinstance(item, dict)
    ]
    seen_changes = {
        str(item.get("file") or item.get("path") or "").strip().lower()
        for item in existing_changes
    }
    for change in file_changes or []:
        if not isinstance(change, dict):
            continue
        path = _file_task_change_path(change)
        if not path or path.lower() in seen_changes:
            continue
        seen_changes.add(path.lower())
        existing_changes.append(
            {
                "file": path,
                "kind": change.get("kind") or change.get("operation") or "update",
                "summary": change.get("summary") or f"已更新 {path}",
                "status": change.get("status") or "applied",
                "after_preview": change.get("after_preview") or change.get("preview") or "",
                "metadata": {
                    key: value
                    for key, value in change.items()
                    if key not in {"path", "file", "file_path", "output_path", "target_path", "operation", "kind", "summary", "status", "after_preview", "preview"}
                },
            }
        )
    result["changes"] = existing_changes

    existing_artifacts = [
        dict(item)
        for item in result.get("artifacts") or []
        if isinstance(item, dict)
    ]
    seen_artifacts = {
        str(item.get("path") or "").strip().lower()
        for item in existing_artifacts
    }
    for change in file_changes or []:
        if not isinstance(change, dict):
            continue
        path = _file_task_change_path(change)
        if not path or path.lower() in seen_artifacts:
            continue
        seen_artifacts.add(path.lower())
        existing_artifacts.append(
            {
                "type": change.get("type") or change.get("file_type") or "data",
                "title": str(path).replace("\\", "/").rsplit("/", 1)[-1] or path,
                "path": path,
                "status": "ready",
                "metadata": {},
            }
        )
    result["artifacts"] = existing_artifacts
    return result


def _attach_file_task_artifact_result(request_payload, event: dict, file_changes: list[dict]) -> dict:
    event_type = str((event or {}).get("type") or "").strip()
    event_payload = event.get("payload") if isinstance((event or {}).get("payload"), dict) else {}
    if isinstance(event_payload.get("artifact_result"), dict):
        outbound_event = dict(event)
        outbound_payload = dict(event_payload)
        outbound_payload["artifact_result"] = _merge_file_changes_into_artifact_result(
            event_payload.get("artifact_result"),
            file_changes,
        )
        outbound_event["payload"] = outbound_payload
        return outbound_event
    if not _should_attach_file_task_artifact_result(event_type, event_payload, file_changes):
        return event
    try:
        from app.core.artifacts import build_file_task_artifact_result

        task_id = str(
            event.get("task_id")
            or getattr(request_payload, "task_id", "")
            or event.get("run_id")
            or getattr(request_payload, "run_id", "")
            or ""
        ).strip()
        run_id = str(event.get("run_id") or getattr(request_payload, "run_id", "") or "").strip()
        task = str(event_payload.get("task") or getattr(request_payload, "task", "") or "").strip()
        summary = str(
            event_payload.get("summary")
            or event_payload.get("text")
            or event_payload.get("detail")
            or ""
        ).strip()
        target_path = str(
            event_payload.get("target_path")
            or event_payload.get("target")
            or getattr(request_payload, "target_path", "")
            or ""
        ).strip()
        result = build_file_task_artifact_result(
            task_id=task_id,
            task=task,
            run_id=run_id,
            status=_file_task_artifact_status(event_type, event_payload),
            summary=summary,
            file_changes=file_changes,
            event_payload=event_payload,
            source_files=getattr(request_payload, "files", []) or [],
            current_file=getattr(request_payload, "current_file", None),
            selection_source=str(getattr(request_payload, "selection_source", "") or ""),
            target_path=target_path,
        )
        outbound_event = dict(event)
        outbound_payload = dict(event_payload)
        outbound_payload["artifact_result"] = result.to_dict()
        outbound_event["payload"] = outbound_payload
        return outbound_event
    except Exception as exc:
        logger.debug("[FileTaskRuntime] artifact result attachment skipped: %s", exc)
        return event


def _build_file_task_ui_message_sse(request_payload, event, *, normalize_event_fn, seq_override=None):
    try:
        ui_message = normalize_event_fn(event)
    except Exception as exc:
        logger.debug("[FileTaskRuntime] ui stream normalization skipped: %s", exc)
        return None
    if ui_message is None:
        return None
    event_payload = _safe_file_task_event_dict(event)
    return _file_task_event_to_safe_sse({
        "type": "ui.message",
        "task_id": event_payload.get("task_id") or getattr(request_payload, "task_id", "") or "",
        "run_id": event_payload.get("run_id") or request_payload.run_id or "file_task",
        "seq": int(seq_override) if seq_override is not None else event_payload.get("seq", 0),
        "step_id": event_payload.get("step_id") or "ui",
        "ts": event_payload.get("ts") or time.time(),
        "payload": ui_message.to_payload(),
    })


def _build_file_task_orchestrator(*, workspace_root, gemini_client):
    from app.core.agent.file_task_model import FileTaskModelClient
    from app.core.agent.file_task_runtime import FileTaskRuntime

    return FileTaskRuntime(
        workspace_root=workspace_root,
        gemini_client=gemini_client,
        model_client=FileTaskModelClient(),
    )


def _build_file_task_request(
    data: dict,
    *,
    request_cls,
    load_recent_summaries_fn,
    format_summaries_as_context_fn,
):
    payload = _normalize_file_task_payload(data)
    payload = _inject_recent_file_task_summary_context(
        payload,
        load_recent_summaries_fn=load_recent_summaries_fn,
        format_summaries_as_context_fn=format_summaries_as_context_fn,
    )
    return request_cls.from_mapping(payload)


def _build_file_task_request_from_data(data: dict):
    from app.core.agent.file_task_contract import FileTaskRequest
    from app.core.agent.file_task_session_store import (
        format_summaries_as_context,
        load_recent_summaries,
    )

    return _build_file_task_request(
        data,
        request_cls=FileTaskRequest,
        load_recent_summaries_fn=load_recent_summaries,
        format_summaries_as_context_fn=format_summaries_as_context,
    )


def _iter_file_task_stream_events(
    request_payload,
    event_iterable,
    *,
    save_task_summary_fn,
    normalize_event_fn,
    persist_progress_fn,
):
    outbound_seq = 0
    file_changes: list[dict] = []
    for event in event_iterable:
        safe_event = _safe_file_task_event_dict(event)
        _collect_file_task_artifact_changes(safe_event, file_changes)
        safe_event = _attach_file_task_artifact_result(request_payload, safe_event, file_changes)
        _persist_file_task_summary_event(
            request_payload,
            safe_event,
            save_task_summary_fn=save_task_summary_fn,
        )
        persist_progress_fn(request_payload, safe_event)
        outbound_seq += 1
        outbound_event = dict(safe_event)
        outbound_event["seq"] = outbound_seq
        raw_sse = _file_task_event_to_safe_sse(outbound_event)
        next_ui_seq = outbound_seq + 1
        ui_sse = _build_file_task_ui_message_sse(
            request_payload,
            event,
            normalize_event_fn=normalize_event_fn,
            seq_override=next_ui_seq,
        )
        yield raw_sse
        if ui_sse is not None:
            outbound_seq = next_ui_seq
            yield ui_sse


def _build_file_task_error_event(request_payload, exc):
    return {
        "type": "run.error",
        "task_id": getattr(request_payload, "task_id", "") or "",
        "run_id": request_payload.run_id or "file_task",
        "seq": 999999,
        "step_id": "run",
        "ts": time.time(),
        "payload": {"text": str(exc)},
    }


def _fallback_file_task_request_for_error(data: dict):
    return SimpleNamespace(
        task=str((data or {}).get("task") or (data or {}).get("instruction") or ""),
        run_id=str((data or {}).get("run_id") or "file_task"),
        session_id=str((data or {}).get("session_id") or ""),
        target_path=str((data or {}).get("target_path") or (data or {}).get("target") or ""),
    )


def stream_file_task_chat_request(
    task_type,
    user_input,
    session_name,
    effective_input=None,
    workspace_dir=None,
    yield_thinking=None,
    _app_logger=None,
    session_manager=None,
    settings_manager=None,
    MODEL_MAP=None,
    context_info=None,
    system_instruction=None,
    _rag_context_block=None,
    history=None,
    request=None,
    client=None,
    _interrupt_manager=None,
    _safe_sse=None,
):
    import uuid
    import time as _time
    import json as _json

    start_time = _time.time()
    effective = effective_input or user_input

    if _safe_sse:
        yield _safe_sse({"type": "progress", "message": f"开始处理{task_type}任务...", "detail": ""})

    try:
        from app.core.agent.file_task_contract import FileTaskRequest
        from app.core.agent.file_task_model import FileTaskModelClient
        from app.core.agent.file_task_runtime import FileTaskRuntime

        run_id = uuid.uuid4().hex[:12]
        raw_data = {
            "task": effective,
            "run_id": run_id,
            "session_id": session_name or "",
            "model_mode": "deepseek",
            "history": history if isinstance(history, list) else [],
            "options": {
                "system_instruction": system_instruction or "",
                "context_info": context_info or {},
                "rag_context": _rag_context_block or "",
                "task_type": task_type,
            },
        }
        task_request = FileTaskRequest.from_mapping(raw_data)

        runtime = FileTaskRuntime(
            workspace_root=workspace_dir or "",
            gemini_client=client,
            model_client=FileTaskModelClient(),
        )

        token_buffer = []
        had_error = False
        final_summary = ""
        saved_files = []

        for event in runtime.run(task_request):
            event_type = getattr(event, "type", "")
            payload = getattr(event, "payload", {}) or {}

            try:
                from app.core.agent.file_task_ui_stream import normalize_ui_state
                ui = normalize_ui_state(event)
            except Exception:
                ui = None

            if ui and _safe_sse:
                progress_kwargs = {
                    "type": "progress",
                    "message": getattr(ui, "title", "") or str(event_type),
                    "detail": f"{getattr(ui, 'progress', 0)}%" if hasattr(ui, 'progress') else "",
                    "stage": getattr(ui, "phase", ""),
                    "progress": getattr(ui, "progress", 0),
                }
                if hasattr(ui, "terminal") and ui.terminal:
                    progress_kwargs["terminal"] = True
                    progress_kwargs["status"] = getattr(ui, "status", "")
                yield _safe_sse(progress_kwargs)

            if event_type in ("plan.created", "plan.proposed"):
                steps = payload.get("steps", []) or payload.get("dynamic_steps", []) or []
                for step in steps[:8]:
                    step_title = step.get("title", "") if isinstance(step, dict) else str(step)
                    if _safe_sse and step_title:
                        yield _safe_sse({
                            "type": "progress",
                            "message": f"📋 {step_title}",
                            "detail": "",
                            "stage": "planning",
                        })

            if event_type == "task.classified":
                clf = payload.get("classification", {}) or {}
                task_family = str(clf.get("task_family", "") or "")
                op_kind = str(clf.get("operation_kind", "") or "")
                if task_family and _safe_sse:
                    detail_msg = f"📊 任务类型: {task_family}"
                    if op_kind:
                        detail_msg += f" · {op_kind}"
                    yield _safe_sse({
                        "type": "progress",
                        "message": detail_msg,
                        "detail": "",
                        "stage": "classifying",
                    })

            if event_type in ("run.started", "task.classified", "plan.checked"):
                msg = str(payload.get("task", payload.get("message", ""))) if payload else ""
                if _safe_sse and msg:
                    yield _safe_sse({"type": "progress", "message": msg[:200], "detail": ""})

            elif event_type == "tool.started":
                tool_name = str(payload.get("tool_name", "")) if payload else ""
                if _safe_sse and tool_name:
                    yield _safe_sse({"type": "progress", "message": f"🔧 调用工具: {tool_name}", "detail": ""})

            elif event_type == "tool.finished":
                result_preview = str(payload.get("result_preview", "")) if payload else ""
                if _safe_sse and result_preview:
                    yield _safe_sse({"type": "info", "message": result_preview[:300]})

            elif event_type == "step.done":
                text = str(payload.get("text", "")) if payload else ""
                token_stream = payload.get("token_stream", []) if payload else []
                if token_stream:
                    for token_text in token_stream:
                        token_buffer.append(str(token_text))
                        if _safe_sse:
                            yield _safe_sse({"type": "token", "content": str(token_text)})
                elif text and _safe_sse:
                    yield _safe_sse({"type": "token", "content": text})

            elif event_type == "run.finished":
                summary = str(payload.get("summary", "")) if payload else ""
                completed = bool(payload.get("completed_task", True)) if payload else True
                target = str(payload.get("target", "")) if payload else ""
                final_summary = summary
                if target:
                    saved_files.append(target)
                file_changes = getattr(event, "file_changes", []) or []
                for fc in file_changes:
                    if isinstance(fc, dict) and fc.get("path"):
                        saved_files.append(str(fc.get("path")))
                artifact = getattr(event, "artifact_result", {}) or {}
                if artifact and isinstance(artifact, dict):
                    art_path = artifact.get("path", "")
                    if art_path:
                        saved_files.append(str(art_path))
                if not completed and _safe_sse:
                    yield _safe_sse({"type": "token", "content": f"\n⚠️ 任务未完全完成。{summary}"})

            elif event_type == "run.error":
                error_text = str(payload.get("text", str(payload))) if payload else "未知错误"
                had_error = True
                if _safe_sse:
                    yield _safe_sse({"type": "token", "content": f"\n❌ 执行错误: {error_text[:500]}"})

            if session_manager and session_name:
                try:
                    if final_summary:
                        session_manager.append_and_save(
                            f"{session_name}.json",
                            effective,
                            final_summary,
                            task=task_type,
                        )
                except Exception:
                    pass

        if _safe_sse:
            total_time = round(_time.time() - start_time, 1)
            yield _safe_sse({
                "type": "done",
                "images": [],
                "saved_files": list(dict.fromkeys(saved_files)),
                "total_time": total_time,
                "had_error": had_error,
            })

    except Exception as e:
        import traceback
        if _app_logger:
            _app_logger.error(f"[file_task_chat] 异常: {traceback.format_exc()}")
        if _safe_sse:
            yield _safe_sse({"type": "token", "content": f"\n❌ 任务异常: {str(e)[:300]}"})
            yield _safe_sse({"type": "done", "images": [], "saved_files": [], "total_time": round(_time.time() - start_time, 1)})

def _drain_file_task_stream_output_in_background(request_payload, stream_iter) -> None:
    task_id = str(getattr(request_payload, "task_id", "") or "").strip()

    def _drain():
        try:
            for _ in stream_iter:
                pass
        except Exception as exc:
            logger.exception(
                "[FileTaskRuntime] background stream drain failed (task_id=%s): %s",
                task_id or "?",
                exc,
            )
            try:
                error_event = _build_file_task_error_event(request_payload, exc)
                _persist_file_task_progress_event(request_payload, error_event)
            except Exception as persist_exc:
                logger.debug(
                    "[FileTaskRuntime] background drain error persistence skipped (task_id=%s): %s",
                    task_id or "?",
                    persist_exc,
                )

    threading.Thread(
        target=_drain,
        daemon=True,
        name=f"file-task-drain-{task_id[:8] or 'anon'}",
    ).start()


def _iter_file_task_stream_output(request_payload, event_iterable):
    from app.core.agent.file_task_session_store import save_task_summary
    from app.core.agent.file_task_ui_stream import normalize_event as _ui_normalize_event

    yield from _iter_file_task_stream_events(
        request_payload,
        event_iterable,
        save_task_summary_fn=save_task_summary,
        normalize_event_fn=_ui_normalize_event,
        persist_progress_fn=_persist_file_task_progress_event,
    )


def stream_file_task_request(
    data: dict,
    *,
    workspace_root: str | None = None,
    gemini_client: Any = None,
) -> Iterable[str]:
    """Stream the Koto-native file task event contract as SSE frames."""
    from web.runtime_context import get_client_proxy, get_workspace_dir

    request_payload = None
    try:
        request_payload = _build_file_task_request_from_data(data)
        _ensure_file_task_record(request_payload)
        orchestrator = _build_file_task_orchestrator(
            workspace_root=workspace_root if workspace_root is not None else get_workspace_dir(),
            gemini_client=gemini_client if gemini_client is not None else get_client_proxy(),
        )
        event_iterable = orchestrator.run(request_payload)
        stream_iter = _iter_file_task_stream_output(request_payload, event_iterable)
        for frame in stream_iter:
            try:
                yield frame
            except GeneratorExit:
                try:
                    from app.core.agent.file_task_runtime import is_cancel_requested

                    cancelled = is_cancel_requested(getattr(request_payload, "run_id", "") or "")
                except Exception:
                    cancelled = False
                if not cancelled:
                    _drain_file_task_stream_output_in_background(
                        request_payload,
                        stream_iter,
                    )
                raise
    except Exception as exc:
        logger.exception("[FileTaskRuntime] stream failed: %s", exc)
        if request_payload is None:
            request_payload = _fallback_file_task_request_for_error(data)
        error_event = _build_file_task_error_event(request_payload, exc)
        _persist_file_task_progress_event(request_payload, error_event)
        yield _file_task_event_to_safe_sse(error_event)
