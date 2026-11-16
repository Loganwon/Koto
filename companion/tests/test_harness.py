import json
import threading

import pytest

from companion.contracts import CompanionError
from companion.harness import HarnessRun, ToolRegistry, ToolSpec, calculate
from companion.reading import TextSnapshot
from companion.workspace import LocalWorkspace
from companion.tests.test_workspace_agent import agent_for


def run_agent(model, tmp_path, **extra):
    workspace = LocalWorkspace()
    workspace.open(tmp_path)
    return model.step(
        original="待补充",
        current="待补充",
        instruction="核对并计算资料后回答",
        feedback=(),
        index=0,
        total=1,
        cancelled=threading.Event(),
        context={},
        document=TextSnapshot("test", "正文"),
        references=workspace.session(),
        progress=lambda *args: None,
        **extra
    )


def test_agent_plans_recovers_bad_arguments_and_calculates_from_source(tmp_path):
    (tmp_path / "费用.txt").write_text("研发120.1，运营79.9", encoding="utf-8")
    plan = [{"title": "核对来源并计算总额", "status": "in_progress"}]

    def answer(payload):
        outputs = [
            json.loads(item["content"])
            for item in payload["messages"]
            if item["role"] == "tool"
        ]
        assert any(item.get("recoverable") for item in outputs)
        assert any(item.get("result") == "200.0" for item in outputs)
        from companion.tests.test_workspace_agent import response

        return response(("answer_user", {"text": "合计200，来源：费用.txt。"}))

    model, requests = agent_for(
        [
            [("update_plan", {"steps": plan})],
            [("read_reference_file", {"file_id": "费用.txt", "start": True})],
            [("read_reference_file", {"file_id": "费用.txt"})],
            [("calculate", {"expression": "120.1+79.9"})],
            answer,
        ]
    )
    assert "200" in run_agent(model, tmp_path).text
    assert len(requests) == 6  # goal handshake + five task steps


def test_long_results_are_retrievable_and_compaction_keeps_tool_pairs():
    run = HarnessRun(lambda *args: None)
    body = {"text": "开头" * 6000 + "尾部事实9876"}
    wrapped = json.loads(run.remember("read", {}, body))
    assert wrapped["evidence_id"] == "e1" and "9876" not in wrapped["preview"]
    assert "9876" in run.read_evidence("e1", 11000)["text"]
    messages = [
        {"role": "system", "content": "指令"},
        {"role": "user", "content": "任务"},
    ]
    for i in range(8):
        messages.extend(
            [
                {"role": "assistant", "tool_calls": [{"id": str(i)}]},
                {"role": "tool", "tool_call_id": str(i), "content": "a" * 5900},
            ]
        )
    run.compact(messages, ToolRegistry())
    assert len(messages) == 18 and messages[1]["content"] == "任务"
    assert sum(len(m.get("content", "")) for m in messages) < 42000


def test_repeated_tool_results_stop_without_a_write(tmp_path):
    model, _ = agent_for([[("read_current_document", {})]] * 5)
    with pytest.raises(CompanionError, match="相同结果"):
        run_agent(model, tmp_path)


@pytest.mark.parametrize(
    "expression", ['__import__("os")', "2**100000", "1/0", "[1,2]", "True+1", "1e100"]
)
def test_calculator_rejects_code_and_unbounded_arithmetic(expression):
    with pytest.raises(CompanionError):
        calculate(expression)


def test_registry_exposes_only_available_capabilities_and_validates_types():
    registry = ToolRegistry()
    definition = {
        "type": "function",
        "function": {
            "name": "example",
            "parameters": {
                "type": "object",
                "properties": {"offset": {"type": "integer", "minimum": 0}},
                "required": ["offset"],
                "additionalProperties": False,
            },
        },
    }
    registry.register(ToolSpec(definition))
    for name, args in [
        ("unknown", {}),
        ("example", {"offset": True}),
        ("example", {"offset": -1}),
        ("example", {"offset": 0, "shell": "x"}),
    ]:
        with pytest.raises(CompanionError):
            registry.check(name, args)
    assert registry.check("example", {"offset": 0}).effect == "read"


def test_latest_feedback_retains_previous_plan_without_replaying_edits(tmp_path):
    plan = [{"title": "只修改当前一段", "status": "in_progress"}]

    def answer(payload):
        request = json.loads(
            [m for m in payload["messages"] if m["role"] == "user"][-1]["content"]
        )
        assert request["previous_plan"] == plan
        assert "replace_current_text" not in [
            t["function"]["name"] for t in payload["tools"]
        ]
        from companion.tests.test_workspace_agent import response

        return response(("answer_user", {"text": "当前片段只读，可以继续核对资料。"}))

    model, _ = agent_for([answer])
    run_agent(model, tmp_path, checkpoint={"plan": plan}, editable=False)


def test_invalid_edit_is_repaired_before_native_mutation(tmp_path):
    from companion.session import EditingSession
    from companion.tests.test_session import Documents, settled

    documents = Documents()

    def repaired(payload):
        assert documents.writes == []
        errors = [
            json.loads(item["content"])
            for item in payload["messages"]
            if item["role"] == "tool"
        ]
        assert errors[-1]["recoverable"]
        from companion.tests.test_workspace_agent import response

        return response(
            ("replace_current_text", {"text": "有效修改。", "note": "修正了非法换行"})
        )

    model, _ = agent_for(
        [
            [("replace_current_text", {"text": "错误\n跨段修改", "note": "不可执行"})],
            repaired,
        ]
    )
    session = EditingSession(documents, lambda: model)
    session.connect("word")
    session.start("修改当前段", agent=True)
    assert settled(session)["phase"] == "review"
    assert documents.writes == ["one"] and documents.text["one"] == "有效修改。"
