"""Native writes accept real query evidence, reject changed/unread sources."""

import threading
from companion.agent_lab.tools import Turn
from companion.pane_task_tools import NativeBroker, NativeDocument, PaneTaskStore
from companion.tests.test_pane_task_session import Host
from companion.workspace import LocalWorkspace
from companion.journal import EventJournal


def setup(tmp_path):
    refs = tmp_path / "refs"
    refs.mkdir()
    (refs / "采购.csv").write_text(
        "项目,数量,单价\n设备,3,12.5\n服务,2,8.25\n", encoding="utf-8"
    )
    workspace = LocalWorkspace()
    workspace.open(refs)
    store = PaneTaskStore(tmp_path / "tasks.sqlite3")
    task = store.create("按真实采购资料修改")
    host = Host()
    native = NativeDocument(
        host, host.target, EventJournal(tmp_path / "journal.sqlite3"), "test", task
    )
    broker = NativeBroker(
        store,
        task,
        workspace,
        tmp_path / "outputs",
        native,
        lambda *a: {"allowed": True},
        True,
    )
    n, e = store.begin_turn(task, "按采购资料修改首段", "auto")
    broker.bind_turn(Turn(task, n, e, "按采购资料修改首段", "auto", threading.Event()))
    broker.allowed_fragments = {"p1"}
    return broker, host, refs


def query(broker):
    return broker.invoke(
        "query_data",
        {
            "sources": [{"name": "s", "file_id": "采购.csv"}],
            "sql": 'SELECT SUM(money_product_cents("数量","单价")) AS cents FROM s',
        },
    )


def bind_fact(broker, result):
    return broker.invoke(
        "set_native_content_checks",
        {
            "fragment_id": "p1",
            "query_facts": [
                {
                    "id": "total",
                    "result_id": result["result_id"],
                    "row": 0,
                    "column": "cents",
                    "label": "采购合计",
                    "from_unit": "分",
                    "to_unit": "元",
                    "decimals": 2,
                }
            ],
        },
    )


def edit(broker, text="采购合计：54.00元。"):
    return broker.invoke(
        "apply_edit",
        {
            "action_id": "edit",
            "fragment_id": "p1",
            "expected": "第一段原文。",
            "text": text,
            "reason": "按真实资料核算",
            "source_ids": ["采购.csv"],
        },
    )


def test_query_read_is_valid_native_provenance_without_text_read(tmp_path):
    broker, host, refs = setup(tmp_path)
    result = query(broker)
    assert result["ok"]
    assert not broker.references.evidence()
    assert bind_fact(broker, result)["required_phrases"] == ["采购合计：54.00元"]
    result = edit(broker)
    assert result["ok"] and host.values["p1"] == "采购合计：54.00元。"
    proof = result["receipt"]["declared_sources"][0]
    assert proof["verification"] == "query_source_sha256" and proof["result_id"]


def test_changed_query_source_is_rejected_before_native_write(tmp_path):
    broker, host, refs = setup(tmp_path)
    bind_fact(broker, query(broker))
    (refs / "采购.csv").write_text("项目,数量,单价\n设备,1,1\n", encoding="utf-8")
    result = edit(broker)
    assert not result["ok"] and "变化" in result["error"]
    assert not host.writes


def test_query_number_requires_binding_before_native_write(tmp_path):
    broker, host, refs = setup(tmp_path)
    query(broker)
    result = edit(broker, "采购合计5400元。")
    assert not result["ok"] and not host.writes
    assert result["recovery"]["code"] == "native_content_check_mismatch"
    assert "set_native_content_checks" in result["recovery"]["next_tool"]["name"]


def test_bound_cents_cannot_be_written_as_yuan_even_if_verifier_allows(tmp_path):
    broker, host, refs = setup(tmp_path)
    bind_fact(broker, query(broker))
    result = edit(broker, "采购合计：5400元。")
    assert not result["ok"] and not host.writes
    assert "54.00元" in result["error"]
    assert edit(broker)["ok"]


def test_unread_declared_source_returns_actionable_recovery(tmp_path):
    broker, host, refs = setup(tmp_path)
    result = edit(broker)
    assert not result["ok"] and not host.writes
    assert result["recovery"]["code"] == "unread_native_sources"
    assert result["recovery"]["next_tools"][0] == {
        "name": "read_reference",
        "arguments": {"file_id": "采购.csv"},
    }


def test_verifier_receives_latest_host_readback_instead_of_old_summary(tmp_path):
    broker, host, refs = setup(tmp_path)
    bind_fact(broker, query(broker))
    assert edit(broker)["ok"]
    assert broker.write_context()["native_fragments"] == {
        "p1": "采购合计：54.00元。",
        "p2": "第二段原文。",
    }
