"""Actual Deep Agents middleware with a scripted model; no live provider calls."""

import pytest

pytest.importorskip("deepagents")
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from companion.agent_lab.deep_engine import DeepEngine
from companion.tests.test_agent_lab import make_lab


class Model(FakeMessagesListChatModel):
    model_name: str = "koto-test"

    def bind_tools(self, tools, **kwargs):
        return self


def test_readonly_followup_rebuilds_old_model_prose_from_fresh_saved_files(tmp_path):
    from companion.tests.test_read_grounding import prepared

    class Recording(Model):
        seen: list = []

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            self.seen.append(list(messages))
            return super()._generate(messages, stop, run_manager, **kwargs)

    store, task, broker = prepared(tmp_path)
    engine = DeepEngine(
        None,
        tmp_path / "checkpoints.sqlite3",
        model=Recording(
            responses=[
                AIMessage(content="旧答复：有差额。"),
                AIMessage(content="两行差额均为0。"),
            ]
        ),
    )
    try:
        engine.run(broker, "只回答", "目前有差额么")
        engine.run(broker, "只回答", "核对当前保存值")
        messages = engine.model.seen[-1]
        assert not any(m.type == "ai" and "旧答复" in str(m.content) for m in messages)
        assert any("A2\\t0" in str(m.content) for m in messages)
        assert broker.turn.writes == 0
    finally:
        engine.close()


def test_cancelled_followup_never_reuses_previous_completion_answer(tmp_path):
    import threading
    from companion.agent_lab.runtime import LabSession

    store, task, broker, _ = make_lab(tmp_path)
    engine = DeepEngine(
        None,
        tmp_path / "checkpoints.sqlite3",
        model=Model(responses=[AIMessage(content="上一轮已全部完成。")]),
    )
    session = LabSession(store, task, broker, engine)
    try:
        assert "全部完成" in session.send("只回答状态", mode="read")["answer"]
        stopped = threading.Event()
        stopped.set()
        answer = session.send("修改文件", cancelled=stopped)["answer"]
        assert "已停止" in answer and "尚未完成" in answer and "全部完成" not in answer
    finally:
        session.close()


def test_stalled_measured_draft_is_published_via_normal_boundary(tmp_path):
    class Verifier:
        def __call__(self, *args):
            return {"allowed": True}

        def repair_draft(self, turn, arguments, state, validation):
            return {**arguments, "sections": [{"heading": "", "text": "短稿"}]}

    store, task, broker, _ = make_lab(tmp_path, Verifier(), outputs=("摘要.docx",))
    broker.invoke(
        "set_output_limits",
        {"limits": [{"file_name": "摘要.docx", "max_body_characters": 5}]},
    )
    args = {
        "file_name": "摘要.docx",
        "format": "docx",
        "sections": [{"heading": "", "text": "一二三四五六七八"}],
    }
    calls = [
        AIMessage(
            content="",
            tool_calls=[
                {"id": f"measure-{n}", "name": "measure_content", "args": args}
            ],
        )
        for n in range(3)
    ]
    calls.extend(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "done", "name": "complete_task", "args": {"summary": "完成"}}
                ],
            ),
            AIMessage(content="已交付"),
        ]
    )
    engine = DeepEngine(
        None, tmp_path / "checkpoints.sqlite3", model=Model(responses=calls)
    )
    try:
        engine.run(broker, "完成明确要求的文件", "生成五字以内摘要")
        assert store.get(task)["phase"] == "complete"
        assert store.get(task)["artifacts"]["摘要.docx"]["verified"]
        assert (
            len(
                [
                    e
                    for e in store.events(task)
                    if e["kind"] == "recovery_publication_requested"
                ]
            )
            == 1
        )
    finally:
        engine.close()


@pytest.mark.parametrize("kind", ["truncated", "invalid", "empty"])
def test_unexecuted_incomplete_tool_output_recovers_without_writes(tmp_path, kind):
    store, task, broker, _ = make_lab(tmp_path)
    if kind == "truncated":
        bad = AIMessage(
            content="",
            response_metadata={"finish_reason": "length"},
            tool_calls=[
                {
                    "id": "bad",
                    "name": "create_word",
                    "args": {
                        "action_id": "x",
                        "file_name": "禁止.docx",
                        "title": "截断",
                        "sections": [],
                    },
                }
            ],
        )
    elif kind == "invalid":
        bad = AIMessage(
            content="",
            invalid_tool_calls=[
                {"id": "bad", "name": "create_word", "args": "{", "error": "partial"}
            ],
        )
    else:
        bad = AIMessage(content="")
    model = Model(
        responses=[bad, AIMessage(content="上次未执行。缺少资料，尚未完成。")]
    )
    engine = DeepEngine(None, tmp_path / "checkpoints.sqlite3", model=model)
    try:
        answer = engine.run(broker, "只能使用登记的工具", "只读核对")
        assert "尚未完成" in answer
        assert not store.get(task)["artifacts"]
        assert (
            len([e for e in store.events(task) if e["kind"] == "model_output_rejected"])
            == 1
        )
    finally:
        engine.close()


def test_repeated_observation_rebuilds_working_context_without_losing_state(tmp_path):
    store, task, broker, doc = make_lab(tmp_path)
    store.change(task, constraints={"keep": "第三段不得修改"})
    calls = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": f"calc-{n}",
                    "name": "calculate",
                    "args": {"expression": "17*23"},
                }
            ],
        )
        for n in range(3)
    ]
    model = Model(responses=[*calls, AIMessage(content="计算结果391，未写入。")])
    engine = DeepEngine(None, tmp_path / "checkpoints.sqlite3", model=model)
    try:
        assert "391" in engine.run(broker, "不修改正文", "核对17乘23")
        recovery = [e for e in store.events(task) if e["kind"] == "context_recovered"]
        assert (
            len(recovery) == 1
            and recovery[0]["body"]["reason"] == "repeated_observation"
        )
        assert store.get(task)["constraints"] == {"keep": "第三段不得修改"}
        assert not store.get(task)["edits"] and doc.read("0") == "甲方验收后付款。"
    finally:
        engine.close()


def test_failed_turn_recovery_retains_the_actual_next_user_message(tmp_path):
    from companion.agent_lab.runtime import LabSession

    class RecordingModel(Model):
        seen: list = []

        def _generate(self, messages, **kwargs):
            self.seen.append([(m.type, m.content) for m in messages])
            return super()._generate(messages, **kwargs)

    store, task, broker, doc = make_lab(tmp_path)
    model = RecordingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "c1", "name": "calculate", "args": {"expression": "17*23"}}
                ],
            ),
            AIMessage(content="旧上下文答复"),
        ]
    )
    engine = DeepEngine(
        None, tmp_path / "checkpoints.sqlite3", model=model, max_models=1
    )
    session = LabSession(store, task, broker, engine)
    try:
        with pytest.raises(RuntimeError):
            session.send("先计算")
        engine.max_models = 5
        model.responses = [AIMessage(content="只解释，没有修改。")]
        model.i = 0
        answer = session.send("只解释，绝不修改正文。", mode="read")
        assert answer["write_calls"] == 0
        assert any(
            e["kind"] == "context_recovered"
            and e["body"]["reason"] == "previous_turn_failed"
            for e in store.events(task)
        )
        assert [content for kind, content in model.seen[-1] if kind == "human"] == [
            "只解释，绝不修改正文。"
        ]
        assert doc.read("0") == "甲方验收后付款。"
    finally:
        session.close()


def test_stop_continue_rebuilds_model_context_from_durable_current_state(tmp_path):
    from companion.agent_lab.runtime import LabSession

    class RecordingModel(Model):
        seen: list = []

        def _generate(self, messages, **kwargs):
            self.seen.append([(m.type, m.content) for m in messages])
            return super()._generate(messages, **kwargs)

    store, task, broker, _ = make_lab(tmp_path)
    model = RecordingModel(
        responses=[AIMessage(content="旧轨迹"), AIMessage(content="继续核对")]
    )
    engine = DeepEngine(None, tmp_path / "checkpoints.sqlite3", model=model)
    session = LabSession(store, task, broker, engine)
    try:
        session.send("旧消息", mode="read")
        store.change(task, constraints={"owner": "负责人=Alice"})
        session.stop()
        session.send("继续，只解释状态", mode="read", interaction="continue")
        assert [content for kind, content in model.seen[-1] if kind == "human"] == [
            "继续，只解释状态"
        ]
        assert any(
            e["kind"] == "context_recovered"
            and e["body"]["reason"] == "previous_turn_interrupted"
            for e in store.events(task)
        )
        assert store.get(task)["constraints"]["owner"] == "负责人=Alice"
    finally:
        session.close()


def test_stalled_read_trajectory_recovers_without_losing_saved_analysis_index(tmp_path):
    store, task, broker, _ = make_lab(tmp_path)
    store.change(
        task,
        analyses=[
            {
                "result_id": "saved-full-result",
                "columns": ["金额"],
                "row_count": 1719,
                "sources": [],
            }
        ],
    )
    calls = [
        AIMessage(
            content="", tool_calls=[{"id": str(i), "name": "read_task", "args": {}}]
        )
        for i in range(24)
    ]
    engine = DeepEngine(
        None,
        tmp_path / "checkpoints.sqlite3",
        model=Model(responses=[*calls, AIMessage(content="沿用完整结果。")]),
    )
    try:
        assert "完整结果" in engine.run(
            broker, "根据已有结果核对，不写入", "核对原任务"
        )
        assert any(
            e["kind"] == "context_recovered"
            and e["body"]["reason"] == "stalled_progress"
            for e in store.events(task)
        )
        assert store.get(task)["analyses"][0]["result_id"] == "saved-full-result"
    finally:
        engine.close()
