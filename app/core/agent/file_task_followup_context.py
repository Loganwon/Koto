# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

from typing import Any

from app.core.agent.file_task_contract import FileTaskRequest
from app.core.agent.file_task_runtime_utils import (
    _preview,
    _sanitize_followup_file_changes,
)

_FOLLOWUP_TEXT_KEYS = (
    "kind",
    "source",
    "followup_action",
    "user_feedback",
    "previous_run_id",
    "previous_task_summary",
    "previous_task_status",
    "previous_task_timestamp",
    "previous_user_request",
    "previous_task_request",
    "previous_task_mode",
    "previous_task_request_kind",
    "previous_task_family",
    "previous_task_operation_kind",
    "previous_task_execution_mode",
    "previous_task_selected_recipe",
    "previous_task_output_mode",
    "previous_task_intent_strategy",
    "previous_task_intent_can_apply",
    "previous_task_intent_requires_confirmation",
    "previous_task_target_file_type",
    "previous_completed_task",
)


def followup_context(request: FileTaskRequest) -> dict[str, Any]:
    if not isinstance(request.options, dict):
        return {}
    value = request.options.get("followup_context")
    if not isinstance(value, dict):
        return {}

    cleaned: dict[str, Any] = {}
    for key in _FOLLOWUP_TEXT_KEYS:
        text = str(value.get(key) or "").strip()
        if text:
            cleaned[key] = _preview(text, 2000)
    previous_task_file_changes = _sanitize_followup_file_changes(
        value.get("previous_task_file_changes")
    )
    if previous_task_file_changes:
        cleaned["previous_task_file_changes"] = previous_task_file_changes
    return cleaned
