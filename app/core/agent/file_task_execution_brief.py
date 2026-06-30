# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

from typing import Any

from app.core.agent.file_task_contract import FileTaskExecutionBrief
from app.core.agent.tool_design_protocol import extract_first_json_value


def execution_brief_schema() -> dict[str, Any]:
    return {
        "execution_brief": {
            "summary": "一句中文概述当前准备怎么处理",
            "objective": "本轮要完成的目标",
            "steps": [{"title": "步骤标题", "description": "准备做什么"}],
            "planned_tools": ["tool_name"],
            "read_targets": ["会读取的文件或对象"],
            "write_targets": ["会写入的文件或对象"],
            "verification": "准备如何验证结果",
        }
    }


def normalize_execution_brief(value: Any) -> FileTaskExecutionBrief | None:
    candidate = value
    if isinstance(candidate, dict) and isinstance(
        candidate.get("execution_brief"), dict
    ):
        candidate = candidate.get("execution_brief")
    if not isinstance(candidate, dict):
        return None
    brief = FileTaskExecutionBrief.from_mapping(candidate)
    if not any(
        (
            brief.summary,
            brief.objective,
            brief.steps,
            brief.planned_tools,
            brief.read_targets,
            brief.write_targets,
            brief.verification,
        )
    ):
        return None
    return brief


def looks_like_brief_only_content(content_text: str) -> bool:
    text = str(content_text or "").strip()
    if not text:
        return False
    if text.startswith(("{", "[")):
        return True
    if text.startswith("```") and extract_first_json_value(text) is not None:
        return True
    return False


def extract_execution_brief(
    response: Any,
    content_text: str,
) -> tuple[FileTaskExecutionBrief | None, str]:
    candidate: Any = None
    if isinstance(response, dict):
        if isinstance(response.get("execution_brief"), dict):
            candidate = response.get("execution_brief")
        elif content_text:
            candidate = extract_first_json_value(content_text)
    elif content_text:
        candidate = extract_first_json_value(content_text)

    brief = normalize_execution_brief(candidate)
    if not brief:
        return None, content_text

    cleaned_content = content_text.strip()
    if looks_like_brief_only_content(cleaned_content):
        cleaned_content = brief.summary or brief.objective or ""
    return brief, cleaned_content
