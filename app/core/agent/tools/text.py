"""Domain module - Text file tools."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..task_tools_common import _TEXT_LIMIT_DEFAULT
from ._internal_backup import (
    _best_effort_backup,
    _ensure_existing_file_writable,
    _nonwritable_target_message,
    _nonwritable_target_next_step,
)
from ._internal_formats import _read_pdf_excerpt, _read_pdf_letter_window
from ._internal_fs import _resolve_path, _result_path
from ._internal_results import _blocked_write_result, _success_result
from ._internal_tempfile import _write_bytes_via_temp_file
from ._internal_warnings import _merge_warnings
from .docx_read import _read_docx_paragraph_window
from .pptx import _read_pptx_slide_window
from .xlsx_read import _read_xlsx_sheet_window


def parse_file_to_text(
    path: str,
    max_chars: int = _TEXT_LIMIT_DEFAULT,
    start_page: int = 1,
    end_page: int = 0,
    window_unit: str = "",
    start: int = 0,
    end: int = 0,
    sheet_index: int = -1,
) -> str:
    """Parse any supported file to plain text (DOCX/XLSX/PPTX/PDF/TXT/CSV)."""
    resolved = _resolve_path(path)
    if not resolved:
        return json.dumps({"error": f"File not found: {path}"}, ensure_ascii=False)

    try:
        from app.core.file.text_extraction import parse_source_file

        suffix = Path(resolved).suffix.lower()
        if suffix == ".pdf" and window_unit == "pdf_letter":
            text = _read_pdf_letter_window(
                resolved,
                max_chars=max_chars,
                start_letter=start or 1,
                end_letter=end or start or 1,
            )
        elif suffix == ".pdf":
            text = _read_pdf_excerpt(
                resolved,
                max_chars=max_chars,
                start_page=start_page,
                end_page=end_page,
            )
        elif suffix in {".doc", ".docx"} and window_unit == "paragraph":
            text = _read_docx_paragraph_window(
                resolved,
                max_chars=max_chars,
                start=start or 1,
                end=end or start or 1,
            )
        elif suffix in {".ppt", ".pptx"} and window_unit == "slide":
            text = _read_pptx_slide_window(
                resolved,
                max_chars=max_chars,
                start=start or 1,
                end=end or start or 1,
            )
        elif suffix in {".xls", ".xlsx", ".xlsm", ".csv"} and window_unit == "sheet":
            text = _read_xlsx_sheet_window(
                resolved,
                max_chars=max_chars,
                sheet_index=sheet_index,
            )
        else:
            text = parse_source_file(resolved, strict=True)
        if not text.strip():
            return f"(File parsed but no text content: {path})"
        return text[:max_chars]
    except Exception as e:
        return f"Error parsing file: {e}"


def _coerce_read_line_number(value: Any, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    try:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return default
            value = float(stripped) if "." in stripped else int(stripped)
        coerced = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, coerced)


def read_file_range(path: str, start_line: int = 1, end_line: int = 100) -> str:
    """Read a specific range of lines from a file.

    Args:
        path: File path.
        start_line: Starting line number (1-indexed).
        end_line: Ending line number (inclusive).

    Returns: The specified lines as text.
    """
    resolved = _resolve_path(path)
    if not resolved:
        return json.dumps({"error": f"File not found: {path}"}, ensure_ascii=False)

    try:
        start_line = _coerce_read_line_number(start_line, 1)
        end_line = _coerce_read_line_number(end_line, 100)
        if end_line < start_line:
            end_line = start_line

        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        start_idx = max(0, start_line - 1)
        end_idx = min(len(lines), end_line)

        selected = lines[start_idx:end_idx]
        return "".join(selected)
    except Exception as e:
        return f"Error: {e}"


def replace_file_selection(
    path: str,
    original_selection: str = "",
    new_content: str = "",
    occurrence: int = 1,
) -> str:
    """Replace a selected text span in an existing text-like file.

    Args:
        path: Target text-like file path.
        original_selection: Exact selected text to replace.
        new_content: Replacement text.
        occurrence: 1-indexed occurrence to replace when the same text appears multiple times.

    Returns: JSON with standard file-change metadata.
    """
    resolved = _resolve_path(path)
    if not resolved:
        return json.dumps({"error": f"File not found: {path}"}, ensure_ascii=False)

    suffix = Path(resolved).suffix.lstrip(".").lower()
    text_like = {
        "txt",
        "md",
        "markdown",
        "text",
        "csv",
        "json",
        "py",
        "js",
        "html",
        "css",
    }
    if suffix not in text_like:
        return json.dumps(
            {
                "error": f"replace_file_selection only supports text-like files, got: {suffix or 'unknown'}",
                "changed": False,
            },
            ensure_ascii=False,
        )

    original = str(original_selection or "")
    replacement = str(new_content or "")
    if not original:
        return json.dumps(
            {"error": "original_selection is required", "changed": False},
            ensure_ascii=False,
        )

    try:
        index_to_replace = max(1, int(occurrence or 1))
    except (TypeError, ValueError):
        index_to_replace = 1

    try:
        with open(
            resolved, "r", encoding="utf-8", errors="replace", newline=""
        ) as handle:
            content = handle.read()
    except Exception as exc:
        return json.dumps({"error": f"Read failed: {exc}"}, ensure_ascii=False)

    starts = [match.start() for match in re.finditer(re.escape(original), content)]
    if not starts:
        return json.dumps(
            {
                "success": False,
                "changed": False,
                "path": _result_path(path, resolved),
                "operation": "replace_file_selection",
                "summary": "未在目标文件中找到选区原文，未写入。",
                "error": "original_selection_not_found",
            },
            ensure_ascii=False,
        )
    if index_to_replace > len(starts):
        return json.dumps(
            {
                "success": False,
                "changed": False,
                "path": _result_path(path, resolved),
                "operation": "replace_file_selection",
                "summary": f"目标文件中只找到 {len(starts)} 处匹配，无法替换第 {index_to_replace} 处。",
                "error": "occurrence_out_of_range",
                "matches_found": len(starts),
            },
            ensure_ascii=False,
        )

    start = starts[index_to_replace - 1]
    end = start + len(original)
    updated = content[:start] + replacement + content[end:]

    backup_warning = _best_effort_backup(resolved)
    write_warning = _ensure_existing_file_writable(resolved)
    try:
        _write_bytes_via_temp_file(
            updated.encode("utf-8"), resolved, suffix=f".{suffix}" if suffix else ".txt"
        )
    except PermissionError as exc:
        return _blocked_write_result(
            _result_path(path, resolved),
            summary=str(exc).strip() or _nonwritable_target_message(resolved),
            suggested_next_step=_nonwritable_target_next_step(resolved),
            operation="replace_file_selection",
            file_type=suffix or "text",
            preview=replacement,
            replacements_made=0,
        )
    except Exception as exc:
        return json.dumps({"error": f"Write failed: {exc}"}, ensure_ascii=False)

    return _success_result(
        _result_path(path, resolved),
        operation="replace_file_selection",
        summary="已替换目标文件中的选区内容。",
        file_type=suffix or "text",
        change_type="modify",
        preview=replacement,
        focus=True,
        replacements_made=1,
        matches_found=len(starts),
        occurrence=index_to_replace,
        original_selection=original[:240],
        warning=_merge_warnings(backup_warning, write_warning),
    )
