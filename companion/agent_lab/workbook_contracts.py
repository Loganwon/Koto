"""Explicit workbook shape requirements, verified before publishing and finishing."""

from .execution_errors import ToolDiagnosticError


def merge_schema(state, arguments):
    name = arguments["file_name"]
    if name not in state["expected_outputs"] or not name.lower().endswith(".xlsx"):
        raise ValueError("结构约束必须对应当前交付清单中的XLSX。")
    sheets = [dict(sheet) for sheet in arguments["sheets"]]
    if len({s["name"].casefold() for s in sheets}) != len(sheets):
        raise ValueError("结构约束中的工作表名称重复。")
    for s in sheets:
        if "exact_item_rows" in s:
            expected = s["exact_item_rows"] + (1 if s.get("totals") else 0)
            if "exact_data_rows" in s and s["exact_data_rows"] != expected:
                raise ValueError("明细行与合计行数量矛盾；exact_data_rows包含合计行。")
            s["exact_data_rows"] = expected
        if not s["name"].strip() or len(s["name"]) > 31:
            raise ValueError("工作表名称必须为1至31个字符。")
        if "columns" in s and (
            any(not str(c).strip() for c in s["columns"])
            or len(set(s["columns"])) != len(s["columns"])
        ):
            raise ValueError("固定列名须非空且不能重复。")
    return {
        **state.get("workbook_schemas", {}),
        name: {"allow_extra_sheets": arguments["allow_extra_sheets"], "sheets": sheets},
    }


def violations(book, schema):
    from decimal import Decimal

    expected = {s["name"] for s in schema["sheets"]}
    actual = set(book.sheetnames)
    errors = []
    if expected - actual:
        errors.append("缺少工作表：" + "、".join(sorted(expected - actual)))
    if not schema["allow_extra_sheets"] and actual - expected:
        errors.append("出现未要求的工作表：" + "、".join(sorted(actual - expected)))
    for spec in schema["sheets"]:
        if spec["name"] not in actual:
            continue
        ws = book[spec["name"]]
        if "columns" in spec and [c.value for c in ws[1]] != spec["columns"]:
            errors.append(
                spec["name"] + "列名或顺序不符，要求：" + "、".join(spec["columns"])
            )
        if "exact_data_rows" in spec and ws.max_row - 1 != spec["exact_data_rows"]:
            errors.append(
                f"{spec['name']}数据行{ws.max_row - 1}行，要求{spec['exact_data_rows']}行。"
            )
        if spec.get("totals"):
            totals = spec["totals"]
            headers = {c.value: c.column for c in ws[1]}
            names = [totals["label_column"], *totals["sum_columns"]]
            if any(name not in headers for name in names):
                errors.append(spec["name"] + "合计检查所需列不存在。")
                continue
            rows = [
                r
                for r in range(2, ws.max_row + 1)
                if ws.cell(r, headers[totals["label_column"]]).value == totals["label"]
            ]
            if len(rows) != 1:
                errors.append(spec["name"] + "需要唯一的合计行：" + totals["label"])
                continue
            total_row = rows[0]
            for name in totals["sum_columns"]:
                values = [
                    ws.cell(r, headers[name]).value
                    for r in range(2, ws.max_row + 1)
                    if r != total_row
                ]
                actual = ws.cell(total_row, headers[name]).value
                if any(type(v) not in (int, float) for v in values) or type(
                    actual
                ) not in (int, float):
                    errors.append(
                        f"{spec['name']}的{name}数据与合计必须为数值，合计不能留空。"
                    )
                    continue
                expected = sum((Decimal(str(v)) for v in values), Decimal(0))
                if abs(Decimal(str(actual)) - expected) > max(
                    Decimal(".000000001"), abs(expected) * Decimal("1e-12")
                ):
                    errors.append(
                        f"{spec['name']}的{name}合计应为{expected}，实际为{actual}。"
                    )
    return errors


def require_schema(book, schema, file_name):
    if not schema:
        return
    errors = violations(book, schema)
    if errors:
        raise ToolDiagnosticError(
            "表格结构未满足，未发布：" + "；".join(errors),
            {
                "code": "workbook_schema_mismatch",
                "file_name": file_name,
                "expected_schema": schema,
                "guidance": "修改实际工作表和表头；result_id导出的表头就是SQL列别名，需要在SQL中使用指定列名后重新查询。不可放宽用户结构约束。",
            },
        )


def path_violations(path, schema):
    from openpyxl import load_workbook

    book = load_workbook(path, read_only=True, data_only=False)
    try:
        return violations(book, schema)
    finally:
        book.close()


def register_tool(add, STRING):
    add(
        "set_workbook_schema",
        "Persist user-specified sheet names and exact header order for an expected XLSX before creating it. Do not translate fixed headers or add sheets when forbidden. Rows count is optional and must follow explicit user requirements or real source evidence. Latest-user semantic verification required; cannot relax old requirements unilaterally.",
        {
            "file_name": STRING,
            "allow_extra_sheets": {"type": "boolean"},
            "sheets": {
                "type": "array",
                "minItems": 1,
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": STRING,
                        "columns": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 64,
                            "items": STRING,
                        },
                        "exact_data_rows": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 20000,
                        },
                        "exact_item_rows": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 20000,
                        },
                        "totals": {
                            "type": "object",
                            "properties": {
                                "label_column": STRING,
                                "label": STRING,
                                "sum_columns": {
                                    "type": "array",
                                    "minItems": 1,
                                    "maxItems": 64,
                                    "items": STRING,
                                },
                            },
                            "required": ["label_column", "label", "sum_columns"],
                            "additionalProperties": False,
                        },
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
            },
        },
        ["file_name", "allow_extra_sheets", "sheets"],
        "contract",
    )
