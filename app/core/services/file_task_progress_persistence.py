"""Task-ledger and progress-bus persistence for streamed file-task events."""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.core.services.file_task_event_safety import coerce_file_task_event_dict
from app.core.services.file_task_event_semantics import (
    file_task_message,
    file_task_step_type,
    file_task_terminal_status,
    trim_file_task_text,
)

logger = logging.getLogger("koto.app")

FILE_TASK_SOURCE = "file_task"
FILE_TASK_CONTRACT = "file_task_v1"


def build_file_task_record_metadata(request_payload) -> dict:
    files = []
    for file_info in getattr(request_payload, "files", []) or []:
        if hasattr(file_info, "public_dict"):
            files.append(file_info.public_dict())
    current_file = getattr(request_payload, "current_file", None)
    current_file_payload = (
        current_file.public_dict()
        if current_file is not None and hasattr(current_file, "public_dict")
        else None
    )
    if isinstance(current_file_payload, dict):
        current_key = (
            str(
                current_file_payload.get("path")
                or current_file_payload.get("name")
                or ""
            )
            .strip()
            .replace("\\", "/")
            .casefold()
        )
        existing_keys = {
            str(item.get("path") or item.get("name") or "")
            .strip()
            .replace("\\", "/")
            .casefold()
            for item in files
            if isinstance(item, dict)
        }
        if not current_key or current_key not in existing_keys:
            files.append(current_file_payload)
    metadata = {
        "task_contract": FILE_TASK_CONTRACT,
        "task_mode": FILE_TASK_CONTRACT,
        "run_id": str(getattr(request_payload, "run_id", "") or "").strip(),
        "target_path": str(getattr(request_payload, "target_path", "") or "").strip(),
        "model_mode": str(getattr(request_payload, "model_mode", "") or "").strip(),
        "model_id": str(getattr(request_payload, "model_id", "") or "").strip(),
        "selection_source": str(
            getattr(request_payload, "selection_source", "") or ""
        ).strip(),
        "has_selection": bool(getattr(request_payload, "selection", "")),
        "file_count": len(files),
        "files": files[:8],
    }
    if isinstance(current_file_payload, dict):
        metadata["current_file"] = current_file_payload
    task_context = getattr(request_payload, "task_context", None)
    if isinstance(task_context, dict) and task_context:
        metadata["task_context"] = task_context
    selection_context = None
    if hasattr(request_payload, "selection_context_file"):
        try:
            selection_context = request_payload.selection_context_file()
        except Exception:
            selection_context = None
    if (
        "current_file" not in metadata
        and selection_context is not None
        and hasattr(selection_context, "public_dict")
    ):
        metadata["current_file"] = selection_context.public_dict()
    return metadata


def ensure_file_task_record(request_payload) -> str:
    from app.core.tasks.task_ledger import get_ledger

    ledger = get_ledger()
    requested_task_id = str(getattr(request_payload, "task_id", "") or "").strip()
    if requested_task_id:
        existing = ledger.get(requested_task_id)
        if existing is not None:
            ledger.update_metadata(
                existing.task_id,
                build_file_task_record_metadata(request_payload),
            )
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
        source=FILE_TASK_SOURCE,
        metadata=build_file_task_record_metadata(request_payload),
        task_id=requested_task_id or None,
    )
    request_payload.task_id = record.task_id
    return record.task_id


def persist_file_task_progress_event(
    request_payload,
    safe_event: Dict[str, Any],
) -> Dict[str, Any]:
    task_id = str(getattr(request_payload, "task_id", "") or "").strip()
    if not task_id:
        return safe_event

    try:
        from app.core.tasks.progress_bus import ProgressEvent, get_progress_bus
        from app.core.tasks.task_ledger import get_ledger

        ledger = get_ledger()
        safe_event = ledger.append_event(task_id, safe_event)
        event_type = str(safe_event.get("type") or "").strip()
        event_payload = (
            safe_event.get("payload")
            if isinstance(safe_event.get("payload"), dict)
            else {}
        )
        message = file_task_message(event_type, event_payload)
        terminal_status = file_task_terminal_status(event_type, event_payload)
        step_type = file_task_step_type(event_type)
        tool_name = (
            trim_file_task_text(
                event_payload.get("tool_name") or event_payload.get("tool"), 120
            )
            or None
        )
        observation = (
            trim_file_task_text(
                event_payload.get("result_preview") or event_payload.get("summary"),
                800,
            )
            or None
        )

        task_record = ledger.get(task_id)
        current_status = task_record.status.value if task_record is not None else ""

        if terminal_status == "running" and current_status != "running":
            ledger.mark_running(task_id)
        elif terminal_status == "waiting" and current_status != "waiting":
            ledger.mark_waiting(task_id, reason=message or "awaiting_confirmation")
        elif terminal_status == "completed" and current_status != "completed":
            ledger.mark_completed(
                task_id,
                result_summary=str(event_payload.get("summary") or message or "")[:500],
            )
        elif terminal_status == "failed" and current_status != "failed":
            ledger.mark_failed(task_id, message or "任务执行失败")
        elif terminal_status == "cancelled" and current_status != "cancelled":
            ledger.mark_cancelled(task_id)

        if terminal_status in {"completed", "failed", "cancelled"}:
            run_id = str(getattr(request_payload, "run_id", "") or "").strip()
            if run_id:
                ledger.mark_control_terminal(run_id, terminal_status)
                checkpoint = ledger.get_kernel_checkpoint(task_id, run_id)
                if (
                    checkpoint
                    and checkpoint["state"].get("runtime_adapter") == "file_task"
                ):
                    finished_state = dict(checkpoint["state"])
                    finished_state["phase"] = (
                        "domain_completed"
                        if terminal_status == "completed"
                        else "domain_failed"
                    )
                    ledger.save_kernel_checkpoint(
                        task_id, run_id, finished_state, resumable=False
                    )

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

        if event_type not in {
            "run.started",
            "message.delta",
            "stream_chunk",
            "token",
            "tool.progress",
        }:
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
                progress=int(
                    (
                        safe_event.get("ui_state")
                        if isinstance(safe_event.get("ui_state"), dict)
                        else {}
                    ).get("progress")
                    or 0
                ),
                step_type=step_type,
                tool_name=tool_name,
                detail={"event": safe_event},
                run_id=str(safe_event.get("run_id") or ""),
                seq=int(safe_event.get("seq") or 0),
                event_id=str(safe_event.get("event_id") or ""),
            )
        )
        return safe_event
    except Exception as exc:
        logger.error("[FileTaskRuntime] durable event persistence failed: %s", exc)
        raise


def persist_file_task_summary_event(
    request_payload,
    event,
    *,
    save_task_summary_fn,
    artifact_status_fn,
) -> None:
    try:
        event_payload = coerce_file_task_event_dict(event)
        event_type = str(event_payload.get("type") or "").strip()
        if event_type != "run.finished":
            return
        payload = (
            event_payload.get("payload")
            if isinstance(event_payload.get("payload"), dict)
            else {}
        )
        event_summary = str(payload.get("summary") or "").strip()
        event_completed = bool(payload.get("completed_task"))
        event_target = str(
            payload.get("target")
            or payload.get("target_path")
            or payload.get("revised_file")
            or getattr(request_payload, "target_path", "")
            or ""
        ).strip()
        if not event_summary or not event_target:
            return
        save_task_summary_fn(
            file_path=event_target,
            task=str(getattr(request_payload, "task", "") or "")[:500],
            outcome=(
                "completed"
                if event_completed
                else artifact_status_fn(event_type, payload)
            ),
            summary=event_summary,
        )
    except Exception as exc:
        logger.debug("[FileTaskRuntime] task summary persistence skipped: %s", exc)


__all__ = [
    "FILE_TASK_CONTRACT",
    "FILE_TASK_SOURCE",
    "build_file_task_record_metadata",
    "ensure_file_task_record",
    "persist_file_task_progress_event",
    "persist_file_task_summary_event",
]
