"""Single deterministic policy boundary for pre-Kernel file-task classification."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_file_facts import (
    request_file_types,
    request_target_file_type,
)
from app.core.agent.file_task_intent_predicates import (
    describes_write_without_execution,
    has_artifact_creation_intent,
    has_explicit_write_intent,
    has_readonly_write_negation,
    has_strong_write_intent,
    has_target_context,
    has_target_scoped_write_intent,
    has_write_intent,
)


@dataclass
class FileTaskClassificationPolicy:
    request_kind: str = "new_task"
    execution_mode: str = "generic_tool_loop"
    diagnostic_request: bool = False
    readonly_write_negation: bool = False
    raw_write_signal: bool = False
    write_signal: bool = False
    task_family: str = "analyze"
    operation_kind: str = "read"
    output_mode: str = "answer"
    write_authorized: bool = False
    write_required: bool = False
    file_types: set[str] = field(default_factory=set)
    target_file_type: str = ""
    reason_codes: list[str] = field(default_factory=list)
    known_gap_name: str = ""


def _followup_field(followup_context: Mapping[str, Any] | None, key: str) -> str:
    if not isinstance(followup_context, Mapping):
        return ""
    return str(followup_context.get(key) or "").strip().lower()


def _has_create_or_export_contract(task: str) -> bool:
    text = str(task or "")
    if not text:
        return False
    return bool(
        re.search(
            r"(?:创建|新建|生成|产出|导出|保存为|整理成|做成|create|generate|export|save as).{0,28}(?:\.docx|\.xlsx|\.pptx|\.pdf|\.md|\.txt|\.csv|word|excel|ppt|文档|表格|幻灯片|报告)",
            text,
            re.IGNORECASE,
        )
        or re.search(
            r"(?:create|generate|export|save as).{0,28}(?:specified|target|output|new).{0,24}(?:text\s+)?(?:file|document|report|spreadsheet|slides?)",
            text,
            re.IGNORECASE,
        )
        or re.search(
            r"(?:write|insert|add|append).{0,32}(?:into|to|in).{0,32}(?:\.docx|\.xlsx|\.pptx|\.pdf|word|excel|ppt|document|spreadsheet|slides?|report)",
            text,
            re.IGNORECASE,
        )
    )


def resolve_classification_policy(
    *,
    classification_task: str,
    classification_request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    followup_context: Mapping[str, Any],
    resume_control: Mapping[str, Any],
    explicit_output_mode: str,
    planner_policy: str,
    planner_backend: str,
    known_tool_gap: Mapping[str, Any] | None,
) -> FileTaskClassificationPolicy:
    """Resolve safety-relevant classification facts exactly once before Kernel."""

    output_mode = str(explicit_output_mode or "").strip().lower()
    if output_mode == "edit":
        output_mode = "write"
    file_types = request_file_types(files)
    target_file_type = request_target_file_type(classification_request, files)
    readonly_write_negation = has_readonly_write_negation(classification_task)
    raw_write_signal = has_explicit_write_intent(classification_task)
    write_signal = has_write_intent(classification_task)
    reasons: list[str] = []
    if output_mode == "write":
        raw_write_signal = True
        write_signal = True
        reasons.append("explicit_write_transport_contract")

    followup_action = _followup_field(followup_context, "followup_action")
    previous_output_mode = _followup_field(
        followup_context, "previous_task_output_mode"
    )
    previous_intent_can_apply = _followup_field(
        followup_context, "previous_task_intent_can_apply"
    )

    request_kind = "new_task"
    stepwise_pdf_docx_resume = False
    if resume_control:
        request_kind = "resume"
        reasons.append("workflow_checkpoint_resume")
        resume_adapter = str(resume_control.get("adapter") or "").strip().lower()
        if resume_adapter:
            reasons.append(f"workflow_adapter:{resume_adapter}")
        stepwise_pdf_docx_resume = (
            str(resume_control.get("policy") or "").strip().lower()
            == "confirm_each_step"
            and "pdf" in file_types
            and target_file_type in {"docx", "doc"}
        )
        if stepwise_pdf_docx_resume:
            reasons.append("stepwise_resume_forced_write_requirement")
            write_signal = True
            raw_write_signal = True
    elif followup_context:
        request_kind = "followup"
        reasons.append(
            f"followup_action:{followup_action}"
            if followup_action
            else "followup_context"
        )

    diagnostic_request = False
    followup_question_is_explicit_write = (
        request_kind == "followup"
        and followup_action == "question"
        and output_mode in {"write", "hybrid"}
    )
    if (
        request_kind == "followup"
        and followup_action == "question"
        and not followup_question_is_explicit_write
    ):
        diagnostic_request = True
        reasons.extend(("followup_question", "diagnostic_request"))
        if write_signal or raw_write_signal:
            write_signal = False
            reasons.append("diagnostic_overrode_write_requirement")
    elif followup_question_is_explicit_write:
        reasons.append("followup_question_explicit_write")

    if (
        output_mode not in {"write", "hybrid"}
        and request_kind != "resume"
        and followup_action != "apply"
        and describes_write_without_execution(classification_task)
    ):
        diagnostic_request = True
        write_signal = False
        reasons.append("described_operation_is_not_execution_authority")

    if readonly_write_negation:
        reasons.append("readonly_write_negation")
        if write_signal or raw_write_signal:
            write_signal = False
            reasons.append("readonly_overrode_write_requirement")

    if request_kind == "followup" and followup_action == "apply":
        if previous_output_mode in {"hybrid", "write"} or (
            previous_intent_can_apply == "true"
        ):
            write_signal = True
            reasons.append("followup_apply_write_requirement")

    # An explicit answer-only request is the final authority.  Resolve it after
    # follow-up context so an old "apply" action cannot silently re-enable writes.
    if output_mode == "answer" and (write_signal or raw_write_signal):
        write_signal = False
        reasons.append("answer_mode_overrode_write_requirement")

    if planner_policy:
        reasons.append(f"planner_policy:{planner_policy}")
    if planner_backend:
        reasons.append(f"planner_backend:{planner_backend}")

    known_gap_name = ""
    if isinstance(known_tool_gap, Mapping):
        known_gap_name = str(known_tool_gap.get("missing_capability") or "").strip()
        if known_gap_name:
            reasons.append(f"native_tool_gap:{known_gap_name}")

    task_family = "transform" if write_signal and not diagnostic_request else "analyze"
    operation_kind = "write" if task_family == "transform" else "read"
    resolved_output_mode = output_mode or ("write" if write_signal else "answer")
    write_required = bool(write_signal and resolved_output_mode == "write")
    write_authorized = bool(write_required or resolved_output_mode == "hybrid")

    reasons.append("mainline_contract:v1")
    if readonly_write_negation:
        resolved_output_mode = "answer"
        write_signal = False
        write_required = False
        write_authorized = False
        task_family = "analyze"
        operation_kind = "read"
        reasons.append("mainline_contract:readonly_guard")
    elif write_required:
        write_has_contract_anchor = bool(
            output_mode in {"write", "hybrid"}
            or request_kind == "resume"
            or "followup_apply_write_requirement" in reasons
            or has_strong_write_intent(classification_task)
            or has_artifact_creation_intent(classification_task)
            or has_target_scoped_write_intent(classification_task)
            or _has_create_or_export_contract(classification_task)
        )
        if not write_has_contract_anchor:
            resolved_output_mode = "answer"
            write_required = False
            write_authorized = False
            task_family = "analyze"
            operation_kind = "read"
            reasons.append("mainline_contract:keyword_write_demoted")
            # Preserve ordinary single-input editing: an existing positive
            # write signal scoped to a target lets the Kernel choose whether
            # to edit. A target alone, an explanation, or a readonly contract
            # never enters this compatibility path.
            if (
                write_signal
                and not diagnostic_request
                and not readonly_write_negation
                and not output_mode
                and has_target_context(classification_request, list(files))
            ):
                resolved_output_mode = "hybrid"
                write_authorized = True
                reasons.append("mainline_contract:target_context_hybrid")

    # Keep the operation and reason codes as projections of the final mode.
    # This prevents a demoted Hybrid task from still looking like a required
    # write, or an explicit Answer task from retaining a write operation.
    if resolved_output_mode == "write":
        operation_kind = "write"
        task_family = "transform"
    elif resolved_output_mode == "hybrid":
        operation_kind = "hybrid"
    else:
        operation_kind = "read"
        task_family = "analyze"

    if write_required:
        reasons.append("write_required")
    elif write_authorized:
        reasons.append("write_optional")

    return FileTaskClassificationPolicy(
        request_kind=request_kind,
        diagnostic_request=diagnostic_request,
        readonly_write_negation=readonly_write_negation,
        raw_write_signal=raw_write_signal,
        write_signal=write_signal,
        task_family=task_family,
        operation_kind=operation_kind,
        output_mode=resolved_output_mode,
        write_authorized=write_authorized,
        write_required=write_required,
        file_types=file_types,
        target_file_type=target_file_type,
        reason_codes=reasons,
        known_gap_name=known_gap_name,
    )


__all__ = ["FileTaskClassificationPolicy", "resolve_classification_policy"]
