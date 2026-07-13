"""Pure user/model-facing messages used by the file-task execution runtime."""

from __future__ import annotations

from typing import Any

from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskExecutionBrief,
    FileTaskIntentPlan,
    FileTaskRequest,
)
from app.core.agent.file_task_whitebox import WhiteboxExecutionPlan


def output_mode_label(output_mode: str) -> str:
    normalized = str(output_mode or "").strip().lower()
    if normalized == "write":
        return "写入文件"
    if normalized == "hybrid":
        return "先分析后决定"
    return "只给答案"


def output_mode_guidance(classification: FileTaskClassification) -> str:
    output_mode = str(classification.output_mode or "answer").strip().lower()
    label = output_mode_label(output_mode)
    if output_mode == "write":
        return (
            f"当前任务反馈模式：{label}。\n"
            "本轮目标是完成真实文件修改；除非进入等待确认状态，否则不要只给建议或总结就结束。\n"
            "如果没有产生真实 file.changed，就不能把任务说成已完成。\n"
            "任务全部完成后，用三部分简短汇报（不要写\"总结与回答\"这类大标题，不要重复前面的步骤日志）：\n"
            "① 核心结果：1-2句话说明完成了什么。\n"
            "② 产出清单，每条一行：- 文件名：描述（如\"- chart1.png：收入趋势\"；\"- xxx.docx：已写入N段分析、插入M张图表\"）。\n"
            "③ 发现的问题，每条一行：- 问题描述（简明扼要，不超过两行）。\n"
            "各部分之间空一行即可，不要加\"总结与回答\"\"任务完成\"\"执行过程\"等冗余标题。\n"
        )
    if output_mode == "hybrid":
        return (
            f"当前任务反馈模式：{label}。\n"
            "本轮先基于显式上下文给出分析、问题清单、修改方向或可应用方案。\n"
            "除非用户这轮已经明确要求直接应用到文件，否则不要直接调用写入工具，也不要声称文件已经更新。\n"
            "如果需要后续落盘，应先把建议说清楚，再等待用户继续要求应用。\n"
        )
    return (
        f"当前任务反馈模式：{label}。\n"
        "本轮默认只返回分析、总结、解释或结论。\n"
        "不要调用写入工具，不要伪造 file.changed，也不要把结果描述成已经写入文件。\n"
        "只有当用户明确要求把结果写入文件时，才改走写回路径。\n"
    )


def intent_plan_guidance(intent_plan: FileTaskIntentPlan) -> str:
    lines = ["高阶意图规划："]
    goal_statement = str(intent_plan.goal_statement or "").strip()
    if goal_statement:
        lines.append(f"- 目标：{goal_statement}")
    lines.append(
        f"- 策略：{str(intent_plan.recommended_strategy or 'answer_only').strip() or 'answer_only'}"
    )
    lines.append(f"- 可应用：{'是' if intent_plan.can_apply else '否'}")
    lines.append(f"- 当前轮会暂停等待确认：{'是' if intent_plan.requires_confirmation else '否'}")
    if intent_plan.dynamic_steps:
        lines.append("- 计划步骤：")
        for index, step in enumerate(intent_plan.dynamic_steps[:8], start=1):
            if not isinstance(step, dict):
                continue
            title = str(step.get("title") or step.get("id") or f"步骤 {index}").strip()
            description = str(step.get("description") or "").strip()
            lines.append(f"  {index}. {title}" + (f"：{description}" if description else ""))
    if intent_plan.write_intent:
        lines.append(
            "- 监管约束：写入型任务必须产生真实 file.changed；分步确认任务必须先完成本步骤写入，再进入等待用户继续。"
        )
    return "\n".join(lines) + "\n"


def execution_brief_continue_message(
    request: FileTaskRequest,
    brief: FileTaskExecutionBrief,
) -> str:
    summary = brief.summary or brief.objective or "已完成任务分析。"
    lines = [
        f"已收到 execution_brief：{summary}",
        "下一轮请在白盒任务骨架内直接调用需要的 Koto 工具继续执行，不要重复输出同一份 brief。",
    ]
    if request.target_path:
        lines.append(f"当前目标文件是：{request.target_path}。")
    return " ".join(lines)


def execution_plan_continue_message(
    request: FileTaskRequest,
    execution_plan: WhiteboxExecutionPlan,
    recipe_skeleton: dict[str, Any],
) -> str:
    summary = execution_plan.plan_summary or execution_plan.goal or "已完成白盒执行计划。"
    lines = [
        f"已收到 execution_plan：{summary}",
        "现在请按该计划继续调用 Koto allowlist 工具执行；不要重复输出计划，也不要跳过必需写入/核验步骤。",
    ]
    completion_check = recipe_skeleton.get("completion_check")
    required_operations = (
        completion_check.get("required_operations")
        if isinstance(completion_check, dict)
        else []
    )
    if required_operations:
        lines.append(
            "完成检查要求包含："
            + "、".join(str(item) for item in required_operations if str(item or "").strip())
        )
    if request.target_path:
        lines.append(f"目标文件：{request.target_path}。")
    return " ".join(lines)


def whitebox_plan_repair_message(
    gate_payload: dict[str, Any],
    recipe_skeleton: dict[str, Any],
) -> str:
    lines = [
        "白盒计划审查未通过或不完整，请修复计划后继续执行。",
        "必须遵守 recipe_skeleton 的 required_steps、allowed_tools、success_criteria 和 completion_check。",
    ]
    violations = gate_payload.get("violations")
    warnings = gate_payload.get("warnings")
    if isinstance(violations, list) and violations:
        lines.append("阻断问题：" + "；".join(str(item) for item in violations[:6]))
    if isinstance(warnings, list) and warnings:
        lines.append("需要补强：" + "；".join(str(item) for item in warnings[:6]))
    allowed_tools = recipe_skeleton.get("allowed_tools")
    if isinstance(allowed_tools, list) and allowed_tools:
        lines.append(
            "只能调用这些工具："
            + "、".join(str(item) for item in allowed_tools[:30] if str(item or "").strip())
        )
    return "\n".join(lines)
