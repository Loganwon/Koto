# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

import json
from typing import Any

from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskRequest,
)
from app.core.agent.file_task_prompt_sections import followup_prompt_prefix
from app.core.agent.file_task_runtime_utils import _preview
from app.core.agent.file_task_whitebox import whitebox_execution_plan_schema
from app.core.agent.tool_design_protocol import TOOL_DESIGN_PROTOCOL


def build_file_task_messages(
    *,
    request: FileTaskRequest,
    snippets: list[dict[str, Any]],
    files: list[FileTaskFile],
    classification: FileTaskClassification,
    intent_plan: FileTaskIntentPlan,
    known_tool_gap: dict[str, Any] | None,
    capability_profiles: list[dict[str, Any]],
    followup_context: dict[str, Any],
    recipe_skeleton: dict[str, Any],
    execution_brief_schema: dict[str, Any],
) -> list[dict[str, Any]]:
    context: dict[str, Any] = {
        "task": request.task,
        "target_path": request.target_path,
        "selection_source": request.selection_source,
        "task_feedback_mode": {
            "output_mode": classification.output_mode,
            "label": _output_mode_label(classification.output_mode),
            "write_intent": bool(classification.write_intent),
            "should_write_this_round": str(classification.output_mode or "")
            .strip()
            .lower()
            == "write",
        },
        "intent_plan": intent_plan.public_dict(),
        "files": [file_info.public_dict() for file_info in files],
        "file_capability_profiles": capability_profiles,
        "context_snippets": snippets[:10],
        "recipe_skeleton": recipe_skeleton,
        "execution_plan_schema": whitebox_execution_plan_schema(),
        "execution_brief_schema": execution_brief_schema,
        "tool_design_protocol": TOOL_DESIGN_PROTOCOL,
    }
    if isinstance(request.options, dict):
        memory_context = str(request.options.get("memory_context") or "").strip()
        if memory_context:
            context["memory_context"] = _preview(memory_context, 6000)
    if known_tool_gap:
        context["known_native_tool_gap"] = known_tool_gap
    if followup_context:
        context["followup_context"] = followup_context

    messages: list[dict[str, Any]] = []
    for item in request.history[-6:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "user").strip().lower()
        content = str(item.get("content") or item.get("text") or "").strip()
        if content and role in {"user", "assistant", "model"}:
            messages.append(
                {
                    "role": "model" if role == "assistant" else role,
                    "content": _preview(content, 1500),
                }
            )

    messages.append(
        {
            "role": "user",
            "content": followup_prompt_prefix(followup_context)
            + "上下文如下：\n"
            + json.dumps(context, ensure_ascii=False, indent=2),
        }
    )
    return messages


def _output_mode_label(output_mode: str) -> str:
    normalized = str(output_mode or "").strip().lower()
    if normalized == "write":
        return "写入文件"
    if normalized == "hybrid":
        return "先分析后决定"
    return "只给答案"
