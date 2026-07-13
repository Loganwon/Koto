"""Compatibility transport helpers for the document annotation SSE contract."""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, Iterable, Optional


def resolve_document_path(file_path: str, workspace_dir: str) -> str:
    text = str(file_path or "").strip()
    if not text:
        return ""
    return text if os.path.isabs(text) else os.path.join(workspace_dir, "documents", text)


def _feedback_system(*, gemini_client: Any, model_id: str):
    # Deferred to preserve the module's one-way dependency on the runtime class.
    from web.document_feedback import DocumentFeedbackSystem

    return DocumentFeedbackSystem(gemini_client=gemini_client, default_model_id=model_id)


def iter_annotation_progress_events(
    *,
    file_path: str,
    user_requirement: str,
    gemini_client: Any,
    model_id: str = "deepseek-chat",
    task_id: Optional[str] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    skill_prompt: str = "",
) -> Iterable[Dict[str, Any]]:
    yield from _feedback_system(
        gemini_client=gemini_client, model_id=model_id
    ).full_annotation_loop_streaming(
        file_path,
        user_requirement,
        task_id=task_id,
        model_id=model_id,
        cancel_check=cancel_check,
        skill_prompt=skill_prompt,
    )


def collect_annotation_result(
    *,
    file_path: str,
    user_requirement: str,
    gemini_client: Any,
    model_id: str = "deepseek-chat",
    task_id: Optional[str] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    skill_prompt: str = "",
) -> Dict[str, Any]:
    last_error = ""
    for progress_event in iter_annotation_progress_events(
        file_path=file_path,
        user_requirement=user_requirement,
        gemini_client=gemini_client,
        model_id=model_id,
        task_id=task_id,
        cancel_check=cancel_check,
        skill_prompt=skill_prompt,
    ):
        stage = str(progress_event.get("stage") or "").strip().lower()
        if stage == "complete":
            result = progress_event.get("result")
            return result if isinstance(result, dict) else {"success": False, "error": "兼容标注路径未返回结果"}
        if stage == "cancelled":
            return {
                "success": False,
                "cancelled": True,
                "message": str(progress_event.get("message") or "文档标注任务已取消").strip() or "文档标注任务已取消",
            }
        if stage == "error":
            last_error = str(
                progress_event.get("message") or progress_event.get("detail") or "文档标注失败"
            ).strip()
    return {"success": False, "error": last_error or "文档标注失败"}


def stream_annotation_events(
    *,
    file_path: str,
    user_requirement: str,
    gemini_client: Any,
    model_id: str = "deepseek-chat",
    task_id: Optional[str] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    skill_prompt: str = "",
) -> Iterable[str]:
    for progress_event in iter_annotation_progress_events(
        file_path=file_path,
        user_requirement=user_requirement,
        gemini_client=gemini_client,
        model_id=model_id,
        task_id=task_id,
        cancel_check=cancel_check,
        skill_prompt=skill_prompt,
    ):
        stage = str(progress_event.get("stage") or "").strip().lower()
        if stage == "complete":
            result = progress_event.get("result") if isinstance(progress_event.get("result"), dict) else {}
            yield f"event: complete\ndata: {json.dumps({'success': bool(result.get('success')), **result}, ensure_ascii=False)}\n\n"
            return
        if stage in {"error", "cancelled"}:
            payload = {
                "success": False,
                "stage": stage,
                "message": str(progress_event.get("message") or progress_event.get("detail") or "文档标注失败").strip() or "文档标注失败",
            }
            yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            return
        payload = {
            "stage": stage,
            "progress": progress_event.get("progress", 0),
            "message": progress_event.get("message", ""),
            "detail": progress_event.get("detail", ""),
        }
        yield f"event: progress\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
