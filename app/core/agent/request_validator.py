"""Prompt and instruction building helpers for doc/editor agent executors."""

from __future__ import annotations

from typing import Any

# ── Constants ──────────────────────────────────────────────────────────────

MAX_HISTORY_TURNS = 10


class RequestValidator:
    """
    Stateless helpers for building system instructions and assembling prompts.
    """

    @staticmethod
    def build_system_instruction(request: Any, hooks: Any = None) -> str:
        """Build the system instruction based on file type and mode.

        The ``hooks`` parameter is accepted for forward-compatibility but is
        not currently used by this method.
        """
        file_ctx = f"文件名：{request.file_name}，" if request.file_name else ""

        # FloatingToolbar actions pass a pre-built system prompt
        if request.action_system_prompt:
            return request.action_system_prompt

        if request.output_mode == "chat":
            return (
                f"你是 Koto 文档 AI 助手。当前文件：{file_ctx}类型 {request.file_type}。\n"
                "用户当前处于【仅对话模式】，你的回复只会显示在聊天栏，不会修改文档。\n"
                "请直接用自然语言回答用户的问题或提供建议，支持 Markdown 格式。\n"
                "不要输出任何 <TOOL> 标签或 JSON 指令。"
            )

        if request.file_type == "pptx":
            if request.has_selection:
                action_hint = (
                    "用户选中了某个文本框的文字（见[用户选中的文字]）。"
                    "修改时必须使用 set_pptx_text 指令，"
                    "slide_index 和 shape_id 从[PPT幻灯片内容]中读取，禁止使用 set_html。"
                )
            else:
                action_hint = (
                    "修改幻灯片文字必须使用 set_pptx_text 指令，"
                    "slide_index 和 shape_id 从[PPT幻灯片内容]中读取，禁止使用 set_html。"
                )
            return (
                f"你是 Koto PPT AI 助手。当前文件：{file_ctx}类型 pptx。\n\n"
                "【重要规则】\n"
                "当用户要求修改、翻译、润色幻灯片文字时，必须在回复末尾输出修改指令。\n"
                "不要只描述——直接输出指令让程序执行。\n\n"
                "指令格式（必须一行完整输出）：\n"
                '<TOOL>{"type":"set_pptx_text","slide_index":N,"shape_id":M,"value":"新内容"}</TOOL>\n\n'
                "示例 — 修改标题：\n"
                "上下文：[PPT幻灯片1内容, slide_index=0]\n"
                '[shape_id=2 name="标题"]: 原标题\n'
                "用户：把标题改成「季度总结」\n"
                'AI：好的。<TOOL>{"type":"set_pptx_text","slide_index":0,"shape_id":2,"value":"季度总结"}</TOOL>\n\n'
                f"{action_hint}\n"
            )

        if request.file_type in ("xlsx", "csv"):
            return (
                f"你是 Koto 表格 AI 助手。当前文件：{file_ctx}类型 {request.file_type}。\n\n"
                "【数据格式说明】\n"
                "表格数据以 CSV 格式提供：第一列'行'为行号（1起），其余列标题为列字母（A/B/C...对应 Excel 列）。\n"
                "示例：\n"
                "  行,A,B,C\n"
                "  1,姓名,销售额,日期\n"
                "  2,张三,12000,2024-01\n\n"
                "【重要规则】\n"
                "- 分析/问答：直接用中文自然语言回答，不需要输出 <TOOL> 指令。\n"
                "- 修改单元格：在回复末尾输出 set_cell 指令（r/c 从 0 开始）：\n"
                '  <TOOL>{"type":"set_cell","r":1,"c":1,"value":"新值"}</TOOL>\n'
                "  （r=0 对应第1行，c=0 对应 A 列，c=1 对应 B 列，以此类推）\n"
                '  value 可以是文本、数字或 Excel 公式（如 "=SUM(B2:B10)"、"=AVERAGE(C2:C20)"）。\n'
                "- 批量修改：连续输出多个 set_cell 指令，每条占一行。\n\n"
                "示例 1 — 修改 B2 单元格：\n"
                "用户：把 B2 改为 15000\n"
                'AI：已更新。<TOOL>{"type":"set_cell","r":1,"c":1,"value":"15000"}</TOOL>\n\n'
                "示例 2 — 在 B11 插入 SUM 公式（B2:B10 求和，r=10 对应第11行）：\n"
                "用户：帮我在 B11 对 B2:B10 求和\n"
                'AI：已插入求和公式。<TOOL>{"type":"set_cell","r":10,"c":1,"value":"=SUM(B2:B10)"}</TOOL>\n\n'
                "示例 3 — 批量翻译表头（A1、B1、C1）：\n"
                "用户：把第一行翻译成英文\n"
                'AI：已更新。<TOOL>{"type":"set_cell","r":0,"c":0,"value":"Name"}</TOOL>\n'
                '<TOOL>{"type":"set_cell","r":0,"c":1,"value":"Sales"}</TOOL>\n'
                '<TOOL>{"type":"set_cell","r":0,"c":2,"value":"Date"}</TOOL>\n'
            )

        # Default: docx / txt / md / etc.
        if request.has_selection:
            action_hint = "用户当前有选中文字。修改时用 set_html 替换选区内容。"
        else:
            action_hint = "用户当前无选区。修改时用 set_html 在光标处插入内容。"

        return (
            f"你是 Koto 文档 AI 助手。当前文件：{file_ctx}类型 {request.file_type}。\n\n"
            "【重要规则】\n"
            "当用户要求插入、修改、翻译、润色等文档操作时，你必须在回复末尾输出修改指令。\n"
            "不要只描述你会做什么——直接输出指令，让程序执行。\n\n"
            "修改指令格式（必须完整、一行输出）：\n"
            '<TOOL>{"type": "set_html", "value": "<p>内容</p>"}</TOOL>\n\n'
            "示例 1 — 用户让你插入内容：\n"
            "用户：写一行「你好世界」插入文档\n"
            'AI：已插入。<TOOL>{"type": "set_html", "value": "<p>你好世界</p>"}</TOOL>\n\n'
            "示例 2 — 用户让你翻译并插入：\n"
            "用户：翻译成英文插入文档\n"
            'AI：<TOOL>{"type": "set_html", "value": "<p>Hello world</p>"}</TOOL>\n\n'
            f"{action_hint}\n"
            "其他文件类型指令：\n"
            '  XLSX → <TOOL>{"type":"set_cell","r":0,"c":0,"value":"值"}</TOOL>\n'
            '  PPTX → <TOOL>{"type":"set_pptx_text","slide_index":0,"shape_id":1,"value":"新文字"}</TOOL>'
        )

    @staticmethod
    def assemble_prompt(request: Any, prompt: str) -> str:
        """Assemble the full prompt with history, selection, CSV data.

        Includes recent conversation history, selected text, and CSV data.
        """
        history = request.history or []
        recent = history[-MAX_HISTORY_TURNS * 2 :] if history else []
        history_text = ""
        if recent:
            parts = []
            for turn in recent:
                role = turn.get("role", "")
                content = turn.get("content", "")
                if role == "user":
                    parts.append(f"用户：{content}")
                elif role == "assistant":
                    parts.append(f"Koto AI：{content}")
            history_text = "\n".join(parts) + "\n\n"

        csv_block = (
            f"[表格数据（CSV）]\n{request.csv_data}\n\n" if request.csv_data else ""
        )
        if request.selection:
            return (
                f'[用户选中的文字]\n"{request.selection}"\n\n'
                f"{csv_block}{history_text}用户：{prompt}"
            )
        return f"{csv_block}{history_text}用户：{prompt}"
