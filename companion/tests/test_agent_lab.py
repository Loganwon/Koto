"""Task lifecycle and write authority across model and process boundaries."""

import threading

import pytest

from companion.contracts import CompanionError, ResultUncertain
from companion.agent_lab.store import TaskStore
from companion.agent_lab.tools import JsonDocument, ToolBroker, Turn
from companion.agent_lab.runtime import LabSession


def make_lab(tmp_path, verifier=None, outputs=()):
    sources = tmp_path / "sources"
    sources.mkdir(exist_ok=True)
    store = TaskStore(tmp_path / "tasks.sqlite3")
    task = store.create("精简首段，确认后生成摘要和预算。", expected_outputs=outputs)
    doc = JsonDocument(tmp_path / "document.json", ["甲方验收后付款。"])
    broker = ToolBroker(
        store,
        task,
        sources,
        tmp_path / "outputs",
        doc,
        verifier or (lambda *a: {"allowed": True}),
    )
    number, epoch = store.begin_turn(task, "精简首段。", "auto")
    broker.bind_turn(Turn(task, number, epoch, "精简首段。", "auto", threading.Event()))
    return store, task, broker, doc


def patch(text="客户方验收后付款。", action="edit-1"):
    return {
        "action_id": action,
        "fragment_id": "0",
        "expected": "甲方验收后付款。",
        "text": text,
        "reason": "统一称呼",
    }


def test_identical_pure_observations_across_models_stop_but_new_inputs_work(tmp_path):
    store, task, broker, _ = make_lab(tmp_path)
    for step in (1, 2):
        broker.turn.model_step = step
        assert broker.invoke("calculate", {"expression": "17*23"})["result"] == "391"
    broker.turn.model_step = 3
    repeated = broker.invoke("calculate", {"expression": "17*23"})
    assert not repeated["ok"] and "391" in repeated["error"]
    assert broker.turn.recovery_observation["tool"] == "calculate"
    assert broker.invoke("calculate", {"expression": "17*24"})["result"] == "408"
    assert len([e for e in store.events(task) if e["kind"] == "observation_loop"]) == 1


def test_parallel_duplicates_and_later_turn_verification_are_not_loops(tmp_path):
    store, task, broker, _ = make_lab(tmp_path)
    broker.turn.model_step = 1
    for _ in range(4):
        assert broker.invoke("calculate", {"expression": "7*8"})["ok"]
    n, e = store.begin_turn(task, "核对上轮计算", "read")
    broker.bind_turn(Turn(task, n, e, "核对上轮计算", "read", threading.Event()))
    broker.turn.model_step = 1
    assert broker.invoke("calculate", {"expression": "7*8"})["ok"]
    assert not broker.turn.recovery_observation


def test_verified_paragraph_does_not_complete_task_and_receipt_replays_after_restart(
    tmp_path,
):
    store, task, broker, doc = make_lab(tmp_path, outputs=("摘要.docx",))
    assert broker.invoke("apply_edit", patch())["ok"]
    assert store.get(task)["phase"] == "review"
    assert store.get(task)["expected_outputs"] == ["摘要.docx"]
    assert not broker.invoke("complete_task", {"summary": "完成"})["ok"]
    store.close()
    restored = TaskStore(tmp_path / "tasks.sqlite3")
    broker.store = restored
    result = broker.invoke("apply_edit", patch())
    assert result["ok"] and result["replayed_receipt"]
    assert len(restored.get(task)["edits"]) == 1
    assert doc.read("0") == "客户方验收后付款。"


def test_unknown_action_after_crash_is_not_replayed(tmp_path):
    store, task, broker, doc = make_lab(tmp_path)
    with store.db:
        store.db.execute(
            "INSERT INTO actions VALUES(?,?,'unknown','started',NULL)", (task, "lost")
        )
    store.close()
    restored = TaskStore(tmp_path / "tasks.sqlite3")
    with pytest.raises(ResultUncertain):
        restored.begin_turn(task, "继续", "auto", True)
    assert restored.get(task)["phase"] == "uncertain"
    assert doc.read("0") == "甲方验收后付款。"


def test_read_mode_removes_writes_and_blocks_forged_calls(tmp_path):
    store, task, broker, doc = make_lab(tmp_path)
    n, e = store.begin_turn(task, "只解释，不修改。", "read")
    broker.bind_turn(Turn(task, n, e, "只解释，不修改。", "read", threading.Event()))
    assert "apply_edit" not in [s["name"] for s in broker.definitions()]
    assert not broker.invoke("apply_edit", patch())["ok"]
    assert not broker.invoke("complete_task", {"summary": "完成"})["ok"]
    assert not store.get(task)["edits"]


def test_auto_semantic_rejection_closes_writes_for_entire_turn(tmp_path):
    checks = []

    def deny(*args):
        checks.append(True)
        return {"allowed": False, "reason": "用户本轮只要解释"}

    store, task, broker, doc = make_lab(tmp_path, deny)
    for i in range(3):
        assert not broker.invoke("apply_edit", patch(action=str(i)))["ok"]
    assert len(checks) == 1 and not store.get(task)["edits"]


def test_factual_rejection_uses_observed_math_and_can_be_corrected(tmp_path):
    evidence = []

    def verify(turn, name, args, state):
        evidence.append(state["write_evidence"])
        return {
            "allowed": "54" in args["text"],
            "kind": "evidence",
            "reason": "必须使用实际计算结果",
        }

    store, task, broker, doc = make_lab(tmp_path, verify)
    source = broker.workspace._root / "采购.txt"
    source.write_text("设备3件，每件12.5元；服务2次，每次8.25元。", encoding="utf-8")
    assert broker.invoke("read_reference", {"file_id": "采购.txt"})["ok"]
    assert (
        broker.invoke("calculate", {"expression": "3*12.5+2*8.25"})["result"] == "54.00"
    )
    assert not broker.invoke("apply_edit", patch("采购53元。"))["ok"]
    assert doc.read("0") == "甲方验收后付款。"
    assert broker.invoke("apply_edit", patch("采购54元。", "corrected"))["ok"]
    assert evidence[0]["calculations"][0]["result"] == "54.00"
    assert evidence[0]["references"][0]["file_id"] == "采购.txt"
    assert any(e["kind"] == "calculation" for e in store.events(task))


def test_stop_invalidates_late_tool_results_and_old_epoch(tmp_path):
    store, task, broker, doc = make_lab(tmp_path)
    state = store.get(task)
    store.change(task, epoch=state["epoch"] + 1)
    result = broker.invoke("apply_edit", patch())
    assert not result["ok"] and not store.get(task)["edits"]


def test_manual_document_change_preserved(tmp_path):
    store, task, broker, doc = make_lab(tmp_path)
    doc.replace("0", doc.read("0"), "用户已手动改写。", lambda: True)
    result = broker.invoke("apply_edit", patch())
    assert not result["ok"] and "已由用户改变" in result["error"]
    assert doc.read("0") == "用户已手动改写。"


def test_multiple_artifacts_and_real_word_table_verified_before_completion(tmp_path):
    from docx import Document
    from openpyxl import load_workbook

    store, task, broker, doc = make_lab(tmp_path, outputs=("摘要.docx", "预算.xlsx"))
    assert not broker.invoke("complete_task", {"summary": "完成"})["ok"]
    word = {
        "action_id": "word",
        "file_name": "摘要.docx",
        "title": "预算摘要",
        "sections": [{"heading": "概况", "text": "预算191.34万元。"}],
        "tables": [[["项目", "万元"], ["研发", "123.45"], ["运营", "67.89"]]],
    }
    assert broker.invoke("create_word", word)["ok"]
    assert not broker.invoke("complete_task", {"summary": "完成"})["ok"]
    assert len(Document(tmp_path / "outputs/摘要.docx").tables) == 1
    bad = {
        "action_id": "book",
        "file_name": "预算.xlsx",
        "title": "预算",
        "rows": [["合计", "=SUM(B2:B3)"]],
    }
    assert not broker.invoke("create_spreadsheet", bad)["ok"]
    assert not (tmp_path / "outputs/预算.xlsx").exists()
    assert store.get(task)["phase"] == "active"
    good = {**bad, "rows": [["合计", 191.34]]}
    assert broker.invoke("create_spreadsheet", good)["ok"]
    assert broker.invoke("create_spreadsheet", good)["replayed_receipt"]
    wb = load_workbook(tmp_path / "outputs/预算.xlsx")
    assert wb.active["B1"].value == 191.34
    wb.close()
    assert broker.invoke("complete_task", {"summary": "两个文件均已完成"})["ok"]
    assert store.get(task)["phase"] == "complete"


def test_new_readonly_messages_keep_task_and_persistent_constraints(tmp_path):
    store, task, broker, doc = make_lab(tmp_path)

    class Engine:
        def run(self, broker, prompt, message):
            assert "客户方" in prompt
            return "收到"

        def close(self):
            pass

    broker.invoke("update_work", {"constraints": [{"key": "称呼", "value": "客户方"}]})
    session = LabSession(store, task, broker, Engine())
    for _ in range(10):
        result = session.send("只回复收到，不修改正文。", mode="read")
        assert result["task"] == task and result["state"]["goal"].startswith("精简首段")
    assert len(store.history(task)) == 21
    assert not store.get(task)["edits"]


def test_no_overwrite_and_changed_receipt_prevents_completion(tmp_path):
    store, task, broker, doc = make_lab(tmp_path, outputs=("摘要.docx",))
    args = {
        "action_id": "word",
        "file_name": "摘要.docx",
        "title": "标题",
        "sections": [{"heading": "", "text": "原始输出"}],
    }
    assert broker.invoke("create_word", args)["ok"]
    assert not broker.invoke(
        "create_word", {**args, "action_id": "new", "title": "新标题"}
    )["ok"]
    (tmp_path / "outputs/摘要.docx").write_bytes(b"user changed file")
    assert not broker.invoke("complete_task", {"summary": "完成"})["ok"]


def test_xlsx_readback_releases_source_without_waiting_for_garbage_collection(tmp_path):
    from openpyxl import Workbook
    from companion.file_readers import parse_file

    path = tmp_path / "atomic-source.xlsx"
    book = Workbook()
    book.active.append(["值", 191.34])
    book.save(path)
    book.close()
    result = parse_file(path)
    assert "191.34" in result.text
    # Windows rejects unlink while any non-sharing ZIP reader still owns it.
    # Do not call gc.collect(): file publication must not depend on GC timing.
    path.unlink()
    assert not path.exists()


def test_independent_sessions_cannot_run_same_task_concurrently(tmp_path):
    store, task, broker, doc = make_lab(tmp_path)
    other = TaskStore(tmp_path / "tasks.sqlite3")
    with store.running(task):
        with pytest.raises(CompanionError):
            with other.running(task):
                pass
    with other.running(task):
        assert other.get(task)["goal"] == store.get(task)["goal"]
    other.close()


def test_reading_completed_task_keeps_completion_state(tmp_path):
    store, task, broker, doc = make_lab(tmp_path)
    store.change(task, phase="complete")
    store.begin_turn(task, "只解释已完成的结果", "read")
    assert store.get(task)["phase"] == "complete"


def test_bound_native_adapter_rejects_unbound_and_readonly_fragments(tmp_path):
    from companion.agent_lab.documents import BoundTextDocument
    from companion.contracts import DocumentTarget, Fragment

    class Port:
        values = {"a": "original", "b": "protected"}

        def read(self, target, fragment):
            return self.values[fragment]

        def replace(self, target, fragment, expected, text, permitted):
            assert self.values[fragment] == expected and permitted()
            self.values[fragment] = text
            return text

    port = Port()
    target = DocumentTarget(
        "native",
        "wps",
        "test.docx",
        "selection",
        (Fragment("a", "original"), Fragment("b", "protected", editable=False)),
    )
    adapter = BoundTextDocument(port, target)
    for fragment in ("outside", "b"):
        with pytest.raises(CompanionError):
            adapter.replace(fragment, "protected", "bad", lambda: True)
    assert adapter.replace("a", "original", "new", lambda: True) == "new"
    assert port.values["b"] == "protected"


def test_bound_native_mismatched_readback_stays_uncertain(tmp_path):
    from companion.agent_lab.documents import BoundTextDocument
    from companion.contracts import DocumentTarget, Fragment

    class Port:
        def read(self, *a):
            return "wrong native content"

        def replace(self, *a):
            return "proposed"

    adapter = BoundTextDocument(
        Port(),
        DocumentTarget(
            "native", "wps", "test.docx", "selection", (Fragment("a", "old"),)
        ),
    )
    with pytest.raises(ResultUncertain):
        adapter.replace("a", "old", "proposed", lambda: True)
