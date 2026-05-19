"""Compatibility shim for document annotation (DOC_ANNOTATE) pipelines.

DOC_ANNOTATE entry points — canonical vs. compat:

  CANONICAL (single file via file-assistant):
    app.core.agent.file_task_doc_annotate_bridge.DocAnnotateBridge
      ↳ invoked by FileTaskRuntime when should_route_request() returns True
      ↳ route: POST /api/editor/ai/task-stream  (SSE whitebox stream)

  CANONICAL (batch via file-upload):
    web.document_annotation_compat.collect_annotation_result   ← THIS FILE
      ↳ used by web/app.py _process_single_file() when task_type == "DOC_ANNOTATE"
      ↳ route: POST /api/upload  (batch, non-streaming)

  LEGACY (WebSocket main-chat):
    web/app.py  # task_type == "DOC_ANNOTATE" branch around line 10432
      ↳ reached via socket_handler → streaming_task_handler → /doc WebSocket
      ↳ still active; fallback for clients that do not use the file-assistant UI

New code should prefer the canonical entry points above.
The legacy WebSocket path is retained for backward compatibility.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, Iterable, Optional


def resolve_document_path(file_path: str, workspace_dir: str) -> str:
    text = str(file_path or "").strip()
    if not text:
        return ""
    if os.path.isabs(text):
        return text
    return os.path.join(workspace_dir, "documents", text)


def _build_feedback_system(*, gemini_client: Any, model_id: str):
    from web.document_feedback import DocumentFeedbackSystem

    return DocumentFeedbackSystem(gemini_client=gemini_client, default_model_id=model_id)


def collect_annotation_result(
    *,
    file_path: str,
    user_requirement: str,
    gemini_client: Any,
    model_id: str = "gemini-2.5-pro",
    task_id: Optional[str] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    skill_prompt: str = "",
) -> Dict[str, Any]:
    feedback_system = _build_feedback_system(gemini_client=gemini_client, model_id=model_id)
    last_error = ""

    for progress_event in feedback_system.full_annotation_loop_streaming(
        file_path,
        user_requirement,
        task_id=task_id,
        model_id=model_id,
        cancel_check=cancel_check,
        skill_prompt=skill_prompt,
    ):
        stage = str(progress_event.get("stage") or "").strip().lower()
        if stage == "complete":
            result = progress_event.get("result")
            if isinstance(result, dict):
                return result
            return {"success": False, "error": "兼容标注路径未返回结果"}
        if stage == "cancelled":
            return {
                "success": False,
                "cancelled": True,
                "message": str(progress_event.get("message") or "文档标注任务已取消").strip() or "文档标注任务已取消",
            }
        if stage == "error":
            last_error = str(progress_event.get("message") or progress_event.get("detail") or "文档标注失败").strip()

    return {"success": False, "error": last_error or "文档标注失败"}


def iter_annotation_progress_events(
    *,
    file_path: str,
    user_requirement: str,
    gemini_client: Any,
    model_id: str = "gemini-2.5-pro",
    task_id: Optional[str] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    skill_prompt: str = "",
) -> Iterable[Dict[str, Any]]:
    feedback_system = _build_feedback_system(gemini_client=gemini_client, model_id=model_id)
    yield from feedback_system.full_annotation_loop_streaming(
        file_path,
        user_requirement,
        task_id=task_id,
        model_id=model_id,
        cancel_check=cancel_check,
        skill_prompt=skill_prompt,
    )


def analyze_annotations_only(
    *,
    file_path: str,
    user_requirement: str,
    gemini_client: Any,
    model_id: str = "gemini-2.5-pro",
) -> Dict[str, Any]:
    feedback_system = _build_feedback_system(gemini_client=gemini_client, model_id=model_id)
    return feedback_system.analyze_for_annotation_chunked(
        file_path,
        user_requirement,
        model_id=model_id,
    )


def stream_annotation_events(
    *,
    file_path: str,
    user_requirement: str,
    gemini_client: Any,
    model_id: str = "gemini-2.5-pro",
    task_id: Optional[str] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    skill_prompt: str = "",
) -> Iterable[str]:
    feedback_system = _build_feedback_system(gemini_client=gemini_client, model_id=model_id)

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