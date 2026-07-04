# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FileTaskChangeTracker:
    """Compatibility adapter for file-task change payloads.

    New file-task code records structured ``file_changes`` dictionaries.  A few
    older coordinator-facing callers still expect ``FileChange.to_dict()`` style
    records, so this adapter keeps the legacy view without reviving the old
    runtime.
    """

    changes: list[dict[str, Any]] = field(default_factory=list)

    def add(self, change: dict[str, Any]) -> dict[str, Any]:
        item = dict(change or {})
        self.changes.append(item)
        return item

    def coordinator_changes(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for change in self.changes:
            result.extend(_coordinator_changes_for_file_change(change))
        return result


def _coordinator_changes_for_file_change(
    change: dict[str, Any],
) -> list[dict[str, Any]]:
    path = str(
        change.get("file_path")
        or change.get("path")
        or change.get("target_path")
        or change.get("output_path")
        or ""
    ).strip()
    if not path:
        return []

    operation = str(change.get("operation") or change.get("tool") or "").strip()
    change_type = str(change.get("change_type") or "modify").strip() or "modify"
    diff = change.get("diff") if isinstance(change.get("diff"), dict) else {}
    items = diff.get("items") if isinstance(diff.get("items"), list) else []

    if items:
        return [
            _coordinator_change_from_diff_item(
                path=path,
                operation=operation,
                change_type=change_type,
                item=item if isinstance(item, dict) else {},
            )
            for item in items
        ]

    return [
        {
            "file_path": path,
            "change_type": change_type,
            "range": [0, 0],
            "original": str(change.get("before") or change.get("original") or ""),
            "modified": str(change.get("after") or change.get("modified") or ""),
            "timestamp": change.get("timestamp", 0),
            "step_id": str(change.get("step_id") or ""),
            "operation": operation,
        }
    ]


def _coordinator_change_from_diff_item(
    *,
    path: str,
    operation: str,
    change_type: str,
    item: dict[str, Any],
) -> dict[str, Any]:
    before = item.get("before")
    after = item.get("after")
    if before is None and "original" in item:
        before = item.get("original")
    if after is None and "modified" in item:
        after = item.get("modified")

    return {
        "file_path": path,
        "change_type": change_type,
        "range": [
            _coerce_int(item.get("range_start")),
            _coerce_int(item.get("range_end")),
        ],
        "original": "" if before is None else str(before),
        "modified": "" if after is None else str(after),
        "timestamp": item.get("timestamp", 0),
        "step_id": str(item.get("step_id") or ""),
        "operation": operation,
    }


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
