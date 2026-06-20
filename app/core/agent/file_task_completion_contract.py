# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Sequence

from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskCompletionContract,
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskRequirementSet,
    FileTaskRequest,
)


def build_completion_contract(
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    classification: FileTaskClassification,
    intent_plan: FileTaskIntentPlan,
    requirements: FileTaskRequirementSet,
    recipe_skeleton: Dict[str, Any],
) -> FileTaskCompletionContract:
    target_file_type = _target_file_type(request, files, classification, requirements)
    required_operations = _unique_strings(
        [
            *(recipe_skeleton.get("completion_check") or {}).get(
                "required_operations", []
            ),
            *_operations_from_quality_gates(recipe_skeleton.get("quality_gates") or []),
        ]
    )
    complexity = _complexity(request, files, recipe_skeleton)
    decomposition_strategy = _decomposition_strategy(
        request,
        files,
        recipe_skeleton,
        complexity=complexity,
    )
    contract_id = str(recipe_skeleton.get("recipe_id") or "").strip()
    if not contract_id:
        contract_id = classification.selected_recipe or "generic_file_task"

    acceptance_criteria = _unique_strings(
        [
            *requirements.acceptance_criteria,
            *[
                str(item)
                for item in recipe_skeleton.get("success_criteria") or []
                if str(item or "").strip()
            ],
        ]
    )
    if classification.output_mode == "hybrid":
        acceptance_criteria.append("先给出分析建议，未获确认前不默认写回原文件")
    if not bool(requirements.write_required):
        acceptance_criteria.append("只读任务必须说明使用的显式上下文来源")

    return FileTaskCompletionContract(
        contract_id=contract_id,
        objective=str(request.task or "").strip()[:800],
        decomposition_strategy=decomposition_strategy,
        complexity=complexity,
        write_required=bool(requirements.write_required),
        output_mode=str(classification.output_mode or "answer").strip() or "answer",
        target_path=str(requirements.target_path or request.target_path or "").strip(),
        target_file_type=target_file_type,
        required_operations=required_operations,
        required_capabilities=_unique_strings(requirements.required_capabilities),
        forbidden_capabilities=_unique_strings(requirements.forbidden_capabilities),
        acceptance_criteria=_unique_strings(acceptance_criteria),
        quality_gates=[
            dict(item)
            for item in recipe_skeleton.get("quality_gates") or []
            if isinstance(item, dict)
        ],
        checkpoints=_checkpoints(
            write_required=bool(requirements.write_required),
            decomposition_strategy=decomposition_strategy,
            required_operations=required_operations,
        ),
        repair_policy=(
            "repair_write_or_quality_failures"
            if bool(requirements.write_required)
            else "surface_read_context_gaps"
        ),
        reason_codes=_unique_strings(
            [
                "completion_contract:v1",
                f"contract:{contract_id}",
                f"complexity:{complexity}",
                f"decomposition:{decomposition_strategy}",
                *requirements.reason_codes,
            ]
        ),
    )


def _target_file_type(
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    classification: FileTaskClassification,
    requirements: FileTaskRequirementSet,
) -> str:
    for value in (
        requirements.target_file_type,
        classification.target_file_type,
        Path(str(request.target_path or "")).suffix.lstrip("."),
    ):
        candidate = str(value or "").strip().lower()
        if candidate:
            return candidate
    for file_info in files:
        if not file_info.target:
            continue
        candidate = str(
            file_info.type
            or Path(str(file_info.path or file_info.name)).suffix.lstrip(".")
        ).strip().lower()
        if candidate:
            return candidate
    return ""


def _operations_from_quality_gates(quality_gates: Sequence[Dict[str, Any]]) -> List[str]:
    operations: List[str] = []
    for gate in quality_gates:
        if not isinstance(gate, dict):
            continue
        operation = str(gate.get("operation") or "").strip()
        if operation:
            operations.append(operation)
        for item in gate.get("any_operation") or []:
            text = str(item or "").strip()
            if text:
                operations.append(text)
    return operations


def _complexity(
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    recipe_skeleton: Dict[str, Any],
) -> str:
    required_steps = [
        item for item in recipe_skeleton.get("required_steps") or [] if isinstance(item, dict)
    ]
    has_windows = bool(
        str(request.options.get("workflow_checkpoint") or "").strip()
        if isinstance(request.options, dict)
        else False
    )
    task_text = str(request.task or "")
    if has_windows or any(
        marker in task_text
        for marker in ("分步", "每一步", "继续", "stepwise", "confirmation")
    ):
        return "stepwise"
    if len(files) >= 2 or len(required_steps) >= 4:
        return "complex"
    if recipe_skeleton.get("quality_gates"):
        return "guarded"
    return "simple"


def _decomposition_strategy(
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    recipe_skeleton: Dict[str, Any],
    *,
    complexity: str,
) -> str:
    file_types = {
        str(file_info.type or Path(str(file_info.path or file_info.name)).suffix.lstrip("."))
        .strip()
        .lower()
        for file_info in files
    }
    if complexity == "stepwise":
        if "pdf" in file_types:
            return "windowed_source_to_target"
        return "confirm_each_step"
    if len(files) >= 2:
        return "multi_source_plan_then_execute"
    if recipe_skeleton.get("quality_gates"):
        return "recipe_gated_execute_verify"
    return "single_pass_execute_verify"


def _checkpoints(
    *,
    write_required: bool,
    decomposition_strategy: str,
    required_operations: Sequence[str],
) -> List[Dict[str, Any]]:
    checkpoints: List[Dict[str, Any]] = [
        {
            "id": "classify_and_contract",
            "required": True,
            "must_observe": ["task.classified", "plan.checked"],
        },
        {
            "id": "read_explicit_context",
            "required": True,
            "must_observe": ["context.loaded"],
        },
    ]
    if write_required:
        checkpoints.append(
            {
                "id": "write_output",
                "required": True,
                "must_observe": ["file.changed"],
                "required_operations": list(required_operations),
            }
        )
    checkpoints.append(
        {
            "id": "verify_outputs",
            "required": True,
            "must_observe": ["check.finished"],
        }
    )
    if decomposition_strategy in {"windowed_source_to_target", "confirm_each_step"}:
        checkpoints.append(
            {
                "id": "resume_or_complete",
                "required": True,
                "must_observe": ["next_action_artifact", "run.finished"],
            }
        )
    return checkpoints


def _unique_strings(values: Sequence[Any]) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


__all__ = ["build_completion_contract"]
