from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from app.core.agent.file_task_contract import FileTaskClassification, FileTaskFile, FileTaskRequest
from app.core.agent.file_task_docx_guidance import build_docx_prompt_guidance
from app.core.agent.file_task_prompt_sections import (
    financial_chart_docx_guidance as _prompt_financial_chart_docx_guidance,
    followup_guidance as _prompt_followup_guidance,
)


@dataclass(frozen=True)
class FileTaskSystemPromptGuidance:
    followup_guidance: str = ""
    financial_chart_docx_guidance: str = ""
    docx_compare_annotate_guidance: str = ""
    clear_docx_review_guidance: str = ""
    single_docx_annotate_guidance: str = ""


def build_file_task_system_prompt_guidance(
    *,
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    classification: FileTaskClassification,
    followup_context: dict[str, Any],
    financial_chart_docx_enabled: bool,
    display_path: Callable[[Any], str],
    first_file_name: Callable[..., str],
) -> FileTaskSystemPromptGuidance:
    docx_guidance = build_docx_prompt_guidance(
        request=request,
        files=files,
        classification=classification,
        display_path=display_path,
        first_file_name=first_file_name,
    )
    return FileTaskSystemPromptGuidance(
        followup_guidance=_prompt_followup_guidance(followup_context),
        financial_chart_docx_guidance=_prompt_financial_chart_docx_guidance(
            financial_chart_docx_enabled
        ),
        docx_compare_annotate_guidance=docx_guidance.docx_compare_annotate_guidance,
        clear_docx_review_guidance=docx_guidance.clear_docx_review_guidance,
        single_docx_annotate_guidance=docx_guidance.single_docx_annotate_guidance,
    )
