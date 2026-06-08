from __future__ import annotations

from typing import Any, Iterable

from app.core.agent.file_task_contract import (
    FileTaskEvent,
    FileTaskRequest,
    FileTaskToolStreamResult,
)
from app.core.agent.file_task_review_intent import request_has_file_type


def should_use_bridge_execution(request: FileTaskRequest) -> bool:
    from app.core.agent import file_task_doc_annotate_intent

    return file_task_doc_annotate_intent.should_use_doc_annotate_bridge_execution(
        request
    )


def bridge_recipe_id(request: FileTaskRequest) -> str:
    return (
        "pdf_docx_review_bridge"
        if request_has_file_type(request, "pdf")
        else "single_docx_review_bridge"
    )


def stream_bridge_request(
    request: FileTaskRequest,
    *,
    workspace_root: str = "",
    gemini_client: Any = None,
) -> Iterable[FileTaskEvent]:
    from app.core.agent import file_task_doc_annotate_bridge

    yield from file_task_doc_annotate_bridge.stream_request(
        request,
        workspace_root=workspace_root,
        gemini_client=gemini_client,
    )


def stream_bridge_request_as_tool(
    request: FileTaskRequest,
    *,
    workspace_root: str = "",
    gemini_client: Any = None,
) -> FileTaskToolStreamResult:
    from app.core.agent import file_task_doc_annotate_bridge

    return file_task_doc_annotate_bridge.stream_request_as_tool(
        request,
        workspace_root=workspace_root,
        gemini_client=gemini_client,
    )


def looks_like_docx_review_clear_request(task_text: str) -> bool:
    from app.core.agent import file_task_doc_annotate_intent

    return file_task_doc_annotate_intent.looks_like_docx_review_clear_request(
        task_text
    )


def looks_like_direct_docx_rewrite_request(task_text: str) -> bool:
    from app.core.agent import file_task_doc_annotate_intent

    return file_task_doc_annotate_intent.looks_like_direct_docx_rewrite_request(
        task_text
    )


def looks_like_multi_file_compare_request(request: FileTaskRequest) -> bool:
    from app.core.agent import file_task_doc_annotate_intent

    return file_task_doc_annotate_intent.looks_like_multi_file_compare_request(
        request
    )
