# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from app.core.agent.file_task_contract import FileTaskEvent, FileTaskLedger
from app.core.agent.file_task_runtime_utils import _is_error_result
from app.core.agent.file_task_tool_catalog import stringify_result, tool_result_preview

logger = logging.getLogger(__name__)

ToolExecutor = Callable[[str, dict[str, Any]], Any]
FileChangeExtractor = Callable[[str, dict[str, Any], Any], list[dict[str, Any]]]


def run_builtin_tool(
    ledger: FileTaskLedger,
    executor: ToolExecutor,
    *,
    step_id: str,
    tool_name: str,
    tool_args: dict[str, Any],
    file_changes: list[dict[str, Any]],
    extract_file_changes: FileChangeExtractor,
) -> tuple[dict[str, Any], list[FileTaskEvent]]:
    events: list[FileTaskEvent] = []
    events.append(
        ledger.event(
            "tool.started",
            {
                "tool_name": tool_name,
                "tool_args": dict(tool_args or {}),
            },
            step_id=step_id,
        )
    )
    try:
        result = executor(tool_name, dict(tool_args or {}))
        success = not _is_error_result(result)
    except Exception as exc:
        result = {"error": str(exc)}
        success = False
        logger.warning(
            "[FileTaskRuntime] deterministic tool %s failed: %s", tool_name, exc
        )

    payload: dict[str, Any]
    try:
        parsed = json.loads(stringify_result(result))
        payload = (
            parsed
            if isinstance(parsed, dict)
            else {"summary": stringify_result(result)}
        )
    except Exception:
        payload = {"summary": stringify_result(result)}

    events.append(
        ledger.event(
            "tool.finished",
            {
                "tool_name": tool_name,
                "success": success,
                "result_preview": tool_result_preview(tool_name, result, 1200),
            },
            step_id=step_id,
        )
    )
    if success:
        for change in extract_file_changes(tool_name, tool_args, result):
            file_changes.append(change)
            events.append(ledger.event("file.changed", change, step_id=step_id))
    return payload, events
