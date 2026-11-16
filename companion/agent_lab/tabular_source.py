"""Explicit, auditable XLSX projections; never evaluate workbook formulas."""

from io import BytesIO
import re
import zipfile

from companion.contracts import CompanionError


def load_xlsx(raw, source):
    from openpyxl import load_workbook
    from openpyxl.utils import range_boundaries, get_column_letter

    with zipfile.ZipFile(BytesIO(raw)) as package:
        if sum(v.file_size for v in package.infolist()) > 32 * 1024 * 1024:
            raise CompanionError("工作簿解压后超过32MiB上限。")
    book = load_workbook(BytesIO(raw), read_only=True, data_only=False)
    cached = expanded = None
    try:
        name = source.get("sheet")
        if not name and len(book.sheetnames) != 1:
            raise CompanionError("多表资料请指定sheet：" + "、".join(book.sheetnames))
        if name and name not in book.sheetnames:
            raise CompanionError("工作表不存在：" + name)
        sheet = book[name] if name else book.active
        if sheet.max_row > 20001 or sheet.max_column > 64:
            raise CompanionError("结构化资料最多20000行、64列。")
        bounds = (1, 1, sheet.max_column, sheet.max_row)
        selection = source.get("cell_range")
        if selection:
            if not re.fullmatch(
                r"[A-Za-z]{1,2}[1-9]\d*:[A-Za-z]{1,2}[1-9]\d*", selection
            ):
                raise CompanionError("cell_range须为包含表头的矩形范围，例如A1:D1720。")
            bounds = range_boundaries(selection)
            if (
                bounds[0] > bounds[2]
                or bounds[1] > bounds[3]
                or bounds[2] > sheet.max_column
                or bounds[3] > sheet.max_row
            ):
                raise CompanionError("读取范围超出实际工作表。")
        left, top, right, bottom = bounds
        header = source.get("header_mode", "first_row")
        if header not in ("first_row", "coordinates"):
            raise CompanionError("header_mode只支持first_row或coordinates。")
        mode = source.get("formula_values", "reject")
        if mode not in ("reject", "cached"):
            raise CompanionError("formula_values只支持reject或cached。")
        if mode == "cached":
            cached = load_workbook(BytesIO(raw), read_only=True, data_only=True)
        anchors = {}
        merged_count = 0
        if source.get("expand_merged", False):
            expanded = load_workbook(BytesIO(raw), read_only=False, data_only=False)
            for region in expanded[sheet.title].merged_cells.ranges:
                if (
                    region.max_row < top
                    or region.min_row > bottom
                    or region.max_col < left
                    or region.min_col > right
                ):
                    continue
                merged_count += 1
                anchor = (region.min_row, region.min_col)
                for row in range(
                    max(top, region.min_row), min(bottom, region.max_row) + 1
                ):
                    for col in range(
                        max(left, region.min_col), min(right, region.max_col) + 1
                    ):
                        if (row, col) != anchor:
                            anchors[row, col] = anchor
        formula_rows = list(
            sheet.iter_rows(min_row=top, max_row=bottom, min_col=left, max_col=right)
        )
        cached_rows = (
            list(
                cached[sheet.title].iter_rows(
                    min_row=top, max_row=bottom, min_col=left, max_col=right
                )
            )
            if cached
            else None
        )
        rows = []
        missing = []
        formula_count = 0
        for offset, cells in enumerate(formula_rows):
            values = []
            row_missing = []
            row_formulas = []
            for index, cell in enumerate(cells):
                row, col = top + offset, left + index
                anchor = anchors.get((row, col))
                actual = expanded[sheet.title].cell(*anchor) if anchor else cell
                value = actual.value
                if actual.data_type == "f":
                    if mode == "reject":
                        raise CompanionError(
                            "输入含公式；当前分析器不计算公式。可显式选择formula_values=cached读取已有缓存，并核对缓存口径。"
                        )
                    formula_count += 1
                    value = (
                        cached[sheet.title].cell(*anchor).value
                        if anchor
                        else cached_rows[offset][index].value
                    )
                    row_formulas.append(actual.coordinate)
                    if value is None:
                        coordinate = actual.coordinate
                        row_missing.append(coordinate)
                        missing.append(coordinate)
                values.append(value)
            if (offset or header == "coordinates") and source.get(
                "include_provenance", False
            ):
                values.extend(
                    [top + offset, ",".join(row_formulas), ",".join(row_missing)]
                )
            rows.append(values)
        columns = (
            [get_column_letter(col) for col in range(left, right + 1)]
            if header == "coordinates"
            else rows[0] if rows else []
        )
        if source.get("include_provenance", False):
            reserved = ["__source_row", "__formula_cells", "__missing_formula_cache"]
            if any(v in columns for v in reserved):
                raise CompanionError("来源表头使用了保留的溯源字段。")
            columns = columns + reserved
        return (
            columns,
            rows if header == "coordinates" else rows[1:],
            {
                "sheet": sheet.title,
                "cell_range": selection,
                "formula_values": mode,
                "header_mode": header,
                "formula_cells": formula_count,
                "missing_formula_cache_count": len(missing),
                "missing_formula_cache_preview": missing[:50],
                "expand_merged": bool(source.get("expand_merged", False)),
                "merged_regions_expanded": merged_count,
                "include_provenance": bool(source.get("include_provenance", False)),
                "formulas_recalculated": False,
            },
        )
    finally:
        book.close()
        if cached:
            cached.close()
        if expanded:
            expanded.close()
