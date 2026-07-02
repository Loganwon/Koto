from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass
class FileTaskClassificationFlow:
    request_kind: str = "new_task"
    execution_mode: str = "generic_tool_loop"
    reason_codes: list[str] = field(default_factory=list)
    followup_action: str = ""
    previous_task_family: str = ""
    previous_task_execution_mode: str = ""
    previous_task_output_mode: str = ""
    previous_task_intent_can_apply: str = ""
    resume_adapter: str = ""
    stepwise_pdf_docx_resume: bool = False
    force_long_pdf_docx_write: bool = False


def build_classification_flow(
    *,
    followup_context: Mapping[str, Any],
    resume_control: Mapping[str, Any],
    semantic: Mapping[str, Any],
    file_types: Sequence[str],
    target_file_type: str,
) -> FileTaskClassificationFlow:
    followup_action = (
        str(followup_context.get("followup_action") or "").strip().lower()
        if isinstance(followup_context, Mapping)
        else ""
    )
    previous_task_family = (
        str(followup_context.get("previous_task_family") or "").strip().lower()
        if isinstance(followup_context, Mapping)
        else ""
    )
    previous_task_execution_mode = (
        str(
            followup_context.get("previous_task_execution_mode")
            or followup_context.get("previous_task_mode")
            or ""
        )
        .strip()
        .lower()
        if isinstance(followup_context, Mapping)
        else ""
    )
    previous_task_output_mode = (
        str(followup_context.get("previous_task_output_mode") or "").strip().lower()
        if isinstance(followup_context, Mapping)
        else ""
    )
    previous_task_intent_can_apply = (
        str(followup_context.get("previous_task_intent_can_apply") or "")
        .strip()
        .lower()
        if isinstance(followup_context, Mapping)
        else ""
    )
    resume_adapter = (
        str(resume_control.get("adapter") or "").strip().lower()
        if isinstance(resume_control, Mapping)
        else ""
    )

    flow = FileTaskClassificationFlow(
        followup_action=followup_action,
        previous_task_family=previous_task_family,
        previous_task_execution_mode=previous_task_execution_mode,
        previous_task_output_mode=previous_task_output_mode,
        previous_task_intent_can_apply=previous_task_intent_can_apply,
        resume_adapter=resume_adapter,
    )
    flow.force_long_pdf_docx_write = bool(
        semantic.get("pdf_source")
        and semantic.get("summary_request")
        and semantic.get("stepwise_confirmation_request")
        and semantic.get("docx_target")
    )
    if flow.force_long_pdf_docx_write:
        flow.reason_codes.append("long_pdf_stepwise_docx_forced_write_intent")

    if resume_control:
        flow.request_kind = "resume"
        flow.execution_mode = "awaiting_confirmation_resume"
        flow.reason_codes.append("workflow_checkpoint_resume")
        if flow.resume_adapter:
            flow.reason_codes.append(f"workflow_adapter:{flow.resume_adapter}")
        if (
            str(resume_control.get("policy") or "").strip().lower()
            == "confirm_each_step"
            and "pdf" in set(str(item or "").strip().lower() for item in file_types)
            and str(target_file_type or "").strip().lower() in {"docx", "doc"}
        ):
            flow.stepwise_pdf_docx_resume = True
            flow.reason_codes.append("stepwise_resume_forced_write_intent")
    elif followup_context:
        flow.request_kind = "followup"
        flow.execution_mode = "followup_contextual"
        if flow.followup_action:
            flow.reason_codes.append(f"followup_action:{flow.followup_action}")
        else:
            flow.reason_codes.append("followup_context")

    return flow
