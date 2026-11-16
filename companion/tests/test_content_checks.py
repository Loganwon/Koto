"""Evidence provenance and actual Office body checks, independent of LLM verdicts."""

from docx import Document
from companion.tests.test_agent_lab import make_lab


def setup_contract(tmp_path):
    store, task, broker, _ = make_lab(tmp_path, outputs=("结果.docx",))
    source = tmp_path / "sources" / "销售.csv"
    source.write_text("项目,金额分\nA,1234567\nB,765433\n", encoding="utf-8")
    result = broker.invoke(
        "query_data",
        {
            "sources": [{"name": "s", "file_id": "销售.csv"}],
            "sql": 'SELECT SUM("金额分") AS total FROM s',
        },
    )
    contract = broker.invoke(
        "set_content_checks",
        {
            "file_name": "结果.docx",
            "query_facts": [
                {
                    "id": "total",
                    "result_id": result["result_id"],
                    "row": 0,
                    "column": "total",
                    "label": "合计",
                    "from_unit": "分",
                    "to_unit": "万元",
                    "decimals": 2,
                }
            ],
            "required_sources": ["销售.csv"],
        },
    )
    assert contract["ok"] and contract["required_phrases"] == ["合计：2.00万元"]
    return store, task, broker, source


def draft(broker, text, title="验收"):
    return broker.invoke(
        "create_word",
        {
            "action_id": "word",
            "file_name": "结果.docx",
            "title": title,
            "sections": [{"heading": "", "text": text}],
        },
    )


def test_wrong_unit_number_or_missing_source_never_published(tmp_path):
    store, task, broker, source = setup_contract(tmp_path)
    for i, text in enumerate(("合计：2000000.00万元。销售.csv", "合计：2.00万元。")):
        broker.turn.model_step = i + 1
        rejected = draft(broker, text)
        assert (
            not rejected["ok"]
            and rejected["recovery"]["code"] == "content_check_mismatch"
        )
        assert not (broker.outputs / "结果.docx").exists()
    assert draft(broker, "合计：2.00万元。来源：销售.csv")["ok"]
    assert broker.invoke("complete_task", {"summary": "完成"})["ok"]
    source.write_text("项目,金额分\nA,1\n", encoding="utf-8")
    facts = broker.invoke("check_completion", {})
    assert not facts["ready"] and "来源已改变" in str(facts["invalid_outputs"])


def test_title_cannot_satisfy_body_and_false_quote_rejected(tmp_path):
    store, task, broker, source = setup_contract(tmp_path)
    assert not draft(broker, "只有正文", "合计：2.00万元 销售.csv")["ok"]
    quoted = broker.invoke(
        "set_content_checks",
        {
            "file_name": "结果.docx",
            "source_quotes": [
                {"id": "q", "file_id": "销售.csv", "quote": "不存在的引文"}
            ],
        },
    )
    assert not quoted["ok"]
    doc = Document()
    doc.add_paragraph("收入为示例，未经独立验证。")
    doc.save(tmp_path / "sources" / "说明.docx")
    result = broker.invoke(
        "set_content_checks",
        {
            "file_name": "结果.docx",
            "source_quotes": [
                {
                    "id": "q",
                    "file_id": "说明.docx",
                    "quote": "收入为示例，未经独立验证。",
                }
            ],
        },
    )
    assert result["ok"]
    assert not draft(broker, "合计：2.00万元。销售.csv 说明.docx")["ok"]
    assert draft(
        broker, "合计：2.00万元。销售.csv 说明.docx 收入为示例，未经独立验证。"
    )["ok"]


def test_persisted_checks_survive_new_broker_and_reject_changed_result(tmp_path):
    from companion.agent_lab.tools import ToolBroker
    from companion.agent_lab.store import TaskStore
    from companion.agent_lab.content_checks import violations

    store, task, broker, source = setup_contract(tmp_path)
    doc = broker.document
    store.close()
    store = TaskStore(tmp_path / "tasks.sqlite3")
    restored = ToolBroker(store, task, tmp_path / "sources", tmp_path / "outputs", doc)
    assert not violations(restored, "结果.docx", "合计：2.00万元。销售.csv")
    assert violations(restored, "结果.docx", "合计：20万元。销售.csv")


def test_registering_ppt_checks_is_not_mistaken_for_zero_page_draft(tmp_path):
    store, task, broker, _ = make_lab(tmp_path, outputs=("简报.pptx",))
    source = tmp_path / "sources" / "资料.txt"
    source.write_text("这是示例数据。", encoding="utf-8")
    assert broker.invoke(
        "set_output_limits",
        {
            "limits": [
                {
                    "file_name": "简报.pptx",
                    "exact_slide_count": 3,
                    "max_slide_body_characters": 60,
                }
            ]
        },
    )["ok"]
    contract = broker.invoke(
        "set_content_checks",
        {"file_name": "简报.pptx", "required_sources": ["资料.txt"]},
    )
    assert contract["ok"]
    args = {
        "action_id": "ppt",
        "file_name": "简报.pptx",
        "title": "简报",
        "sections": [{"heading": "标题", "text": "这是示例数据。资料.txt"}],
    }
    assert not broker.invoke("create_presentation", args)["ok"]
    args["sections"] *= 3
    assert broker.invoke("create_presentation", args)["ok"]


def test_bad_fact_cell_reports_real_typed_row_and_supports_saved_result_read(tmp_path):
    store, task, broker, source = setup_contract(tmp_path)
    result = broker.invoke(
        "query_data",
        {
            "sources": [{"name": "s", "file_id": "销售.csv"}],
            "sql": 'SELECT "项目", "金额分", printf("%.2f", "金额分"/100.0) AS display FROM s',
        },
    )
    fact = {
        "id": "bad",
        "result_id": result["result_id"],
        "row": 0,
        "column": "项目",
        "label": "金额",
        "from_unit": "分",
        "to_unit": "元",
        "decimals": 2,
    }
    failed = broker.invoke(
        "set_content_checks", {"file_name": "结果.docx", "query_facts": [fact]}
    )
    assert not failed["ok"] and failed["recovery"]["code"] == "invalid_fact_cell"
    assert failed["recovery"]["actual_row"][1] == {
        "column": "金额分",
        "value": "1234567",
        "type": "str",
    }
    assert failed["recovery"]["column_units"]["金额分"] == "分"
    broker.analysis_evidence = []  # A new turn need not retain model observations.
    page = broker.invoke(
        "read_query_result",
        {
            "result_id": result["result_id"],
            "start": 1,
            "limit": 1,
            "columns": ["项目", "金额分"],
        },
    )
    assert page["ok"] and page["rows"] == [{"row": 1, "values": ["B", "765433"]}]
    assert broker.analysis_evidence[-1]["result_id"] == result["result_id"]
    repaired = broker.invoke(
        "set_content_checks",
        {"file_name": "结果.docx", "query_facts": [{**fact, "column": "金额分"}]},
    )
    assert repaired["ok"]
    source.write_text("项目,金额分\nA,1\n", encoding="utf-8")
    assert not broker.invoke("read_query_result", {"result_id": result["result_id"]})[
        "ok"
    ]


def test_old_full_result_remains_discoverable_after_many_preview_queries(tmp_path):
    store, task, broker, source = setup_contract(tmp_path)
    full = broker.invoke(
        "query_data",
        {"sources": [{"name": "s", "file_id": "销售.csv"}], "sql": "SELECT * FROM s"},
    )
    for number in range(12):
        assert broker.invoke(
            "query_data",
            {
                "sources": [{"name": "s", "file_id": "销售.csv"}],
                "sql": f"SELECT {number} AS position FROM s LIMIT 1",
            },
        )["ok"]
    values = broker.invoke("list_query_results", {"minimum_rows": 2})
    assert values["ok"] and any(
        v["result_id"] == full["result_id"] for v in values["results"]
    )
    invalid = broker.invoke(
        "read_query_result", {"result_id": full["result_id"], "limit": 50}
    )
    assert invalid["recovery"]["code"] == "invalid_arguments"
    assert invalid["recovery"]["schema"]["properties"]["limit"]["maximum"] == 20
