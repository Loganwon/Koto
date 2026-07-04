# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.agent.file_task_runtime_utils import _preview
from app.core.agent.file_task_tool_catalog import is_file_task_tool, is_write_tool


def build_supervisor_step_verification_payload(
    *,
    tool_name: str,
    tool_args: Dict[str, Any],
    success: bool,
    blocked: bool = False,
    skipped: bool = False,
    summary: Optional[str] = None,
    round_index: int = 0,
    tool_index: int = 0,
    file_changes: Optional[List[Dict[str, Any]]] = None,
    artifacts: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    name = str(tool_name or "").strip()
    changes = [dict(item) for item in (file_changes or []) if isinstance(item, dict)]
    artifact_list = [dict(item) for item in (artifacts or []) if isinstance(item, dict)]
    allowlisted = is_file_task_tool(name)
    finished_or_guarded = bool(success or blocked or skipped or summary)
    write_evidence = True
    if is_write_tool(name) and success and not blocked and not skipped:
        write_evidence = bool(changes or artifact_list or str(summary or "").strip())
    criteria = [
        {
            "name": "tool_allowlisted",
            "passed": allowlisted,
            "detail": "工具必须来自 Koto 文件任务 allowlist。",
        },
        {
            "name": "tool_call_finished_or_guarded",
            "passed": finished_or_guarded,
            "detail": "每个模型工具选择必须产生完成、跳过或监管阻断结论。",
        },
        {
            "name": "write_has_result_evidence",
            "passed": write_evidence,
            "detail": "写入类工具需要变更、产物或结果摘要作为验证证据。",
        },
    ]
    passed = all(bool(item.get("passed")) for item in criteria)
    outcome = (
        "blocked"
        if blocked
        else "skipped" if skipped else "succeeded" if success else "failed"
    )
    return {
        "passed": passed,
        "outcome": outcome,
        "tool_name": name,
        "tool_args": dict(tool_args or {}),
        "round": round_index,
        "tool_index": tool_index,
        "success": bool(success),
        "blocked": bool(blocked),
        "skipped": bool(skipped),
        "summary": _preview(summary or "", 500),
        "criteria": criteria,
        "file_changes": changes[:8],
        "artifacts": artifact_list[:8],
    }
