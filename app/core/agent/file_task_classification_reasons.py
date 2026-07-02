from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.core.agent.file_task_classification_semantics import semantic_reason_codes


@dataclass
class FileTaskClassificationReasons:
    reason_codes: list[str] = field(default_factory=list)
    known_gap_name: str = ""


def build_classification_reason_codes(
    *,
    reason_codes: list[str],
    planner_policy: str,
    planner_reason: str,
    planner_backend: str,
    known_tool_gap: Mapping[str, Any] | None,
    matched_capabilities: list[str],
    chart_request: bool,
    table_request: bool,
    summary_request: bool,
    translation_request: bool,
    polish_request: bool,
    financial_request: bool,
    ppt_slide_write_request: bool,
    ppt_design_request: bool,
    docx_report_request: bool,
) -> FileTaskClassificationReasons:
    reasons = list(reason_codes or [])
    if planner_policy:
        reasons.append(f"planner_policy:{planner_policy}")
    elif planner_reason == "deferred_to_execution_brief":
        reasons.append("planner_deferred:model_first")
    if planner_backend:
        reasons.append(f"planner_backend:{planner_backend}")

    known_gap_name = ""
    if isinstance(known_tool_gap, Mapping):
        known_gap_name = str(known_tool_gap.get("missing_capability") or "").strip()
        if known_gap_name:
            reasons.append(f"native_tool_gap:{known_gap_name}")

    reasons.extend(f"capability:{name}" for name in matched_capabilities[:4])
    reasons.extend(
        semantic_reason_codes(
            chart_request=chart_request,
            table_request=table_request,
            summary_request=summary_request,
            translation_request=translation_request,
            polish_request=polish_request,
            financial_request=financial_request,
            ppt_slide_write_request=ppt_slide_write_request,
            ppt_design_request=ppt_design_request,
            docx_report_request=docx_report_request,
        )
    )

    return FileTaskClassificationReasons(
        reason_codes=reasons,
        known_gap_name=known_gap_name,
    )
