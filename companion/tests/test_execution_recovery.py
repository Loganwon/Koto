"""Schemas and repeated-query identity are actual tool observations, not intent rules."""

from openpyxl import Workbook
from companion.tests.test_agent_lab import make_lab
from companion.tests.test_agent_lab_generality import source, query


def test_inspector_reports_true_matrix_columns_and_explicit_projection(tmp_path):
    store, task, broker, _ = make_lab(tmp_path)
    book = Workbook()
    book.active.title = "P&L"
    book.active.append([None, "2025E"])
    book.active.append(["收入", 75])
    book.save(broker.workspace._root / "矩阵.xlsx")
    book.close()
    facts = broker.invoke("inspect_source", {"file_id": "矩阵.xlsx"})
    assert (
        facts["ok"] and facts["columns"][:2] == ["A", "B"] and facts["row_count"] == 2
    )
    assert (
        facts["query_source"]["header_mode"] == "coordinates"
        and facts["query_source"]["formula_values"] == "cached"
    )
    assert facts["preview"][1][:3] == ["收入", 75, 2]


def test_sql_error_returns_actual_columns_and_recovers_before_hard_stop(tmp_path):
    store, task, broker, _ = make_lab(tmp_path)
    source(tmp_path)
    for step in (1, 2):
        broker.turn.model_step = step
        failure = query(broker, "SELECT F69 FROM orders")
    assert failure["recovery"]["code"] == "query_error"
    assert failure["recovery"]["inputs"][0]["columns"] == ["id", "amount"]
    assert failure["recovery"]["next_tool"]["name"] == "inspect_source"
    assert broker.turn.recovery_observation and not broker.turn.blocked_error
    assert query(broker, "SELECT id FROM orders")["ok"]


def test_unstructured_source_has_read_tool_path_instead_of_repeating_sql(tmp_path):
    store, task, broker, _ = make_lab(tmp_path)
    (broker.workspace._root / "说明.txt").write_text("业务限定", encoding="utf-8")
    inspected = broker.invoke("inspect_source", {"file_id": "说明.txt"})
    assert (
        not inspected["structured_query"]
        and inspected["next_tool"]["name"] == "read_reference"
    )
    failed = broker.invoke(
        "query_data",
        {"sources": [{"name": "s", "file_id": "说明.txt"}], "sql": "SELECT * FROM s"},
    )
    assert failed["recovery"]["code"] == "unsupported_query_source"


def test_equivalent_queries_share_observation_identity_but_new_rows_do_not(tmp_path):
    store, task, broker, _ = make_lab(tmp_path)
    source(tmp_path)
    replies = []
    for step, sql in enumerate(
        [
            "SELECT * FROM orders",
            "SELECT  * FROM orders",
            "SELECT * FROM orders WHERE 1=1",
        ],
        1,
    ):
        broker.turn.model_step = step
        replies.append(query(broker, sql))
    assert len({r["result_id"] for r in replies}) == 3
    assert len({r["evidence_digest"] for r in replies}) == 1
    assert "progress_notice" in replies[-1] and broker.turn.recovery_observation
    (broker.workspace._root / "订单.csv").write_text(
        "客户,类别,金额\nA,硬件,15.00\n", encoding="utf-8"
    )
    broker.turn.recovery_observation = None
    broker.turn.model_step = 4
    fresh = query(broker, "SELECT * FROM orders")
    assert (
        fresh["evidence_digest"] != replies[-1]["evidence_digest"]
        and not broker.turn.recovery_observation
    )


def test_inspection_exposes_missing_formula_cache_and_does_not_modify_source(tmp_path):
    import hashlib

    store, task, broker, _ = make_lab(tmp_path)
    book = Workbook()
    book.active.append(["项目", "金额"])
    book.active.append(["预测", "=1+2"])
    path = broker.workspace._root / "缓存.xlsx"
    book.save(path)
    book.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    facts = broker.invoke("inspect_source", {"file_id": "缓存.xlsx"})
    assert facts["ok"] and facts["source"]["missing_formula_cache_count"] == 1
    assert (
        facts["preview"][0][1] is None and not facts["source"]["formulas_recalculated"]
    )
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
