"""Validation helpers for successful and sufficiently complete read evidence."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List

from app.core.agent.file_task_evidence_policy import SPREADSHEET_TYPES, file_type

_INCOMPLETE_ANSWER_PATTERNS = (
    r"读取不完整",
    r"尚未读取",
    r"需要继续读取",
    r"继续读取.{0,12}(?:正文|报告|文档)",
    r"未读取到具体",
    r"当前只读取.{0,20}(?:封面|声明|前部)",
    r"(?:只|仅|只能)看到.{0,20}预览",
    r"建议继续读取",
)


def _mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _successful_payload(output: Dict[str, Any]) -> Dict[str, Any]:
    payload = _mapping(output.get("result"))
    return {} if payload.get("error") else payload


def _successful_output(output: Dict[str, Any]) -> bool:
    result = output.get("result")
    if isinstance(result, dict):
        return not bool(result.get("error"))
    text = str(result or "").strip().lower()
    return bool(text) and not any(
        marker in text for marker in ("file not found", "error parsing file", '"error"')
    )


def _file_label(file_info: Any) -> str:
    return str(
        getattr(file_info, "name", "")
        or getattr(file_info, "path", "")
        or (file_info.get("name") if isinstance(file_info, dict) else "")
        or (file_info.get("path") if isinstance(file_info, dict) else "")
        or "文件"
    ).strip()


def _normalized_path(value: Any) -> str:
    return str(value or "").strip().replace("\\", "/").rstrip("/").casefold()


def _output_matches_file(output: Dict[str, Any], file_info: Any) -> bool:
    args = output.get("args") if isinstance(output.get("args"), dict) else {}
    output_path = _normalized_path(
        args.get("path") or args.get("source_path") or args.get("file_path")
    )
    file_path = _normalized_path(
        getattr(file_info, "path", "")
        or (file_info.get("path") if isinstance(file_info, dict) else "")
    )
    file_name = _normalized_path(_file_label(file_info))
    if not output_path:
        return False
    return bool(
        (file_path and output_path == file_path)
        or (
            file_name and output_path.rsplit("/", 1)[-1] == file_name.rsplit("/", 1)[-1]
        )
    )


def _docx_read_is_complete(output: Dict[str, Any]) -> bool:
    payload = _successful_payload(output)
    if not payload:
        return False
    paragraphs = payload.get("paragraphs")
    tables = payload.get("tables")
    if not isinstance(paragraphs, list) or not isinstance(tables, list):
        return False
    try:
        if len(paragraphs) < int(payload.get("total_paragraphs") or 0):
            return False
        if len(tables) < int(payload.get("total_tables") or 0):
            return False
        for table in tables:
            if not isinstance(table, dict):
                return False
            if len(table.get("rows") or []) < int(table.get("row_count") or 0):
                return False
    except (TypeError, ValueError):
        return False
    return not bool(payload.get("truncated"))


def missing_readonly_source_coverage(
    files: Iterable[Any],
    readonly_tool_outputs: Iterable[Dict[str, Any]],
) -> List[str]:
    outputs = [item for item in readonly_tool_outputs or [] if isinstance(item, dict)]
    missing: List[str] = []
    for file_info in files or []:
        current_type = file_type(file_info)
        if not current_type:
            continue
        matching = [item for item in outputs if _output_matches_file(item, file_info)]
        covered = False
        if current_type == "docx":
            covered = any(
                item.get("tool_name") == "read_docx_content"
                and _docx_read_is_complete(item)
                for item in matching
            )
        elif current_type in SPREADSHEET_TYPES:
            covered = any(
                item.get("tool_name") == "read_sheet_data"
                and bool(_successful_payload(item))
                for item in matching
            )
        else:
            covered = any(
                item.get("tool_name") == "parse_file_to_text"
                and _successful_output(item)
                for item in matching
            )
        if not covered:
            missing.append(f"{_file_label(file_info)} 的完整读取证据")
    return missing


def answer_declares_incomplete_read(final_summary: str) -> bool:
    text = str(final_summary or "")
    return any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in _INCOMPLETE_ANSWER_PATTERNS
    )


__all__ = [
    "answer_declares_incomplete_read",
    "missing_readonly_source_coverage",
]
