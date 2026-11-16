"""The evaluator accepts presentation changes, rejects changed numeric facts."""

import pytest

from companion.tests.run_agent_evaluation import (
    Case, EvaluationDocument, amount_matches, checks_for, fact_matches,
)


@pytest.mark.parametrize(
    "expected,text,correct",
    [
        ("12840", "活跃用户 12,840", True),
        ("2027年2月", "周期为 2027 年 2 月", True),
        ("12840", "活跃用户 128400", False),
        ("240", "营收1240万元", False),
        ("410.7", "410.70万元", True),
        ("410.7", "410.71万元", False),
        ("8760", "预算876万元", False),
        ("20%", "同比 20%", True),
        ("20%", "同比120%", False),
        ("万元", "总额200万元", True),
    ],
)
def test_grader_distinguishes_numeric_facts_from_formatting(expected, text, correct):
    assert fact_matches(expected, text) is correct


@pytest.mark.parametrize(
    "text,value,unit,strict,correct",
    [
        ("总额4107000元", "410.7", "万元", False, True),
        ("总额4107000元", "410.7", "万元", True, False),
        ("总额87.6万元", "8760", "万元", False, False),
        ("总额8,760.00 万元", "8760", "万元", True, True),
    ],
)
def test_grader_checks_amounts_and_preserves_explicit_units(
    text, value, unit, strict, correct
):
    assert amount_matches(value, unit, text, strict) is correct


def test_audit_retains_wrong_target_write_instead_of_hiding_it_as_empty_answer():
    case = Case("create a separate file", "Create a PPT", phase="answered")
    document = EvaluationDocument(("original", "untouched"))
    document.text[0] = "unrequested replacement"
    document.writes.append({"index": 0, "text": document.text[0]})
    state = {
        "phase": "review", "latest": {"after": document.text[0]}, "answer": "",
        "sources": [], "events": [],
    }
    output, checks = checks_for(case, state, document, document.original)
    assert output == "unrequested replacement"
    assert not checks["任务类型正确"]
    assert not checks["只改一个片段或保持只读"]
