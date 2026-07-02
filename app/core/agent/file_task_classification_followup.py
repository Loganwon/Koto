from __future__ import annotations

from dataclasses import dataclass, field

from app.core.agent.file_task_contract import FileTaskRequest
from app.core.agent.file_task_review_intent import request_has_file_type


@dataclass
class FileTaskFollowupAnnotationOverrides:
    docx_annotation_request: bool = False
    write_intent: bool = False
    execution_mode: str = "generic_tool_loop"
    reason_codes: list[str] = field(default_factory=list)


def apply_followup_annotation_overrides(
    *,
    classification_request: FileTaskRequest,
    request_kind: str,
    followup_action: str,
    previous_task_family: str,
    previous_task_execution_mode: str,
    previous_task_output_mode: str,
    previous_task_intent_can_apply: str,
    resume_adapter: str,
    docx_annotation_request: bool,
    write_intent: bool,
    execution_mode: str,
    reason_codes: list[str],
) -> FileTaskFollowupAnnotationOverrides:
    reasons = list(reason_codes or [])
    has_docx_context = request_has_file_type(classification_request, "docx")

    if resume_adapter == "doc_annotate_bridge":
        docx_annotation_request = True

    if request_kind == "followup" and followup_action == "improve":
        if previous_task_family == "annotate":
            reasons.append("followup_previous_task_family:annotate")
            if has_docx_context:
                docx_annotation_request = True
        if previous_task_execution_mode in {
            "annotate_tool_loop",
            "awaiting_confirmation_resume",
            "doc_annotate_bridge",
        }:
            reasons.append(
                f"followup_previous_execution_mode:{previous_task_execution_mode}"
            )
            if has_docx_context:
                docx_annotation_request = True

    if request_kind == "followup" and followup_action == "apply":
        if (
            previous_task_output_mode in {"hybrid", "write"}
            or previous_task_intent_can_apply == "true"
        ):
            write_intent = True
            reasons.append("followup_apply_write_intent")

    if docx_annotation_request:
        if request_kind == "new_task":
            execution_mode = "annotate_tool_loop"
        elif (
            request_kind == "followup"
            and followup_action == "improve"
            and previous_task_execution_mode == "doc_annotate_bridge"
        ):
            execution_mode = "doc_annotate_bridge"
        reasons.append("docx_annotation_request")
        if not write_intent:
            write_intent = True
            reasons.append("docx_annotation_forced_write_intent")

    return FileTaskFollowupAnnotationOverrides(
        docx_annotation_request=bool(docx_annotation_request),
        write_intent=bool(write_intent),
        execution_mode=execution_mode,
        reason_codes=reasons,
    )
