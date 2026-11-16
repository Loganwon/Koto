# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from app.core.agent.file_task_contract import FileTaskRequest
from app.core.agent.file_task_explicit_quality_gates import (
    _explicit_bullet_count_gate,
    _explicit_chart_output_requested,
    _explicit_docx_section_gates,
    _explicit_required_phrase_gate,
    _explicit_slide_count_gate,
    _pptx_native_visual_requirement_gate,
    _quality_target_paths,
    _resolve_quality_path,
    _source_content_in_output_gate,
    _spreadsheet_chart_requirement_gate,
    _spreadsheet_formula_requirement_gate,
    _target_docx_quality_paragraph_count,
    _target_text_for_quality_gate,
    _top_table_requirement_gate,
    quality_gate_result,
)
from app.core.agent.file_task_targeting import files_explicitly_mentioned_in_task

_DOCX_TABLE_OUTPUT_PATTERN = re.compile(
    r"(?:创建|新增|生成|插入|添加|加入|追加|写入|放入|包含|包括|附上).{0,40}"
    r"(?:真实\s*)?(?:word|docx|文档)?\s*(?:表格|table)"
    r"|(?:真实\s*)?(?:word|docx|文档)?\s*(?:表格|table).{0,40}"
    r"(?:创建|新增|生成|插入|添加|加入|追加|写入|放入|包含|包括|附上)"
    r"|(?:create|add|insert|append|write|include|put).{0,40}"
    r"(?:real\s*)?(?:word|docx|document)?\s*table"
    r"|(?:风险登记表|风险表|risk\s+register\s+table)",
    re.IGNORECASE,
)


def should_attempt_repair(
    check_payload: Dict[str, Any] | None,
    *,
    round_index: int,
    repair_attempts: int,
    max_rounds: int,
    max_repair_attempts: int,
) -> bool:
    if not isinstance(check_payload, dict):
        return False
    if repair_attempts >= max_repair_attempts:
        return False
    if round_index >= max_rounds:
        return False
    if bool(check_payload.get("passed")):
        return False
    status = str(check_payload.get("status") or "").strip().lower()
    return status in {
        "write_not_performed",
        "quality_gate_failed",
    }


def change_operations(file_changes: List[Dict[str, Any]]) -> set[str]:
    return {
        str(change.get("operation") or "").strip()
        for change in file_changes
        if str(change.get("operation") or "").strip()
    }


def change_sum_int(file_changes: List[Dict[str, Any]], key: str) -> int:
    total = 0
    for change in file_changes:
        try:
            total += int(change.get(key) or 0)
        except Exception:
            continue
    return total


def target_or_request_type(
    request: FileTaskRequest,
    file_changes: List[Dict[str, Any]],
) -> str:
    target_type = Path(str(request.target_path or "")).suffix.lstrip(".").lower()
    if target_type:
        return target_type
    for change in file_changes:
        candidate = (
            str(
                change.get("file_type")
                or Path(str(change.get("path") or "")).suffix.lstrip(".")
            )
            .lower()
            .strip()
        )
        if candidate:
            return candidate
    for file_info in request.files or []:
        if file_info.target:
            candidate = (
                str(
                    file_info.type
                    or Path(str(file_info.path or file_info.name)).suffix.lstrip(".")
                )
                .lower()
                .strip()
            )
            if candidate:
                return candidate
    return ""


def evaluate_task_quality_gate(
    request: FileTaskRequest,
    file_changes: List[Dict[str, Any]],
    *,
    write_intent: bool,
    output_mode: str,
) -> Dict[str, Any]:
    del output_mode
    if not write_intent:
        return {"passed": True, "criteria_results": [], "remaining": []}

    operations = change_operations(file_changes)
    target_type = target_or_request_type(request, file_changes)
    paragraphs_written = change_sum_int(file_changes, "paragraphs_written")
    images_inserted = change_sum_int(file_changes, "images_inserted")
    rows_written = change_sum_int(file_changes, "rows_written")
    cells_written = change_sum_int(file_changes, "cells_written")
    slides_updated = change_sum_int(file_changes, "slides_updated")
    slides_added = change_sum_int(file_changes, "slides_added")
    slides_designed = change_sum_int(file_changes, "slides_designed")
    text_shapes_styled = change_sum_int(file_changes, "text_shapes_styled")
    annotations_added = change_sum_int(file_changes, "annotations_added")
    differences_detected = change_sum_int(file_changes, "differences_detected")
    comments_removed = change_sum_int(file_changes, "comments_removed")
    revisions_accepted = change_sum_int(file_changes, "revisions_accepted")
    paragraphs_rewritten = change_sum_int(file_changes, "paragraphs_rewritten")
    placeholders_replaced = change_sum_int(file_changes, "placeholders_replaced")
    task_text = str(request.task or "")
    local_docx_replace_request = target_type in {
        "docx",
        "doc",
    } and _looks_like_local_docx_replace_request(task_text)
    local_docx_edit_request = (
        target_type in {"docx", "doc"}
        and (
            _looks_like_local_docx_edit_request(task_text) or local_docx_replace_request
        )
        and not _looks_like_docx_table_output_request(task_text)
    )
    actual_docx_paragraphs = (
        _target_docx_quality_paragraph_count(request, file_changes)
        if target_type in {"docx", "doc"} and file_changes
        else 0
    )

    criteria: List[Dict[str, Any]] = []
    explicit_source_content_gate = _source_content_in_output_gate(request, file_changes)
    explicit_top_table_gate = _top_table_requirement_gate(request, file_changes)
    explicit_section_gates = _explicit_docx_section_gates(request, file_changes)
    explicit_phrase_gate = _explicit_required_phrase_gate(request, file_changes)
    explicit_bullet_count_gate = _explicit_bullet_count_gate(request, file_changes)
    explicit_slide_count_gate = _explicit_slide_count_gate(
        request, file_changes, target_type
    )
    explicit_pptx_native_visual_gate = _pptx_native_visual_requirement_gate(
        request,
        file_changes,
        target_type,
    )
    explicit_spreadsheet_chart_gate = _spreadsheet_chart_requirement_gate(
        request,
        file_changes,
        target_type,
    )
    explicit_spreadsheet_formula_gate = _spreadsheet_formula_requirement_gate(
        request,
        file_changes,
        target_type,
    )
    explicit_docx_table_gate = _docx_table_requirement_gate(
        request,
        file_changes,
        target_type,
        operations,
        rows_written,
    )
    if target_type in {"docx", "doc"} and _explicit_chart_output_requested(task_text):
        criteria.append(
            quality_gate_result(
                criterion="docx_chart_request_has_image",
                passed="insert_image_into_docx" in operations and images_inserted >= 1,
                detail=f"用户要求图表/图片进入 Word；当前图片写入数：{images_inserted}。",
                priority="critical",
            )
        )

    if local_docx_edit_request:
        if local_docx_replace_request:
            targeted_replace_ops = {"run_python_code", "rewrite_docx_paragraph_window"}
            criteria.append(
                quality_gate_result(
                    criterion="docx_local_replace_has_targeted_write",
                    passed=bool(file_changes)
                    and bool(operations.intersection(targeted_replace_ops)),
                    detail=(
                        "DOCX 定位替换应在保留原结构的前提下完成一次目标写回；"
                        f"当前操作：{', '.join(sorted(operations)) or '无'}，"
                        f"目标变更数：{len(file_changes)}。"
                    ),
                    priority="high",
                )
            )
        else:
            inserted_text = any(
                str(change.get("inserted_text") or "").strip()
                for change in file_changes
                if str(change.get("operation") or "").strip() == "insert_docx_paragraph"
            )
            criteria.append(
                quality_gate_result(
                    criterion="docx_local_edit_has_paragraph_insert",
                    passed="insert_docx_paragraph" in operations
                    and (paragraphs_written >= 1 or inserted_text),
                    detail=(
                        "局部 Word 编辑任务应使用保留原结构的段落插入工具；"
                        f"当前操作：{', '.join(sorted(operations)) or '无'}，"
                        f"段落插入数：{paragraphs_written}。"
                    ),
                    priority="high",
                )
            )
        if explicit_source_content_gate:
            criteria.append(explicit_source_content_gate)
        criteria.extend(explicit_section_gates)
        if explicit_phrase_gate:
            criteria.append(explicit_phrase_gate)
        if explicit_bullet_count_gate:
            criteria.append(explicit_bullet_count_gate)
        if explicit_slide_count_gate:
            criteria.append(explicit_slide_count_gate)
        failed = [item for item in criteria if not item.get("passed")]
        return {
            "passed": not failed,
            "criteria_results": criteria,
            "remaining": [
                str(item.get("detail") or item.get("criterion")) for item in failed
            ],
        }

    if explicit_docx_table_gate:
        criteria.append(explicit_docx_table_gate)
        table_narrative_gate = _table_narrative_requirement_gate(
            task_text,
            target_type,
            operations,
            paragraphs_written,
        )
        if table_narrative_gate:
            criteria.append(table_narrative_gate)

    if target_type in {"docx", "doc"} and operations.intersection(
        {"compare_docx_and_annotate", "write_docx_comments"}
    ):
        criteria.append(
            quality_gate_result(
                criterion="docx_compare_has_difference_annotations",
                passed=annotations_added > 0,
                detail=f"DOCX 对比标注任务必须写入真实差异批注；当前批注数：{annotations_added}。",
                priority="critical",
            )
        )

    if target_type in {"docx", "doc"} and not criteria:
        docx_write_ops = {
            "write_docx_content",
            "insert_excel_as_docx_table",
            "insert_image_into_docx",
            "compare_docx_and_annotate",
            "clear_docx_review_marks",
            "insert_docx_paragraph",
            "fill_docx_template",
            "rewrite_docx_paragraph_window",
        }
        docx_metric_total = (
            paragraphs_written
            + images_inserted
            + rows_written
            + annotations_added
            + differences_detected
            + comments_removed
            + revisions_accepted
            + paragraphs_rewritten
            + placeholders_replaced
        )
        run_python_docx_writeback = (
            "run_python_code" in operations
            and bool(file_changes)
            and actual_docx_paragraphs > 0
        )
        criteria.append(
            quality_gate_result(
                criterion="generic_docx_has_native_write",
                passed=bool(operations.intersection(docx_write_ops))
                and docx_metric_total > 0
                or run_python_docx_writeback,
                detail=(
                    "DOCX 写入任务必须产生可核验的 Word 原生写入指标；"
                    f"当前操作：{', '.join(sorted(operations)) or '无'}，"
                    f"段落/图片/表格/批注/修订指标合计：{docx_metric_total}。"
                ),
                priority="high",
            )
        )

    if target_type in {"pptx", "ppt"} and not criteria:
        pptx_write_ops = {
            "add_pptx_slides",
            "write_pptx_slides",
            "design_pptx_theme_layout",
        }
        pptx_metric_total = (
            slides_updated + slides_added + slides_designed + text_shapes_styled
        )
        criteria.append(
            quality_gate_result(
                criterion="generic_pptx_has_native_write",
                passed=bool(operations.intersection(pptx_write_ops))
                and pptx_metric_total > 0,
                detail=(
                    "PPTX 写入任务必须产生可核验的幻灯片写入、更新或设计指标；"
                    f"当前操作：{', '.join(sorted(operations)) or '无'}，"
                    f"幻灯片/文本样式指标合计：{pptx_metric_total}。"
                ),
                priority="high",
            )
        )

    if target_type in {"xlsx", "xlsm"} and not criteria:
        spreadsheet_metric_total = rows_written + cells_written
        spreadsheet_write_ops = {"write_sheet_data", "run_python_code"}
        criteria.append(
            quality_gate_result(
                criterion="generic_spreadsheet_has_native_write",
                passed=bool(operations.intersection(spreadsheet_write_ops))
                and spreadsheet_metric_total > 0,
                detail=(
                    "表格写入任务必须产生可核验的单元格/行写入指标；"
                    f"当前操作：{', '.join(sorted(operations)) or '无'}，"
                    f"行/单元格指标合计：{spreadsheet_metric_total}。"
                ),
                priority="high",
            )
        )

    if target_type == "csv" and not criteria:
        csv_metric_total = rows_written + cells_written
        csv_write_ops = {
            "create_file",
            "run_python_code",
            "write_sheet_data",
        }
        csv_output_text = _target_text_for_quality_gate(request, file_changes)
        csv_has_content = bool(str(csv_output_text or "").strip())
        csv_replacements = change_sum_int(
            [
                change
                for change in _target_write_changes(request, file_changes)
                if str(change.get("operation") or "") == "replace_file_selection"
            ],
            "replacements_made",
        )
        native_selection_write = csv_replacements > 0 and csv_has_content
        criteria.append(
            quality_gate_result(
                criterion="generic_csv_has_written_content",
                passed=(
                    bool(operations.intersection(csv_write_ops))
                    and (csv_metric_total > 0 or csv_has_content)
                )
                or native_selection_write,
                detail=(
                    "CSV 写入任务必须产生非空 CSV 内容或可核验的行/单元格指标；"
                    f"当前操作：{', '.join(sorted(operations)) or '无'}，"
                    f"行/单元格指标合计：{csv_metric_total}，"
                    f"原生精确替换数：{csv_replacements}，"
                    f"CSV 内容：{'已生成' if csv_has_content else '未检测到'}。"
                ),
                priority="high",
            )
        )

    if explicit_source_content_gate:
        criteria.append(explicit_source_content_gate)
    if explicit_top_table_gate:
        criteria.append(explicit_top_table_gate)
    criteria.extend(explicit_section_gates)
    if explicit_phrase_gate:
        criteria.append(explicit_phrase_gate)
    if explicit_bullet_count_gate:
        criteria.append(explicit_bullet_count_gate)
    if explicit_slide_count_gate:
        criteria.append(explicit_slide_count_gate)
    if explicit_pptx_native_visual_gate:
        criteria.append(explicit_pptx_native_visual_gate)
    if explicit_spreadsheet_chart_gate:
        criteria.append(explicit_spreadsheet_chart_gate)
    if explicit_spreadsheet_formula_gate:
        criteria.append(explicit_spreadsheet_formula_gate)

    failed = [item for item in criteria if not item.get("passed")]
    return {
        "passed": not failed,
        "criteria_results": criteria,
        "remaining": [
            str(item.get("detail") or item.get("criterion")) for item in failed
        ],
    }


def repair_retry_message(
    request: FileTaskRequest,
    check_payload: Dict[str, Any],
    file_changes: List[Dict[str, Any]],
) -> str:
    lines = [
        "核验未通过，当前任务还不能结束。下一轮必须修复目标文件，而不是重复上一轮完全相同的调用。",
    ]
    status = str(check_payload.get("status") or "").strip()
    summary = str(check_payload.get("summary") or "").strip()
    if status:
        lines.append(f"当前核验状态：{status}")
    if summary:
        lines.append(f"核验摘要：{summary}")
    if request.target_path:
        lines.append(f"目标文件：{request.target_path}")

    request_files = list(getattr(request, "files", []) or [])
    if not request_files:
        request_files.extend(
            files_explicitly_mentioned_in_task(
                workspace_root=Path.cwd() / "workspace",
                task=request.task,
            )
        )
    remaining = (
        check_payload.get("remaining")
        if isinstance(check_payload.get("remaining"), list)
        else []
    )
    if remaining:
        lines.append("仍需满足：")
        for index, item in enumerate(remaining[:5], start=1):
            text = str(item or "").strip()
            if text:
                lines.append(f"{index}. {text}")

    if any(
        "表格" in str(item or "") and "Word" in str(item or "") for item in remaining
    ):
        target_path = str(request.target_path or "").strip()
        xlsx_sources = [
            str(file_info.path or file_info.name or "").strip()
            for file_info in request_files
            if str(
                file_info.type
                or Path(str(file_info.path or file_info.name)).suffix.lstrip(".")
            )
            .lower()
            .strip()
            in {"xlsx", "xlsm", "xls", "csv"}
            and str(file_info.path or file_info.name or "").strip()
        ]
        if xlsx_sources:
            lines.append(
                "表格修复要求：调用 insert_excel_as_docx_table，把源表格作为真实 Word 表格写入目标 DOCX；"
                "只调用 write_docx_content 写文字段落不能通过。"
            )
            lines.append(f"推荐 source_path：{xlsx_sources[0]}")
        else:
            lines.append(
                "表格修复要求：当前没有表格源文件。请使用可用的原生 Word 表格写入能力，"
                "或通过 run_python_code 使用 python-docx 打开并保存 TASK_TARGET_PATH，"
                "在该沙箱目标中创建真实 table；不要直接写宿主绝对路径。"
                "只写标题和文字段落不能通过。"
            )
        if target_path:
            lines.append(f"推荐 target_path：{target_path}")

    if file_changes:
        lines.append("已观察到的文件变更：")
        for change in file_changes[-3:]:
            if not isinstance(change, dict):
                continue
            change_summary = str(change.get("summary") or "").strip()
            path_text = str(change.get("path") or change.get("file_path") or "").strip()
            if change_summary and path_text:
                lines.append(f"- {path_text}: {change_summary}")
            elif change_summary:
                lines.append(f"- {change_summary}")
            elif path_text:
                lines.append(f"- {path_text}")

    lines.append(
        "要求：先理解核验失败原因；只有当参数、代码、工具选择或写入位置已经改变时，才允许再次调用工具；修复后再结束。"
    )
    return "\n".join(lines)


def success_criteria(
    request: FileTaskRequest,
    *,
    write_intent: bool,
    output_mode: str,
) -> List[str]:
    criteria = [
        "每个步骤都产生 typed event，可被前端时间线渲染",
        "所有上下文来源都来自显式输入",
    ]
    if write_intent:
        criteria.extend(
            [
                "写入工具必须产生 file.changed 事件",
                "最终 checker 必须确认目标文件已更新",
            ]
        )
    elif output_mode == "hybrid":
        criteria.append("最终摘要必须给出明确建议，且当前轮不默认直接写入原文件")
    else:
        criteria.append("最终摘要说明已使用的上下文和未完成项")
    return criteria


def _looks_like_docx_table_output_request(task: str) -> bool:
    # A preservation constraint is not a table-creation requirement. Evaluate
    # clauses separately so an earlier "append a paragraph" cannot borrow the
    # word "table" from the next "keep the table unchanged" clause.
    clauses = re.split(r"[,，。;；\n]", str(task or ""))
    for clause in clauses:
        protected = re.search(
            r"(?:保留|保持|\bkeep\b|\bpreserve\b).*(?:表格|\btable\b).*(?:不变|原样|\bunchanged\b|\bintact\b)",
            clause,
            re.IGNORECASE,
        )
        if protected:
            clause = clause[: protected.start()] + clause[protected.end() :]
        if _DOCX_TABLE_OUTPUT_PATTERN.search(clause):
            return True
    return False


def _docx_table_requirement_gate(
    request: FileTaskRequest,
    file_changes: List[Dict[str, Any]],
    target_type: str,
    operations: set[str],
    reported_rows: int,
) -> Dict[str, Any] | None:
    task = str(request.task or "")
    if target_type not in {"docx", "doc"}:
        return None
    if not _looks_like_docx_table_output_request(task):
        return None
    table_count, actual_rows, max_columns = _target_docx_quality_table_metrics(
        request, file_changes
    )
    target_changes = _target_write_changes(request, file_changes)
    native_insert = any(
        str(change.get("operation") or "") == "insert_excel_as_docx_table"
        and change_sum_int([change], "rows_written") > 0
        and (
            change.get("structure_verified") is not True
            or _positive_table_delta(change, table_count)
        )
        for change in target_changes
    )
    verified_new_tables = any(
        change.get("structure_verified") is True
        and _positive_table_delta(change, table_count)
        for change in target_changes
    )
    table_present = table_count >= 1 and actual_rows >= 2 and max_columns >= 2
    # A current table proves inclusion, never that this run inserted one. A
    # distinct insertion contract needs the native insertion receipt or a
    # host-verified before/after structural increase on the same target.
    insertion_required = _requires_new_docx_table(task)
    passed = native_insert or (
        table_present and (not insertion_required or verified_new_tables)
    )
    return quality_gate_result(
        criterion="docx_table_request_has_table",
        passed=passed,
        detail=(
            "用户要求表格数据进入 Word；"
            f"工具报告写入行数：{reported_rows}，"
            f"目标文档实际表格数：{table_count}，"
            f"实际表格总行数：{actual_rows}，最大列数：{max_columns}。"
            + (
                f" 本轮要求新增表格；新增操作回执：{'有' if native_insert else '无'}，"
                f"已核实的结构增量：{'有' if verified_new_tables else '无'}。"
                if insertion_required
                else ""
            )
        ),
        priority="critical",
    )


def _requires_new_docx_table(task: str) -> bool:
    # These clauses express the acceptance criterion, not a routing decision.
    # Presence-only contracts ("include a table") retain their old behavior.
    for clause in re.split(r"[,，。;；\n]", str(task or "")):
        if not _looks_like_docx_table_output_request(clause):
            continue
        if re.search(
            r"(?:创建|新增|生成|插入|添加|加入|追加|放入|附上).{0,40}(?:表格|table|风险登记表|风险表)"
            r"|\b(?:create|add|insert|append|put)\b.{0,40}\b(?:table|risk\s+register)\b"
            r"|(?:新(?:的)?|另一个|\bnew\b|\banother\b).{0,12}(?:表格|\btable\b)",
            clause,
            re.IGNORECASE,
        ):
            return True
    return False


def _positive_table_delta(change: Dict[str, Any], current_count: int) -> bool:
    try:
        before = int(change["docx_tables_before"])
        after = int(change["docx_tables_after"])
        return before >= 0 and after > before and current_count >= after
    except (KeyError, TypeError, ValueError):
        return False


def _target_write_changes(request, file_changes):
    from app.core.agent.file_task_artifact_transaction import resolved_write_path

    target = str(request.target_path or "").strip()
    if not target:
        return [
            change
            for change in file_changes
            if isinstance(change, dict)
            and any(
                str(change.get(key) or "").strip()
                for key in ("path", "file_path", "target_path")
            )
        ]
    target_key = str(resolved_write_path(target)).casefold()
    matched = []
    for change in file_changes:
        if not isinstance(change, dict):
            continue
        for key in ("path", "file_path", "target_path"):
            value = str(change.get(key) or "").strip()
            if not value:
                continue
            if str(resolved_write_path(value)).casefold() == target_key:
                matched.append(change)
                break
    return matched


def _target_docx_quality_table_metrics(
    request: FileTaskRequest, file_changes: List[Dict[str, Any]]
) -> tuple[int, int, int]:
    best = (0, 0, 0)
    paths = (
        {str(request.target_path)}
        if request.target_path
        else _quality_target_paths(request, file_changes)
    )
    for path_text in paths:
        if not str(path_text or "").lower().endswith((".docx", ".doc")):
            continue
        resolved = _resolve_quality_path(path_text)
        if not resolved:
            continue
        try:
            from docx import Document
            from docx.oxml.ns import qn
            from docx.table import Table

            document = Document(str(resolved))
        except Exception:
            continue
        # Match the transaction's XML counts, including nested Word tables.
        tables = [
            Table(node, document._body)
            for node in document.element.body.iter(qn("w:tbl"))
        ]
        table_count = len(tables)
        total_rows = sum(len(table.rows) for table in tables)
        max_columns = max((len(table.columns) for table in tables), default=0)
        best = max(best, (table_count, total_rows, max_columns))
    return best


def _table_narrative_requirement_gate(
    task: str,
    target_type: str,
    operations: set[str],
    paragraphs_written: int,
) -> Dict[str, Any] | None:
    if target_type not in {"docx", "doc"}:
        return None
    if not re.search(
        r"(?:表格.{0,24}(?:说明|摘要|总结|结论|分析|要点)|"
        r"(?:说明|摘要|总结|结论|分析|要点|写一句|一句简短说明).{0,40}表格|"
        r"\b(?:summary|narrative|explanation|analysis|conclusion)\b.{0,40}\btable\b|"
        r"\btable\b.{0,40}\b(?:summary|narrative|explanation|analysis|conclusion)\b)",
        task,
        re.IGNORECASE,
    ):
        return None
    return quality_gate_result(
        criterion="docx_table_request_has_narrative",
        passed="write_docx_content" in operations and paragraphs_written >= 1,
        detail=(
            "用户要求 Word 表格配套文字说明/摘要；"
            f"当前说明段落写入数：{paragraphs_written}。"
        ),
        priority="high",
    )


def _looks_like_local_docx_edit_request(task: str) -> bool:
    text = str(task or "")
    if not text.strip():
        return False
    return bool(
        re.search(
            r"(?:只|仅|只是|仅仅)?(?:追加|添加|插入|加上|补充|写入).{0,30}"
            r"(?:一句|一段|一条|少量|这句|这段|文本|段落)",
            text,
            re.IGNORECASE,
        )
        or re.search(
            r"(?:保留|保持).{0,30}(?:已有|现有|原有).{0,20}"
            r"(?:表格|结构|内容|格式).{0,12}(?:不变|不修改|不要改|原样)",
            text,
            re.IGNORECASE,
        )
        or re.search(
            r"\b(?:append|insert|add)\b.{0,50}\b(?:sentence|paragraph|line)\b",
            text,
            re.IGNORECASE,
        )
        or re.search(
            r"\b(?:keep|preserve)\b.{0,40}\b(?:existing|current|original)\b"
            r".{0,30}\b(?:table|structure|content|format)\b",
            text,
            re.IGNORECASE,
        )
    )


def _looks_like_local_docx_replace_request(task: str) -> bool:
    text = str(task or "")
    if not text.strip():
        return False
    return bool(
        re.search(
            r"(?:只替换|仅替换|替换.{0,16}(?:一处|那一处|这一处|第\s*\d+\s*处|第\s*\d+\s*段)|"
            r"(?:第\s*\d+\s*段|一处|那一处|这一处).{0,24}(?:替换|删除|改成|换成)|"
            r"local(?:ized)?\s+(?:replace|edit)|replace\s+only)",
            text,
            re.IGNORECASE,
        )
    )
