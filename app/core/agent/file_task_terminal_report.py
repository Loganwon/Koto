# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

from typing import Any, Dict, List


def apply_terminal_check_overrides(
    *,
    check_payload: Dict[str, Any],
    write_intent: bool,
    file_changes: List[Dict[str, Any]],
    final_summary: str,
    output_mode: str,
    tool_gap: Dict[str, Any] | None,
    snippets: List[Dict[str, Any]],
    readonly_tool_outputs: List[Dict[str, Any]],
    requires_file_context: bool,
    missing_read_refs: List[str],
) -> Dict[str, Any]:
    payload = dict(check_payload)
    no_read_context = not snippets and not readonly_tool_outputs

    if (
        not file_changes
        and no_read_context
        and requires_file_context
        and not tool_gap
    ):
        payload["passed"] = False
        payload["status"] = "needs_attention"
        payload["summary"] = "任务明确要求读取文件，但没有成功读取任何显式文件上下文。"
        payload["remaining"] = [
            "确认文件位于工作区内，或将目标文件加入临时工作区后重试。"
        ]
        payload["criteria_results"] = [
            {
                "criterion": "explicit_file_context_read",
                "passed": False,
                "detail": "任务包含明确文件引用，但运行时没有可用于分析的读取片段。",
                "priority": "critical",
            }
        ]
        return payload

    if not file_changes and missing_read_refs and not tool_gap:
        refs_text = "、".join(missing_read_refs[:3])
        payload["passed"] = False
        payload["status"] = "needs_attention"
        payload["summary"] = (
            f"任务明确要求读取文件，但没有成功读取目标文件：{refs_text}。"
        )
        payload["remaining"] = [
            "确认文件名和路径是否正确，或将目标文件加入临时工作区后重试。"
        ]
        payload["criteria_results"] = [
            {
                "criterion": "explicit_file_reference_read",
                "passed": False,
                "detail": "任务包含明确文件引用，但读取结果没有覆盖该目标文件。",
                "priority": "critical",
            }
        ]
        return payload

    if (
        not write_intent
        and final_summary
        and not tool_gap
        and payload.get("passed")
        and output_mode == "hybrid"
    ):
        payload["summary"] = final_summary

    return payload


def build_terminal_run_summary(
    *,
    check_payload: Dict[str, Any],
    final_summary: str,
    write_intent: bool,
    tool_gap: Dict[str, Any] | None,
    selected_recipe: str,
    file_changes: List[Dict[str, Any]],
) -> str:
    run_summary = check_payload.get("summary") or final_summary or "任务执行结束。"
    if not write_intent and final_summary and not tool_gap:
        run_summary = final_summary
    if selected_recipe == "docx_contract_compare_review":
        contract_risks = None
        for change in file_changes:
            risks = (
                change.get("contract_risk_summary")
                if isinstance(change, dict)
                else None
            )
            if isinstance(risks, list) and risks:
                contract_risks = risks
                break
        if (
            isinstance(contract_risks, list)
            and contract_risks
            and "风险关注点" not in str(run_summary)
        ):
            risk_lines = "\n".join(f"- {item}" for item in contract_risks[:5])
            run_summary = f"{run_summary}\n风险关注点：\n{risk_lines}"
    return str(run_summary)


def terminal_completed_task(
    *,
    check_payload: Dict[str, Any],
    completed_task: bool,
    write_intent: bool,
    file_changes: List[Dict[str, Any]],
) -> bool:
    return bool(check_payload.get("passed")) and (
        completed_task or not write_intent or bool(file_changes)
    )
