"""Shared text normalization for editor and file-task SSE requests."""

from __future__ import annotations

import re


_SYSTEM_LOG_MARKERS = (
    "执行过程未完成", "准备处理", "分析需求", "耗时", "正在处理", "异常",
    "制定计划", "读取文件", "检查结果", "任务未完成", "任务理解",
    "我理解的任务", "查看产物", "追问原因", "重新发起", "已写入任务记忆",
    "记忆摘要", "任务结果",
)
_SYSTEM_LOG_MARKER_PATTERN = re.compile(
    r"\*\*\*?(" + "|".join(re.escape(marker) for marker in _SYSTEM_LOG_MARKERS) + r")\*\*\*?",
    re.IGNORECASE,
)


def clean_selection_text(value: str) -> str:
    """Remove task-progress text accidentally copied into editor input."""
    text = str(value or "")
    if not text:
        return ""
    match = _SYSTEM_LOG_MARKER_PATTERN.search(text)
    if match:
        text = text[:match.start()].rstrip()
    clean_lines = [
        line
        for line in text.split("\n")
        if line.strip() and not _SYSTEM_LOG_MARKER_PATTERN.search(line.strip())
    ]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(clean_lines)).strip()
