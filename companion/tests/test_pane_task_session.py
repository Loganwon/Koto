"""Real task store and native adapter boundary; editor below is a fixture."""

from dataclasses import replace
import time

import pytest

from companion.contracts import (
    DocumentTarget,
    Fragment,
    DocumentConflict,
    ResultUncertain,
)
from companion.journal import EventJournal
from companion.model import ModelConfig
from companion.reading import TextSnapshot
from companion.workspace import LocalWorkspace
from companion.agent_lab.preflight import validate_estimate
from companion.agent_lab.documents import BoundTextDocument
from companion.pane_task_session import PaneTaskSession


class Host:
    def __init__(self):
        self.values = {"p1": "第一段原文。", "p2": "第二段原文。"}
        self.writes = []
        self.target = DocumentTarget(
            "bound",
            "wps",
            "测试.docx",
            "已选两段",
            tuple(Fragment(k, v) for k, v in self.values.items()),
            "C:/synthetic/test.docx",
        )

    def bind_current(self):
        return replace(
            self.target, fragments=tuple(Fragment(k, v) for k, v in self.values.items())
        )

    def read(self, target, fragment):
        assert target == "bound"
        return self.values[fragment]

    def replace(self, target, fragment, expected, text, permitted):
        assert permitted()
        if self.values[fragment] != expected:
            raise DocumentConflict("changed")
        self.values[fragment] = text
        self.writes.append(fragment)
        return text

    def read_open_file(self, path):
        return None

    def text_snapshot(self, target):
        return TextSnapshot(
            "测试.docx", "\n".join(self.values.values()) + "\n表格：合计191.34"
        )

    def locate(self, *args):
        pass

    def close(self):
        pass


class Predictor:
    def __init__(self, config):
        pass

    def predict(self, context, **kwargs):
        return validate_estimate(
            {
                "summary": "修改选区并交付两份文件",
                "deliveries": [
                    {
                        "kind": "edit",
                        "name": "测试.docx",
                        "format": "docx",
                        "target_id": "bound",
                        "source_ids": ["selection"],
                        "reason": "精简选区",
                    },
                    {
                        "kind": "create",
                        "name": "摘要.docx",
                        "format": "docx",
                        "target_id": "",
                        "source_ids": ["selection"],
                        "reason": "摘要",
                    },
                    {
                        "kind": "create",
                        "name": "预算.xlsx",
                        "format": "xlsx",
                        "target_id": "",
                        "source_ids": [],
                        "reason": "预算",
                    },
                ],
                "questions": [],
                "warnings": [],
            },
            context,
        )


class Engine:
    def __init__(self, *args):
        self.seen = []

    def run(self, broker, prompt, message):
        self.seen.append((broker.interaction, message))
        state = broker.store.get(broker.task)
        if broker.allowed_fragments:
            key = sorted(broker.allowed_fragments)[0]
            old = broker.document.read(key)
            result = broker.invoke(
                "apply_edit",
                {
                    "action_id": "edit-" + str(broker.turn.number),
                    "fragment_id": key,
                    "expected": old,
                    "text": old + "已改。",
                    "reason": message,
                },
            )
            assert result["ok"], result
            return "已修改。"
        if "摘要.docx" not in state["artifacts"]:
            assert broker.invoke(
                "create_word",
                {
                    "action_id": "doc",
                    "file_name": "摘要.docx",
                    "title": "摘要",
                    "sections": [{"heading": "", "text": "真实文件输出"}],
                },
            )["ok"]
        if "预算.xlsx" not in state["artifacts"]:
            assert broker.invoke(
                "create_spreadsheet",
                {
                    "action_id": "book",
                    "file_name": "预算.xlsx",
                    "title": "预算",
                    "rows": [["金额"], [191.34]],
                },
            )["ok"]
        assert broker.invoke("complete_task", {"summary": "全部完成"})["ok"]
        return "已完成两个文件。"

    def close(self):
        pass


class FixtureRequirements:
    """Explicit mechanism-test contract; no live semantic compiler is exercised."""

    def __init__(self, *args):
        pass

    def compile(self, context, estimate, **kwargs):
        from companion.agent_lab.task_requirements import validate

        return validate(
            {
                "deliverables": [
                    {
                        "kind": d["kind"],
                        "name": d["name"],
                        "criteria": [d["reason"]],
                        "limits": {},
                        "required_sources": [],
                        "workbook_schema": None,
                    }
                    for d in estimate["deliveries"]
                ]
            },
            context,
            estimate,
        )


def wait(session):
    deadline = time.monotonic() + 8
    while session.busy and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not session.busy
    return session.snapshot()


@pytest.fixture
def native(tmp_path):
    host = Host()
    ws = LocalWorkspace()
    root = tmp_path / "sources"
    root.mkdir()
    (root / "资料.txt").write_text("预算191.34", encoding="utf-8")
    ws.open(root)
    session = PaneTaskSession(
        host,
        ws,
        lambda: ModelConfig("https://example.test", "test", "not-a-key"),
        EventJournal(tmp_path / "history.sqlite3"),
        state_dir=tmp_path / "state",
        engine_factory=Engine,
        predictor_factory=Predictor,
        requirements_factory=FixtureRequirements,
    )
    yield session, host, ws
    session.close()


def accept(session):
    session.prepare("精简两段并生成摘要和预算", [])
    state = wait(session)
    assert state["phase"] == "planned"
    # Mechanism tests use a local verifier, no network calls.
    from companion import pane_task_session

    return state["workflow"]["prepared"]["id"]


def test_independent_contract_removes_a_predicted_but_unrequested_native_edit(native):
    session, host, _ = native

    class Requirements(FixtureRequirements):
        def compile(self, context, estimate, **kwargs):
            value = super().compile(context, estimate, **kwargs)
            value["deliverables"] = [
                d for d in value["deliverables"] if d["kind"] == "create"
            ]
            return value

    session.requirements_factory = Requirements
    session.prepare("只生成摘要和预算，保留原文", [])
    state = wait(session)
    assert state["phase"] == "planned"
    assert all(
        d["kind"] == "create" for d in state["workflow"]["prepared"]["deliveries"]
    )
    assert not host.writes
    assert any(
        e["kind"] == "delivery_estimate_scope_corrected"
        for e in session.store.events(session.task)
    )


def test_prepare_is_readonly_and_versions_are_checked_before_execution(native):
    session, host, ws = native
    plan = accept(session)
    assert not host.writes and not list(ws._root.rglob("*.docx"))
    host.values["p1"] = "用户刚改"
    session.execute(plan)
    state = wait(session)
    assert state["phase"] == "conflict" and not host.writes


def test_native_pipeline_feedback_and_multiple_actual_files(native, monkeypatch):
    session, host, ws = native
    monkeypatch.setattr(
        "companion.pane_task_session.WriteVerifier",
        lambda *_: lambda *args: {"allowed": True, "reason": "fixture only"},
    )
    plan = accept(session)
    session.execute(plan)
    state = wait(session)
    assert state["phase"] == "review" and host.writes == ["p1"]
    activity = state["workflow"]["activity"]
    assert any(
        row["title"] == "写回原文并读回核对" and row["status"] == "done"
        for row in activity
    )
    assert session.snapshot()["workflow"]["activity"] == activity
    assert not state["workflow"]["artifacts"]
    session.turn_task("称呼改成客户方", "feedback")
    assert wait(session)["phase"] == "review"
    assert host.writes == ["p1", "p1"]
    session.turn_task("", "continue")
    assert wait(session)["shown"] == 2
    assert host.writes == ["p1", "p1", "p2"]
    session.turn_task("", "continue")
    state = wait(session)
    assert state["phase"] == "complete", state
    assert {v["name"] for v in state["workflow"]["artifacts"]} == {
        "摘要.docx",
        "预算.xlsx",
    }
    from docx import Document
    from openpyxl import load_workbook

    assert "真实文件输出" in "\n".join(
        p.text for p in Document(session.outputs / "摘要.docx").paragraphs
    )
    book = load_workbook(session.outputs / "预算.xlsx")
    assert book.active["A2"].value == 191.34
    book.close()
    assert session.lab.engine.seen[1] == ("feedback", "称呼改成客户方")


def test_sources_changed_after_prediction_prevent_start(native):
    session, host, ws = native
    session.prepare("精简选区", ["资料.txt"])
    plan = wait(session)["workflow"]["prepared"]["id"]
    (ws._root / "资料.txt").write_text("预算已变化", encoding="utf-8")
    session.execute(plan)
    assert wait(session)["phase"] == "conflict"
    assert not host.writes


def test_readback_failure_after_write_is_uncertain_not_retryable():
    host = Host()
    doc = BoundTextDocument(host, host.bind_current())
    original = host.read

    def read(target, fragment):
        if host.writes:
            raise OSError("transport gone after commit")
        return original(target, fragment)

    host.read = read
    with pytest.raises(ResultUncertain):
        doc.replace("p1", "第一段原文。", "完成。", lambda: True)
    assert host.writes == ["p1"] and host.values["p1"] == "完成。"


def test_question_from_single_feedback_composer_preserves_review(native, monkeypatch):
    session, host, ws = native
    monkeypatch.setattr(
        "companion.pane_task_session.WriteVerifier",
        lambda *_: lambda *args: {"allowed": True},
    )
    session.execute(accept(session))
    before = wait(session)
    session.engine.run = lambda *args: "这里只解释，不写入。"
    session.turn_task("只解释这次改了什么", "feedback")
    state = wait(session)
    assert state["phase"] == "review" and state["can_revise"]
    assert state["latest"] == before["latest"] and host.writes == ["p1"]


def test_preserved_fragment_counts_without_host_write_and_detects_later_changes(
    native, monkeypatch
):
    session, host, ws = native
    monkeypatch.setattr(
        "companion.pane_task_session.WriteVerifier",
        lambda *_: lambda *args: {"allowed": True},
    )
    session.execute(accept(session))
    wait(session)
    broker = session.lab.broker
    # Next turn's explicit range is p2; retaining it does not replay p1.
    number, epoch = session.store.begin_turn(
        session.task, "第二段保留原文", "auto", True
    )
    from companion.agent_lab.tools import Turn
    import threading

    broker.bind_turn(
        Turn(session.task, number, epoch, "第二段保留原文", "auto", threading.Event())
    )
    broker.interaction = "continue"
    broker.allowed_fragments = {"p2"}
    result = broker.invoke(
        "preserve_fragment",
        {"fragment_id": "p2", "expected": host.values["p2"], "reason": "用户要求保留"},
    )
    assert result["ok"] and result["native_write"] is False
    assert host.writes == ["p1"] and broker.processed_fragments() == {"p1", "p2"}
    assert broker.invoke(
        "create_word",
        {
            "action_id": "kept-summary",
            "file_name": "摘要.docx",
            "title": "摘要",
            "sections": [{"heading": "", "text": "保留原文的摘要"}],
        },
    )["ok"]
    host.values["p2"] = "用户稍后修改了保留段落。"
    result = broker.invoke("complete_task", {"summary": "完成"})
    assert not result["ok"] and "用户改变" in result["error"]
    assert session.store.get(session.task)["phase"] != "complete"
    assert host.values["p2"] == "用户稍后修改了保留段落。"


def test_stop_while_engine_initializes_never_starts_late_native_write(
    native, monkeypatch
):
    import threading

    session, host, ws = native
    entered, release = threading.Event(), threading.Event()

    def delayed_engine(*args):
        entered.set()
        assert release.wait(3)
        return Engine()

    session.engine_factory = delayed_engine
    monkeypatch.setattr(
        "companion.pane_task_session.WriteVerifier",
        lambda *_: lambda *args: {"allowed": True},
    )
    session.execute(accept(session))
    assert entered.wait(3)
    session.stop()
    release.set()
    state = wait(session)
    assert state["phase"] == "stopped" and not host.writes
