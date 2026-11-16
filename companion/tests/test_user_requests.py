"""Interrupted feedback survives model reset and actual files gate acceptance."""

import json
import threading
from types import SimpleNamespace

import pytest

from companion.contracts import CompanionError
from companion.agent_lab.delivery_acceptance import review
from companion.agent_lab.store import TaskStore
from companion.agent_lab.runtime import LabSession
from companion.agent_lab.tools import Turn
from companion.agent_lab.user_requests import acceptance, pending
from companion.agent_lab.working_context import build
from companion.tests.test_delivery_acceptance import prepared


def test_explicit_readonly_question_is_history_not_pending_content_revision(tmp_path):
    store = TaskStore(tmp_path / "tasks.sqlite3")
    task = store.create("生成摘要")
    store.begin_turn(task, "生成摘要", "auto")
    store.change(task, phase="complete", accepted_request_turn=1)
    store.begin_turn(task, "解释内容，不修改", "read")
    assert not pending(store.get(task))
    assert store.history(task)[-1]["body"]["message"] == "解释内容，不修改"
    store.close()


def test_continue_with_new_text_is_durable_but_empty_ui_control_is_not(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    store = TaskStore(path)
    task = store.create("制作摘要")
    store.begin_turn(task, "制作摘要", "auto")
    store.begin_turn(task, "继续，并把负责人改为Noor", "auto", interaction="continue")
    store.begin_turn(
        task,
        "Host-generated Continue control",
        "auto",
        interaction="continue",
        record_request=False,
    )
    store.close()
    store = TaskStore(path)
    store.begin_turn(
        task,
        "Host-generated Continue control",
        "auto",
        interaction="continue",
        record_request=False,
    )
    requests = store.get(task)["user_requests"]
    assert [r["turn"] for r in requests] == [1, 2]
    assert requests[-1]["message"] == "继续，并把负责人改为Noor"
    store.close()


def test_old_dropped_continue_text_is_restored_from_unmodified_event_ledger(tmp_path):
    store = TaskStore(tmp_path / "tasks.sqlite3")
    task = store.create("制作摘要")
    store.begin_turn(task, "制作摘要", "auto")
    store.event(
        task,
        "user_message",
        {
            "turn": 2,
            "message": "继续，把负责人写成Noor",
            "mode": "auto",
            "interaction": "continue",
        },
    )
    store.change(task, turn=2, epoch=2)
    store.begin_turn(
        task,
        "Host-generated Continue control",
        "auto",
        interaction="continue",
        record_request=False,
    )
    requests = store.get(task)["user_requests"]
    assert (
        requests[-1]["turn"] == 2
        and requests[-1]["message"] == "继续，把负责人写成Noor"
    )
    assert len(requests) == 2
    store.close()


def test_pending_feedback_survives_store_reopen_and_explicit_continue(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    store = TaskStore(path)
    task = store.create("生成摘要和简报")
    store.begin_turn(task, "生成摘要和简报", "auto", interaction="start")
    store.change(task, phase="complete", accepted_request_turn=1)
    message = "只修改已有两份文件：摘要和简报都写负责人：Alice。"
    store.begin_turn(task, message, "auto", interaction="feedback")
    store.event(task, "run_failed", {"error": "cancelled during compaction"})
    LabSession(store, task, None, None).stop()
    store.close()
    restored = TaskStore(path)
    restored.begin_turn(
        task, "继续当前任务", "auto", True, interaction="continue", record_request=False
    )
    state = restored.get(task)
    assert pending(state) == [
        {"turn": 2, "message": message, "interaction": "feedback"}
    ]
    assert build(state)["user_requests"][-1]["pending"] is True
    assert build(state)["user_requests"][-1]["message"] == message
    restored.close()


@pytest.mark.parametrize("indexes", [None, [0, 0], [0], [0, 2]])
def test_reviewer_requires_every_pending_request_once(indexes):
    class Client:
        config = SimpleNamespace(model="test")

        def _request(self, *args):
            content = {
                "checks": [
                    {
                        "criterion": 0,
                        "applicable": True,
                        "assertions": [
                            {"requirement": "旧要求", "quote": "Alice", "issue": ""}
                        ],
                        "reason": "旧要求符合",
                    }
                ]
            }
            if indexes is not None:
                content["feedback_checks"] = [
                    {
                        "request": i,
                        "applicable": True,
                        "assertions": [
                            {"requirement": "反馈", "quote": "Alice", "issue": ""}
                        ],
                        "reason": "反馈符合",
                    }
                    for i in indexes
                ]
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(content)},
                    }
                ]
            }

    with pytest.raises(CompanionError, match="完整结果"):
        review(
            Client(),
            SimpleNamespace(cancelled=None),
            {
                "criteria": ["有负责人"],
                "feedback_requests": ["改摘要", "改简报"],
                "actual_content": "Alice",
            },
        )


def test_existing_ppt_must_satisfy_new_feedback_after_interruption(tmp_path):
    observations = []

    def verifier(turn, tool, args, state):
        if tool != "review_delivery":
            return {"allowed": True}
        observations.append(args)
        requires_owner = any(
            "负责人：Alice" in r["message"] for r in args["feedback_requests"]
        )
        ok = not requires_owner or "负责人：Alice" in args["actual_content"]
        return {
            "allowed": ok,
            "checks": [{"criterion": 0, "status": "satisfied", "reason": "旧措施符合"}],
            "feedback_checks": [
                {
                    "request": i,
                    "status": "satisfied" if ok else "violated",
                    "reason": "负责人格式已改" if ok else "漏改负责人：Alice",
                }
                for i, _ in enumerate(args["feedback_requests"])
            ],
            "reason": "" if ok else "漏改负责人：Alice",
        }

    store, task, broker = prepared(tmp_path, verifier)
    assert broker.invoke("complete_task", {"summary": "原任务完成"})["ok"]
    number, epoch = store.begin_turn(
        task, "摘要和简报都改为负责人：Alice", "auto", interaction="feedback"
    )
    LabSession(store, task, broker, None).stop()
    number, epoch = store.begin_turn(task, "继续", "auto", True, interaction="continue")
    broker.bind_turn(
        Turn(
            task,
            number,
            epoch,
            "继续",
            "auto",
            threading.Event(),
            interaction="continue",
        )
    )
    failed = broker.invoke("complete_task", {"summary": "旧要求都满足"})
    assert failed["recovery"]["code"] == "delivery_acceptance_failed"
    assert failed["recovery"]["issues"][0]["user_request"]["turn"] == 2
    assert store.get(task)["accepted_request_turn"] == 1
    artifact = broker.invoke("read_artifact", {"file_name": "简报.pptx"})
    block = next(
        b for b in artifact["editable_blocks"]["blocks"] if "线索" in b["text"]
    )
    assert broker.invoke(
        "revise_office_text",
        {
            "action_id": "repair-feedback",
            "file_name": "简报.pptx",
            "expected_sha256": artifact["receipt"]["sha256"],
            "changes": [
                {
                    "block_id": block["id"],
                    "expected": block["text"],
                    "text": block["text"] + "负责人：Alice。",
                }
            ],
        },
    )["ok"]
    assert broker.invoke("complete_task", {"summary": "新反馈也已核对"})["ok"]
    assert not pending(store.get(task))
    count = len(observations)
    assert broker.invoke("complete_task", {"summary": "同一轮复核"})["ok"]
    assert len(observations) == count
