"""Turn continuity retains only observed, live-version-verified source facts."""

import threading
from openpyxl import Workbook

from companion.agent_lab.tools import Turn
from companion.agent_lab.draft_editorial import canonical_facts
from companion.reading import TextSnapshot
from companion.tests.test_native_query_sources import setup, edit, query, bind_fact


def next_turn(broker):
    n, epoch = broker.store.begin_turn(broker.task, "继续原任务", "auto")
    broker.bind_turn(
        Turn(broker.task, n, epoch, "继续原任务", "auto", threading.Event())
    )


def test_unchanged_observed_sources_continue_without_reread(tmp_path):
    broker, host, refs = setup(tmp_path)
    assert broker.invoke("read_reference", {"file_id": "采购.csv"})["ok"]
    first = broker.verification_reads.copy()
    next_turn(broker)
    assert broker.verification_reads == first
    assert edit(broker)["ok"]
    assert host.writes


def test_source_change_discards_context_and_blocks_stale_write(tmp_path):
    broker, host, refs = setup(tmp_path)
    broker.invoke("read_reference", {"file_id": "采购.csv"})
    (refs / "采购.csv").write_text("项目,数量,单价\n设备,1,1\n", encoding="utf-8")
    next_turn(broker)
    assert not broker.verification_reads
    assert broker.invalidated_source_ids == ["采购.csv"]
    assert edit(broker)["recovery"]["code"] == "unread_native_sources"
    assert not host.writes


def test_live_unsaved_source_is_rechecked_even_with_same_disk_bytes(tmp_path):
    broker, host, refs = setup(tmp_path)
    values = ["未保存的旧资料"]
    broker.live_reader = broker.references.live_reader = lambda path: TextSnapshot(
        "采购.csv", values[0]
    )
    broker.invoke("read_reference", {"file_id": "采购.csv"})
    values[0] = "未保存的新资料"
    next_turn(broker)
    assert not broker.verification_reads
    assert edit(broker)["recovery"]["code"] == "unread_native_sources"
    assert not host.writes


def test_persisted_query_result_continues_with_verified_units(tmp_path):
    broker, host, refs = setup(tmp_path)
    result = query(broker)
    assert bind_fact(broker, result)["ok"]
    next_turn(broker)
    assert broker.analysis_evidence[0]["result_id"] == result["result_id"]
    assert edit(broker)["ok"]
    assert host.values["p1"] == "采购合计：54.00元。"


def test_inspection_schema_matches_default_query_projection(tmp_path):
    broker, host, refs = setup(tmp_path)
    book = Workbook()
    sheet = book.active
    sheet.append(["项目", "数量", "单价"])
    sheet.append(["设备", 3, 12.5])
    book.save(refs / "采购.xlsx")
    found = broker.invoke("inspect_source", {"file_id": "采购.xlsx"})
    assert found["ok"] and found["columns"] == ["项目", "数量", "单价"]
    result = broker.invoke(
        "query_data",
        {"sources": [{"name": "s", "file_id": "采购.xlsx"}], "sql": "SELECT * FROM s"},
    )
    assert result["ok"] and result["columns"] == found["columns"]
    assert "__source_row" not in found["columns"]


def test_required_fact_punctuation_does_not_duplicate_or_change_value():
    phrase = "总额：54.00元"
    assert canonical_facts(["总额54.00元人民币"], [phrase]) == ["总额：54.00元人民币"]
    assert canonical_facts(["总额5400元"], [phrase]) == ["总额5400元", phrase]
    assert canonical_facts(["总额54.00万元"], [phrase]) == ["总额54.00万元", phrase]
    quote = "总额54.00元"
    assert canonical_facts([quote], [phrase], quotes=[quote]) == [quote, phrase]
