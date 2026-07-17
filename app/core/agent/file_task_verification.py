# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.agent.file_task_contract import FileTaskRequest
from app.core.agent.tool_design_protocol import TOOL_DESIGN_PROTOCOL


def verification_precheck(
    *,
    request: FileTaskRequest,
    file_changes: List[Dict[str, Any]],
    write_intent: bool,
    model_failed: bool,
    execution_failure: Optional[Dict[str, Any]],
    readonly_fallback_used: bool,
    runtime_status: str,
    tool_runtime_outcome: Optional[Dict[str, Any]],
    tool_gap: Optional[Dict[str, Any]],
    next_action_artifact: Optional[Dict[str, Any]],
    requires_file_change_before_pause: bool,
) -> Optional[Dict[str, Any]]:
    if tool_gap:
        remaining = []
        if tool_gap.get("suggested_next_step"):
            remaining.append(str(tool_gap.get("suggested_next_step")))
        if isinstance(tool_gap.get("proposed_tool"), dict) and tool_gap[
            "proposed_tool"
        ].get("name"):
            remaining.append(
                f"按 {TOOL_DESIGN_PROTOCOL} 评估并实现新工具：{tool_gap['proposed_tool']['name']}"
            )
        if not remaining:
            remaining = ["根据缺口说明补充 Koto 原生工具或调整任务范围"]
        return {
            "passed": False,
            "status": "tool_gap",
            "remaining": remaining,
            "tool_gap": tool_gap,
            "next_action_artifact": next_action_artifact,
        }

    if (
        runtime_status == "awaiting_confirmation"
        and write_intent
        and not file_changes
        and requires_file_change_before_pause
    ):
        return {
            "passed": False,
            "status": "write_not_performed",
            "summary": "任务请求分步写入并等待确认，但本步骤尚未产生任何文件变更。",
            "remaining": ["先调用真实写入工具更新目标文件，再进入等待确认状态"],
            "next_action_artifact": next_action_artifact,
            "criteria_results": [
                {
                    "criterion": "write_before_stepwise_pause",
                    "passed": False,
                    "detail": "分步写入任务必须先产生 file.changed，再等待用户继续。",
                    "priority": "critical",
                }
            ],
        }

    if runtime_status == "awaiting_confirmation":
        outcome = tool_runtime_outcome or {}
        artifact = (
            outcome.get("next_action_artifact")
            if isinstance(outcome.get("next_action_artifact"), dict)
            else next_action_artifact
        )
        remaining: List[str] = []
        if isinstance(artifact, dict):
            suggested = str(
                artifact.get("suggested_next_step") or artifact.get("summary") or ""
            ).strip()
            if suggested:
                remaining.append(suggested)
        if not remaining:
            remaining = ["等待用户确认后继续下一步。"]
        return {
            "passed": False,
            "status": "awaiting_confirmation",
            "summary": str(outcome.get("summary") or "任务已暂停，等待用户确认继续。"),
            "remaining": remaining,
            "next_action_artifact": artifact,
        }

    if runtime_status in {"blocked", "write_blocked"}:
        outcome = tool_runtime_outcome or {}
        suggested = str(outcome.get("suggested_next_step") or "").strip()
        remaining = (
            [suggested] if suggested else ["关闭占用目标文件的程序或页签后重试。"]
        )
        return {
            "passed": False,
            "status": runtime_status,
            "summary": str(outcome.get("summary") or "目标文件当前不可写。"),
            "remaining": remaining,
            "next_action_artifact": next_action_artifact,
        }

    if isinstance(execution_failure, dict) and execution_failure and not file_changes:
        status = str(execution_failure.get("status") or "model_error").strip()
        summary = str(
            execution_failure.get("summary")
            or "文件任务模型调用失败，执行未完成文件写入。"
        ).strip()
        remaining = [
            str(item).strip()
            for item in execution_failure.get("remaining") or []
            if str(item).strip()
        ]
        return {
            "passed": False,
            "status": status,
            "summary": summary,
            "remaining": remaining or ["恢复模型后重新执行文件任务。"],
            "failure": dict(execution_failure),
            "criteria_results": [
                {
                    "criterion": "model_execution_completed",
                    "passed": False,
                    "detail": str(execution_failure.get("detail") or summary),
                    "priority": "critical",
                }
            ],
        }

    if write_intent and not file_changes:
        return {
            "status": "write_not_performed",
            "summary": "模型已完成响应，但没有调用任何成功的文件写入工具。",
            "passed": False,
            "remaining": ["重新执行并确保写入工具成功产生 file.changed 事件。"],
            "criteria_results": [
                {
                    "criterion": "file_change_emitted",
                    "passed": False,
                    "detail": "模型调用已返回，但本轮没有成功的文件写入工具结果。",
                    "priority": "critical",
                }
            ],
        }

    if not write_intent and model_failed:
        return {
            "passed": False,
            "status": "model_unavailable",
            "summary": "模型不可用，已完成显式上下文读取但未生成 AI 分析。",
            "remaining": ["检查云端 API Key 或启动本地 Ollama 后重试"],
        }

    if not write_intent and readonly_fallback_used:
        return {
            "passed": False,
            "status": "context_summary_fallback",
            "summary": "模型未返回完整自然语言答案，已基于显式上下文生成临时摘要，但仍需重新生成完整回答。",
            "remaining": ["恢复模型后重新生成完整 AI 分析，而不是仅使用上下文摘要"],
        }

    return None
