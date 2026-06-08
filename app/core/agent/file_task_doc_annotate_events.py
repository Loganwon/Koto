from __future__ import annotations

from typing import Any, Optional


def coerce_progress_value(value: Any) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def runtime_payload(terminal_status: str) -> dict[str, Any]:
    return {
        "execution_path": "native",
        "terminal_status": terminal_status,
    }


def build_live_write_progress_payload(
    progress_event: dict[str, Any],
    *,
    default_path: str,
) -> dict[str, Any]:
    payload = {
        "detail": str(
            progress_event.get("detail")
            or progress_event.get("message")
            or "正在写回 Word 修订。"
        ).strip(),
        "message": str(progress_event.get("message") or "").strip(),
        "progress": coerce_progress_value(progress_event.get("progress")),
        "level": "progress",
    }
    if progress_event.get("file_updated"):
        live_path = str(
            progress_event.get("path")
            or progress_event.get("file_path")
            or default_path
            or ""
        ).strip()
        if live_path:
            payload.update(
                {
                    "file_updated": True,
                    "path": live_path,
                    "file_path": live_path,
                    "supported": bool(progress_event.get("supported", True)),
                }
            )
        applied = progress_event.get("applied")
        if applied is not None:
            payload["applied"] = applied
    return payload


def build_review_progress_payload(
    progress_event: dict[str, Any],
    *,
    default_path: str,
) -> dict[str, Any]:
    stage = str(progress_event.get("stage") or "").strip().lower()
    payload = {
        "detail": str(
            progress_event.get("detail") or progress_event.get("message") or ""
        ).strip(),
        "message": str(progress_event.get("message") or "").strip(),
        "progress": coerce_progress_value(progress_event.get("progress")),
        "level": "warning"
        if stage == "warning"
        else ("info" if stage == "info" else "progress"),
    }
    for key in (
        "chunk_status",
        "chunk_index",
        "chunk_total",
        "global_chunk_index",
        "global_chunk_total",
        "added_count",
        "total_annotations",
    ):
        value = progress_event.get(key)
        if value not in (None, "", [], {}):
            payload[key] = value

    partial_proposals = progress_event.get("partial_proposals")
    if isinstance(partial_proposals, list) and partial_proposals:
        payload["partial_proposals"] = [
            dict(item) for item in partial_proposals if isinstance(item, dict)
        ]

    target_path = str(progress_event.get("target_path") or default_path or "").strip()
    if target_path and (
        payload.get("chunk_status")
        or payload.get("partial_proposals")
        or progress_event.get("target_path")
    ):
        payload["target_path"] = target_path
    return payload


def tool_result_from_bridge_payload(
    run_payload: dict[str, Any],
    *,
    last_change: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    summary = str(run_payload.get("summary") or "").strip()
    awaiting_confirmation = bool(run_payload.get("awaiting_confirmation"))
    next_action_artifact = (
        run_payload.get("next_action_artifact")
        if isinstance(run_payload.get("next_action_artifact"), dict)
        else None
    )

    if awaiting_confirmation:
        payload = dict(last_change or {})
        if summary:
            payload["summary"] = summary
        payload["awaiting_confirmation"] = True
        payload.setdefault("operation", "annotate_file")
        payload.setdefault("change_type", "annotate")
        payload.setdefault("focus", True)
        payload.setdefault("supported", True)
        payload.setdefault("updated_in_place", True)
        if next_action_artifact is not None:
            payload["next_action_artifact"] = next_action_artifact
        for key in (
            "batch_index",
            "total_batches",
            "target_path",
            "source_path",
            "revised_file",
            "annotations_added",
        ):
            value = run_payload.get(key)
            if value not in (None, ""):
                payload[key] = value
        return payload

    if bool(run_payload.get("completed_task")) or last_change:
        payload = dict(last_change or {})
        revised_file = str(
            run_payload.get("revised_file")
            or payload.get("path")
            or payload.get("file_path")
            or ""
        ).strip()
        if revised_file and "path" not in payload:
            payload["path"] = revised_file
            payload["file_path"] = revised_file
            payload["operation"] = "annotate_file"
            payload["supported"] = True
        payload.setdefault("operation", "annotate_file")
        payload.setdefault("change_type", "annotate")
        payload.setdefault("focus", True)
        payload.setdefault("supported", True)
        payload.setdefault("updated_in_place", True)
        if summary:
            payload["summary"] = summary
        for key in ("target_path", "source_path", "annotations_added", "revised_file"):
            value = run_payload.get(key)
            if value not in (None, ""):
                payload[key] = value
        return payload

    return {"error": summary or "文档审校未完成。"}
