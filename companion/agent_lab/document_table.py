"""Explicit saved DOCX table projection, with no document mutations."""

from io import BytesIO
import zipfile

from companion.contracts import CompanionError


def tables(raw):
    from docx import Document

    with zipfile.ZipFile(BytesIO(raw)) as package:
        if sum(v.file_size for v in package.infolist()) > 32 * 1024 * 1024:
            raise CompanionError("文档解压后超过32MiB上限。")
    document = Document(BytesIO(raw))
    if len(document.tables) > 32:
        raise CompanionError("本版结构化读取最多支持32个顶层Word表格。")
    return document.tables


def describe(raw):
    return [
        {
            "table": i,
            "rows": len(t.rows),
            "columns": len(t.columns),
            "headers": [c.text for c in t.rows[0].cells] if t.rows else [],
        }
        for i, t in enumerate(tables(raw))
    ]


def load(raw, source):
    values = tables(raw)
    index = source.get("table")
    if index is None:
        if len(values) != 1:
            raise CompanionError("请先inspect_source，并显式指定0起始table编号。")
        index = 0
    if type(index) is not int or not 0 <= index < len(values):
        raise CompanionError("Word表格编号不存在。")
    if any(
        k in source
        for k in (
            "sheet",
            "cell_range",
            "header_mode",
            "formula_values",
            "expand_merged",
        )
    ):
        raise CompanionError("Word表格使用table编号，不接受XLSX投影参数。")
    table = values[index]
    if len(table.rows) > 20001 or len(table.columns) > 64:
        raise CompanionError("Word表格最多20000数据行、64列。")
    rows = [[c.text if c.text else None for c in row.cells] for row in table.rows]
    columns = rows[0] if rows else []
    data = rows[1:]
    if source.get("include_provenance"):
        if "__source_row" in columns:
            raise CompanionError("来源表头使用了保留的溯源字段。")
        columns = [*columns, "__source_row"]
        data = [[*r, i + 2] for i, r in enumerate(data)]
    return (
        columns,
        data,
        {
            "format": "docx",
            "table": index,
            "formulas_recalculated": False,
            "values": "saved Word table text; empty cells stay NULL",
        },
    )
