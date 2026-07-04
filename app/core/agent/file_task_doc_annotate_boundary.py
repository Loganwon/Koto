# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Re-export bridge functions from their canonical source modules.

All functions previously defined here as one-line delegations now import directly
from the source modules and re-export at module level.  Callers do not need to
change their imports.
"""

from __future__ import annotations

from typing import Any, Iterable

from app.core.agent.file_task_contract import (
    FileTaskEvent,
    FileTaskRequest,
    FileTaskToolStreamResult,
)
from app.core.agent.file_task_doc_annotate_intent import (
    looks_like_direct_docx_rewrite_request as _looks_like_direct_docx_rewrite_request,
)
from app.core.agent.file_task_doc_annotate_intent import (
    looks_like_docx_review_clear_request as _looks_like_docx_review_clear_request,
)
from app.core.agent.file_task_doc_annotate_intent import (
    looks_like_multi_file_compare_request as _looks_like_multi_file_compare_request,
)
from app.core.agent.file_task_doc_annotate_intent import (
    should_use_doc_annotate_bridge_execution as _should_use_bridge_exec,
)
from app.core.agent.file_task_review_intent import request_has_file_type


def should_use_bridge_execution(request: FileTaskRequest) -> bool:
    return _should_use_bridge_exec(request)


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
    from app.core.agent.file_task_doc_annotate_bridge import stream_request

    yield from stream_request(
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
    from app.core.agent.file_task_doc_annotate_bridge import stream_request_as_tool

    return stream_request_as_tool(
        request,
        workspace_root=workspace_root,
        gemini_client=gemini_client,
    )


def looks_like_docx_review_clear_request(task_text: str) -> bool:
    return _looks_like_docx_review_clear_request(task_text)


def looks_like_direct_docx_rewrite_request(task_text: str) -> bool:
    return _looks_like_direct_docx_rewrite_request(task_text)


def looks_like_multi_file_compare_request(request: FileTaskRequest) -> bool:
    return _looks_like_multi_file_compare_request(request)
