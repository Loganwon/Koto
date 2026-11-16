"""Typed workbook writes, optimistic revision and independent package readback."""

from io import BytesIO
import os
from pathlib import Path
import re
import uuid

from companion.contracts import CompanionError, DocumentConflict, ResultUncertain
from companion.file_actions import FileActions
from .data_engine import scalar

NUMBER_FORMATS = {
    "General",
    "0",
    "0.00",
    "0.0000",
    "#,##0",
    "#,##0.00",
    "0%",
    "0.00%",
    "yyyy-mm-dd",
}


def set_format(cell, value):
    if value not in NUMBER_FORMATS:
        raise CompanionError("不支持的数字显示格式。")
    cell.number_format = value


def coordinate(value):
    from openpyxl.utils.cell import coordinate_to_tuple

    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Z]{1,3}[1-9][0-9]{0,5}", value
    ):
        raise CompanionError("请使用明确的大写单元格地址。")
    row, col = coordinate_to_tuple(value)
    if row > 20001 or col > 64:
        raise CompanionError("当前写入范围最多20001行、64列。")
    return value


def set_cell(cell, kind, value):
    from openpyxl.formula.tokenizer import Tokenizer, TokenizerError

    scalar(value)
    if kind == "text" and isinstance(value, str):
        # An empty inline string reopens as an empty cell in XLSX. Normalize it
        # before the independent readback instead of retrying a valid workbook.
        cell.value = value if value else None
        cell.data_type = "s" if value else "n"
    elif kind == "number" and type(value) in (float, int):
        cell.value = value
    elif kind == "boolean" and type(value) is bool:
        cell.value = value
    elif kind == "blank" and value is None:
        cell.value = None
    elif kind == "formula" and isinstance(value, str) and value.startswith("="):
        # Only local pure expressions. External links and callable side effects
        # are not enabled simply because a value starts with '='.
        if len(value) > 2000 or any(c in value for c in "[]|\\\r\n"):
            raise CompanionError("公式包含外部引用或不支持的语法。")
        functions = {
            "SUM",
            "AVERAGE",
            "MIN",
            "MAX",
            "ABS",
            "ROUND",
            "ROUNDUP",
            "ROUNDDOWN",
            "COUNT",
            "COUNTA",
            "COUNTIF",
            "COUNTIFS",
            "SUMIF",
            "SUMIFS",
            "IF",
            "IFERROR",
            "AND",
            "OR",
            "NOT",
            "CONCAT",
            "CONCATENATE",
            "LEN",
            "LEFT",
            "RIGHT",
            "MID",
            "TRIM",
            "VALUE",
        }
        try:
            tokens = Tokenizer(value).items
        except TokenizerError:
            raise CompanionError("无法解析公式。") from None
        if any(
            t.type == "FUNC"
            and t.subtype == "OPEN"
            and t.value[:-1].upper() not in functions
            for t in tokens
        ):
            raise CompanionError("公式函数未在本地纯计算白名单中。")
        cell.value = value
    else:
        raise CompanionError("单元格值与显式类型不匹配。")


def write_scalar(cell, value):
    scalar(value)
    kind = (
        "blank"
        if value is None
        else (
            "boolean"
            if type(value) is bool
            else "text" if isinstance(value, str) else "number"
        )
    )
    set_cell(cell, kind, value)


def _publish(
    book,
    destination,
    permitted,
    *,
    expected=None,
    backup_dir=None,
    action="create_workbook",
    sources=(),
    query_exports=(),
    schema=None
):
    from openpyxl import load_workbook

    temporary = destination.parent / (".koto-" + uuid.uuid4().hex + ".xlsx")
    published = False
    try:
        from .workbook_contracts import require_schema

        require_schema(book, schema, destination.name)
        if sum(ws.max_row * ws.max_column for ws in book) > 250000:
            raise CompanionError("输出工作簿超过250000单元格上限。")
        book.save(temporary)
        check = load_workbook(BytesIO(temporary.read_bytes()), data_only=False)
        try:
            if check.sheetnames != book.sheetnames:
                raise CompanionError("工作表名称读回不一致。")
            for original, reopened in zip(book, check):
                for row in original:
                    for cell in row:
                        actual = reopened[cell.coordinate]
                        # openpyxl serializes numeric cells to 16 significant
                        # digits. Compare that exact persisted representation,
                        # not binary float noise (e.g. 1070.2600000000002).
                        expected_value = cell.value
                        if cell.data_type == "n" and type(expected_value) is float:
                            expected_value = float(format(expected_value, ".16g"))
                        if (
                            actual.value != expected_value
                            or (
                                cell.value is not None
                                and actual.data_type != cell.data_type
                            )
                            or actual.number_format != cell.number_format
                        ):
                            raise CompanionError("单元格读回不一致：" + cell.coordinate)
        finally:
            check.close()
        if not permitted():
            raise CompanionError("任务已停止，没有发布结果。")
        previous = None
        if expected is not None:
            if (
                destination.is_symlink()
                or FileActions.receipt(destination, "verify")["sha256"] != expected
            ):
                raise DocumentConflict("原文件已变化，没有覆盖。")
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup = backup_dir / (expected + ".xlsx")
            raw = destination.read_bytes()
            import hashlib

            if hashlib.sha256(raw).hexdigest() != expected:
                raise DocumentConflict("原文件已变化，没有覆盖。")
            if not backup.exists():
                backup.write_bytes(raw)
            # Check again immediately before replacing; the host task lease
            # prevents other Koto actors, and the hash detects external edits.
            if (
                FileActions.receipt(destination, "verify")["sha256"] != expected
                or not permitted()
            ):
                raise DocumentConflict("原文件已变化或任务已停止，没有覆盖。")
            os.replace(temporary, destination)
            previous = expected
        else:
            try:
                FileActions.publish_new(temporary, destination)
            except FileExistsError:
                raise CompanionError("同名文件已存在，没有覆盖。") from None
        published = True
        return FileActions.receipt(
            destination,
            action,
            sheets=book.sheetnames,
            previous_sha256=previous,
            formulas_recalculated=False,
            sources=list(sources),
            query_exports=list(query_exports),
        )
    except CompanionError:
        if published:
            raise ResultUncertain(
                "工作簿已经发布，但回执未确认；不要重复执行。"
            ) from None
        raise
    except Exception as error:
        if published:
            raise ResultUncertain(
                "工作簿已经发布，但读回未确认；不要重复执行。"
            ) from None
        raise CompanionError("工作簿未发布：" + str(error)[:200]) from None
    finally:
        book.close()
        temporary.unlink(missing_ok=True)


def create_workbook(broker, args):
    from openpyxl import Workbook

    destination = broker.files._destination(args["file_name"], {".xlsx"})
    book = Workbook()
    book.remove(book.active)
    sources, names, exports = [], set(), []
    try:
        if not args["sheets"]:
            raise CompanionError("至少需要一个工作表。")
        for spec in args["sheets"]:
            name = spec["name"]
            if (
                not name
                or len(name) > 31
                or re.search(r"[\\/*?:\[\]]", name)
                or name.casefold() in names
            ):
                raise CompanionError("工作表名称无效或重复。")
            names.add(name.casefold())
            ws = book.create_sheet(name)
            rows = spec.get("rows", [])
            if spec.get("result_id"):
                if rows:
                    raise CompanionError("一个工作表使用rows或result_id之一。")
                result = broker.data.result(spec["result_id"])
                rows = [result["columns"], *result["rows"]]
                sources.extend(result["sources"])
                exports.append(
                    {
                        "sheet": name,
                        "result_id": spec["result_id"],
                        "excluded_cells": [p["address"] for p in spec.get("cells", [])],
                    }
                )
            if len(rows) > 20001 or any(len(row) > 64 for row in rows):
                raise CompanionError("工作表超出行列上限。")
            for i, row in enumerate(rows, 1):
                for j, value in enumerate(row, 1):
                    write_scalar(ws.cell(i, j), value)
            for patch in spec.get("cells", []):
                set_cell(
                    ws[coordinate(patch["address"])], patch["type"], patch["value"]
                )
                if "number_format" in patch:
                    set_format(ws[patch["address"]], patch["number_format"])
            for fmt in spec.get("column_formats", []):
                from openpyxl.utils.cell import column_index_from_string

                column = fmt["column"]
                if not re.fullmatch(
                    r"[A-Z]{1,2}", column
                ) or not 1 <= column_index_from_string(column) <= min(
                    64, ws.max_column
                ):
                    raise CompanionError("数字格式列必须是当前工作表已有列。")
                for row in range(2, ws.max_row + 1):
                    set_format(
                        ws.cell(row, column_index_from_string(column)),
                        fmt["number_format"],
                    )
            ws.freeze_panes = "A2"
        broker.data.verify(sources)
        return _publish(
            book,
            destination,
            broker.permitted,
            sources=sources,
            query_exports=exports,
            schema=broker.store.get(broker.task)
            .get("workbook_schemas", {})
            .get(args["file_name"]),
        )
    except Exception:
        book.close()
        raise


def revise_workbook(broker, args):
    from openpyxl import load_workbook

    receipt = broker.store.get(broker.task)["artifacts"].get(args["file_name"])
    if not receipt or receipt["sha256"] != args["expected_sha256"]:
        raise DocumentConflict("请先读回当前文件，并使用其SHA256版本。")
    path = broker.outputs / receipt["name"]
    if path.suffix.lower() != ".xlsx" or path.is_symlink():
        raise CompanionError("只支持本任务已生成的XLSX修订。")
    if FileActions.receipt(path, "verify")["sha256"] != args["expected_sha256"]:
        raise DocumentConflict("工作簿已被外部修改，没有覆盖。")
    book = load_workbook(BytesIO(path.read_bytes()), data_only=False)
    try:
        seen, value_changes = set(), set()
        for patch in args["changes"]:
            key = (patch["sheet"], coordinate(patch["address"]))
            if key in seen or key[0] not in book.sheetnames:
                raise CompanionError("工作表不存在或单元格修改重复。")
            seen.add(key)
            cell = book[key[0]][key[1]]
            if (
                cell.value != patch["expected"]
                or type(cell.value) is bool
                and type(patch["expected"]) is not bool
            ):
                raise DocumentConflict("单元格当前内容与预期不一致，没有覆盖。")
            old_value, old_type = cell.value, cell.data_type
            set_cell(cell, patch["type"], patch["value"])
            if cell.value != old_value or cell.data_type != old_type:
                value_changes.add(key)
            if "number_format" in patch:
                set_format(cell, patch["number_format"])
        if not seen:
            raise CompanionError("没有提供需要修改的单元格。")
        return _publish(
            book,
            path,
            broker.permitted,
            expected=args["expected_sha256"],
            backup_dir=broker.outputs.parent / "artifact_versions",
            action="revise_workbook",
            query_exports=[
                {
                    **item,
                    "excluded_cells": sorted(
                        set(item.get("excluded_cells", []))
                        | {
                            p["address"]
                            for p in args["changes"]
                            if p["sheet"] == item["sheet"]
                            and (p["sheet"], p["address"]) in value_changes
                        }
                    ),
                }
                for item in receipt.get("query_exports", [])
            ],
            schema=broker.store.get(broker.task)
            .get("workbook_schemas", {})
            .get(args["file_name"]),
        )
    except Exception:
        book.close()
        raise
