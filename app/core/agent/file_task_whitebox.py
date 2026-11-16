from __future__ import annotations

import json
from typing import Any, Dict, List, Sequence

from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskRequest,
)
from app.core.agent.file_task_file_facts import request_target_file_type
from app.core.agent.toolkits.foundation.catalog import is_write_tool


def _clean_text(value: Any, limit: int = 0) -> str:
    text = str(value or "").strip()
    if limit and len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _tool_name(definition: Dict[str, Any]) -> str:
    function_payload = (
        definition.get("function")
        if isinstance(definition.get("function"), dict)
        else {}
    )
    return str(definition.get("name") or function_payload.get("name") or "").strip()


def _target_type(request: FileTaskRequest, files: Sequence[FileTaskFile]) -> str:
    return request_target_file_type(request, files)


def build_recipe_skeleton(
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    classification: FileTaskClassification,
    intent_plan: FileTaskIntentPlan,
    tool_defs: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    write_authorized = bool(classification.write_authorized)
    write_required = bool(classification.write_required)
    allowed_tools = [_tool_name(definition) for definition in tool_defs]
    allowed_tools = [name for name in allowed_tools if name]
    target_file_type = str(
        classification.target_file_type or ""
    ).strip().lower() or _target_type(request, files)

    required_steps: List[Dict[str, Any]] = []
    success_criteria: List[str] = []
    quality_gates: List[Dict[str, Any]] = []
    required_tools: List[str] = []
    task_family = (
        str(classification.task_family or intent_plan.intent_type or "analyze").strip()
        or "analyze"
    )
    operation_kind = str(classification.operation_kind or "read").strip() or "read"

    if intent_plan.dynamic_steps:
        required_steps = [
            dict(step) for step in intent_plan.dynamic_steps if isinstance(step, dict)
        ]

    if write_required and not success_criteria:
        success_criteria = ["必须产生真实 file.changed 事件"]

    return {
        "version": "whitebox_workflow_v2",
        "recipe_id": "kernel_generic_file_task",
        "task_family": task_family,
        "operation_kind": operation_kind,
        "output_mode": str(classification.output_mode or "answer").strip().lower()
        or "answer",
        "write_authorized": write_authorized,
        "write_required": write_required,
        "target_file_type": target_file_type,
        "required_steps": required_steps,
        "required_tools": required_tools,
        "allowed_tools": allowed_tools,
        "success_criteria": success_criteria,
        "quality_gates": quality_gates,
        "completion_check": {
            "must_have_file_change": write_required,
            "required_operations": _required_operations(
                required_tools, quality_gates, write_required
            ),
        },
        "model_freedom": (
            "constrained_fill_and_execute"
            if str(request.model_mode or "").lower() == "local"
            else "constrained_plan_and_execute"
        ),
    }


def _required_operations(
    required_tools: Sequence[str],
    quality_gates: Sequence[Dict[str, Any]],
    write_intent: bool,
) -> List[str]:
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


def _alternatives_rejected(
    request: FileTaskRequest, skeleton: Dict[str, Any], tool_name: str
) -> List[str]:
    rejected: List[str] = []
    if bool(skeleton.get("write_required")) and is_write_tool(tool_name):
        rejected.append("只返回文本：不满足写入型任务的真实落盘要求")
    if bool(skeleton.get("write_required")) and not is_write_tool(tool_name):
        rejected.append("直接结束：尚未满足写入型任务的完成检查")
    if (
        str(skeleton.get("target_file_type") or "").lower() in {"docx", "doc"}
        and tool_name == "run_python_code"
    ):
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
    "build_recipe_skeleton",
]
