# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

import json
import uuid
from typing import Any

from app.core.shared.tool_parser import parse_task_tool_calls


def normalize_model_response(
    response: dict[str, Any],
    tool_defs: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(response, dict):
        return str(response or ""), []
    content_text = str(response.get("content") or "")
    tool_calls = response.get("tool_calls") or []
    normalized = coerce_tool_calls(tool_calls)
    if not normalized and content_text:
        allowed = {str(definition.get("name") or "") for definition in tool_defs}
        content_text, normalized = parse_task_tool_calls(content_text, allowed)
    return content_text.strip(), normalized


def coerce_tool_calls(raw_tool_calls: Any) -> list[dict[str, Any]]:
    items = raw_tool_calls if isinstance(raw_tool_calls, list) else [raw_tool_calls]
    normalized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        function_payload = (
            item.get("function") if isinstance(item.get("function"), dict) else {}
        )
        tool_name = str(
            item.get("name")
            or item.get("tool_name")
            or function_payload.get("name")
            or ""
        ).strip()
        if not tool_name:
            continue
        tool_args = item.get("args")
        if tool_args is None:
            tool_args = item.get("arguments")
        if tool_args is None and function_payload:
            tool_args = function_payload.get("arguments")
        if isinstance(tool_args, str):
            try:
                tool_args = json.loads(tool_args)
            except Exception:
                tool_args = {}
        if not isinstance(tool_args, dict):
            tool_args = {}
        normalized.append(
            {
                "id": str(item.get("id") or uuid.uuid4().hex[:8]),
                "name": tool_name,
                "args": tool_args,
            }
        )
    return normalized


def tool_batch_signature(tool_calls: list[dict[str, Any]]) -> str:
    if not tool_calls:
        return ""
    safe_calls = [
        {"name": item.get("name"), "args": item.get("args") or {}}
        for item in tool_calls
    ]
    try:
        return json.dumps(safe_calls, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return str(safe_calls)
