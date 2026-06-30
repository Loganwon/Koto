# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from app.core.agent.file_task_step_verification import (
    build_supervisor_step_verification_payload,
)


@dataclass(frozen=True)
class ToolGuardEmission:
    tool_finished_payload: Dict[str, Any]
    step_verified_payload: Dict[str, Any]
    function_message: Dict[str, Any]


def build_tool_guard_emission(
    *,
    tool_name: str,
    tool_args: Dict[str, Any],
    tool_call_id: str,
    result_preview: str,
    feedback_content: str,
    round_index: int,
    tool_index: int,
    success: bool = False,
    blocked: bool = True,
    skipped: bool = False,
    event_tool_name: str = "",
    message_tool_name: str = "",
    include_blocked_in_finished: bool = True,
) -> ToolGuardEmission:
    finished_payload: Dict[str, Any] = {
        "tool_name": event_tool_name or tool_name,
        "success": bool(success),
        "result_preview": result_preview,
    }
    if include_blocked_in_finished and blocked:
        finished_payload["blocked"] = True
    if skipped:
        finished_payload["skipped"] = True

    step_payload = build_supervisor_step_verification_payload(
        tool_name=tool_name,
        tool_args=tool_args,
        success=success,
        blocked=blocked,
        skipped=skipped,
        summary=result_preview,
        round_index=round_index,
        tool_index=tool_index,
    )

    message = {
        "role": "function",
        "name": message_tool_name or tool_name,
        "tool_call_id": tool_call_id,
        "content": feedback_content,
    }
    return ToolGuardEmission(
        tool_finished_payload=finished_payload,
        step_verified_payload=step_payload,
        function_message=message,
    )
