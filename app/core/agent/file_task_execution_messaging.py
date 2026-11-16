"""Pure user/model-facing messages used by the file-task execution runtime."""

from __future__ import annotations

from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskIntentPlan,
    FileTaskRequest,
)


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
            '任务全部完成后，用三部分简短汇报（不要写"总结与回答"这类大标题，不要重复前面的步骤日志）：\n'
            "① 核心结果：1-2句话说明完成了什么。\n"
            '② 产出清单，每条一行：- 文件名：描述（如"- chart1.png：收入趋势"；"- xxx.docx：已写入N段分析、插入M张图表"）。\n'
            "③ 发现的问题，每条一行：- 问题描述（简明扼要，不超过两行）。\n"
            '各部分之间空一行即可，不要加"总结与回答""任务完成""执行过程"等冗余标题。\n'
        )
    if output_mode == "hybrid":
        return (
            f"当前任务反馈模式：{label}。\n"
            "本轮先基于显式上下文给出分析、问题清单、修改方向或可应用方案。\n"
            "目标和依据明确、写入有助于完成用户目标时，可以按需调用写入工具；也可以只返回分析。\n"
            "文件变更不是本模式的完成条件；如果选择写入，必须以真实 file.changed 为依据，不能声称未发生的更新。\n"
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
    lines.append(
        f"- 当前轮会暂停等待确认：{'是' if intent_plan.requires_confirmation else '否'}"
    )
    if intent_plan.dynamic_steps:
        lines.append("- 计划步骤：")
        for index, step in enumerate(intent_plan.dynamic_steps[:8], start=1):
            if not isinstance(step, dict):
                continue
            title = str(step.get("title") or step.get("id") or f"步骤 {index}").strip()
            description = str(step.get("description") or "").strip()
            lines.append(
                f"  {index}. {title}" + (f"：{description}" if description else "")
            )
    if intent_plan.write_required:
        lines.append(
            "- 监管约束：写入型任务必须产生真实 file.changed；分步确认任务必须先完成本步骤写入，再进入等待用户继续。"
        )
    elif intent_plan.write_authorized:
        lines.append(
            "- 写入权限：模型可以按用户本轮明确要求调用写工具，但文件变更不是预设完成条件。"
        )
    return "\n".join(lines) + "\n"
