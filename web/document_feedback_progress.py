"""Stable SSE event shapes for document-feedback analysis and writeback."""

from __future__ import annotations

from typing import Any, Dict


_ANALYSIS_META_FIELDS = (
    "chunk_status",
    "chunk_index",
    "chunk_total",
    "global_chunk_index",
    "global_chunk_total",
    "added_count",
    "total_annotations",
    "target_path",
)


def build_analysis_progress_event(
    current: int, total: int, message: str, meta: Dict[str, Any]
) -> Dict[str, Any]:
    event: Dict[str, Any] = {
        "stage": "analyzing",
        "progress": 15 + int((current / max(1, total)) * 35),
        "message": f"🤖 {message}",
        "detail": message,
    }
    for key in _ANALYSIS_META_FIELDS:
        value = meta.get(key)
        if value not in (None, "", [], {}):
            event[key] = value
    proposals = meta.get("partial_proposals")
    if isinstance(proposals, list) and proposals:
        event["partial_proposals"] = [dict(item) for item in proposals if isinstance(item, dict)]
    return event


def build_apply_progress_event(
    current: int,
    total: int,
    status: str,
    detail: str,
    meta: Dict[str, Any],
    *,
    revised_file: str,
) -> Dict[str, Any]:
    status_text = {
        "start": "准备写入修订",
        "processing": "正在写入修订",
        "success": "已完成当前修订",
        "saved": "已写回原文",
        "failed": "写回失败",
    }.get(str(status or "").strip().lower(), str(status or "正在写回").strip() or "正在写回")
    event: Dict[str, Any] = {
        "stage": "applying",
        "progress": 60 + int((current / total) * 25) if total > 0 else 60,
        "message": f"📝 {status_text}",
        "detail": detail,
    }
    if meta.get("file_updated"):
        path = str(meta.get("file_path") or revised_file)
        event.update(
            {
                "file_updated": True,
                "path": path,
                "file_path": path,
                "supported": True,
                "applied": int(meta.get("applied") or current or 0),
                "updated_in_place": bool(meta.get("updated_in_place", True)),
            }
        )
    return event
