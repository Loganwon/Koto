# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import os
import re
import uuid
from typing import Any

_UNIVER_TYPE_STRING = 1
_UNIVER_TYPE_NUMBER = 2
_UNIVER_TYPE_BOOLEAN = 3
_CACHED_VALUE_MISSING = object()

_ALIGN_H_MAP = {
    "general": 0,
    "left": 1,
    "center": 2,
    "right": 3,
    "justify": 4,
    "centerContinuous": 5,
    "distributed": 6,
}

_ALIGN_V_MAP = {
    "top": 1,
    "middle": 2,
    "center": 2,
    "bottom": 3,
    "justify": 4,
    "distributed": 5,
}


def xlsx_contains_formula_fast(path: str) -> bool:
    import zipfile

    try:
        with zipfile.ZipFile(path, "r") as zf:
            for info in zf.infolist():
                name = info.filename
                if not name.startswith("xl/worksheets/") or not name.endswith(".xml"):
                    continue
                with zf.open(info) as fh:
                    tail = b""
                    for chunk in iter(lambda: fh.read(65536), b""):
                        data = tail + chunk
                        if b"<f" in data:
                            return True
                        tail = data[-8:]
    except Exception:
        return False
    return False


def _value_to_univer(value: Any) -> tuple[Any, int]:
    if isinstance(value, bool):
        return int(value), _UNIVER_TYPE_BOOLEAN
    if isinstance(value, (int, float)):
        return value, _UNIVER_TYPE_NUMBER
    return str(value), _UNIVER_TYPE_STRING


def _quote_sheet_references(formula: str, sheet_names: list[str]) -> str:
    """Quote same-workbook sheet references for Univer's formula parser."""
    normalized = formula
    for sheet_name in sorted(sheet_names, key=len, reverse=True):
        quoted = "'" + sheet_name.replace("'", "''") + "'"
        normalized = re.sub(
            rf"(?<!['\w]){re.escape(sheet_name)}(?=!)",
            lambda _match, replacement=quoted: replacement,
            normalized,
        )
    return normalized


def _formula_requires_cached_fallback(formula: str) -> bool:
    """Return whether Univer cannot safely evaluate this Excel formula."""
    upper = formula.upper()
    return (
        "!" in formula
        or "[" in formula
        or "GETPIVOTDATA(" in upper
        or "_XLFN." in upper
    )


def openpyxl_cell_to_univer(
    cell: Any,
    *,
    cached_value: Any = _CACHED_VALUE_MISSING,
    sheet_names: list[str] | None = None,
) -> dict[str, Any] | None:
    v = cell.value
    if v is None and getattr(cell, "has_style", False) is not True:
        return None
    cell_data: dict[str, Any] = {}
    if v is None:
        pass
    elif getattr(cell, "data_type", None) == "f":
        formula = str(v)
        formula = formula if formula.startswith("=") else f"={formula}"
        normalized_formula = _quote_sheet_references(formula, sheet_names or [])
        has_cached_value = (
            cached_value is not _CACHED_VALUE_MISSING and cached_value is not None
        )
        custom: dict[str, Any] = {"kotoOriginalFormula": formula}
        if has_cached_value:
            cached_v, cached_t = _value_to_univer(cached_value)
            custom["kotoCachedValue"] = cached_v
            cell_data["v"] = cached_v
            cell_data["t"] = cached_t
        else:
            cell_data["t"] = _UNIVER_TYPE_NUMBER

        # Cross-sheet references, Excel-only functions, and external workbook
        # references can replace a valid cached result with #NAME? in Univer.
        # Display the cached result while retaining the original formula in
        # custom metadata for export.
        if not (_formula_requires_cached_fallback(formula) and has_cached_value):
            cell_data["f"] = normalized_formula
        cell_data["custom"] = custom
    else:
        cell_data["v"], cell_data["t"] = _value_to_univer(v)

    style: dict[str, Any] = {}
    try:
        font = cell.font
        if font:
            if font.bold:
                style["bl"] = 1
            if font.italic:
                style["it"] = 1
            if font.size:
                style["fs"] = int(font.size)
            if (
                font.color
                and font.color.type == "rgb"
                and font.color.rgb
                not in (
                    "00000000",
                    "FF000000",
                )
            ):
                style["cl"] = {"rgb": "#" + font.color.rgb[2:]}
        fill = cell.fill
        if fill and fill.fill_type not in (None, "none") and fill.fgColor:
            if fill.fgColor.type == "rgb" and fill.fgColor.rgb not in (
                "00000000",
                "FFFFFFFF",
            ):
                style["bg"] = {"rgb": "#" + fill.fgColor.rgb[2:]}
        alignment = cell.alignment
        if alignment:
            if alignment.horizontal and alignment.horizontal in _ALIGN_H_MAP:
                style["ht"] = _ALIGN_H_MAP[alignment.horizontal]
            if alignment.vertical and alignment.vertical in _ALIGN_V_MAP:
                style["vt"] = _ALIGN_V_MAP[alignment.vertical]
            if alignment.wrap_text is True:
                style["tb"] = 3
        number_format = cell.number_format
        if (
            isinstance(number_format, str)
            and number_format
            and number_format != "General"
        ):
            style["n"] = {"pattern": number_format}
    except Exception:
        pass

    if style:
        cell_data["s"] = style
    return cell_data or None


def parse_xlsx(file_path: str, original_name: str | None = None) -> dict[str, Any]:
    try:
        import openpyxl
    except ImportError:
        raise RuntimeError("openpyxl 未安装，请执行: pip install openpyxl")

    warnings: list[str] = []
    if xlsx_contains_formula_fast(file_path):
        warnings.append(
            "此表格包含公式（如 =SUM(...)）。Koto 会保留并重新计算常用公式；"
            "外部链接、宏与部分 Excel 专有函数仍可能需要在 Excel 中刷新。"
        )

    # Keep formulas editable, but load Excel's last calculated values alongside
    # them. These values prevent unsupported Excel-only formulas from turning
    # into #NAME? while their original formulas remain available for export.
    wb = openpyxl.load_workbook(file_path, data_only=False)
    cached_wb = openpyxl.load_workbook(file_path, data_only=True)
    sheet_names = list(wb.sheetnames)

    workbook_id = str(uuid.uuid4())
    if original_name:
        workbook_name = os.path.splitext(os.path.basename(original_name))[0]
    else:
        workbook_name = os.path.splitext(os.path.basename(file_path))[0]
    sheet_order: list[str] = []
    sheets: dict[str, Any] = {}
    style_hash_to_id: dict[str, str] = {}
    styles_registry: dict[str, Any] = {}

    def _get_style_id(style_obj: dict[str, Any]) -> str:
        import json as _json

        style_hash = _json.dumps(style_obj, sort_keys=True, ensure_ascii=False)
        if style_hash not in style_hash_to_id:
            style_id = str(len(style_hash_to_id))
            style_hash_to_id[style_hash] = style_id
            styles_registry[style_id] = style_obj
        return style_hash_to_id[style_hash]

    for idx, ws in enumerate(wb.worksheets):
        cached_ws = cached_wb[ws.title]
        sheet_id = f"sheet{idx + 1}"
        sheet_order.append(sheet_id)

        cell_data: dict[int, dict[int, Any]] = {}
        for row in ws.iter_rows():
            for cell in row:
                converted = openpyxl_cell_to_univer(
                    cell,
                    cached_value=cached_ws.cell(cell.row, cell.column).value,
                    sheet_names=sheet_names,
                )
                if converted is None:
                    continue
                if "s" in converted and isinstance(converted["s"], dict):
                    converted["s"] = _get_style_id(converted["s"])
                row_idx = cell.row - 1
                col_idx = cell.column - 1
                cell_data.setdefault(row_idx, {})[col_idx] = converted

        merge_data: list[dict[str, int]] = []
        for merge_range in ws.merged_cells.ranges:
            merge_data.append(
                {
                    "startRow": merge_range.min_row - 1,
                    "startColumn": merge_range.min_col - 1,
                    "endRow": merge_range.max_row - 1,
                    "endColumn": merge_range.max_col - 1,
                }
            )

        column_data: dict[int, dict] = {}
        for col_letter, col_dim in ws.column_dimensions.items():
            if col_dim.width and col_dim.width > 0:
                col_idx = openpyxl.utils.column_index_from_string(col_letter) - 1
                column_data[col_idx] = {"w": max(4, round(col_dim.width * 7 + 5))}

        row_data: dict[int, dict] = {}
        for row_num, row_dim in ws.row_dimensions.items():
            if row_dim.height and row_dim.height > 0:
                row_data[row_num - 1] = {"h": max(4, round(row_dim.height * 96 / 72))}

        sheets[sheet_id] = {
            "id": sheet_id,
            "name": ws.title,
            "rowCount": max(ws.max_row or 30, 30),
            "columnCount": max(ws.max_column or 10, 10),
            "cellData": cell_data,
            "mergeData": merge_data,
            "columnData": column_data,
            "rowData": row_data,
        }

    wb.close()
    cached_wb.close()

    return {
        "id": workbook_id,
        "name": workbook_name,
        "appVersion": "0.5.0",
        "locale": "zh-CN",
        "sheetOrder": sheet_order,
        "sheets": sheets,
        "styles": styles_registry,
        "resources": [],
        "_warnings": warnings,
    }


__all__ = [
    "openpyxl_cell_to_univer",
    "parse_xlsx",
    "xlsx_contains_formula_fast",
]
