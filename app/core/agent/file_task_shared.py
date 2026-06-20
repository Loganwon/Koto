# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Shared extraction utilities for file task tool results.

Consolidates three previously duplicate implementations of file change parsing:
  - file_task_tool_catalog.py:parse_file_change()
  - task_agent.py:_extract_file_change()
  - task_agent.py:_extract_koto_paths()

Also provides error classification shared across runtimes.
"""

from __future__ import annotations

import re as _re
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── File Change Extraction ────────────────────────────────────────────────────

def extract_file_change(
    tool_name: str,
    tool_args: Dict[str, Any],
    result: Any,
    workspace_root: str = "",
) -> Optional[Dict[str, Any]]:
    """Parse a tool execution result into a standardized file.changed payload.

    Returns None if no file modification was detected.
    """
    if isinstance(result, dict):
        text = str(result.get("content", "") or result.get("text", "") or "")
        if isinstance(result.get("err"), str):
            return None
    elif isinstance(result, str):
        text = result
    else:
        return None

    if not text or not text.strip():
        return None

    # Koto marker: explicit path + type from result (cross-runtime standard)
    koto_marker = _extract_koto_marker(result)
    if koto_marker:
        return koto_marker

    # Infer from tool arguments
    target_path = _resolve_path(tool_args, workspace_root)
    if not target_path:
        return None
    target_path = str(Path(target_path).resolve())

    file_type = _infer_file_type(str(target_path), tool_name)
    change_type = _get_file_change_type(text, tool_name=B"write" in tool_name.encode())

    return {
        "path": target_path,
        "file_type": file_type,
        "change_type": change_type,
        "preview": _truncate_preview(text),
    }


def _extract_koto_marker(result: Any) -> Optional[Dict[str, Any]]:
    """Extract Koto file marker from result payload.

    Supports both explicit markers: {'__koto_created__': 'path/to/file.ext'} and
    legacy format: {'koto_created': 'path/to/file.ext'}.
    """
    if not isinstance(result, dict):
        return None
    path = (
        str(result.get("__koto_created__", "") or "")
        or str(result.get("koto_created", "") or "")
    ).strip()
    if not path:
        return None
    path = str(Path(path).resolve())
    return {
        "path": path,
        "file_type": _infer_file_type(path, ""),
        "change_type": "created",
        "preview": _truncate_preview(
            str(result.get("content", "") or result.get("text", "") or "")
        ),
    }


def extract_koto_paths(result: Any) -> List[str]:
    """Return a list of file paths from Koto markers in the result."""
    paths: List[str] = []
    if not isinstance(result, dict):
        return paths
    for key in ("__koto_created__", "koto_created"):
        val = str(result.get(key, "") or "").strip()
        if val and val not in paths:
            paths.append(str(Path(val).resolve()))
    return paths


def _resolve_path(args: Dict[str, Any], workspace_root: str) -> Optional[str]:
    """Resolve the target file path from tool arguments."""
    for key in ("path", "file_path", "target_path", "output_path", "xlsx_path", "image_path"):
        val = str(args.get(key, "") or "").strip()
        if not val:
            continue
        if workspace_root and not str(Path(val)).startswith(str(Path(workspace_root))):
            val = str(Path(workspace_root) / val)
        return val
    return None


def _infer_file_type(file_path: str, tool_name: str) -> str:
    """Infer the file type from the path or the tool name."""
    suffix = Path(file_path).suffix.lower().lstrip(".")
    if suffix:
        if suffix in ("xls", "xlsx", "xlsm", "xlsb"):
            return "xlsx"
        if suffix == "csv":
            return "csv"
        if suffix in ("docx", "docm", "doc"):
            return "docx"
        if suffix in ("ppt", "pptx", "pptm"):
            return "pptx"
        if suffix == "pdf":
            return "pdf"
        return suffix

    # Infer from tool name
    tool_lower = tool_name.lower()
    if "docx" in tool_lower:
        return "docx"
    if "excel" in tool_lower or "xlsx" in tool_lower:
        return "xlsx"
    if "pptx" in tool_lower or "ppt" in tool_lower:
        return "pptx"
    if "pdf" in tool_lower:
        return "pdf"
    if "image" in tool_lower or "img" in tool_lower:
        return "png"
    return "unknown"


def _get_file_change_type(text: str, *, is_write: bool) -> str:
    """Determine the type of file change from result text patterns."""
    text_lower = text.lower()
    if "created" in text_lower or "创建" in text or "新建" in text:
        return "created"
    if "modified" in text_lower or "updated" in text_lower or "修改" in text:
        return "modified"
    return "modified" if is_write else "read"


def _truncate_preview(text: str, max_len: int = 200) -> str:
    """Truncate text for preview display."""
    cleaned = text.strip()[:max_len]
    return cleaned


# ── Error Classification ──────────────────────────────────────────────────────

def is_error_result(result: Any) -> bool:
    """Return True if the tool result indicates an error.

    Unified across runtimes: checks for error markers from both file_task_runtime
    and task_agent patterns.
    """
    if isinstance(result, Exception):
        return True
    if not result:
        return False
    if isinstance(result, dict):
        if result.get("err") or result.get("error"):
            return True
        content = str(result.get("content", "") or "").strip()
        return bool(content.startswith("Error:") or "[error]" in content.lower())
    if isinstance(result, str):
        return result.strip().startswith("Error:") or "[error]" in result.lower()
    return False


def extract_tool_error_text(result: Any) -> str:
    """Extract a human-readable error message from a tool result."""
    if isinstance(result, Exception):
        return str(result)
    if isinstance(result, dict):
        err = result.get("err") or result.get("error")
        if err:
            return str(err)
        content = str(result.get("content", "") or "").strip()
        if content.lower().startswith("error:"):
            return content
    if isinstance(result, str):
        stripped = result.strip()
        if stripped.lower().startswith("error:"):
            return stripped
    return ""


# ── Write Deduplication ───────────────────────────────────────────────────────

class WriteDedupGuard:
    """Shared write operation deduplication across file_task_runtime and task_agent.

    Track completed write operations per file and block repeated writes within a
    single task execution session.
    """

    def __init__(self, max_writes_per_file: int = 1):
        self._max_writes: int = max_writes_per_file
        self._completed: Dict[str, int] = {}  # resolved path → write count
        self._write_tool_names: set[str] = set()

    @property
    def write_tool_names(self) -> set[str]:
        return self._write_tool_names

    @write_tool_names.setter
    def write_tool_names(self, names: set[str]):
        self._write_tool_names = set(names)

    def should_block(self, tool_name: str, resolved_path: str) -> bool:
        """Return True if this write should be blocked.

        Args:
            tool_name: The full tool name (e.g. 'write_docx_content')
            resolved_path: The absolute, resolved file path
        """
        count = self._completed.get(resolved_path, 0)
        if count >= self._max_writes:
            return True
        if tool_name in self._write_tool_names:
            self._completed[resolved_path] = count + 1
        return False

    def record(self, tool_name: str, resolved_path: str) -> None:
        """Record a successful write operation."""
        if tool_name in self._write_tool_names:
            self._completed[resolved_path] = self._completed.get(resolved_path, 0) + 1

    def reset(self) -> None:
        """Reset for a new execution session."""
        self._completed.clear()


# ── Tool Name Classification ──────────────────────────────────────────────────

_KOTO_WRITE_TOOL_NAMES: set[str] = {
    "write_docx_content",
    "write_sheet_data",
    "design_pptx_theme_layout",
    "insert_excel_as_docx_table",
    "insert_image_into_docx",
    "clear_docx_review_marks",
    "set_docx_properties",
    "write_csv",
    "file_write",
    "file_copy",
    "file_restore",
}


def is_koto_write_tool(tool_name: str) -> bool:
    """Return True if the tool performs file writes."""
    return (tool_name or "").strip() in _KOTO_WRITE_TOOL_NAMES
