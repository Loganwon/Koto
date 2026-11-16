"""User-facing read guards and terminal completion gates for file tasks."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from app.core.agent.file_task_evidence_policy import requires_readonly_source_coverage
from app.core.agent.file_task_evidence_validation import (
    answer_declares_incomplete_read,
    missing_readonly_source_coverage,
)


def source_coverage_guard_message(*, task: str, missing: List[str]) -> str:
    missing_text = "、".join(missing) or "各来源文件的完整读取证据"
    return (
        "当前只读分析的来源覆盖不足，不能把预览片段当作完整文件，也不能以‘建议继续读取’结束任务。\n"
        f"用户任务：{task}\n"
        f"仍缺少：{missing_text}。\n"
        "请为每个参与分析或比较的文件调用适合的读取工具：DOCX 使用 read_docx_content 并确认 "
        "truncated=false，表格行数与 row_count 一致；Excel/CSV 使用 read_sheet_data；其他格式使用 "
        "parse_file_to_text。所有来源覆盖后再输出逐项差异、共同点和无法确认项。"
    )


def apply_readonly_source_coverage_completion_gate(
    *,
    check_payload: Dict[str, Any],
    task: str,
    files: Iterable[Any],
    final_summary: str,
    readonly_tool_outputs: Iterable[Dict[str, Any]],
    write_intent: bool,
) -> Dict[str, Any]:
    payload = dict(check_payload)
    file_list = list(files or [])
    if (
        write_intent
        or not payload.get("passed")
        or not requires_readonly_source_coverage(task, file_list)
    ):
        return payload
    missing = missing_readonly_source_coverage(file_list, readonly_tool_outputs)
    self_reported_gap = answer_declares_incomplete_read(final_summary)
    if not missing and not self_reported_gap:
        return payload

    remaining = list(missing)
    if self_reported_gap:
        remaining.append("最终回答仍明确声明来源读取不完整")
    payload.update(
        {
            "passed": False,
            "status": "analysis_incomplete",
            "summary": "只读分析未完成：参与分析的来源文件尚未全部取得完整读取证据。",
            "remaining": remaining,
            "criteria_results": [
                {
                    "criterion": "readonly_source_coverage",
                    "passed": False,
                    "detail": "；".join(remaining),
                    "priority": "critical",
                }
            ],
        }
    )
    return payload


def apply_declared_incomplete_read_completion_gate(
    *,
    check_payload: Dict[str, Any],
    files: Iterable[Any],
    final_summary: str,
    write_intent: bool,
) -> Dict[str, Any]:
    """Never mark a file analysis complete when its answer says reading is pending."""
    payload = dict(check_payload)
    if (
        write_intent
        or not payload.get("passed")
        or not list(files or [])
        or not answer_declares_incomplete_read(final_summary)
    ):
        return payload
    detail = "最终回答明确声明仍有文件内容未读取。"
    payload.update(
        {
            "passed": False,
            "status": "analysis_incomplete",
            "summary": "只读文件分析未完成：最终回答仍声明存在未读取内容。",
            "remaining": [detail],
            "criteria_results": [
                {
                    "criterion": "declared_file_read_completeness",
                    "passed": False,
                    "detail": detail,
                    "priority": "critical",
                }
            ],
        }
    )
    return payload


__all__ = [
    "apply_declared_incomplete_read_completion_gate",
    "apply_readonly_source_coverage_completion_gate",
    "source_coverage_guard_message",
]
