"""Bounded relational analysis over explicit workspace inputs, without host code execution."""

import csv
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
from io import BytesIO, StringIO
import json
import math
from pathlib import Path
import re
import sqlite3
import time

from companion.contracts import CompanionError, DocumentConflict
from .execution_errors import ToolDiagnosticError


def scalar(value):
    if type(value) not in (str, int, float, bool, type(None)):
        raise CompanionError("表格值必须是普通文本、数字、布尔值或空值。")
    if isinstance(value, str) and len(value) > 4000:
        raise CompanionError("单元格文本超过4000字符。")
    if isinstance(value, float) and not math.isfinite(value):
        raise CompanionError("表格不接受非有限数值。")
    if type(value) is int and abs(value) > 2**53:
        raise CompanionError("大整数请用文本保存，以免表格损失精度。")
    return value


def money_cents(value):
    """Invalid amounts stay NULL, never silently convert bad input into zero."""
    if value is None or not re.fullmatch(
        r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?", str(value).strip()
    ):
        return None
    try:
        result = int(Decimal(str(value).strip().replace(",", "")) * 100)
        return result if abs(result) <= 2**53 else None
    except (InvalidOperation, ValueError):
        return None


def money_product_cents(quantity, unit_price):
    """Round each exact decimal product to cents, then aggregate integers in SQL."""
    try:
        if (
            quantity is None
            or unit_price is None
            or isinstance(quantity, bool)
            or isinstance(unit_price, bool)
        ):
            return None
        a, b = Decimal(str(quantity).strip()), Decimal(str(unit_price).strip())
        if not a.is_finite() or not b.is_finite():
            return None
        value = int((a * b).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)
        return value if abs(value) <= 2**53 else None
    except (InvalidOperation, ValueError, OverflowError):
        return None


class DataEngine:
    def __init__(self, workspace, folder, permitted):
        self.workspace, self.folder, self.permitted = workspace, Path(folder), permitted
        self.folder.mkdir(parents=True, exist_ok=True)

    def _load(self, source):
        path = self.workspace._path(source["file_id"])
        if path.stat().st_size > 16 * 1024 * 1024:
            raise CompanionError("结构化资料超过16MiB上限。")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        suffix = path.suffix.lower()
        details = {}
        if suffix in (".csv", ".tsv"):
            rows = list(
                csv.reader(
                    StringIO(raw.decode("utf-8-sig")),
                    delimiter="\t" if suffix == ".tsv" else ",",
                )
            )
            columns = rows[0] if rows else []
            rows = rows[1:]
        elif suffix == ".json":
            objects = json.loads(raw.decode("utf-8-sig"))
            if (
                not isinstance(objects, list)
                or not objects
                or not all(isinstance(v, dict) for v in objects)
            ):
                raise CompanionError("JSON 表格资料需要非空对象数组。")
            columns = list(dict.fromkeys(k for row in objects for k in row))
            rows = [[row.get(k) for k in columns] for row in objects]
        elif suffix == ".docx":
            from .document_table import load

            columns, rows, details = load(raw, source)
        elif suffix == ".xlsx":
            from .tabular_source import load_xlsx

            columns, rows, details = load_xlsx(raw, source)
        else:
            raise ToolDiagnosticError(
                "结构化分析支持CSV、TSV、JSON对象数组、XLSX投影及显式Word表格。",
                {
                    "code": "unsupported_query_source",
                    "next_tool": {
                        "name": "read_reference",
                        "arguments": {"file_id": source["file_id"]},
                    },
                    "guidance": "先读取这种文件的真实内容；不要把文档直接作为SQL表。",
                },
            )
        if not columns or len(columns) > 64 or len(rows) > 20000:
            raise CompanionError("资料需要表头且最多20000行、64列。")
        if any(
            not isinstance(c, str) or not c.strip() or len(c) > 100 for c in columns
        ) or len({c.casefold() for c in columns}) != len(columns):
            raise ToolDiagnosticError(
                "表头必须是非空且不重复的文本。无规则表头的XLSX矩阵请显式选header_mode=coordinates，列名为A/B/C等，并用include_provenance的__source_row定位原始行；不要重复用无效表头查询。",
                {
                    "code": "invalid_table_headers",
                    "next_tool": {
                        "name": "inspect_source",
                        "arguments": {
                            k: v for k, v in source.items() if k in ("file_id", "sheet")
                        },
                    },
                },
            )
        if any(len(row) != len(columns) for row in rows):
            raise CompanionError("资料行列数不一致，请核实来源；没有静默丢弃数据。")
        return (
            columns,
            [[scalar(v) for v in row] for row in rows],
            {
                "file_id": source["file_id"],
                "sha256": digest,
                "sheet": source.get("sheet"),
                **details,
            },
        )

    def verify(self, sources):
        for source in sources:
            path = self.workspace._path(source["file_id"])
            if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
                raise DocumentConflict(
                    "分析来源已变化，请重新查询：" + source["file_id"]
                )

    def describe(self, file_id, sheet=None):
        source = {
            "file_id": file_id,
            "formula_values": "cached",
        }
        path = self.workspace._path(file_id)
        if path.suffix.lower() == ".docx":
            from .document_table import describe

            if path.stat().st_size > 16 * 1024 * 1024:
                raise CompanionError("结构化资料超过16MiB上限。")
            raw = path.read_bytes()
            entries = describe(raw)
            return {
                "file_id": file_id,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "format": "docx",
                "structured_query": bool(entries),
                "tables": entries,
                "guidance": "用table编号查询真实Word表格；单元格为文本，金额含千位分组时用money_cents，空值保留NULL。不查询普通段落或未保存改动。",
            }
        if path.suffix.lower() not in (".xlsx", ".csv", ".tsv", ".json"):
            if path.stat().st_size > 16 * 1024 * 1024:
                raise CompanionError("资料超过16MiB上限。")
            return {
                "file_id": file_id,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "format": path.suffix.lower().lstrip("."),
                "structured_query": False,
                "next_tool": {
                    "name": "read_reference",
                    "arguments": {"file_id": file_id},
                },
                "guidance": "先读取真实文本/表格；query_data不直接查询这种文件。需要定位时使用search_reference。",
            }
        names = []
        if path.suffix.lower() == ".xlsx":
            from openpyxl import load_workbook
            import zipfile

            if path.stat().st_size > 16 * 1024 * 1024:
                raise CompanionError("结构化资料超过16MiB上限。")
            with zipfile.ZipFile(path) as package:
                if sum(v.file_size for v in package.infolist()) > 32 * 1024 * 1024:
                    raise CompanionError("工作簿解压后超过32MiB上限。")

            book = load_workbook(path, read_only=True, data_only=True)
            try:
                names = book.sheetnames
            finally:
                book.close()
            if sheet is None and len(names) > 1:
                return {
                    "file_id": file_id,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "sheets": names,
                    "structured_query": True,
                    "guidance": "指定其中一个真实sheet后再次inspect_source。",
                }
            source["sheet"] = sheet or names[0]
        header_reason = ""
        try:
            columns, rows, proof = self._load(source)
        except CompanionError as error:
            # Structural metadata fallback only; the actual query remains explicit.
            if path.suffix.lower() != ".xlsx" or not str(error).startswith("表头必须"):
                raise
            source["header_mode"] = "coordinates"
            source["include_provenance"] = True
            columns, rows, proof = self._load(source)
            header_reason = (
                "原表首行不是唯一非空表头，已展示坐标投影；查询须显式采用这些选项。"
            )
        self.verify([proof])
        return {
            "file_id": file_id,
            "sheets": names,
            "structured_query": True,
            "columns": columns,
            "row_count": len(rows),
            "preview": rows[:5],
            "source": proof,
            "header_reason": header_reason,
            "query_source": {"name": "source", **source},
            "guidance": "SQL列名必须使用columns中的真实字段，sources须保留query_source的投影选项。__source_row等溯源列仅在include_provenance=true时存在，F69不是SQL列名。缓存未重算。",
        }

    def query(self, sources, sql, preview=15):
        if not sources or len(sources) > 8 or len(sql) > 12000:
            raise CompanionError("一次查询支持1至8个来源，SQL最多12000字符。")
        conn = sqlite3.connect(":memory:")
        evidence, info, names, total = [], [], set(), 0
        functions = set()
        try:
            conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1_000_000)
            conn.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 64)
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.create_function("money_cents", 1, money_cents, deterministic=True)
            conn.create_function(
                "money_product_cents", 2, money_product_cents, deterministic=True
            )
            for source in sources:
                name = source["name"]
                if (
                    not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,40}", name)
                    or name.casefold() in names
                ):
                    raise CompanionError("来源表别名需是唯一的英文标识符。")
                names.add(name.casefold())
                columns, rows, proof = self._load(source)
                total += len(rows)
                if total > 40000:
                    raise CompanionError("一次分析总输入最多40000行。")
                quoted = ['"' + c.replace('"', '""') + '"' for c in columns]
                conn.execute(f'CREATE TABLE "{name}" ({",".join(quoted)})')
                conn.executemany(
                    f'INSERT INTO "{name}" VALUES({",".join("?" for _ in columns)})',
                    rows,
                )
                evidence.append(proof)
                info.append({"name": name, "columns": columns, "rows": len(rows)})
            allowed = {
                sqlite3.SQLITE_SELECT,
                sqlite3.SQLITE_READ,
                sqlite3.SQLITE_RECURSIVE,
            }
            functions = {
                "abs",
                "round",
                "sum",
                "total",
                "avg",
                "min",
                "max",
                "count",
                "coalesce",
                "ifnull",
                "nullif",
                "trim",
                "ltrim",
                "rtrim",
                "lower",
                "upper",
                "length",
                "substr",
                "substring",
                "replace",
                "char",
                "unicode",
                "printf",
                "like",
                "glob",
                "instr",
                "typeof",
                "money_cents",
                "money_product_cents",
                "row_number",
                "rank",
                "dense_rank",
                "lag",
                "lead",
            }
            conn.set_authorizer(
                lambda action, a, b, db, origin: (
                    sqlite3.SQLITE_OK
                    if action in allowed
                    or (action == sqlite3.SQLITE_FUNCTION and b in functions)
                    else sqlite3.SQLITE_DENY
                )
            )
            deadline = time.monotonic() + 3
            conn.set_progress_handler(
                lambda: int(time.monotonic() > deadline or not self.permitted()), 1000
            )
            cursor = conn.execute(sql)
            if not cursor.description:
                raise CompanionError("只支持返回数据的只读SELECT查询。")
            columns = [v[0] for v in cursor.description]
            if len(columns) > 64 or len(set(columns)) != len(columns):
                raise CompanionError("查询结果列名必须唯一，最多64列。")
            rows, size = [], 0
            for row in cursor:
                if len(rows) == 20000:
                    raise CompanionError("查询结果超过20000行，请缩小范围。")
                row = [scalar(value) for value in row]
                size += len(json.dumps(row, ensure_ascii=False).encode("utf-8"))
                if size > 16 * 1024 * 1024:
                    raise CompanionError("查询结果超过16MiB。")
                rows.append(row)
            self.verify(evidence)
            from .query_units import infer_units

            column_units = infer_units(sql, info, columns)
            result = {
                "columns": columns,
                "rows": rows,
                "sources": evidence,
                "sql": sql,
                "column_units": column_units,
            }
            encoded = json.dumps(result, ensure_ascii=False, allow_nan=False).encode(
                "utf-8"
            )
            if len(encoded) > 16 * 1024 * 1024:
                raise CompanionError("查询结果超过16MiB。")
            result_id = hashlib.sha256(encoded).hexdigest()
            evidence_digest = hashlib.sha256(
                json.dumps(
                    {k: v for k, v in result.items() if k != "sql"},
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            destination = self.folder / (result_id + ".json")
            if not destination.exists():
                destination.write_bytes(encoded)
            return {
                "result_id": result_id,
                "columns": columns,
                "row_count": len(rows),
                "preview": result["rows"][:preview],
                "preview_truncated": len(rows) > preview,
                "inputs": info,
                "sources": evidence,
                "evidence_digest": evidence_digest,
                "column_units": column_units,
            }
        except (sqlite3.Error, UnicodeError, json.JSONDecodeError) as error:
            raise ToolDiagnosticError(
                "结构化分析未完成：" + str(error)[:300],
                {
                    "code": "query_error",
                    "inputs": info,
                    "supported_functions": sorted(functions),
                    "next_tool": {
                        "name": "inspect_source",
                        "arguments": {
                            k: v
                            for k, v in sources[0].items()
                            if k in ("file_id", "sheet")
                        },
                    },
                    "guidance": "根据真实字段/函数修正SQL；不要原样重试失败查询。坐标单元格需列名配合__source_row，不把F69当列名。",
                },
            ) from None
        finally:
            conn.close()

    def result(self, result_id):
        if not re.fullmatch(r"[a-f0-9]{64}", result_id):
            raise CompanionError("分析结果编号无效。")
        path = self.folder / (result_id + ".json")
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != result_id
        ):
            raise CompanionError("分析结果不存在或已改变。")
        result = json.loads(path.read_text(encoding="utf-8"))
        self.verify(result["sources"])
        return result
