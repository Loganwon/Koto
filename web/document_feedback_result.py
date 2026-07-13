"""Synchronous compatibility result collection for document-feedback streams."""

from __future__ import annotations

from typing import Any, Dict, Iterable


def collect_annotation_loop_result(
    events: Iterable[Dict[str, Any]], *, file_path: str
) -> Dict[str, Any]:
    """Collapse the streaming contract into the legacy synchronous result."""
    final_error = ""
    for event in events:
        stage = str(event.get("stage") or "").strip().lower()
        if stage == "complete":
            result = event.get("result")
            return result if isinstance(result, dict) else {
                "success": False,
                "error": "文档修订完成但未返回结果。",
                "original_file": file_path,
            }
        if stage == "cancelled":
            return {
                "success": False,
                "cancelled": True,
                "message": str(event.get("message") or event.get("detail") or "文档修订任务已取消").strip() or "文档修订任务已取消",
                "original_file": file_path,
            }
        if stage == "error":
            final_error = str(event.get("message") or event.get("detail") or "文档修订失败").strip()
            return {
                "success": False,
                "error": final_error or "文档修订失败",
                "original_file": file_path,
            }
    return {"success": False, "error": final_error or "文档修订失败", "original_file": file_path}
