"""Deterministic request projection used by file-task classification."""

from __future__ import annotations

from typing import Any

from app.core.agent.file_task_contract import FileTaskRequest


def classification_task_text(
    request: FileTaskRequest, resume_control: dict[str, Any]
) -> str:
    task_text = str(request.task or "").strip()
    original_task = ""
    if isinstance(resume_control, dict):
        original_task = str(resume_control.get("original_task") or "").strip()
    if original_task and original_task not in task_text:
        return f"{task_text}\n原始分步任务：{original_task}".strip()
    return task_text


def request_with_task(request: FileTaskRequest, task_text: str) -> FileTaskRequest:
    if str(task_text or "") == str(request.task or ""):
        return request
    return FileTaskRequest(
        task=task_text,
        task_id=request.task_id,
        run_id=request.run_id,
        session_id=request.session_id,
        files=list(request.files),
        current_file=request.current_file,
        selection=request.selection,
        selection_source=request.selection_source,
        target_path=request.target_path,
        model_mode=request.model_mode,
        model_id=request.model_id,
        history=list(request.history),
        options=dict(request.options),
        routing_decision=request.routing_decision,
    )


__all__ = ["classification_task_text", "request_with_task"]
