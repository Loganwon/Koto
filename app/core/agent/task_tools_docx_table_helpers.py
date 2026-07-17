from __future__ import annotations

import json
import math
import re
from typing import Any, List, Optional

def _normalize_table_columns(columns: Any) -> List[str]:
    if not columns:
        return []
    value = columns
    if isinstance(columns, str):
        text = columns.strip()
        if not text:
            return []
        try:
            value = json.loads(text)
        except Exception:
            value = re.split(r"[,，、|]", text)
    if not isinstance(value, list):
        return []
    normalized: List[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _match_header_index(headers: List[str], wanted: str) -> Optional[int]:
    wanted_text = str(wanted or "").strip().casefold()
    if not wanted_text:
        return None
    normalized_headers = [str(header or "").strip().casefold() for header in headers]
    for index, header in enumerate(normalized_headers):
        if header == wanted_text:
            return index
    for index, header in enumerate(normalized_headers):
        if wanted_text in header or header in wanted_text:
            return index
    return None


def _table_sort_value(value: Any) -> tuple[int, Any]:
    text = str(value or "").strip()
    if not text:
        return (0, 0)
    numeric_text = re.sub(r"[,$%￥¥\s]", "", text)
    try:
        return (1, float(numeric_text))
    except ValueError:
        return (1, text.casefold())


_FINANCIAL_REPORT_KEY_ROWS = {
    "收入合计",
    "增速%",
    "销量",
    "硬件收入",
    "配件收入",
    "互联网业务收入",
    "成本合计",
    "硬件成本",
    "毛利合计",
    "综合毛利率%",
    "费用合计",
    "研发费用",
    "销售费用",
    "管理费用",
    "财务费用",
    "利润总额",
    "所得税费用",
    "净利润",
    "净利率%",
}


def _financial_table_display_value(label: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "—"
    try:
        number = float(text.replace(",", ""))
    except (TypeError, ValueError):
        return text
    if not math.isfinite(number):
        return text
    if "%" in str(label or ""):
        ratio = number * 100 if abs(number) <= 2 else number
        return f"{ratio:.1f}%"
    if abs(number - round(number)) < 1e-9:
        return f"{number:,.0f}"
    return f"{number:,.1f}"


def _compact_financial_table_rows(
    raw_rows: List[List[str]], max_rows: int
) -> List[List[str]]:
    """Project a model-style P&L sheet into a readable report table."""
    header_index = -1
    year_columns: List[tuple[int, str]] = []
    for index, row in enumerate(raw_rows[:30]):
        matches = [
            (column, str(value or "").strip())
            for column, value in enumerate(row)
            if re.fullmatch(r"20\d{2}[AE]?", str(value or "").strip(), re.I)
        ]
        if len(matches) >= 2:
            header_index = index
            year_columns = matches
            break
    if header_index < 0:
        return []

    label_column = max(0, year_columns[0][0] - 1)
    projected: List[List[str]] = [
        ["指标", *[label for _column, label in year_columns]]
    ]
    candidates: List[List[str]] = []
    preferred: List[List[str]] = []
    for row in raw_rows[header_index + 1 :]:
        label = str(row[label_column] if label_column < len(row) else "").strip()
        if not label:
            continue
        values = [
            _financial_table_display_value(
                label, row[column] if column < len(row) else ""
            )
            for column, _year in year_columns
        ]
        item = [label, *values]
        candidates.append(item)
        if label in _FINANCIAL_REPORT_KEY_ROWS:
            preferred.append(item)
    selected = preferred or candidates
    projected.extend(selected[:max_rows])
    return projected if len(projected) > 1 else []


def _style_compact_financial_docx_table(table: Any, document: Any) -> None:
    """Apply stable widths and restrained report styling to a compact table."""
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor

    column_count = max(1, len(table.columns))
    section = document.sections[-1]
    usable_inches = float(
        section.page_width - section.left_margin - section.right_margin
    ) / 914400.0
    label_width = min(1.7, max(1.35, usable_inches * 0.25))
    value_width = max(0.85, (usable_inches - label_width) / max(1, column_count - 1))
    widths = [label_width, *([value_width] * (column_count - 1))]
    table.autofit = False

    for column_index, column in enumerate(table.columns):
        column.width = Inches(widths[column_index])
    for row_index, row in enumerate(table.rows):
        for column_index, cell in enumerate(row.cells):
            cell.width = Inches(widths[column_index])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if row_index == 0:
                shading = OxmlElement("w:shd")
                shading.set(qn("w:fill"), "2F5597")
                cell._tc.get_or_add_tcPr().append(shading)
            for paragraph in cell.paragraphs:
                paragraph.alignment = (
                    WD_ALIGN_PARAGRAPH.LEFT
                    if column_index == 0
                    else WD_ALIGN_PARAGRAPH.CENTER
                )
                paragraph.paragraph_format.space_before = Pt(2)
                paragraph.paragraph_format.space_after = Pt(2)
                for run in paragraph.runs:
                    run.font.size = Pt(9)
                    run.font.bold = row_index == 0
                    if row_index == 0:
                        run.font.color.rgb = RGBColor(255, 255, 255)
