"""Readback proof of query-exported cells, distinct from business interpretation."""

from io import BytesIO
from hashlib import sha256

from companion.contracts import DocumentConflict
from .fact_ledger import blocks


def collect(broker, path, receipt, body):
    if path.suffix.lower() != ".xlsx":
        return {}
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter
    import sqlglot
    from sqlglot import exp

    raw = path.read_bytes()
    if sha256(raw).hexdigest() != receipt["sha256"]:
        raise DocumentConflict("工作簿版本已变化，不能恢复查询凭据。")
    book = load_workbook(BytesIO(raw), data_only=False)
    candidates, exports = {}, []
    formats = []
    for ws in book:
        groups = {}
        for row in ws:
            for c in row:
                if c.value is not None and c.number_format != "General":
                    groups.setdefault((c.column_letter, c.number_format), []).append(
                        c.row
                    )
        for (column, fmt), rows in groups.items():
            start = previous = rows[0]
            for current in [*rows[1:], None]:
                if current is None or current != previous + 1:
                    formats.append(
                        {
                            "sheet": ws.title,
                            "range": f"{column}{start}:{column}{previous}",
                            "number_format": fmt,
                        }
                    )
                    start = current
                previous = current
    try:
        bindings = list(receipt.get("query_exports", []))
        # Engines may explicitly copy a small result into rows rather than use
        # result_id. Recover provenance only for an exact, complete typed table
        # match; never infer it from a preview, similar values, or file names.
        for sheet in book:
            for analysis in reversed(broker.store.get(broker.task).get("analyses", [])):
                columns = analysis.get("columns", [])
                if (
                    not columns
                    or analysis.get("row_count", sheet.max_row) > sheet.max_row - 1
                    or columns
                    != [sheet.cell(1, col).value for col in range(1, len(columns) + 1)]
                ):
                    continue
                result = broker.data.result(analysis["result_id"])
                exact = all(
                    sheet.cell(i, j).value
                    == (float(format(value, ".16g")) if type(value) is float else value)
                    and (
                        (type(sheet.cell(i, j).value) is bool) == (type(value) is bool)
                    )
                    for i, row in enumerate(result["rows"], 2)
                    for j, value in enumerate(row, 1)
                )
                if exact:
                    bindings = [
                        binding
                        for binding in bindings
                        if binding["sheet"] != sheet.title
                    ]
                    bindings.append(
                        {
                            "sheet": sheet.title,
                            "result_id": analysis["result_id"],
                            "excluded_cells": [],
                        }
                    )
                    break
        for export in bindings:
            result = broker.data.result(export["result_id"])
            sheet = book[export["sheet"]]
            exclusions = set(export.get("excluded_cells", []))
            projection = sqlglot.parse_one(result["sql"], read="sqlite").expressions
            direct = {
                i
                for i, node in enumerate(projection)
                if isinstance(node.unalias(), exp.Column)
            }
            if len(projection) == 1 and isinstance(projection[0], exp.Star):
                direct = set(range(len(result["columns"])))
            exports.append(
                {
                    "sheet": sheet.title,
                    "result_id": export["result_id"],
                    "sql": result["sql"],
                    "columns": result["columns"],
                    "rows": len(result["rows"]),
                    "source_versions": result["sources"],
                    "preview": result["rows"][:3],
                }
            )
            for row_index, row in enumerate(result["rows"], 2):
                for col_index, expected in enumerate(row, 1):
                    coordinate = f"{get_column_letter(col_index)}{row_index}"
                    if coordinate in exclusions or expected is None:
                        continue
                    cell = sheet[coordinate]
                    persisted = (
                        float(format(expected, ".16g"))
                        if type(expected) is float
                        else expected
                    )
                    if cell.value != persisted or (type(cell.value) is bool) != (
                        type(persisted) is bool
                    ):
                        raise DocumentConflict(
                            "查询导出单元格已变化，不能复用来源凭据："
                            + sheet.title
                            + "!"
                            + coordinate
                        )
                    if cell.data_type == "f" or (
                        isinstance(expected, str)
                        and (col_index - 1 not in direct or "\n" in expected)
                    ):
                        continue
                    text = f"{sheet.title}!{coordinate}\t{cell.value}"
                    candidates[text] = {
                        "result_id": export["result_id"],
                        "sheet": sheet.title,
                        "cell": coordinate,
                        "column": result["columns"][col_index - 1],
                    }
    finally:
        book.close()
    verified = {}
    for bid, text in blocks(body).items():
        if text.rstrip("\n") in candidates:
            verified[bid] = candidates[text.rstrip("\n")]
    return {
        "verified_blocks": verified,
        "queries": exports,
        "number_formats": formats,
        "scope": "仅证明保存单元格与完整查询结果的值、类型、来源版本一致；不证明SQL业务口径、列名单位或额外说明正确。",
    }
