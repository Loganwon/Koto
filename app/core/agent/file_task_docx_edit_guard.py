from __future__ import annotations

import json
import re
from typing import Any


def tool_args_docx_paragraph_count(tool_args: dict[str, Any]) -> int:
    raw_paragraphs = tool_args.get("paragraphs")
    if isinstance(raw_paragraphs, str) and raw_paragraphs.strip():
        try:
            items = json.loads(raw_paragraphs)
        except Exception:
            return 1
    elif isinstance(raw_paragraphs, list):
        items = raw_paragraphs
    else:
        return 1 if str(tool_args.get("content") or "").strip() else 0
    return len(items) if isinstance(items, list) else 1


def local_docx_edit_block_message(
    *,
    task_text: str,
    tool_name: str,
    tool_args: dict[str, Any],
) -> str:
    if tool_name != "write_docx_content":
        return ""
    if re.search(
        r"(?:只替换|仅替换|替换.{0,16}(?:一处|那一处|这一处|第\s*\d+\s*处|第\s*\d+\s*段)|"
        r"(?:第\s*\d+\s*段|一处|那一处|这一处).{0,24}(?:替换|删除|改成|换成)|"
        r"local(?:ized)?\s+(?:replace|edit)|replace\s+only)",
        str(task_text or ""),
        re.IGNORECASE,
    ):
        return (
            "监管层阻止写入：当前任务是 DOCX 定位替换，write_docx_content 只会向现有文档追加段落，"
            "不能用于局部替换。请改用 run_python_code 配合 python-docx 精确修改目标段落一次，"
            "完成后不能再调用 write_docx_content 重复追加。"
        )
    if not re.search(
        r"(?:只追加|只加|追加一句|加一句|插入一句|保留已有表格|保留.*表格|append one|add one|insert one|preserve.*table|keep.*table)",
        str(task_text or ""),
        re.IGNORECASE,
    ):
        return ""
    if tool_args_docx_paragraph_count(tool_args) <= 1:
        return ""
    return (
        "监管层阻止写入：当前任务是 DOCX 局部编辑，用户要求只追加少量内容并保留已有表格，"
        "不能用 write_docx_content 把多段正文重新追加到文末。"
        "请改用 insert_docx_paragraph(path=目标 DOCX, text=要追加的句子, "
        "before_heading=下一章节标题，如 Next Actions；如没有下一章节，再使用 after_heading)。"
    )
