"""Saved Word tables become versioned numeric evidence, rather than LLM memory."""

from docx import Document
import pytest

from companion.agent_lab.data_engine import money_cents
from companion.tests.test_agent_lab import make_lab


def test_word_table_can_be_aggregated_and_bound_to_actual_currency_facts(tmp_path):
    store, task, broker, _ = make_lab(tmp_path, outputs=("摘要.docx",))
    doc = Document()
    table = doc.add_table(rows=1, cols=2)
    for c, t in zip(table.rows[0].cells, ["季度", "收入"]):
        c.text = t
    for quarter, amount in [
        ("2025Q1", "1,730,000"),
        ("2025Q2", "2,080,000"),
        ("2025Q3", "2,470,000"),
        ("2025Q4", "3,070,000"),
    ]:
        row = table.add_row().cells
        row[0].text = quarter
        row[1].text = amount
    path = tmp_path / "sources/收入.docx"
    doc.save(path)
    description = broker.invoke("inspect_source", {"file_id": "收入.docx"})
    assert description["structured_query"] and description["tables"][0]["rows"] == 5
    result = broker.invoke(
        "query_data",
        {
            "sources": [{"name": "s", "file_id": "收入.docx", "table": 0}],
            "sql": 'SELECT SUM(money_cents("收入")) AS total FROM s',
        },
    )
    assert (
        result["ok"]
        and result["preview"] == [[935000000]]
        and result["column_units"]["total"] == "分"
    )
    check = broker.invoke(
        "set_content_checks",
        {
            "file_name": "摘要.docx",
            "query_facts": [
                {
                    "id": "annual",
                    "result_id": result["result_id"],
                    "row": 0,
                    "column": "total",
                    "label": "全年收入",
                    "from_unit": "分",
                    "to_unit": "万元",
                    "decimals": 2,
                }
            ],
        },
    )
    assert check["ok"] and check["required_phrases"] == ["全年收入：935.00万元"]
    doc.add_paragraph("资料更新")
    doc.save(path)
    assert not broker.invoke("read_query_result", {"result_id": result["result_id"]})[
        "ok"
    ]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1,234.50", 123450),
        ("12,34.50", None),
        ("1,234.567", None),
        ("", None),
        ("bad", None),
    ],
)
def test_grouped_currency_is_explicitly_validated_and_never_coerced_to_zero(
    value, expected
):
    assert money_cents(value) == expected
