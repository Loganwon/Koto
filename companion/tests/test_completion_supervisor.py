"""Real SDK graph transitions; fixtures isolate permissions from model API variance."""

import threading

import pytest

pytest.importorskip("deepagents")
from langchain_core.messages import AIMessage
from companion.agent_lab.tools import Turn
from companion.agent_lab.deep_engine import DeepEngine
from companion.tests.test_agent_lab import make_lab
from companion.tests.test_deep_engine import Model


def call(name, args, identity):
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": identity}]
    )


def test_first_file_and_final_answer_do_not_skip_second_delivery(tmp_path):
    store, task, broker, doc = make_lab(tmp_path, outputs=("摘要.docx", "明细.xlsx"))
    responses = [
        call(
            "create_word",
            {
                "action_id": "word",
                "file_name": "摘要.docx",
                "title": "摘要",
                "sections": [{"heading": "", "text": "真实摘要"}],
            },
            "w",
        ),
        AIMessage(content="都完成了。"),
        call(
            "create_workbook",
            {
                "action_id": "book",
                "file_name": "明细.xlsx",
                "sheets": [{"name": "数据", "rows": [["数量"], [7]]}],
            },
            "b",
        ),
        call("complete_task", {"summary": "两份文件完成"}, "c"),
        AIMessage(content="两份文件已完成。"),
    ]
    engine = DeepEngine(
        None, tmp_path / "checkpoints.sqlite3", model=Model(responses=responses)
    )
    try:
        assert "已完成" in engine.run(broker, "只使用登记工具", "生成两份交付后完成")
        assert store.get(task)["phase"] == "complete" and set(
            store.get(task)["artifacts"]
        ) == {"摘要.docx", "明细.xlsx"}
        assert (
            len([e for e in store.events(task) if e["kind"] == "completion_continued"])
            == 1
        )
        assert doc.read("0") == "甲方验收后付款。"
    finally:
        engine.close()


def test_repeated_empty_completion_claims_are_bounded_and_reported_incomplete(tmp_path):
    store, task, broker, _ = make_lab(tmp_path, outputs=("摘要.docx",))
    engine = DeepEngine(
        None,
        tmp_path / "checkpoints.sqlite3",
        model=Model(
            responses=[
                AIMessage(content="已经完成。", id=f"claim-{i}") for i in range(3)
            ]
        ),
    )
    try:
        answer = engine.run(broker, "使用工具生成", "生成摘要")
        assert answer.startswith("任务尚未完成") and not store.get(task)["artifacts"]
        assert (
            len([e for e in store.events(task) if e["kind"] == "completion_continued"])
            == 2
        )
        assert (
            len([e for e in store.events(task) if e["kind"] == "model_requested"]) == 3
        )
    finally:
        engine.close()


@pytest.mark.parametrize("mode", ["read", "auto"])
def test_followup_question_does_not_restart_unfinished_deliveries(tmp_path, mode):
    store, task, broker, _ = make_lab(tmp_path, outputs=("摘要.docx",))
    n, e = store.begin_turn(task, "只解释目前内容", mode)
    broker.bind_turn(Turn(task, n, e, "只解释目前内容", mode, threading.Event()))
    engine = DeepEngine(
        None,
        tmp_path / "checkpoints.sqlite3",
        model=Model(responses=[AIMessage(content="这里只解释原文。")]),
    )
    try:
        assert (
            engine.run(broker, "最新用户消息优先", "只解释目前内容")
            == "这里只解释原文。"
        )
        assert not any(e["kind"] == "completion_continued" for e in store.events(task))
        assert broker.turn.writes == 0 and store.get(task)["expected_outputs"] == [
            "摘要.docx"
        ]
    finally:
        engine.close()
