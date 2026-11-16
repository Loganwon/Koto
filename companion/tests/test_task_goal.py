"""Wrong-target writes must fail even when their native text is valid."""

import json

import pytest

from companion.session import EditingSession
from companion.workspace import LocalWorkspace
from companion.tests.test_session import Documents, settled
from companion.tests.test_workspace_agent import agent_for, response


def declare(target, operation):
    return (
        "declare_task_goal",
        {"target": target, "operation": operation, "summary": "用户本轮的明确要求"},
    )


@pytest.mark.parametrize(
    "target,operation",
    [
        ("new_file", "create"),
        ("current_fragment", "export"),
        ("reference_file", "edit"),
        ("none", "deliver"),
        ("current_fragment", "save"),
        ("none", "answer"),
    ],
)
def test_unavailable_goal_never_exposes_or_executes_current_fragment_write(
    target, operation
):
    docs = Documents()

    def refuses(payload):
        assert not docs.writes
        offered = {item["function"]["name"] for item in payload["tools"]}
        assert "replace_current_text" not in offered
        assert "skip_current_fragment" not in offered
        errors = [
            json.loads(m["content"]) for m in payload["messages"] if m["role"] == "tool"
        ]
        assert errors[-1]["recoverable"]
        return response(
            ("answer_user", {"text": "这项文件操作尚未接入，当前文档未修改。"})
        )

    model, requests = agent_for(
        [
            [declare(target, operation)],
            [
                (
                    "replace_current_text",
                    {"text": "不能写入的PPT大纲", "note": "错误目标"},
                )
            ],
            refuses,
        ],
        goal=None,
    )
    session = EditingSession(docs, lambda: model)
    session.submit("制作并保存一个新PPT，当前Word不是输出目标")
    state = settled(session)
    assert state["phase"] == "answered", state["message"]
    assert not docs.writes
    assert state["harness"]["goal"]["target"] == target
    assert all(
        item["function"]["name"] != "replace_current_text"
        for item in requests[0]["tools"]
    )


def test_undeclared_write_is_rejected_without_native_mutation():
    model, _ = agent_for(
        [
            [("replace_current_text", {"text": "未确认目标的结果", "note": "无效"})],
            [("answer_user", {"text": "没有取得编辑目标，保持原文。"})],
        ],
        goal=None,
    )
    docs = Documents()
    session = EditingSession(docs, lambda: model)
    session.submit("处理文件")
    assert settled(session)["phase"] == "answered"
    assert not docs.writes


def test_feedback_must_declare_a_fresh_goal_instead_of_inheriting_edit_authority():
    docs = Documents()
    model, _ = agent_for(
        [
            [declare("current_fragment", "edit")],
            [("replace_current_text", {"text": "第一段已处理", "note": "精简"})],
            [declare("new_file", "create")],
            [("answer_user", {"text": "尚不能新建PPT，已完成的第一段保留。"})],
        ],
        goal=None,
    )
    session = EditingSession(docs, lambda: model)
    session.submit("逐段精简")
    assert settled(session)["phase"] == "review"
    session.revise("先不要改Word，改为新建一个PPT文件")
    state = settled(session)
    assert state["phase"] == "review" and "PPT" in state["answer"]
    assert docs.writes == ["one"]
    assert docs.text["two"] == "second original"
    assert state["harness"]["goal"]["target"] == "new_file"


def test_inventory_distinguishes_unreadable_existing_file_from_absence(tmp_path):
    (tmp_path / "旧合同.doc").write_bytes(b"synthetic legacy fixture")
    (tmp_path / "合同.docx").write_bytes(b"not read in this test")
    workspace = LocalWorkspace()
    workspace.open(tmp_path)
    reads = workspace.session()
    result = reads.list(query="旧合同")
    assert result["count"] == 1
    assert result["files"][0]["readable"] is False
    assert result["files"][0]["status"] == "unsupported_format"
    from companion.contracts import CompanionError

    with pytest.raises(CompanionError, match="存在，但暂不支持读取"):
        reads.read("旧合同.doc")
    assert reads.evidence() == []


def test_readonly_followup_survives_invalid_binding_but_edit_still_conflicts():
    class DriftingRead(Documents):
        drift = False

        def read(self, target_id, fragment_id):
            if self.drift:
                return "模拟失效的宿主Range读到其他内容"
            return super().read(target_id, fragment_id)

    docs = DriftingRead()
    model, requests = agent_for(
        [
            [declare("current_fragment", "edit")],
            [("replace_current_text", {"text": "第一段已处理", "note": "精简"})],
            [("answer_user", {"text": "上次把第一段精简为第一段已处理。"})],
            [declare("current_fragment", "edit")],
            [("answer_user", {"text": "仍可解释上次的已验证修改。"})],
        ],
        goal=None,
    )
    session = EditingSession(docs, lambda: model)
    session.submit("逐段精简")
    assert settled(session)["phase"] == "review"
    requests_before = len(requests)
    docs.drift = True
    session.revise("只解释改了什么，不要修改")
    state = settled(session)
    assert state["phase"] == "review" and state["answer"]
    assert len(requests) == requests_before + 1 and docs.writes == ["one"]
    session.revise("现在把第一段继续缩短")
    state = settled(session)
    assert state["phase"] == "conflict"
    assert docs.writes == ["one"]
    assert "手动" not in state["message"]
    event = state["events"][-1]
    assert event["stage"] == "before_edit" and event["origin"] == "unknown"
    assert event["expected_hash"] != event["actual_hash"]
    assert state["harness"]["phase"] == "conflict"
    assert state["harness"]["verification_scope"] == "previous_checkpoint"
    session.revise("解释上次的已验证修改")
    state = settled(session)
    assert state["phase"] == "conflict" and state["answer"]
    assert state["conversation"]["phase"] == "answered"
    assert state["checkpoint"]["phase"] == "conflict" and not state["can_continue"]
    assert docs.writes == ["one"]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("旧侧栏文字", "旧侧栏文字"),
        (
            {
                "text": "新侧栏文字",
                "binding": {
                    "adapter": "wps_range",
                    "fragment": "f1",
                    "start": 3,
                    "end": 9,
                },
            },
            "新侧栏文字",
        ),
    ],
)
def test_native_readback_keeps_legacy_support_and_range_diagnostics(value, expected):
    from companion.host_rpc import PaneDocuments

    docs = PaneDocuments("wps")
    docs.call = lambda *args, **kwargs: value
    assert docs.read("target", "f1") == expected
    assert docs.replace("target", "f1", "before", "after", lambda: True) == expected
    if isinstance(value, dict):
        assert docs.last_read == value["binding"]
    else:
        assert docs.last_read is None
