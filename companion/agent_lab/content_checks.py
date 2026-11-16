"""Evidence-bound acceptance checks; prose and model verdicts are not evidence."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import hashlib
from pathlib import Path

from companion.contracts import CompanionError, DocumentConflict
from companion.file_readers import parse_file
from .execution_errors import ToolDiagnosticError

SCALES = {"分": -2, "元": 0, "千元": 3, "万元": 4, "百万元": 6, "亿元": 8}
UNITS = ["number", "%", *SCALES]


def register_tool(add, string):
    fact = {
        "type": "object",
        "properties": {
            "id": string,
            "result_id": string,
            "row": {"type": "integer", "minimum": 0, "maximum": 19999},
            "column": string,
            "label": string,
            "from_unit": {"type": "string", "enum": UNITS},
            "to_unit": {"type": "string", "enum": UNITS},
            "decimals": {"type": "integer", "minimum": 0, "maximum": 8},
        },
        "required": [
            "id",
            "result_id",
            "row",
            "column",
            "label",
            "from_unit",
            "to_unit",
            "decimals",
        ],
        "additionalProperties": False,
    }
    quote = {
        "type": "object",
        "properties": {"id": string, "file_id": string, "quote": string},
        "required": ["id", "file_id", "quote"],
        "additionalProperties": False,
    }
    add(
        "set_content_checks",
        "Bind acceptance checks to a current DOCX/PPTX/XLSX deliverable BEFORE drafting. query_facts reference an actual durable query_data result cell (zero-based row, exact column), never a model-provided expected number. Host returns required phrases 'label：valueunit', with exact decimal unit conversion/rounding. Include these phrases in BODY text or worksheet text cells. source_quotes are ONLY for user-required VERBATIM quotations, never impose them on a paraphrased summary; they must exist literally in the source. required_sources requires literal file_id citations. Checks persist, merge by stable id, and run before publishing and at completion. Source changes invalidate old checks. This checks registered facts, not every claim or the truth of a SQL query.",
        {
            "file_name": string,
            "query_facts": {"type": "array", "maxItems": 30, "items": fact},
            "source_quotes": {"type": "array", "maxItems": 20, "items": quote},
            "required_sources": {"type": "array", "maxItems": 20, "items": string},
        },
        ["file_name"],
        "contract",
    )


def _proof(broker, file_id):
    path = broker.workspace._path(file_id)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise CompanionError("内容验收来源超过16MiB上限。")
    return {"file_id": file_id, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _fact(broker, args):
    result = broker.data.result(args["result_id"])
    try:
        value = result["rows"][args["row"]][result["columns"].index(args["column"])]
        if value is None or isinstance(value, bool):
            raise ValueError()
        number = Decimal(str(value))
        if not number.is_finite() or number.adjusted() > 40:
            raise ValueError()
    except (ValueError, IndexError, InvalidOperation):
        raise _fact_error(
            args,
            result,
            "invalid_fact_cell",
            "事实定位无效或对应值不是数字；请核对查询的真实行列。",
        ) from None
    a, b = args["from_unit"], args["to_unit"]
    units = result.get("column_units", {})
    actual_unit = units.get(args["column"])
    if a in SCALES and actual_unit is None:
        raise _fact_error(
            args,
            result,
            "unknown_fact_unit",
            "查询列的金额单位无法追溯；请使用money_cents/money_product_cents或带明确单位的来源列重新查询。",
        )
    if actual_unit is not None and actual_unit != a:
        raise _fact_error(
            args,
            result,
            "fact_unit_mismatch",
            f"查询列实际单位为{actual_unit}，不能声明为{a}；请按真实单位绑定。",
        )
    if a in SCALES and b in SCALES:
        factor = Decimal(10) ** (SCALES[a] - SCALES[b])
    elif a == b:
        factor = Decimal(1)
    elif (a, b) == ("number", "%"):
        factor = Decimal(100)
    elif (a, b) == ("%", "number"):
        factor = Decimal(".01")
    else:
        raise CompanionError("不能将金额与比例/无量纲数字互相换算。")
    label = args["label"]
    if not label.strip() or len(label) > 80:
        raise CompanionError("事实标签需要1至80字符。")
    with localcontext() as ctx:
        ctx.prec = 64
        rendered = format(
            (number * factor).quantize(
                Decimal(1).scaleb(-args["decimals"]), rounding=ROUND_HALF_UP
            ),
            "f",
        )
    return {
        **args,
        "phrase": label + "：" + rendered + ("" if b == "number" else b),
        "sources": result["sources"],
    }


def _fact_error(args, result, code, message):
    """Expose saved evidence, without guessing the intended cell or its unit."""
    row = args["row"]
    values = result["rows"][row] if 0 <= row < len(result["rows"]) else []
    return ToolDiagnosticError(
        message,
        {
            "code": code,
            "result_id": args["result_id"],
            "requested": {
                k: args[k] for k in ("row", "column", "from_unit", "to_unit")
            },
            "row_count": len(result["rows"]),
            "row_index_base": 0,
            "column_units": result.get("column_units", {}),
            "actual_row": [
                {
                    "column": c,
                    "value": v[:160] if isinstance(v, str) else v,
                    "type": type(v).__name__,
                }
                for c, v in zip(result["columns"], values)
            ],
            "next_tool": {
                "name": "read_query_result",
                "arguments": {
                    "result_id": args["result_id"],
                    "start": max(0, row - 1),
                    "limit": 3,
                },
            },
            "guidance": "按真实列名及0起始行号选数值列；格式化文字列不能作数值事实。未知金额单位不能靠SQL别名或money_cents伪造；需先读取来源单位依据。仅说明口径的文档可以不登记额外数字事实，仍须通过既有内容验收。",
        },
    )


def declare(broker, args):
    state = broker.store.get(broker.task)
    name = args["file_name"]
    if name not in state["expected_outputs"] or Path(name).suffix.lower() not in {
        ".docx",
        ".pptx",
        ".xlsx",
    }:
        raise CompanionError("内容验收仅绑定当前交付清单中的DOCX/PPTX/XLSX。")
    previous = state.get("content_checks", {}).get(name, {})
    facts = {v["id"]: v for v in previous.get("facts", [])}
    quotes = {v["id"]: v for v in previous.get("quotes", [])}
    for item in args.get("query_facts", []):
        fact = _fact(broker, item)
        required = getattr(broker, "required_fact_ids", None)
        prior = facts.get(item["id"], {})
        fact["required"] = (
            prior.get("required", False) or required is None or item["id"] in required
        )
        facts[item["id"]] = fact
    for item in args.get("source_quotes", []):
        # These durable contracts bind SAVED bytes, not an unpersisted live
        # snapshot whose disk hash could remain unchanged after user edits.
        proof = _proof(broker, item["file_id"])
        snap = parse_file(broker.workspace._path(item["file_id"]))
        if (
            not item["quote"].strip()
            or len(item["quote"]) > 1500
            or item["quote"] not in snap.text
        ):
            raise CompanionError(
                "引文未在实际资料中找到；不能登记模型编造或改写的引文。"
            )
        if _proof(broker, item["file_id"]) != proof:
            raise DocumentConflict("引文读取期间来源已改变。")
        quotes[item["id"]] = {**item, "sources": [proof]}
    proofs = {v["file_id"]: v for v in previous.get("sources", [])}
    for item in [*facts.values(), *quotes.values()]:
        for proof in item["sources"]:
            old = proofs.get(proof["file_id"])
            if old and old["sha256"] != proof["sha256"]:
                raise DocumentConflict(
                    "同一验收合同中来源版本冲突，请使用新交付重新核对。"
                )
            proofs[proof["file_id"]] = proof
    for file_id in args.get("required_sources", []):
        proof = _proof(broker, file_id)
        if file_id in proofs and proofs[file_id]["sha256"] != proof["sha256"]:
            raise DocumentConflict("来源版本变化，请重新核对资料。")
        proofs[file_id] = proof
    if not (facts or quotes or proofs):
        raise CompanionError("请登记至少一项实际事实、引文或来源。")
    if len(facts) > 30 or len(quotes) > 20 or len(proofs) > 20:
        raise CompanionError("本交付内容验收超过预算。")
    contract = {
        "facts": list(facts.values()),
        "quotes": list(quotes.values()),
        "sources": list(proofs.values()),
        "terms": previous.get("terms", []),
    }
    checks = {**state.get("content_checks", {}), name: contract}
    broker.store.change(
        broker.task,
        content_checks=checks,
        phase="review" if state["review"] else "active",
    )
    broker.store.event(
        broker.task,
        "content_checks_updated",
        {
            "file_name": name,
            "facts": len(facts),
            "quotes": len(quotes),
            "sources": len(proofs),
        },
    )
    return {
        "file_name": name,
        "required_phrases": [
            v["phrase"] for v in facts.values() if v.get("required", True)
        ],
        "verified_phrases": [v["phrase"] for v in facts.values()],
        "required_quotes": [v["quote"] for v in quotes.values()],
        "required_citations": list(proofs),
        "required_terms": contract["terms"],
        "scope": "仅核对已登记事实、真实引文和来源版本；SQL语义及其他陈述仍需验收。",
    }


def body_text(path):
    if path.suffix.lower() == ".xlsx":
        return parse_file(path).text
    if path.suffix.lower() == ".docx":
        from docx import Document

        doc = Document(path)
        return "\n".join(
            [p.text for p in doc.paragraphs if p.style.name != "Title"]
            + [c.text for t in doc.tables for r in t.rows for c in r.cells]
        )
    from pptx import Presentation

    return "\n".join(
        s.text
        for slide in Presentation(path).slides
        for s in slide.shapes
        if s.has_text_frame
        and (slide.shapes.title is None or s.shape_id != slide.shapes.title.shape_id)
    )


def violations(broker, name, text):
    contract = broker.store.get(broker.task).get("content_checks", {}).get(name)
    if not contract:
        return []
    errors = []
    for term in contract.get("terms", []):
        if term not in text:
            errors.append("正文缺少必留词：" + term)
    for proof in contract["sources"]:
        try:
            if _proof(broker, proof["file_id"])["sha256"] != proof["sha256"]:
                errors.append("来源已改变：" + proof["file_id"])
        except (OSError, CompanionError):
            errors.append("来源无法核对：" + proof["file_id"])
        if proof["file_id"] not in text:
            errors.append("正文缺少来源：" + proof["file_id"])
    for item in contract["facts"]:
        if item["phrase"] not in text and (
            item.get("required", True) or item["label"] in text
        ):
            errors.append("正文需包含核对值：" + item["phrase"])
    for item in contract["quotes"]:
        if item["quote"] not in text:
            errors.append("正文缺少真实引文：" + item["quote"])
    return errors


def check_draft(broker, name, args):
    if name not in {"create_word", "create_presentation"}:
        return
    text = "\n".join(
        [s["heading"] + "\n" + s["text"] for s in args.get("sections", [])]
        + [c for t in args.get("tables", []) for r in t for c in r]
    )
    errors = violations(broker, args["file_name"], text)
    if errors:
        raise ToolDiagnosticError(
            "内容验收未通过，未发布：" + "；".join(errors),
            {
                "code": "content_check_mismatch",
                "violations": errors,
                "guidance": "按真实工具返回的数值、单位、引文及来源修正正文，不要放宽验收。",
            },
        )
