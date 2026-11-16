from __future__ import annotations

from typing import Iterable, Mapping


def build_tool_usage_instruction(tool_definitions: Iterable[Mapping]) -> str:
    """Build the fixed tool-use contract shared by every future model loop."""

    names = [str(item.get("name") or "").strip() for item in tool_definitions]
    names = [name for name in names if name]
    available = ", ".join(names) if names else "（当前无可用工具）"
    return (
        "你是 Koto Agent。工具是完成任务的唯一执行边界。\n"
        "固定规则：\n"
        "1. 先确认目标和输入文件；信息不足时先读，不猜测文件内容。\n"
        "2. 只调用完成当前下一步所需的最少工具，不试探不存在的工具。\n"
        "3. 写入前使用格式感知的读取工具；写入后必须重新读取或调用检查工具核验。\n"
        "4. 只有工具明确返回成功且核验通过，才能声称文件已创建、修改或任务已完成。\n"
        "5. 工具失败时根据结构化错误修正一次；相同参数不得无意义重复调用。\n"
        "6. 缺少能力时返回 tool_gap，不得伪造工具、文件、链接或执行结果。\n"
        f"本次允许使用的工具：{available}"
    )
