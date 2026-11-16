"""Bind native prose numbers to durable query cells before a host write."""

from .agent_lab.content_checks import _fact
from .agent_lab.execution_errors import ToolDiagnosticError
from .contracts import CompanionError
from decimal import Decimal, InvalidOperation
import re


def inferred_dependencies(broker, args):
    """A newly introduced monetary claim cannot disclaim a real query read."""
    from .agent_lab.content_checks import SCALES

    claims = re.findall(
        r"([+-]?\d[\d,]*(?:\.\d+)?)\s*(百万元|千元|万元|亿元|元|分)", args["text"]
    )
    introduced = [
        (value, unit)
        for value, unit in claims
        if value + unit not in re.sub(r"\s", "", args.get("expected", ""))
    ]
    if not introduced:
        return set()
    raw_claims = {Decimal(text.replace(",", "")) for text, _ in introduced}
    normalized = {
        unit: {
            Decimal(text.replace(",", "")) * Decimal(10) ** SCALES[unit]
            for text, actual in introduced
            if actual == unit
        }
        for _, unit in introduced
    }
    yuan_claims = set().union(*normalized.values())
    found = set()
    for observation in broker.analysis_evidence:
        units = observation.get("column_units", {})
        if not any(unit in SCALES for unit in units.values()):
            continue
        result = broker.data.result(observation["result_id"])
        for i, column in enumerate(result["columns"]):
            unit = units.get(column)
            if unit not in SCALES:
                continue
            for row in result["rows"]:
                if row[i] is None or isinstance(row[i], bool):
                    continue
                try:
                    number = Decimal(str(row[i]))
                    if (
                        number in raw_claims
                        or number * Decimal(10) ** SCALES[unit] in yuan_claims
                    ):
                        found.update(s["file_id"] for s in result["sources"])
                except InvalidOperation:
                    continue
    return found


def install(broker):
    source = broker.specs["set_content_checks"]["parameters"]["properties"]
    broker.specs["set_native_content_checks"] = {
        "name": "set_native_content_checks",
        "description": (
            "Before apply_edit uses query_data numbers, bind the allowed fragment's "
            "facts to actual result cells. Same query_facts schema as set_content_checks. "
            "Host returns exact required_phrases with decimal unit conversion; include "
            "them literally in native text. money_product_cents returns CENTS (分), "
            "not yuan: 5400分 = 54.00元. This registers checks only; it does not edit."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "fragment_id": {"type": "string"},
                "query_facts": {**source["query_facts"], "minItems": 1},
            },
            "required": ["fragment_id", "query_facts"],
            "additionalProperties": False,
        },
        "effect": "contract",
    }


def declare(broker, args):
    fragment = args["fragment_id"]
    if not broker.edit_allowed or fragment not in broker.allowed_fragments:
        raise CompanionError("事实验收只能绑定本轮允许修改的原文片段。")
    facts = [_fact(broker, item) for item in args["query_facts"]]
    if len({v["id"] for v in facts}) != len(facts):
        raise CompanionError("事实验收标识不能重复。")
    state = broker.store.get(broker.task)
    prior = state.get("native_content_checks", {}).get(fragment, {})
    if prior.get("plan_revision") != broker.store.revision:
        prior = {}
    merged = {v["id"]: v for v in prior.get("facts", [])}
    merged.update({v["id"]: v for v in facts})
    contract = {"plan_revision": broker.store.revision, "facts": list(merged.values())}
    broker.store.change(
        broker.task,
        native_content_checks={
            **state.get("native_content_checks", {}),
            fragment: contract,
        },
    )
    broker.store.event(
        broker.task, "native_content_checks_updated", {"fragment": fragment, **contract}
    )
    return {
        "fragment_id": fragment,
        "required_phrases": [v["phrase"] for v in contract["facts"]],
    }


def check(broker, name, args):
    if name != "apply_edit":
        return
    contract = (
        broker.store.get(broker.task)
        .get("native_content_checks", {})
        .get(args["fragment_id"], {})
    )
    if contract.get("plan_revision") != broker.store.revision:
        contract = {}
    facts = contract.get("facts", [])
    declared = set(args.get("source_ids", []))
    query_sources = {
        s["file_id"]
        for observation in broker.analysis_evidence
        for s in observation["sources"]
        if s["file_id"] in declared
    }
    query_sources |= inferred_dependencies(broker, args)
    covered = {s["file_id"] for fact in facts for s in fact["sources"]}
    errors = []
    if query_sources - covered:
        errors.append(
            "查询数字须先绑定原文事实验收："
            + "、".join(sorted(query_sources - covered))
        )
    for fact in facts:
        # Reopens the immutable result and validates every source hash again.
        current = _fact(
            broker, {k: v for k, v in fact.items() if k not in {"phrase", "sources"}}
        )
        if current["phrase"] != fact["phrase"]:
            errors.append("事实验收已变化，请重新核对。")
        if fact["phrase"] not in args["text"]:
            errors.append("原文需包含核对值：" + fact["phrase"])
    if errors:
        raise ToolDiagnosticError(
            "原文事实验收未通过，未写入：" + "；".join(errors),
            {
                "code": "native_content_check_mismatch",
                "violations": errors,
                "next_tool": {
                    "name": "set_native_content_checks",
                    "arguments": {"fragment_id": args["fragment_id"]},
                },
                "guidance": "将实际query_data结果单元格及其真实单位绑定到当前片段，使用宿主返回的准确换算短语，不把整数分当成元。",
            },
        )
