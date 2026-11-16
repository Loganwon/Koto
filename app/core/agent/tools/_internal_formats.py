"""Internal helpers: format-specific helpers."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from app.core.agent.toolkits.foundation.pdf_window import (
    read_pdf_excerpt as _foundation_read_pdf_excerpt,
)
from app.core.agent.toolkits.foundation.pdf_window import (
    read_pdf_letter_window as _foundation_read_pdf_letter_window,
)
from app.core.agent.toolkits.foundation.pptx import PptxOperationContext
from app.core.agent.toolkits.foundation.xlsx_sheet_selection import (
    sheet_matches_statement as _sheet_matches_statement,
)
from app.core.agent.toolkits.foundation.xlsx_structure import (
    collect_formula_examples as _collect_formula_examples,
)
from app.core.agent.toolkits.foundation.xlsx_structure import (
    detect_year_header as _detect_year_header,
)
from app.core.agent.toolkits.foundation.xlsx_structure import (
    display_series_value as _display_series_value,
)
from app.core.agent.toolkits.foundation.xlsx_structure import (
    extract_external_link_targets as _extract_external_link_targets,
)
from app.core.agent.toolkits.foundation.xlsx_structure import (
    row_label_for_year_series as _row_label_for_year_series,
)
from app.core.agent.toolkits.foundation.xlsx_structure import (
    sample_sheet_rows as _sample_sheet_rows,
)
from app.core.agent.toolkits.foundation.xlsx_structure import (
    severity_for_financial_label as _xlsx_severity_for_financial_label,
)

from ..task_tools_common import (
    _HIGH_PRIORITY_FINANCIAL_LABEL_HINTS,
    _TEXT_LIMIT_MAX,
    _TEXT_LIMIT_MIN,
)
from ._internal_backup import (  # noqa: F401
    _best_effort_backup,
    _ensure_existing_file_writable,
    _nonwritable_target_message,
    _nonwritable_target_next_step,
)
from ._internal_fs import _resolve_path, _result_path  # noqa: F401
from ._internal_results import _blocked_write_result, _success_result  # noqa: F401
from ._internal_tempfile import _save_pptx_via_temp_file  # noqa: F401
from ._internal_warnings import _merge_warnings  # noqa: F401

logger = logging.getLogger(__name__)


def _pptx_operation_context() -> PptxOperationContext:
    """Bind shared mutation services without coupling PPTX code to this facade."""

    return PptxOperationContext(
        resolve_path=_resolve_path,
        result_path=_result_path,
        best_effort_backup=_best_effort_backup,
        ensure_existing_file_writable=_ensure_existing_file_writable,
        merge_warnings=_merge_warnings,
        nonwritable_target_message=_nonwritable_target_message,
        nonwritable_target_next_step=_nonwritable_target_next_step,
        save_presentation=_save_pptx_via_temp_file,
        success_result=_success_result,
        blocked_write_result=_blocked_write_result,
    )


def _next_available_docx_copy_path(target_path: str) -> str:
    target = str(target_path or "").strip()
    if not target:
        raise ValueError("target_path is required")

    directory = os.path.dirname(target) or os.getcwd()
    target_path_obj = Path(target)
    stem = target_path_obj.stem or "document"
    suffix = target_path_obj.suffix or ".docx"
    for index in range(1, 1000):
        copy_suffix = ".koto-copy" if index == 1 else f".koto-copy-{index}"
        candidate = os.path.join(directory, f"{stem}{copy_suffix}{suffix}")
        if not os.path.exists(candidate):
            return candidate
    raise RuntimeError(f"Unable to allocate fallback copy path for {target}")


def _normalize_text_limit(max_chars: Any, default: int) -> int:
    try:
        value = int(max_chars)
    except (TypeError, ValueError):
        value = default
    return min(max(_TEXT_LIMIT_MIN, value), _TEXT_LIMIT_MAX)


def _normalize_positive_int(value: Any, *, default: int, upper: int) -> int:
    try:
        if isinstance(value, str):
            value = value.strip()
        parsed = int(float(value))
    except (TypeError, ValueError):
        parsed = default
    if parsed < 1:
        parsed = default
    return min(parsed, upper)


def _normalize_positive_float(value: Any, *, default: float, upper: float) -> float:
    try:
        if isinstance(value, str):
            value = value.strip()
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed <= 0:
        parsed = default
    return min(parsed, upper)


def _build_workbook_structure_payload(
    resolved_path: str,
    *,
    sample_rows_per_sheet: int,
    max_formula_examples_per_sheet: int,
) -> Dict[str, Any]:
    import openpyxl

    wb_formula = openpyxl.load_workbook(resolved_path, data_only=False)
    wb_values = openpyxl.load_workbook(resolved_path, data_only=True)
    try:
        value_sheets = {sheet.title: sheet for sheet in wb_values.worksheets}
        external_link_targets = _extract_external_link_targets(wb_formula)
        sheet_summaries: List[Dict[str, Any]] = []
        total_formulas = 0
        total_external_formula_refs = 0
        statement_presence = {
            "profit_and_loss": {"present": False, "matched_sheet": ""},
            "balance_sheet": {"present": False, "matched_sheet": ""},
            "cash_flow": {"present": False, "matched_sheet": ""},
        }

        for sheet in wb_formula.worksheets:
            value_sheet = value_sheets.get(sheet.title, sheet)
            year_header = _detect_year_header(value_sheet)
            formula_info = _collect_formula_examples(
                sheet, max_formula_examples=max_formula_examples_per_sheet
            )
            total_formulas += int(formula_info["formula_count"])
            total_external_formula_refs += int(formula_info["external_formula_count"])

            for statement_key in statement_presence:
                if not statement_presence[statement_key][
                    "present"
                ] and _sheet_matches_statement(sheet.title, statement_key):
                    statement_presence[statement_key] = {
                        "present": True,
                        "matched_sheet": sheet.title,
                    }

            summary: Dict[str, Any] = {
                "name": sheet.title,
                "max_row": int(getattr(sheet, "max_row", 0) or 0),
                "max_column": int(getattr(sheet, "max_column", 0) or 0),
                "hidden": str(getattr(sheet, "sheet_state", "visible") or "visible")
                != "visible",
                "sample_rows": _sample_sheet_rows(
                    value_sheet, max_rows=sample_rows_per_sheet
                ),
                "formula_count": int(formula_info["formula_count"]),
                "external_formula_count": int(formula_info["external_formula_count"]),
            }
            if formula_info["formula_examples"]:
                summary["formula_examples"] = formula_info["formula_examples"]
            if formula_info["external_formula_examples"]:
                summary["external_formula_examples"] = formula_info[
                    "external_formula_examples"
                ]
            if year_header:
                summary["year_header"] = year_header
            sheet_summaries.append(summary)

        summary_parts = [f"已检查 {len(sheet_summaries)} 个工作表"]
        if external_link_targets:
            summary_parts.append(f"发现 {len(external_link_targets)} 个外部链接")
        if total_formulas:
            summary_parts.append(f"共扫描到 {total_formulas} 个公式单元格")
        return {
            "sheet_count": len(sheet_summaries),
            "sheet_names": [sheet["name"] for sheet in sheet_summaries],
            "sheets": sheet_summaries,
            "external_link_targets": external_link_targets,
            "external_link_count": len(external_link_targets),
            "total_formula_cells": total_formulas,
            "total_external_formula_refs": total_external_formula_refs,
            "statement_presence": statement_presence,
            "summary": "；".join(summary_parts) + "。",
        }
    finally:
        wb_formula.close()
        wb_values.close()


def _severity_for_financial_label(label: str) -> str:
    return _xlsx_severity_for_financial_label(
        label,
        _HIGH_PRIORITY_FINANCIAL_LABEL_HINTS,
    )


def _detect_financial_series_gap_findings(
    resolved_path: str,
    *,
    max_findings: int,
    max_rows_per_sheet: int = 240,
) -> List[Dict[str, Any]]:
    import openpyxl

    try:
        from openpyxl.utils import get_column_letter
    except Exception:  # pragma: no cover - openpyxl is already required by caller
        return []

    wb_formula = openpyxl.load_workbook(resolved_path, data_only=False)
    wb_values = openpyxl.load_workbook(resolved_path, data_only=True)
    findings: List[Dict[str, Any]] = []
    try:
        value_sheets = {sheet.title: sheet for sheet in wb_values.worksheets}
        for formula_sheet in wb_formula.worksheets:
            value_sheet = value_sheets.get(formula_sheet.title, formula_sheet)
            year_header = _detect_year_header(value_sheet)
            if not year_header:
                continue
            year_columns = [int(item["index"]) for item in year_header["columns"]]
            headers = [str(item["header"]) for item in year_header["columns"]]
            first_year_column = min(year_columns)
            row_limit = min(
                int(getattr(formula_sheet, "max_row", 0) or 0),
                year_header["row"] + max_rows_per_sheet,
            )
            for row_index in range(int(year_header["row"]) + 1, row_limit + 1):
                label = _row_label_for_year_series(
                    value_sheet, row_index, before_column=first_year_column
                )
                if not label:
                    continue
                populated_positions: List[int] = []
                series: List[Dict[str, Any]] = []
                for offset, column_index in enumerate(year_columns):
                    formula_cell = formula_sheet.cell(
                        row=row_index, column=column_index
                    )
                    value_cell = value_sheet.cell(row=row_index, column=column_index)
                    formula_text = (
                        str(formula_cell.value or "")
                        if getattr(formula_cell, "data_type", "") == "f"
                        else ""
                    )
                    display_value = _display_series_value(
                        value_cell.value, formula_text
                    )
                    populated = display_value not in (None, "")
                    if populated:
                        populated_positions.append(offset)
                    series.append(
                        {
                            "header": headers[offset],
                            "column": get_column_letter(column_index),
                            "value": display_value,
                        }
                    )
                if len(populated_positions) < 2:
                    continue
                first_populated = min(populated_positions)
                last_populated = max(populated_positions)
                gap_positions = [
                    index
                    for index in range(first_populated, last_populated + 1)
                    if index not in populated_positions
                ]
                if not gap_positions:
                    continue
                findings.append(
                    {
                        "severity": _severity_for_financial_label(label),
                        "type": "year_series_gap",
                        "sheet": formula_sheet.title,
                        "row": row_index,
                        "label": label,
                        "message": f"行“{label}”在年份序列中存在空档：{', '.join(headers[index] for index in gap_positions)} 为空，但前后年份仍有数据或公式。",
                        "evidence": {
                            "header_row": year_header["row"],
                            "series": series,
                        },
                    }
                )
                if len(findings) >= max_findings:
                    return findings
        return findings
    finally:
        wb_formula.close()
        wb_values.close()


def _read_pdf_excerpt(
    path: str,
    *,
    max_chars: int,
    start_page: int = 1,
    end_page: int = 0,
    allow_full_fallback: bool = True,
) -> str:
    return _foundation_read_pdf_excerpt(
        path,
        max_chars=max_chars,
        start_page=start_page,
        end_page=end_page,
        allow_full_fallback=allow_full_fallback,
        logger=logger,
    )


def _read_pdf_letter_window(
    path: str,
    *,
    max_chars: int,
    start_letter: int,
    end_letter: int,
) -> str:
    return _foundation_read_pdf_letter_window(
        path,
        max_chars=max_chars,
        start_letter=start_letter,
        end_letter=end_letter,
        read_excerpt=_read_pdf_excerpt,
    )
