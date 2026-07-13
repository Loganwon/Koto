# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping


def _preview(value: Any, limit: int = 700) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _compact_line(value: Any, limit: int = 260) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _json_payload(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _is_error_result(value: Any) -> bool:
    payload = _json_payload(value)
    if payload.get("error"):
        return True
    text = str(value or "").strip()
    return (
        text.startswith(("Error:", "Sandbox error:", "[error]")) or "\n[error]" in text
    )


def _sanitize_followup_file_changes(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return []
    if not isinstance(value, list):
        return []

    cleaned: List[Dict[str, Any]] = []
    for item in value[:8]:
        if not isinstance(item, dict):
            continue
        entry: Dict[str, Any] = {}
        for key in (
            "path",
            "file_type",
            "operation",
            "summary",
            "source_path",
            "sheet",
            "requested_sheet",
            "table_title",
            "change_type",
            "original_target_path",
        ):
            text = str(item.get(key) or "").strip()
            if text:
                entry[key] = _preview(text, 400)
        for key in ("rows_written", "columns_written"):
            raw_value = item.get(key)
            if raw_value in (None, ""):
                continue
            try:
                entry[key] = int(raw_value)
            except Exception:
                continue
        if bool(item.get("fallback_copy")):
            entry["fallback_copy"] = True
        if entry:
            cleaned.append(entry)
    return cleaned


def _followup_has_prior_excel_docx_insert(followup_context: Dict[str, Any]) -> bool:
    for change in _sanitize_followup_file_changes(
        followup_context.get("previous_task_file_changes")
    ):
        if str(change.get("operation") or "").strip() == "insert_excel_as_docx_table":
            return True
    return False


def workflow_checkpoint_from_options(options: Mapping[str, Any]) -> Dict[str, Any]:
    checkpoint = options.get("workflow_checkpoint")
    if isinstance(checkpoint, Mapping):
        return dict(checkpoint)

    return {}
