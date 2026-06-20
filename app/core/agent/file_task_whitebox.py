from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskRequest,
)
from app.core.agent.file_task_recipes import select_task_recipe
from app.core.agent.file_task_tool_catalog import is_write_tool, write_target_for_tool
from app.core.agent.tool_design_protocol import extract_first_json_value


def _clean_text(value: Any, limit: int = 0) -> str:
    text = str(value or "").strip()
    if limit and len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _tool_name(definition: Dict[str, Any]) -> str:
    function_payload = definition.get("function") if isinstance(definition.get("function"), dict) else {}
    return str(definition.get("name") or function_payload.get("name") or "").strip()


def _target_type(request: FileTaskRequest, files: Sequence[FileTaskFile]) -> str:
    candidate = Path(str(request.target_path or "")).suffix.lstrip(".").lower().strip()
    if candidate:
        return candidate
    for file_info in files:
        if file_info.target:
            candidate = str(file_info.type or Path(str(file_info.path or file_info.name)).suffix.lstrip(".")).lower().strip()
            if candidate:
                return candidate
    for file_info in files:
        candidate = str(file_info.type or Path(str(file_info.path or file_info.name)).suffix.lstrip(".")).lower().strip()
        if candidate:
            return candidate
    return ""


@dataclass
class WhiteboxExecutionPlan:
    goal: str = ""
    plan_summary: str = ""
    steps: List[Dict[str, Any]] = field(default_factory=list)
    completion_check: Dict[str, Any] = field(default_factory=dict)
    risks: List[str] = field(default_factory=list)
    source: str = "model"

    def public_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "goal": self.goal,
            "plan_summary": self.plan_summary,
            "steps": [dict(step) for step in self.steps if isinstance(step, dict)],
            "completion_check": dict(self.completion_check or {}),
            "source": self.source,
        }
        if self.risks:
            payload["risks"] = [str(item) for item in self.risks if str(item or "").strip()]
        return payload

    def why_for_tool(self, tool_name: str) -> str:
        target = str(tool_name or "").strip()
        if not target:
            return ""
        for step in self.steps:
            if not isinstance(step, dict):
                continue
            candidate = str(step.get("tool") or step.get("tool_name") or "").strip()
            if candidate == target:
                return _clean_text(step.get("why"), 600)
        return ""


def whitebox_execution_plan_schema() -> Dict[str, Any]:
    return {
        "execution_plan": {
            "goal": "本轮要完成的可验证目标",
            "plan_summary": "一句话说明执行路线",
            "steps": [
                {
                    "id": "inspect",
                    "title": "步骤标题",
                    "tool": "tool_name 或空字符串",
                    "required": True,
                    "why": "为什么需要这一步",
                    "expected_result": "这一步完成后应观察到什么",
                    "args_strategy": "参数如何从上下文或前一步结果中确定",
                }
            ],
            "completion_check": {
                "must_have_file_change": True,
                "required_operations": ["write_docx_content"],
                "quality_gates": ["paragraphs_written >= 1"],
            },
            "risks": ["可能失败或需要用户介入的点"],
        }
    }


def build_recipe_skeleton(
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    classification: FileTaskClassification,
    intent_plan: FileTaskIntentPlan,
    tool_defs: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    write_intent = bool(classification.write_intent)
    recipe_match = select_task_recipe(request, files, write_intent=write_intent)
    allowed_tools = [_tool_name(definition) for definition in tool_defs]
    allowed_tools = [name for name in allowed_tools if name]
    target_file_type = str(classification.target_file_type or "").strip().lower() or _target_type(request, files)

    required_steps: List[Dict[str, Any]] = []
    success_criteria: List[str] = []
    quality_gates: List[Dict[str, Any]] = []
    required_tools: List[str] = []
    recipe_id = ""
    task_family = str(classification.task_family or intent_plan.intent_type or "analyze").strip() or "analyze"
    operation_kind = str(classification.operation_kind or "read").strip() or "read"

    if recipe_match:
        recipe = recipe_match.recipe
        recipe_id = recipe.id
        task_family = recipe.task_family or task_family
        operation_kind = recipe.write_operation_kind if write_intent else recipe.read_operation_kind
        required_steps = [dict(step) for step in recipe.plan_steps if isinstance(step, dict)]
        success_criteria = [str(item) for item in recipe.success_criteria if str(item or "").strip()]
        quality_gates = [dict(item) for item in recipe.quality_gates if isinstance(item, dict)]
        required_tools = [str(item) for item in recipe.matched_capabilities if str(item or "").strip()]
    elif intent_plan.dynamic_steps:
        required_steps = [dict(step) for step in intent_plan.dynamic_steps if isinstance(step, dict)]

    if write_intent and not success_criteria:
        success_criteria = ["必须产生真实 file.changed 事件"]

    return {
        "version": "whitebox_workflow_v2",
        "recipe_id": recipe_id or "generic_file_task",
        "task_family": task_family,
        "operation_kind": operation_kind,
        "output_mode": str(classification.output_mode or "answer").strip().lower() or "answer",
        "write_intent": write_intent,
        "target_file_type": target_file_type,
        "required_steps": required_steps,
        "required_tools": required_tools,
        "allowed_tools": allowed_tools,
        "success_criteria": success_criteria,
        "quality_gates": quality_gates,
        "completion_check": {
            "must_have_file_change": write_intent,
            "required_operations": _required_operations(required_tools, quality_gates, write_intent),
        },
        "model_freedom": "constrained_fill_and_execute" if str(request.model_mode or "").lower() == "local" else "constrained_plan_and_execute",
    }


def _required_operations(required_tools: Sequence[str], quality_gates: Sequence[Dict[str, Any]], write_intent: bool) -> List[str]:
    operations: List[str] = []
    for tool in required_tools:
        if is_write_tool(str(tool)) and str(tool) not in operations:
            operations.append(str(tool))
    for gate in quality_gates:
        operation = str(gate.get("operation") or "").strip()
        if operation and operation not in operations:
            operations.append(operation)
        for item in gate.get("any_operation") or []:
            text = str(item or "").strip()
            if text and text not in operations:
                operations.append(text)
    if write_intent and not operations:
        operations.append("file.changed")
    return operations


def extract_whitebox_execution_plan(response: Any, content_text: str = "") -> Optional[WhiteboxExecutionPlan]:
    candidate: Any = None
    if isinstance(response, dict):
        if isinstance(response.get("execution_plan"), dict):
            candidate = response.get("execution_plan")
        elif isinstance(response.get("plan"), dict):
            candidate = response.get("plan")
        elif content_text:
            candidate = extract_first_json_value(content_text)
    elif content_text:
        candidate = extract_first_json_value(content_text)

    if isinstance(candidate, dict) and isinstance(candidate.get("execution_plan"), dict):
        candidate = candidate.get("execution_plan")
    if not isinstance(candidate, dict):
        return None

    raw_steps = candidate.get("steps") or []
    steps: List[Dict[str, Any]] = []
    if isinstance(raw_steps, list):
        for index, item in enumerate(raw_steps[:12], start=1):
            if not isinstance(item, dict):
                continue
            step = {
                "id": _clean_text(item.get("id") or f"step_{index}", 80),
                "title": _clean_text(item.get("title") or item.get("name") or item.get("step"), 160),
                "tool": _clean_text(item.get("tool") or item.get("tool_name"), 120),
                "required": bool(item.get("required", True)),
                "why": _clean_text(item.get("why") or item.get("reason"), 600),
                "expected_result": _clean_text(item.get("expected_result") or item.get("expected"), 500),
                "args_strategy": _clean_text(item.get("args_strategy") or item.get("args"), 500),
            }
            steps.append({key: value for key, value in step.items() if value not in ("", None)})

    plan = WhiteboxExecutionPlan(
        goal=_clean_text(candidate.get("goal") or candidate.get("objective"), 800),
        plan_summary=_clean_text(candidate.get("plan_summary") or candidate.get("summary"), 800),
        steps=steps,
        completion_check=dict(candidate.get("completion_check") or {}) if isinstance(candidate.get("completion_check"), dict) else {},
        risks=[_clean_text(item, 240) for item in (candidate.get("risks") or []) if _clean_text(item, 240)]
        if isinstance(candidate.get("risks"), list)
        else [],
    )
    if not any((plan.goal, plan.plan_summary, plan.steps, plan.completion_check, plan.risks)):
        return None
    return plan


def validate_whitebox_plan(
    plan: Optional[WhiteboxExecutionPlan],
    skeleton: Dict[str, Any],
    *,
    tool_calls: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    violations: List[str] = []
    warnings: List[str] = []
    allowed = {str(item) for item in skeleton.get("allowed_tools") or [] if str(item)}
    write_intent = bool(skeleton.get("write_intent"))

    if plan is None:
        warnings.append("model_execution_plan_missing")
    else:
        if not plan.goal:
            warnings.append("execution_plan_goal_missing")
        if not plan.steps:
            warnings.append("execution_plan_steps_missing")
        plan_tools = {
            str(step.get("tool") or step.get("tool_name") or "").strip()
            for step in plan.steps
            if isinstance(step, dict)
            and str(step.get("tool") or step.get("tool_name") or "").strip()
        }
        plan_stage_text = " ".join(
            str(step.get("stage") or step.get("title") or step.get("id") or "")
            for step in plan.steps
            if isinstance(step, dict)
        ).lower()
        for index, step in enumerate(plan.steps, start=1):
            tool = str(step.get("tool") or "").strip()
            if tool and allowed and tool not in allowed:
                violations.append(f"plan_step_{index}_tool_not_allowed:{tool}")
            if not str(step.get("why") or "").strip():
                warnings.append(f"plan_step_{index}_why_missing")
        for index, required_step in enumerate(
            skeleton.get("required_steps") or [], start=1
        ):
            if not isinstance(required_step, dict):
                continue
            if required_step.get("required") is False:
                continue
            required_tool = str(
                required_step.get("tool") or required_step.get("tool_name") or ""
            ).strip()
            required_stage = str(required_step.get("stage") or "").strip().lower()
            required_id = str(required_step.get("id") or "").strip()
            if required_tool and required_tool not in plan_tools:
                warnings.append(f"required_step_{index}_tool_missing:{required_tool}")
            elif required_stage and required_stage not in plan_stage_text:
                warnings.append(f"required_step_{index}_stage_missing:{required_stage}")
            elif required_id and required_id.lower() not in plan_stage_text:
                warnings.append(f"required_step_{index}_id_not_visible:{required_id}")

    calls = list(tool_calls or [])
    for index, call in enumerate(calls, start=1):
        tool_name = str(call.get("name") or "").strip()
        if tool_name and allowed and tool_name not in allowed:
            violations.append(f"tool_call_{index}_not_allowed:{tool_name}")
    if write_intent and calls:
        has_write_or_code = any(is_write_tool(str(call.get("name") or "")) for call in calls)
        if not has_write_or_code:
            warnings.append("write_task_current_tool_batch_has_no_write_tool")

    return {
        "passed": not violations,
        "status": "pass" if not violations else "blocked",
        "summary": "白盒计划审查通过。" if not violations else "白盒计划审查发现阻断问题。",
        "violations": violations,
        "warnings": warnings,
    }


def build_decision_audit(
    *,
    request: FileTaskRequest,
    skeleton: Dict[str, Any],
    tool_name: str,
    tool_args: Dict[str, Any],
    round_index: int,
    tool_index: int,
    execution_plan: Optional[WhiteboxExecutionPlan] = None,
) -> Dict[str, Any]:
    target = write_target_for_tool(tool_name, tool_args) if is_write_tool(tool_name) else ""
    why = execution_plan.why_for_tool(tool_name) if execution_plan else ""
    if not why:
        if is_write_tool(tool_name):
            why = "当前任务需要真实写入，且该工具属于 recipe/allowlist 中的写入能力。"
        else:
            why = "当前步骤需要先读取、检查或生成中间结果，供后续可验证执行使用。"
    evidence = [
        f"recipe={skeleton.get('recipe_id') or 'generic_file_task'}",
        f"write_intent={bool(skeleton.get('write_intent'))}",
        f"output_mode={skeleton.get('output_mode') or 'answer'}",
    ]
    if target:
        evidence.append(f"target={target}")
    return {
        "decision": f"调用 {tool_name}",
        "why": why,
        "evidence": evidence,
        "alternatives_rejected": _alternatives_rejected(request, skeleton, tool_name),
        "audited_tool_name": tool_name,
        "tool_args_preview": _tool_args_preview(tool_args),
        "round": round_index,
        "tool_index": tool_index,
    }


def _alternatives_rejected(request: FileTaskRequest, skeleton: Dict[str, Any], tool_name: str) -> List[str]:
    rejected: List[str] = []
    if bool(skeleton.get("write_intent")) and is_write_tool(tool_name):
        rejected.append("只返回文本：不满足写入型任务的真实落盘要求")
    if bool(skeleton.get("write_intent")) and not is_write_tool(tool_name):
        rejected.append("直接结束：尚未满足写入型任务的完成检查")
    if str(skeleton.get("target_file_type") or "").lower() in {"docx", "doc"} and tool_name == "run_python_code":
        rejected.append("用脚本文本替代 Office 专用写入：不满足格式感知工作流")
    if not rejected:
        rejected.append("跳过该步骤：会降低后续完成检查的可验证性")
    return rejected[:4]


def _tool_args_preview(tool_args: Dict[str, Any]) -> Dict[str, Any]:
    preview: Dict[str, Any] = {}
    for key, value in dict(tool_args or {}).items():
        if key.lower() in {"content", "paragraphs", "code", "text"}:
            preview[key] = _clean_text(value, 240)
        else:
            preview[key] = value
    try:
        json.dumps(preview, ensure_ascii=False, default=str)
    except Exception:
        return {"preview": _clean_text(preview, 500)}
    return preview


__all__ = [
    "WhiteboxExecutionPlan",
    "build_decision_audit",
    "build_recipe_skeleton",
    "extract_whitebox_execution_plan",
    "validate_whitebox_plan",
    "whitebox_execution_plan_schema",
]
