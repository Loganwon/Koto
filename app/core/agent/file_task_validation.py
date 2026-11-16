from __future__ import annotations

from pathlib import Path
from typing import List

from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskIntentPlan,
    FileTaskPlanCheck,
    FileTaskRequest,
    FileTaskRequirementSet,
)


def _target_file_type(
    request: FileTaskRequest, classification: FileTaskClassification
) -> str:
    file_type = str(classification.target_file_type or "").strip().lower()
    if file_type:
        return file_type
    if request.target_path:
        suffix = Path(str(request.target_path)).suffix.lstrip(".").lower().strip()
        if suffix:
            return suffix
    for file_info in request.files:
        candidate = (
            str(
                file_info.type
                or Path(str(file_info.path or file_info.name)).suffix.lstrip(".")
            )
            .strip()
            .lower()
        )
        if candidate:
            return candidate
    return ""


def build_file_task_requirements(
    request: FileTaskRequest,
    classification: FileTaskClassification,
) -> FileTaskRequirementSet:
    target_file_type = _target_file_type(request, classification)
    requested_operation = (
        str(classification.operation_kind or "read").strip().lower() or "read"
    )
    write_authorized = bool(classification.write_authorized)
    write_required = bool(classification.write_required)
    required_capabilities: List[str] = []
    forbidden_capabilities: List[str] = []
    acceptance_criteria: List[str] = []
    reason_codes: List[str] = []

    if write_required:
        acceptance_criteria.append("必须产生真实文件变更")
        reason_codes.append("write_required")
    elif write_authorized:
        acceptance_criteria.append("允许按需使用写入工具，但文件变更不是完成条件")
        reason_codes.append("write_optional")
    else:
        acceptance_criteria.append("不应误触发写入工具")
        reason_codes.append("read_only_request")

    return FileTaskRequirementSet(
        requested_operation=requested_operation,
        target_path=str(request.target_path or "").strip(),
        target_file_type=target_file_type,
        write_authorized=write_authorized,
        write_required=write_required,
        required_capabilities=required_capabilities,
        forbidden_capabilities=forbidden_capabilities,
        acceptance_criteria=acceptance_criteria,
        reason_codes=reason_codes,
    )


def validate_file_task_plan(
    requirements: FileTaskRequirementSet,
    classification: FileTaskClassification,
    intent_plan: FileTaskIntentPlan,
) -> FileTaskPlanCheck:
    violations: List[str] = []

    if requirements.write_required and intent_plan.write_required is False:
        violations.append("write_required_but_plan_not_write")
    if requirements.write_required and intent_plan.output_mode != "write":
        violations.append("write_required_but_output_not_write")

    if requirements.write_authorized != classification.write_authorized:
        violations.append("write_authorization_contract_mismatch")
    if intent_plan.write_authorized != classification.write_authorized:
        violations.append("write_authorization_plan_mismatch")

    if requirements.requested_operation == "read":
        if intent_plan.output_mode == "write" and not classification.write_authorized:
            violations.append("read_request_escalated_to_write")

    if violations:
        return FileTaskPlanCheck(
            passed=False,
            status="replan",
            summary="规划检查未通过：当前计划与任务要求不匹配，已阻止继续执行。",
            violations=violations,
        )

    return FileTaskPlanCheck(
        passed=True,
        status="pass",
        summary="规划检查通过：当前计划与任务要求匹配。",
        violations=[],
    )


__all__ = [
    "build_file_task_requirements",
    "validate_file_task_plan",
]
