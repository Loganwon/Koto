# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

from typing import Any


def followup_guidance(followup_context: dict[str, Any]) -> str:
    if str(followup_context.get("kind") or "").strip() != "review_last_task":
        return ""
    followup_action = str(followup_context.get("followup_action") or "").strip().lower()
    if followup_action == "apply":
        return (
            "当前输入是用户要求把上一轮文件任务中的建议直接应用到文件。这不是一个无关的新任务，而是同一任务的写回续跑。\n"
            "优先沿用上一轮的目标文件、分析建议、文件变更和约束；必要时只补充最少量上下文后直接执行写入。\n"
            "如果上一轮已经给出可应用建议，这一轮应进入真实写回路径并产生 file.changed；不要只重复建议文本。\n"
        )
    if followup_action == "improve":
        guidance = (
            "当前输入是用户要求围绕上一轮文件任务结果继续优化。这不是一个无关的新任务，而是同一任务的后续回合。\n"
            "先解释上一轮结果的不足和这次准备如何改进；如果确实需要，可以继续调用工具修正目标文件。"
            "优先沿用上一轮的目标、目标文件、失败点和约束，不要把上下文重置成新的独立任务。\n"
        )
        return guidance
    return (
        "当前输入是用户对上一轮文件任务结果的反馈或质问，不要默认把它当作全新的执行任务。\n"
        "先解释上一轮结果、指出可能的问题，并回答用户的追问。"
        "只有当用户明确要求重新修改文件、继续执行或调用工具时，才进入新的工具执行。"
        "如果当前只是反馈上一轮结果，不要调用写入工具，也不要伪造新的完成状态。\n"
    )


def followup_prompt_prefix(followup_context: dict[str, Any]) -> str:
    if str(followup_context.get("kind") or "").strip() != "review_last_task":
        return "请完成这个文件任务。"
    followup_action = str(followup_context.get("followup_action") or "").strip().lower()
    if followup_action == "apply":
        return (
            "用户要求把上一轮文件任务中已经给出的建议直接应用到目标文件。"
            "请把它视为同一任务的写回续跑，优先沿用上一轮建议、目标文件和已知约束，不要重新从头分析。"
        )
    if followup_action == "improve":
        prefix = (
            "用户要求在上一轮文件任务结果基础上继续优化。"
            "请把它视为同一任务的后续处理回合，先说明你准备如何改进，再继续处理。"
        )
        return prefix
    return (
        "用户正在对上一轮文件任务结果提出反馈。"
        "请先回答上一轮结果为什么会这样、哪里可能有问题，以及是否需要重做。"
        "除非用户已经明确提出新的文件修改要求，否则不要把这条消息当成新的文件执行任务。"
    )
