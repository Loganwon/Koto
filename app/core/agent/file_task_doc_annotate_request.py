from __future__ import annotations

from typing import Callable, Sequence

from app.core.agent import file_task_doc_annotate_boundary
from app.core.agent.file_task_classification_contract import (
    docx_annotation_has_contract as _classification_docx_annotation_has_contract,
)
from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskRequest,
)
from app.core.agent.file_task_followup_context import followup_context
from app.core.agent.file_task_review_intent import (
    has_explicit_docx_review_intent,
    request_has_file_type,
)


def is_docx_annotation_request(request: FileTaskRequest) -> bool:
    if not request_has_file_type(request, "docx"):
        return False
    options = request.options if isinstance(request.options, dict) else {}
    if bool(options.get("skip_doc_annotate_bridge")):
        return False
    if file_task_doc_annotate_boundary.looks_like_docx_review_clear_request(
        request.task
    ):
        return False
    if file_task_doc_annotate_boundary.looks_like_direct_docx_rewrite_request(
        request.task
    ):
        return False
    if file_task_doc_annotate_boundary.looks_like_multi_file_compare_request(request):
        return False

    task_lower = str(request.task or "").strip().lower()
    if not task_lower:
        return False
    if (
        request_has_file_type(request, "pdf")
        and any(marker in task_lower for marker in ("翻译", "translation", "译稿"))
        and any(marker in task_lower for marker in ("原文", "source", "pdf"))
        and any(marker in task_lower for marker in ("处理", "分段", "拆成", "batch"))
    ):
        return True
    return has_explicit_docx_review_intent(task_lower)


def is_docx_clear_review_request(request: FileTaskRequest) -> bool:
    if not request_has_file_type(request, "docx"):
        return False
    return file_task_doc_annotate_boundary.looks_like_docx_review_clear_request(
        request.task
    )


def docx_annotation_has_request_contract(
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    classification: FileTaskClassification,
) -> bool:
    del files
    return _classification_docx_annotation_has_contract(
        classification,
        request_has_docx=request_has_file_type(request, "docx"),
        direct_docx_annotation_request=is_docx_annotation_request(request),
        followup_context=followup_context(request),
    )


def docx_annotation_contract_for_request(
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
) -> Callable[[FileTaskClassification], bool]:
    def has_contract(classification: FileTaskClassification) -> bool:
        return docx_annotation_has_request_contract(request, files, classification)

    return has_contract
