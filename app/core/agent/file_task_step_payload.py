# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

from typing import Any


def build_runtime_metadata(
    *,
    terminal_status: str,
    readonly_fallback_used: bool,
    model_failed: bool,
    planner_payload: dict[str, Any] | None = None,
    planner_fallback_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    planner_payload = planner_payload if isinstance(planner_payload, dict) else {}
    planner_fallback_payload = (
        planner_fallback_payload if isinstance(planner_fallback_payload, dict) else {}
    )

    backend = str(planner_payload.get("backend") or "")
    source = str(planner_payload.get("source") or "")
    policy = str(planner_payload.get("policy") or "")
    transport = str(planner_payload.get("transport") or "")
    reason = str(planner_payload.get("reason") or "")
    fallback_from = str(planner_fallback_payload.get("from") or "")

    execution_path = "native"
    if readonly_fallback_used:
        execution_path = "readonly_fallback"
    elif fallback_from:
        execution_path = "planner_fallback"
    elif backend and backend != "native":
        execution_path = "planner"
    elif source and source != "native":
        execution_path = "planner"

    planner_runtime: dict[str, Any] = {
        "backend": backend,
        "source": source,
        "policy": policy,
        "transport": transport,
        "reason": reason,
    }
    round_index = planner_payload.get("round")
    if round_index:
        planner_runtime["round"] = round_index
    if fallback_from:
        planner_runtime["fallback_from"] = fallback_from

    return {
        "execution_path": execution_path,
        "terminal_status": str(terminal_status or ""),
        "model_unavailable": bool(model_failed or readonly_fallback_used),
        "readonly_fallback_used": bool(readonly_fallback_used),
        "planner": planner_runtime,
    }


def with_runtime_context(
    artifact: dict[str, Any] | None,
    runtime_metadata: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(artifact, dict) or not artifact:
        return artifact
    enriched = dict(artifact)
    enriched["runtime_context"] = dict(runtime_metadata)
    return enriched


def step_result_file_changes(
    file_changes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for change in file_changes[:8]:
        if not isinstance(change, dict):
            continue
        item: dict[str, Any] = {}
        for key in (
            "path",
            "file_path",
            "file_type",
            "operation",
            "summary",
            "warning",
            "annotations_added",
            "rows_written",
            "columns_written",
            "requested_sheet",
            "sheet",
            "source_path",
            "slides_designed",
            "theme_name",
            "table_title",
        ):
            value = change.get(key)
            if value in (None, "", [], {}):
                continue
            item[key] = value
        if item:
            items.append(item)
    return items


def public_context_snippets(snippets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    public_items: list[dict[str, Any]] = []
    for item in snippets or []:
        if not isinstance(item, dict):
            continue
        public_items.append(
            {key: value for key, value in item.items() if not str(key).startswith("_")}
        )
    return public_items


def build_step_result_payload(
    *,
    title: str,
    summary: str,
    status: str = "completed",
    round_index: int = 0,
    snippet_count: int = 0,
    snippets: list[dict[str, Any]] | None = None,
    file_changes: list[dict[str, Any]] | None = None,
    runtime: dict[str, Any] | None = None,
    passed: bool | None = None,
    next_action_artifact: dict[str, Any] | None = None,
    supervisor_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": str(title or "").strip() or "步骤结果",
        "summary": str(summary or "").strip()
        or str(title or "步骤结果").strip()
        or "步骤结果",
        "status": str(status or "completed").strip().lower() or "completed",
    }
    if round_index > 0:
        payload["round"] = int(round_index)
    if snippet_count > 0:
        payload["snippet_count"] = int(snippet_count)
    if snippets:
        payload["snippets"] = public_context_snippets(snippets[:4])
    safe_changes = step_result_file_changes(file_changes or [])
    if safe_changes:
        payload["file_change_count"] = len(file_changes or [])
        payload["file_changes"] = safe_changes
    if isinstance(runtime, dict) and runtime:
        payload["runtime"] = dict(runtime)
    if passed is not None:
        payload["passed"] = bool(passed)
    if isinstance(next_action_artifact, dict) and next_action_artifact:
        payload["next_action_artifact"] = next_action_artifact
    if isinstance(supervisor_audit, dict) and supervisor_audit:
        payload["supervisor_audit"] = dict(supervisor_audit)
    return payload


def execute_step_summary(
    *,
    round_index: int,
    final_summary: str,
    model_failed: bool,
    tool_gap: dict[str, Any] | None,
    file_changes: list[dict[str, Any]],
    tool_runtime_outcome: dict[str, Any] | None,
    runtime_status: str,
) -> str:
    summary = str(final_summary or "").strip()
    if summary:
        return summary
    if runtime_status == "awaiting_confirmation":
        return "已生成下一步执行方案，等待用户确认继续。"
    if runtime_status in {"blocked", "write_blocked"}:
        return str(
            (tool_runtime_outcome or {}).get("summary")
            or "目标文件当前不可写，已停止继续重试。"
        )
    if model_failed:
        return "模型调用失败，已停止工具执行。"
    if isinstance(tool_gap, dict) and tool_gap:
        return str(tool_gap.get("summary") or "当前任务缺少对应的 Koto 原生工具。")
    if file_changes:
        return f"已完成第 {round_index} 轮工具执行，累计记录 {len(file_changes)} 次文件变更。"
    if round_index > 0:
        return f"已完成第 {round_index} 轮工具执行。"
    return "模型未再请求工具调用。"


def execute_step_result_status(
    *,
    completed: bool,
    tool_gap: dict[str, Any] | None,
    model_failed: bool,
    runtime_status: str,
) -> str:
    if runtime_status == "awaiting_confirmation":
        return "needs_attention"
    if runtime_status in {"blocked", "write_blocked"}:
        return "failed"
    if model_failed or (isinstance(tool_gap, dict) and tool_gap):
        return "failed"
    return "completed" if completed else "needs_attention"


def check_step_result_status(check_payload: dict[str, Any]) -> str:
    status = str(check_payload.get("status") or "").strip().lower()
    if status == "awaiting_confirmation":
        return "needs_attention"
    return "completed" if check_payload.get("passed") else "failed"
