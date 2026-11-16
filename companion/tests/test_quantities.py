import pytest

from companion.contracts import CompanionError
from companion.quantities import QuantityLedger
from companion.session import EditingSession
from companion.tests.test_session import Documents, settled
from companion.tests.test_workspace_agent import agent_for, response


def test_scale_conversion_keeps_value_and_unit_together():
    ledger = QuantityLedger()
    proof = ledger.convert("87.6", "million yuan", "万元")
    assert proof["target"] == {"value": "8760", "unit": "万元"}
    ledger.verify("批准预算为8,760.00 万元。", [proof["quantity_id"]])
    for text, identifiers in [
        ("87.6万元", ["q1"]),
        ("8760元", ["q1"]),
        ("8760万元", []),
        ("8760万元", ["q2"]),
    ]:
        with pytest.raises(CompanionError):
            ledger.verify(text, identifiers)


@pytest.mark.parametrize(
    "value,source,target",
    [
        ("NaN", "元", "万元"),
        ("1e1000", "元", "万元"),
        ("1", "USD", "万元"),
        ("1", "元", "美元"),
    ],
)
def test_converter_rejects_unbounded_numbers_and_currency_exchange(
    value, source, target
):
    with pytest.raises(CompanionError):
        QuantityLedger().convert(value, source, target)


def test_wrong_converted_amount_is_repaired_before_any_document_write():
    documents = Documents()

    def corrected(payload):
        assert not documents.writes
        error = [m for m in payload["messages"] if m["role"] == "tool"][-1]["content"]
        assert "8760" in error and "尚未执行" in error
        return response(
            (
                "replace_current_text",
                {
                    "text": "批准预算为8760万元。",
                    "note": "已核对数量级",
                    "quantity_checks": ["q1"],
                },
            )
        )

    model, _ = agent_for(
        [
            [
                (
                    "convert_quantity",
                    {"value": "87.6", "from_unit": "million yuan", "to_unit": "万元"},
                )
            ],
            [
                (
                    "replace_current_text",
                    {
                        "text": "批准预算为87.6万元。",
                        "note": "单位错误",
                        "quantity_checks": ["q1"],
                    },
                )
            ],
            corrected,
        ]
    )
    session = EditingSession(documents, lambda: model)
    session.connect("word")
    session.start("把87.6百万元写成万元", agent=True)
    state = settled(session)
    assert state["phase"] == "review" and documents.writes == ["one"]
    assert documents.text["one"] == "批准预算为8760万元。"
