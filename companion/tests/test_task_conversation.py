"""Past-task display history must not masquerade as current edit evidence."""

from dataclasses import replace
import json

from companion.agent import AnswerProposal
from companion.journal import EventJournal, document_scope
from companion.model import EditProposal
from companion.session import EditingSession
from companion.tests.test_session import Documents, settled
from companion.tests.test_workspace_agent import agent_for


class FileDocuments(Documents):
    def connect(self, host):
        return replace(super().connect(host), path="C:/synthetic/history.docx")


def test_new_task_keeps_display_history_but_followup_uses_current_task_only():
    calls = []

    class Model:
        def step(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return AnswerProposal("旧任务：删除开头的n。")
            if len(calls) == 2:
                return EditProposal("first edited", "精简")
            return AnswerProposal("本次只精简了第一段。")

    docs = FileDocuments()
    session = EditingSession(docs, Model)
    session.submit("旧任务删除n")
    assert settled(session)["phase"] == "answered"
    session.submit("新任务：精简当前两段")
    state = settled(session)
    assert state["phase"] == "review" and calls[1]["history"] == []
    assert calls[1]["context"]["selection"]["text"] == "first original\nsecond original"
    assert calls[1]["context"]["selection"]["fragment_count"] == 2
    session.revise("解释刚才改动，不修改文字")
    state = settled(session)
    assert len(calls[2]["history"]) == 2
    assert all("删除" not in row["content"] for row in calls[2]["history"])
    assert (
        calls[2]["context"]["checkpoint_context"]["latest"]["before"]
        == "first original"
    )
    assert (
        calls[2]["context"]["checkpoint_context"]["latest"]["after"] == "first edited"
    )
    assert any("删除" in row["content"] for row in state["history"])
    assert docs.writes == ["one"] and docs.text["two"] == "second original"
    assert state["conversation"]["context_turns"] == 2


def test_restored_history_is_available_through_explicit_read_tool_without_editing():
    journal = EventJournal()
    scope = document_scope("word", "C:/synthetic/history.docx")
    journal.record(
        scope,
        "old-task",
        "old-turn",
        "turn_completed",
        {
            "user": "旧任务的预算是多少",
            "assistant": "旧任务预算120万元。",
        },
    )

    def answer(payload):
        old = [
            json.loads(row["content"])
            for row in payload["messages"]
            if row["role"] == "tool"
        ][-1]
        assert old["items"][0]["task"] == "old-task"
        assert old["items"][0]["assistant"] == "旧任务预算120万元。"
        from companion.tests.test_workspace_agent import response

        return response(("answer_user", {"text": "根据之前的交流，预算120万元。"}))

    model, requests = agent_for(
        [
            [("read_conversation_history", {"query": "预算", "limit": 2})],
            answer,
        ],
        goal=None,
    )
    docs = FileDocuments()
    session = EditingSession(docs, lambda: model, journal=journal)
    session.restore_history({"host": "word", "path": "C:/synthetic/history.docx"})
    session.submit("请查一下之前的预算交流", "word")
    state = settled(session)
    assert state["phase"] == "answered" and not docs.writes
    assert state["answer"].endswith("120万元。")
    assert "旧任务预算120万元" not in json.dumps(
        requests[0]["messages"], ensure_ascii=False
    )
    assert state["recovery"] is None


def test_read_only_tool_reads_all_bound_fragments_without_increasing_write_scope():
    def answer(payload):
        from companion.tests.test_workspace_agent import response

        outputs = [
            json.loads(row["content"])
            for row in payload["messages"]
            if row["role"] == "tool"
        ]
        assert outputs[-1]["text"] == "first original\nsecond original"
        return response(("answer_user", {"text": "已读取选中的两段。"}))

    model, _ = agent_for([[("read_selected_text", {})], answer], goal=None)
    docs = FileDocuments()
    session = EditingSession(docs, lambda: model)
    session.submit("只读两段选区，不修改", "word")
    state = settled(session)
    assert state["phase"] == "answered" and state["answer"] == "已读取选中的两段。"
    assert not docs.writes
