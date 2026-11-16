"""Pure policy predicates for deciding which read evidence a task requires."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

SPREADSHEET_TYPES = {"xlsx", "xls", "xlsm", "csv"}

_COMPARE_MARKERS = (
    "对账",
    "对得上",
    "对的上",
    "对上",
    "是否一致",
    "一致吗",
    "核对",
    "匹配",
    "比较",
    "对比",
    "compare",
    "reconcile",
    "consistent",
)
_FULL_READ_MARKERS = (
    "完整分析",
    "完整读取",
    "全部内容",
    "全文",
    "逐页",
    "通读",
    "whole document",
    "entire document",
)


def file_type(file_info: Any) -> str:
    explicit = (
        str(
            getattr(file_info, "type", "")
            or (file_info.get("type") if isinstance(file_info, dict) else "")
            or (file_info.get("file_type") if isinstance(file_info, dict) else "")
            or ""
        )
        .strip()
        .lower()
        .lstrip(".")
    )
    if explicit:
        return explicit
    path = str(
        getattr(file_info, "path", "")
        or (file_info.get("path") if isinstance(file_info, dict) else "")
        or ""
    )
    return Path(path).suffix.lower().lstrip(".")


def requires_readonly_source_coverage(task: str, files: Iterable[Any]) -> bool:
    text = str(task or "").strip().lower()
    source_files = [item for item in files or [] if file_type(item)]
    is_comparison = len(source_files) >= 2 and any(
        marker in text for marker in _COMPARE_MARKERS
    )
    explicit_full_read = bool(source_files) and any(
        marker in text for marker in _FULL_READ_MARKERS
    )
    return is_comparison or explicit_full_read


__all__ = [
    "SPREADSHEET_TYPES",
    "file_type",
    "requires_readonly_source_coverage",
]
