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
from app.core.agent.file_task_doc_annotate_boundary import (
    looks_like_docx_review_clear_request,
)
from app.core.agent.file_task_recipes import select_task_recipe


def _target_file_type(request: FileTaskRequest, classification: FileTaskClassification) -> str:
    file_type = str(classification.target_file_type or "").strip().lower()
    if file_type:
        return file_type
    if request.target_path:
        suffix = Path(str(request.target_path)).suffix.lstrip(".").lower().strip()
        if suffix:
            return suffix
    for file_info in request.files:
        candidate = str(file_info.type or Path(str(file_info.path or file_info.name)).suffix.lstrip(".")).strip().lower()
        if candidate:
            return candidate
    return ""


def build_file_task_requirements(
    request: FileTaskRequest,
    classification: FileTaskClassification,
) -> FileTaskRequirementSet:
    target_file_type = _target_file_type(request, classification)
    requested_operation = str(classification.operation_kind or "read").strip().lower() or "read"
    write_required = bool(classification.write_intent)
    required_capabilities: List[str] = []
    forbidden_capabilities: List[str] = []
    acceptance_criteria: List[str] = []
    reason_codes: List[str] = []

    if looks_like_docx_review_clear_request(request.task):
        requested_operation = "clear_review"
        write_required = True
        required_capabilities.append("clear_docx_review_marks")
        forbidden_capabilities.append("annotate_file")
        acceptance_criteria.extend([
            "不得新增批注或标注",
            "应清理目标 DOCX 中现有的批注或审阅痕迹",
        ])
        reason_codes.append("clear_review_request")
    elif classification.docx_annotation_request:
        requested_operation = "annotate"
        write_required = True
        required_capabilities.append("annotate_file")
        acceptance_criteria.append("应在目标文件中新增批注或审校意见")
        reason_codes.append("annotation_request")
    elif write_required:
        recipe_match = select_task_recipe(request, request.files or [], write_intent=True)
        if recipe_match:
            requested_operation = recipe_match.recipe.write_operation_kind or requested_operation
            required_capabilities.extend(
                capability
                for capability in recipe_match.recipe.matched_capabilities
                if capability and capability not in required_capabilities
            )
            acceptance_criteria.extend(str(item) for item in recipe_match.recipe.success_criteria if str(item or "").strip())
            reason_codes.append(f"recipe:{recipe_match.recipe.id}")
        if not acceptance_criteria:
            acceptance_criteria.append("必须产生真实文件变更")
        reason_codes.append("write_intent")
    else:
        acceptance_criteria.append("不应误触发写入工具")
        reason_codes.append("read_only_request")

    return FileTaskRequirementSet(
        requested_operation=requested_operation,
        target_path=str(request.target_path or "").strip(),
        target_file_type=target_file_type,
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

    if requirements.write_required and intent_plan.write_intent is False:
        violations.append("write_required_but_plan_not_write")
    if requirements.write_required and intent_plan.output_mode != "write":
        violations.append("write_required_but_output_not_write")

    if requirements.requested_operation == "clear_review":
        if classification.docx_annotation_request:
            violations.append("clear_review_misclassified_as_annotation")
        if "annotate_file" in classification.matched_capabilities:
            violations.append("clear_review_allows_annotate_file")
    elif requirements.requested_operation == "annotate":
        if not classification.docx_annotation_request:
            violations.append("annotation_request_not_classified_as_annotation")
    elif requirements.requested_operation == "read":
        if intent_plan.output_mode == "write" and not classification.write_intent:
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
