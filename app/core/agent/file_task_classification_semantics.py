# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

from typing import Any


def semantic_reason_codes(
    *,
    chart_request: bool,
    table_request: bool,
    summary_request: bool,
    translation_request: bool,
    polish_request: bool,
    financial_request: bool,
    ppt_slide_write_request: bool,
    ppt_design_request: bool,
    docx_report_request: bool,
) -> list[str]:
    semantic_reason_markers = {
        "chart_request": chart_request,
        "table_request": table_request,
        "summary_request": summary_request,
        "translation_request": translation_request,
        "polish_request": polish_request,
        "financial_request": financial_request,
        "ppt_slide_write_request": ppt_slide_write_request,
        "ppt_design_request": ppt_design_request,
        "docx_report_request": docx_report_request,
    }
    return [name for name, enabled in semantic_reason_markers.items() if enabled]


def infer_task_family_operation(
    *,
    diagnostic_request: bool,
    clear_docx_review_request: bool,
    selected_recipe_match: Any,
    docx_compare_annotate_request: bool,
    docx_annotation_request: bool,
    financial_request: bool,
    chart_request: bool,
    docx_report_request: bool,
    ppt_slide_write_request: bool,
    translation_request: bool,
    polish_request: bool,
    problem_analysis_request: bool,
    summary_request: bool,
    table_request: bool,
    write_intent: bool,
    matched_capabilities: list[str],
    execution_mode: str,
) -> tuple[str, str, bool, list[str], str]:
    task_family = "analyze"
    operation_kind = "read"
    if diagnostic_request:
        task_family = "analyze"
        operation_kind = "read"
    elif clear_docx_review_request:
        task_family = "transform"
        operation_kind = "write"
        docx_annotation_request = False
        if "annotate_file" in matched_capabilities:
            matched_capabilities = [
                name for name in matched_capabilities if name != "annotate_file"
            ]
    elif (
        selected_recipe_match
        and selected_recipe_match.recipe.execution_mode == "doc_annotate_bridge"
    ):
        task_family = selected_recipe_match.recipe.task_family
        operation_kind = selected_recipe_match.recipe.write_operation_kind
        docx_annotation_request = True
    elif (
        selected_recipe_match
        and selected_recipe_match.recipe.id == "docx_contract_compare_review"
    ):
        task_family = selected_recipe_match.recipe.task_family
        operation_kind = selected_recipe_match.recipe.write_operation_kind
    elif (
        selected_recipe_match
        and selected_recipe_match.recipe.id == "docx_compare_annotation"
    ):
        task_family = selected_recipe_match.recipe.task_family
        operation_kind = selected_recipe_match.recipe.write_operation_kind
        if "annotate_file" in matched_capabilities:
            matched_capabilities = [
                name for name in matched_capabilities if name != "annotate_file"
            ]
    elif docx_compare_annotate_request:
        task_family = "compare"
        operation_kind = "compare_annotate"
    elif docx_annotation_request or "annotate_file" in matched_capabilities:
        task_family = "annotate"
        operation_kind = "annotate"
    elif selected_recipe_match:
        task_family = selected_recipe_match.recipe.task_family
        operation_kind = (
            selected_recipe_match.recipe.write_operation_kind
            if write_intent
            else selected_recipe_match.recipe.read_operation_kind
        )
        for capability in selected_recipe_match.recipe.matched_capabilities:
            if capability not in matched_capabilities:
                matched_capabilities.append(capability)
        if selected_recipe_match.recipe.execution_mode != "generic_tool_loop":
            execution_mode = selected_recipe_match.recipe.execution_mode
    elif financial_request and chart_request and docx_report_request:
        task_family = "financial_report"
        operation_kind = (
            "analyze_visualize_write" if write_intent else "analyze_visualize"
        )
    elif "compare_files" in matched_capabilities:
        task_family = "compare"
        operation_kind = "compare"
    elif ppt_slide_write_request:
        task_family = "presentation"
        operation_kind = "write_slides" if write_intent else "read"
    elif translation_request:
        task_family = "translate"
        operation_kind = "write" if write_intent else "read"
    elif polish_request:
        task_family = "polish"
        operation_kind = "write" if write_intent else "read"
    elif problem_analysis_request:
        task_family = "analyze"
        operation_kind = "write" if write_intent else "read"
    elif summary_request:
        task_family = "summarize"
        operation_kind = "write" if write_intent else "read"
    elif chart_request:
        task_family = "visualize"
        operation_kind = "visualize_write" if write_intent else "visualize"
    elif table_request and write_intent:
        task_family = "table_transfer"
        operation_kind = "write_table"
    elif "run_python_code" in matched_capabilities:
        task_family = "automation"
        operation_kind = "compute"
    elif write_intent:
        task_family = "transform"
        operation_kind = "write"
    return (
        task_family,
        operation_kind,
        docx_annotation_request,
        matched_capabilities,
        execution_mode,
    )
