# -*- coding: utf-8 -*-
"""Single source of truth for file-task preflight safety constraints.

Classification decides what the user asked for and completion/quality gates
verify the result after execution.  This module owns the small middle layer:
whether the resolved request, plan and target can safely start execution.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskRequest,
    FileTaskRequirementSet,
)
from app.core.agent.file_task_recipes import (
    explicit_new_artifact_file_type,
    file_type_from_file_info,
)

_OFFICE_TARGET_TYPES = {"docx", "doc", "pptx", "ppt", "xlsx", "xlsm"}


def build_preflight_constraint_audit(
    *,
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    classification: FileTaskClassification,
    intent_plan: FileTaskIntentPlan,
    requirements: FileTaskRequirementSet,
    recipe_skeleton: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate blocking preconditions once, before any tool may run."""
    recipe = dict(recipe_skeleton or {})
    hard: list[str] = ["allowlist_tools_only"]
    soft: list[str] = []
    conflicts: list[str] = []

    recipe_id = str(recipe.get("recipe_id") or "").strip()
    if recipe_id and recipe_id != "generic_file_task":
        hard.append(f"recipe:{recipe_id}")
    if bool(requirements.write_required):
        hard.append("write_requires_file_changed")
    if bool(recipe.get("quality_gates")):
        hard.append("quality_gates_enforced")
    if recipe_id == "financial_xlsx_docx_report":
        hard.append("financial_whitebox_workflow")

    target_type = _target_file_type(requirements, classification)
    creates_new_artifact = _creates_new_artifact_of_type(request.task, target_type)
    if target_type in _OFFICE_TARGET_TYPES:
        hard.append(
            "new_artifact_target_required"
            if creates_new_artifact
            else "explicit_or_unambiguous_target_required"
        )

    if classification.output_mode == "hybrid":
        soft.append("hybrid_mode_default_no_write_without_apply")
    if intent_plan.requires_confirmation:
        soft.append("confirmation_required_before_apply")
    if recipe_id == "generic_file_task":
        soft.append("model_guided_generic_loop")

    if requirements.write_required and classification.output_mode != "write":
        conflicts.append("write_required_output_mode_mismatch")
    if requirements.write_required and intent_plan.write_intent is False:
        conflicts.append("write_required_intent_plan_mismatch")
    if not requirements.write_required and classification.output_mode == "write":
        conflicts.append("readonly_request_escalated_to_write")
    if not requirements.write_required and classification.write_intent:
        conflicts.append("readonly_request_write_intent_mismatch")

    write_target_required = any(
        (
            bool(requirements.write_required),
            bool(classification.write_intent),
            str(classification.output_mode or "").strip().lower() == "write",
            bool(intent_plan.write_intent),
            str(intent_plan.output_mode or "").strip().lower() == "write",
        )
    )
    matching_targets = [
        file_info
        for file_info in files
        if file_type_from_file_info(file_info) == target_type
    ]
    if (
        write_target_required
        and target_type
        and len(matching_targets) > 1
        and not _has_explicit_target(request, files)
        and not creates_new_artifact
    ):
        conflicts.append(f"ambiguous_target:{target_type}")

    return {
        "version": "file_task_constraint_audit_v1",
        "hard_constraints": sorted(set(hard)),
        "soft_constraints": sorted(set(soft)),
        "ignored_deprecated_options": [],
        "conflicts": sorted(set(conflicts)),
        "status": "conflict" if conflicts else "clear",
    }


def _target_file_type(
    requirements: FileTaskRequirementSet,
    classification: FileTaskClassification,
) -> str:
    return str(
        requirements.target_file_type or classification.target_file_type or ""
    ).strip().lower()


def _creates_new_artifact_of_type(task: str, target_type: str) -> bool:
    return explicit_new_artifact_file_type(task) == target_type


def _has_explicit_target(
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
) -> bool:
    return bool(str(request.target_path or "").strip()) or any(
        bool(getattr(file_info, "target", False)) for file_info in files
    )
