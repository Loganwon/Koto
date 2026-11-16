"""Internal helpers: result construction."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._internal_fs import _resolve_path  # noqa: F401
from ._internal_sandbox import _fingerprint_file  # noqa: F401


def _success_result(
    path: str,
    *,
    operation: str,
    summary: str,
    file_type: str = "",
    change_type: str = "modify",
    preview: str = "",
    focus: bool = False,
    **extra: Any,
) -> str:
    summary_code = str(
        extra.pop(
            "summary_code",
            "CREATE_OK" if str(change_type or "").lower() == "create" else "WRITE_OK",
        )
        or ""
    )
    payload: Dict[str, Any] = {
        "success": True,
        "path": path,
        "file_type": file_type or Path(str(path)).suffix.lstrip(".").lower(),
        "change_type": change_type,
        "operation": operation,
        "summary_code": summary_code,
        "summary": summary,
        "preview": preview[:400],
        "focus": focus,
    }
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False, default=str)


def _file_task_diff(
    kind: str,
    items: List[Dict[str, Any]],
    *,
    limit: int = 80,
) -> Dict[str, Any]:
    normalized = [dict(item) for item in items if isinstance(item, dict)]
    return {
        "kind": kind,
        "items": normalized[:limit],
        "changed_count": len(normalized),
        "truncated": len(normalized) > limit,
    }


def _blocked_write_result(
    path: str,
    *,
    summary: str,
    suggested_next_step: str = "",
    **extra: Any,
) -> str:
    payload: Dict[str, Any] = {
        "success": False,
        "path": path,
        "status": "write_blocked",
        "summary_code": "WRITE_BLOCKED",
        "summary": summary,
        "error": summary,
    }
    if suggested_next_step:
        payload["suggested_next_step"] = suggested_next_step
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False, default=str)


def _resolve_task_file_entries(
    task_files: Optional[List[Dict[str, str]]],
) -> List[Dict[str, str]]:
    """Resolve task file metadata into concrete files that can be staged."""
    resolved_entries: List[Dict[str, str]] = []
    seen: set[str] = set()

    for item in task_files or []:
        if not isinstance(item, dict):
            continue

        raw_path = str(item.get("path") or "").strip()
        raw_name = str(item.get("name") or "").strip()
        resolved_path = _resolve_path(raw_path or raw_name)
        if not resolved_path or not os.path.isfile(resolved_path):
            continue

        key = os.path.normcase(os.path.abspath(resolved_path))
        if key in seen:
            continue
        seen.add(key)

        resolved_entries.append(
            {
                "display_name": raw_name or os.path.basename(resolved_path),
                "source_path": resolved_path,
                "source_fingerprint_initial": _fingerprint_file(resolved_path),
            }
        )

    return resolved_entries
