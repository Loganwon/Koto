# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

from typing import Any, Mapping, Sequence

from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskPlanCheck,
    FileTaskRequest,
    FileTaskRequirementSet,
    FileTaskSupervisorAudit,
)

_LOW_CONFIDENCE_THRESHOLD = 0.58


def _clean(value: Any, limit: int = 180) -> str:
    text = str(value or "").strip()
    if limit and len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _risk_level(status: str, warnings: Sequence[str]) -> str:
    if status == "blocked":
        return "high"
    if len(warnings) >= 2:
        return "medium"
    if warnings:
        return "low"
    return "low"


def build_supervisor_audit(
    *,
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    classification: FileTaskClassification,
    intent_plan: FileTaskIntentPlan,
    requirements: FileTaskRequirementSet,
    plan_check: FileTaskPlanCheck,
    constraint_audit: Mapping[str, Any] | None = None,
) -> FileTaskSupervisorAudit:
    warnings: list[str] = []
    required_actions: list[str] = []
    execution_constraints: list[str] = []
    user_actions: list[str] = []
    reason_codes: list[str] = ["supervisor_audit:v1"]
    blocked = False
    constraints = dict(constraint_audit or {})
    conflicts = [
        _clean(item, 160)
        for item in constraints.get("conflicts") or []
        if _clean(item, 160)
    ]

    confidence = float(classification.confidence or intent_plan.confidence or 0.0)
    if confidence < _LOW_CONFIDENCE_THRESHOLD:
        warnings.append("任务识别置信度偏低，执行时需要保守处理。")
        execution_constraints.append("优先读取显式上下文，避免把模糊意图升级为写入。")
        reason_codes.append("low_classification_confidence")

    if not plan_check.passed:
        blocked = True
        warnings.append(plan_check.summary or "计划检查未通过。")
        execution_constraints.append("重新分类或修正执行计划后再继续。")
        reason_codes.extend(
            f"plan_check:{_clean(item, 120)}"
            for item in plan_check.violations
            if _clean(item, 120)
        )

    if conflicts:
        blocked = True
        warnings.append("任务边界存在冲突：" + "；".join(conflicts[:4]))
        user_actions.extend(_user_actions_for_conflicts(conflicts))
        reason_codes.extend(f"constraint_conflict:{item}" for item in conflicts[:6])

    if intent_plan.requires_confirmation:
        warnings.append("当前计划是先分析后应用，写入需单独授权。")
        user_actions.append("确认是否将分析建议应用到文件。")
        execution_constraints.append("先输出分析结论，获得应用授权后再写入。")
        reason_codes.append("confirmation_required")

    if requirements.write_required:
        reason_codes.append("write_supervision_enabled")
    else:
        reason_codes.append("readonly_supervision_enabled")

    status = "blocked" if blocked else ("warning" if warnings else "clear")
    if status == "blocked":
        summary = "监管检查发现高风险冲突，已阻止任务继续执行。"
    elif status == "warning":
        summary = "监管检查发现需要保守处理的风险，任务可继续但会加强核验。"
    else:
        summary = "任务识别、目标和执行边界检查通过。"

    required_actions = list(dict.fromkeys([*execution_constraints, *user_actions]))

    return FileTaskSupervisorAudit(
        status=status,
        risk_level=_risk_level(status, warnings),
        summary=summary,
        confidence=confidence,
        execution_allowed=status != "blocked",
        review_recommended=bool(warnings),
        warnings=list(dict.fromkeys(warnings)),
        required_actions=list(dict.fromkeys(required_actions)),
        execution_constraints=list(dict.fromkeys(execution_constraints)),
        user_actions=list(dict.fromkeys(user_actions)),
        reason_codes=list(dict.fromkeys(reason_codes)),
    )


def _user_actions_for_conflicts(conflicts: Sequence[str]) -> list[str]:
    actions: list[str] = []
    if any(str(item).startswith("ambiguous_target:") for item in conflicts):
        actions.append("指定要修改或生成的目标文件。")
    if any(str(item).startswith("readonly_request_") for item in conflicts):
        actions.append("如需写入，请明确授权修改目标文件。")
    if any(str(item).startswith("write_required_") for item in conflicts):
        actions.append("重新校验写入意图与输出方式后再继续。")
    return actions or ["澄清目标文件、输出方式或允许的写入范围。"]


__all__ = ["build_supervisor_audit"]
