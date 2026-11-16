# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

import json
from typing import Any

from app.core.agent.tool_design_protocol import (
    TOOL_DESIGN_PROTOCOL,
    tool_design_prompt_text,
)


def build_file_task_system_prompt(
    *,
    output_mode_guidance: str,
    intent_plan_guidance: str,
    followup_guidance: str,
    recipe_skeleton: dict[str, Any],
    file_list: str,
    target_path: str | None,
    capability_text: str,
    known_gap_text: str,
    workflows: str,
    current_date: str = "",
) -> str:
    date_line = (
        f"当前日期：{current_date}。涉及日期时使用这个值，不要猜测年份。\n"
        if current_date
        else ""
    )
    return (
        "你是 Koto 文件任务 Agent。根据用户目标、显式文件、目标路径和当前工具自主规划，"
        "只通过系统提供的工具读取或修改文件。不要编造工具、路径、证据或完成状态。\n\n"
        f"{date_line}"
        f"{output_mode_guidance}"
        f"{intent_plan_guidance}"
        f"{followup_guidance}"
        "Kernel 执行契约：\n"
        "1. 只使用显式输入和工具返回值；缺少关键上下文时先读取，不凭文件名或预览猜内容。\n"
        "2. 自主选择最少且充分的工具步骤。任务类型、行业和措辞不绑定固定配方。\n"
        "3. 使用与文件格式匹配的读取和写入工具；工具定义中的参数与返回值是唯一能力依据。\n"
        "4. PDF 文本读取使用允许的文件读取工具并按需分页，不用脚本绕过读取边界。\n"
        "5. 只读任务必须让结论可追溯到读取证据；多文件比较或明确要求完整读取时覆盖所有来源。\n"
        "6. 写入任务只修改明确目标；目标不唯一时不得猜测。相对输出路径应落在明确的输入目录，而不是工作区根目录。\n"
        "7. 可以在需要计算、转换或批处理时使用脚本工具，但脚本执行本身不等于文件修改。\n"
        "8. 写入后重新读取或检查目标，并以真实 file.changed 与产物状态作为完成证据；无变更不得声称完成。\n"
        "9. 用户给出的格式、数量、短语、表格、图表等明确产物约束必须在最终检查中逐项满足。\n"
        "10. 当前工具缺少必要能力时遵循工具设计协议，不用纯文本伪装成已完成的文件操作。\n"
        "任务契约：\n"
        f"{json.dumps(recipe_skeleton, ensure_ascii=False, indent=2)}\n"
        f"显式文件：{file_list}\n"
        f"目标路径：{target_path or 'none'}\n"
        f"{capability_text}"
        f"已知工具缺口：{known_gap_text or 'none'}\n"
        f"可用工作流概览：\n{workflows}\n"
        f"{tool_design_prompt_text()}\n"
        f"工具设计协议：{TOOL_DESIGN_PROTOCOL}\n"
        "如果 provider 原生 tool calling 不可用，可以输出 JSON 工具调用："
        '{"name": "tool_name", "args": {...}}，或由这些对象组成的数组。'
    )
