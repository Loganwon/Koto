"""Mechanism tests: authority, bounded data queries and versioned workbook writes."""

import hashlib
import json
import threading

from openpyxl import load_workbook
import pytest

from companion.agent_lab.tools import Turn
from companion.tests.test_agent_lab import make_lab


def query(broker, sql="SELECT * FROM orders", preview=15):
    return broker.invoke(
        "query_data",
        {
            "sources": [{"name": "orders", "file_id": "订单.csv"}],
            "sql": sql,
            "preview": preview,
        },
    )


def source(tmp_path):
    (tmp_path / "sources/订单.csv").write_text(
        "id,amount\nA,12.34\nA,12.34\nB,8.11\nC,待定\n", encoding="utf-8"
    )


def test_query_deduplicates_and_reports_invalid_numbers_without_silent_zero(tmp_path):
    store, task, broker, doc = make_lab(tmp_path)
    source(tmp_path)
    result = query(
        broker,
        "SELECT SUM(money_cents(amount)) AS cents, COUNT(*) AS n FROM (SELECT DISTINCT id, amount FROM orders) WHERE money_cents(amount) IS NOT NULL",
    )
    assert result["ok"] and result["row_count"] == 1
    assert result["preview"] == [[2045, 2]]
    invalid = query(broker, "SELECT id FROM orders WHERE money_cents(amount) IS NULL")
    assert invalid["preview"] == [["C"]]
    assert not store.get(task)["artifacts"]


@pytest.mark.parametrize(
    "sql",
    [
        "ATTACH DATABASE 'secret.sqlite3' AS host",
        "DROP TABLE orders",
        "SELECT load_extension('x')",
        "SELECT readfile('C:/Users/12524/Desktop/DS_KEY.txt')",
        "SELECT randomblob(1000000000)",
        "SELECT 1; SELECT 2",
    ],
)
def test_query_rejects_host_access_and_non_select_programs(tmp_path, sql):
    store, task, broker, doc = make_lab(tmp_path)
    source(tmp_path)
    assert not query(broker, sql)["ok"]
    assert query(broker)["ok"]


def test_result_handles_export_every_row_after_restart_and_detect_changed_source(
    tmp_path,
):
    store, task, broker, doc = make_lab(tmp_path)
    source(tmp_path)
    result = query(broker, preview=1)
    assert result["row_count"] == 4 and result["preview_truncated"]
    from companion.agent_lab.data_engine import DataEngine

    broker.data = DataEngine(broker.workspace, broker.data.folder, broker.permitted)
    args = {
        "action_id": "book",
        "file_name": "全部.xlsx",
        "sheets": [{"name": "明细", "result_id": result["result_id"]}],
    }
    assert broker.invoke("create_workbook", args)["ok"]
    wb = load_workbook(tmp_path / "outputs/全部.xlsx")
    assert wb.active.max_row == 5
    wb.close()
    (tmp_path / "sources/订单.csv").write_text("id,amount\nA,99.99\n", encoding="utf-8")
    assert not broker.invoke(
        "create_workbook", {**args, "file_name": "过期.xlsx", "action_id": "stale"}
    )["ok"]
    assert not (tmp_path / "outputs/过期.xlsx").exists()
    assert store.get(task)["phase"] != "uncertain"


def test_literal_equals_text_and_explicit_formulas_roundtrip_separately(tmp_path):
    store, task, broker, doc = make_lab(tmp_path)
    args = {
        "action_id": "book",
        "file_name": "预算.xlsx",
        "sheets": [
            {
                "name": "明细",
                "rows": [["=1+1", 3, 12.5]],
                "cells": [{"address": "D1", "type": "formula", "value": "=B1*C1"}],
            },
            {
                "name": "汇总",
                "cells": [
                    {"address": "A1", "type": "formula", "value": "=SUM(明细!D1:D1)"}
                ],
            },
        ],
    }
    result = broker.invoke("create_workbook", args)
    assert result["ok"] and result["receipt"]["formulas_recalculated"] is False
    wb = load_workbook(tmp_path / "outputs/预算.xlsx")
    assert wb["明细"]["A1"].value == "=1+1" and wb["明细"]["A1"].data_type == "s"
    assert wb["明细"]["D1"].data_type == "f"
    assert wb["汇总"]["A1"].value == "=SUM(明细!D1:D1)"
    wb.close()


def test_numeric_readback_compares_exact_spreadsheet_serialization(
    tmp_path, monkeypatch
):
    from companion.agent_lab import workbooks
    from companion.contracts import CompanionError
    from openpyxl import Workbook

    store, task, broker, doc = make_lab(tmp_path)
    value = 1070.2600000000002
    result = broker.invoke(
        "create_workbook",
        {
            "action_id": "float",
            "file_name": "精度.xlsx",
            "sheets": [{"name": "金额", "rows": [[value], ["", None]]}],
        },
    )
    assert result["ok"], result
    wb = load_workbook(tmp_path / "outputs/精度.xlsx")
    assert wb.active["A1"].value == float(format(value, ".16g"))
    assert wb.active["A2"].value is None and wb.active["B2"].value is None
    wb.close()
    # A genuine one-cent readback discrepancy must still reject publication.
    original_save = Workbook.save

    def corrupt_save(book, path):
        expected = book.active["A1"].value
        book.active["A1"] = expected + 0.01
        original_save(book, path)
        book.active["A1"] = expected

    monkeypatch.setattr(Workbook, "save", corrupt_save)
    book = Workbook()
    book.active["A1"] = 54.0
    target = tmp_path / "outputs/错误.xlsx"
    with pytest.raises(CompanionError, match="读回不一致"):
        workbooks._publish(book, target, lambda: True)
    assert not target.exists()


@pytest.mark.parametrize(
    "formula",
    [
        '=WEBSERVICE("https://example.com")',
        "='[other.xlsx]sheet'!A1",
        '=HYPERLINK("https://example.com")',
    ],
)
def test_unsupported_formulas_do_not_publish_or_poison_retry(tmp_path, formula):
    store, task, broker, doc = make_lab(tmp_path)
    args = {
        "action_id": "book",
        "file_name": "预算.xlsx",
        "sheets": [
            {
                "name": "明细",
                "cells": [{"address": "A1", "type": "formula", "value": formula}],
            }
        ],
    }
    assert not broker.invoke("create_workbook", args)["ok"]
    assert not (tmp_path / "outputs/预算.xlsx").exists()
    assert store.get(task)["phase"] != "uncertain"
    args["sheets"][0]["cells"][0]["value"] = "=SUM(1,2)"
    assert broker.invoke("create_workbook", args)["ok"]


def test_revision_preserves_other_sheets_cells_and_prior_version_with_idempotency(
    tmp_path,
):
    store, task, broker, doc = make_lab(tmp_path)
    args = {
        "action_id": "book",
        "file_name": "预算.xlsx",
        "sheets": [
            {
                "name": "明细",
                "rows": [["项目", "金额"], ["设备", 37.5], ["服务", 16.5]],
            },
            {"name": "备注", "rows": [["保持此页"]]},
        ],
    }
    old = broker.invoke("create_workbook", args)["receipt"]
    changes = {
        "action_id": "rev1",
        "file_name": "预算.xlsx",
        "expected_sha256": old["sha256"],
        "changes": [
            {
                "sheet": "明细",
                "address": "B3",
                "expected": 16.5,
                "type": "number",
                "value": 18.5,
            }
        ],
    }
    result = broker.invoke("revise_workbook", changes)
    assert result["ok"] and result["receipt"]["previous_sha256"] == old["sha256"]
    assert (
        hashlib.sha256(
            (tmp_path / "artifact_versions" / (old["sha256"] + ".xlsx")).read_bytes()
        ).hexdigest()
        == old["sha256"]
    )
    wb = load_workbook(tmp_path / "outputs/预算.xlsx")
    assert wb["明细"]["B3"].value == 18.5 and wb["明细"]["B2"].value == 37.5
    assert wb["备注"]["A1"].value == "保持此页"
    wb.close()
    assert broker.invoke("revise_workbook", changes)["replayed_receipt"]
    assert not broker.invoke("revise_workbook", {**changes, "action_id": "stale"})["ok"]


def test_external_workbook_edits_are_never_overwritten(tmp_path):
    store, task, broker, doc = make_lab(tmp_path)
    old = broker.invoke(
        "create_workbook",
        {
            "action_id": "create",
            "file_name": "预算.xlsx",
            "sheets": [{"name": "数据", "rows": [[1]]}],
        },
    )["receipt"]
    path = tmp_path / "outputs/预算.xlsx"
    wb = load_workbook(path)
    wb.active["A1"] = 7
    wb.save(path)
    wb.close()
    result = broker.invoke(
        "revise_workbook",
        {
            "action_id": "rev",
            "file_name": "预算.xlsx",
            "expected_sha256": old["sha256"],
            "changes": [
                {
                    "sheet": "数据",
                    "address": "A1",
                    "expected": 1,
                    "type": "number",
                    "value": 2,
                }
            ],
        },
    )
    assert not result["ok"]
    wb = load_workbook(path)
    assert wb.active["A1"].value == 7
    wb.close()


def test_contract_revision_requires_verifier_and_exact_revision(tmp_path):
    store, task, broker, doc = make_lab(tmp_path, outputs=("摘要.docx", "汇报.pptx"))
    args = {
        "expected_revision": 0,
        "expected_outputs": ["客户简报.docx"],
        "reason": "用户取消并改名",
    }
    assert broker.invoke("revise_deliverables", args)["ok"]
    assert store.get(task)["expected_outputs"] == ["客户简报.docx"]
    assert store.get(task)["contract_history"][0]["before"] == [
        "摘要.docx",
        "汇报.pptx",
    ]
    assert not broker.invoke("revise_deliverables", args)["ok"]
    n, e = store.begin_turn(task, "只解释", "read")
    broker.bind_turn(Turn(task, n, e, "只解释", "read", threading.Event()))
    assert "revise_deliverables" not in [s["name"] for s in broker.definitions()]
    assert not broker.invoke("revise_deliverables", {**args, "expected_revision": 1})[
        "ok"
    ]
    n, e = store.begin_turn(task, "继续", "auto")
    broker.bind_turn(Turn(task, n, e, "继续", "auto", threading.Event()))
    broker.verifier = lambda *a: {"allowed": False, "reason": "用户没有取消交付物"}
    assert not broker.invoke(
        "revise_deliverables", {**args, "expected_revision": 1, "expected_outputs": []}
    )["ok"]
    assert store.get(task)["expected_outputs"] == ["客户简报.docx"]


def test_stop_during_semantic_check_cannot_change_contract(tmp_path):
    store, task, broker, doc = make_lab(tmp_path, outputs=("摘要.docx",))

    def stopped(*a):
        broker.turn.cancelled.set()
        return {"allowed": True}

    broker.verifier = stopped
    assert not broker.invoke(
        "revise_deliverables",
        {"expected_revision": 0, "expected_outputs": [], "reason": "取消"},
    )["ok"]
    assert store.get(task)["expected_outputs"] == ["摘要.docx"]


def test_query_result_limits_are_enforced_before_materializing_large_results(tmp_path):
    store, task, broker, doc = make_lab(tmp_path)
    source(tmp_path)
    assert not query(
        broker,
        "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<20001) SELECT x FROM n",
    )["ok"]
    assert not query(
        broker,
        "SELECT replace('xxxxxxxxxx', 'x', '"
        + "a" * 500
        + "') AS too_long FROM orders",
    )["ok"]
    assert query(broker)["ok"]


def test_safe_sql_text_functions_support_newlines_and_display_numbers(tmp_path):
    store, task, broker, doc = make_lab(tmp_path)
    source(tmp_path)
    result = query(
        broker,
        "SELECT char(10) AS newline, unicode('中') AS codepoint, printf('%.2f',12.3) AS amount FROM orders LIMIT 1",
    )
    assert result["ok"] and result["preview"] == [["\n", 20013, "12.30"]]
    assert not query(broker, "SELECT load_extension('untrusted') FROM orders")["ok"]


def test_new_revision_reopens_completed_task_until_completion_is_verified_again(
    tmp_path,
):
    store, task, broker, doc = make_lab(tmp_path, outputs=("预算.xlsx",))
    receipt = broker.invoke(
        "create_workbook",
        {
            "action_id": "create",
            "file_name": "预算.xlsx",
            "sheets": [{"name": "数据", "rows": [[1]]}],
        },
    )["receipt"]
    assert broker.invoke("complete_task", {"summary": "初稿完成"})["ok"]
    assert store.get(task)["phase"] == "complete"
    assert broker.invoke(
        "revise_workbook",
        {
            "action_id": "rev",
            "file_name": "预算.xlsx",
            "expected_sha256": receipt["sha256"],
            "changes": [
                {
                    "sheet": "数据",
                    "address": "A1",
                    "expected": 1,
                    "type": "number",
                    "value": 2,
                }
            ],
        },
    )["ok"]
    assert store.get(task)["phase"] == "active"
    assert broker.invoke("complete_task", {"summary": "修订完成"})["ok"]
    assert store.get(task)["phase"] == "complete"
