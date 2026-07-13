from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskRequest,
)
from app.core.agent.file_task_doc_annotate_request import is_docx_clear_review_request
from app.core.agent.file_task_prompt_sections import (
    clear_docx_review_guidance as _prompt_clear_docx_review_guidance,
    docx_compare_annotate_guidance as _prompt_docx_compare_annotate_guidance,
    single_docx_annotate_guidance as _prompt_single_docx_annotate_guidance,
)

DisplayPath = Callable[[Any], str]
FirstFileName = Callable[[Sequence[FileTaskFile], set[str]], str]


@dataclass(frozen=True)
class DocxPromptGuidance:
    docx_compare_annotate_guidance: str = ""
    clear_docx_review_guidance: str = ""
    single_docx_annotate_guidance: str = ""


def build_docx_prompt_guidance(
    *,
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    classification: FileTaskClassification,
    display_path: DisplayPath,
    first_file_name: Callable[..., str],
) -> DocxPromptGuidance:
    docx_files = [
        display_path(file_info.path or file_info.name)
        for file_info in files
        if _file_type(file_info) in {"docx", "doc"}
    ]
    target_docx = (
        display_path(request.target_path)
        or first_file_name(files, {"docx"}, target=True)
        or first_file_name(files, {"docx"})
        or "当前 DOCX"
    )

    return DocxPromptGuidance(
        docx_compare_annotate_guidance=_prompt_docx_compare_annotate_guidance(
            "compare_docx_and_annotate" in classification.matched_capabilities,
            docx_files,
        ),
        single_docx_annotate_guidance=_prompt_single_docx_annotate_guidance(
            classification.docx_annotation_request,
            target_docx,
        ),
        clear_docx_review_guidance=_prompt_clear_docx_review_guidance(
            (not classification.docx_annotation_request)
            and is_docx_clear_review_request(request),
            target_docx,
        ),
    )


def _file_type(file_info: FileTaskFile) -> str:
    return (
        file_info.type or Path(str(file_info.path or file_info.name)).suffix.lstrip(".")
    ).lower()
