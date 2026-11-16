"""Real saved artifacts must pass final acceptance; model prose is not proof."""

import json
from types import SimpleNamespace
import pytest

from companion.contracts import CompanionError
from companion.agent_lab.delivery_acceptance import review
from companion.tests.test_agent_lab import make_lab


def prepared(tmp_path, verifier):
    store, task, broker, _ = make_lab(tmp_path, verifier, outputs=("简报.pptx",))
    assert broker.invoke(
        "create_presentation",
        {
            "action_id": "create",
            "file_name": "简报.pptx",
            "title": "简报",
            "sections": [{"heading": "安排", "text": "先核查线索，再改进转化。"}],
        },
    )["ok"]
    store.change(
        task,
        contract_required=True,
        task_contract={
            "id": "accepted",
            "deliverables": [
                {
                    "kind": "create",
                    "name": "简报.pptx",
                    "criteria": ["说明提高效率的目标和措施先后"],
                }
            ],
        },
    )
    return store, task, broker


def test_real_file_omission_blocks_completion_and_revision_rechecks_it(tmp_path):
    reviewed = []

    def verifier(turn, tool, args, state):
        if tool != "review_delivery":
            return {"allowed": True}
        reviewed.append(args)
        allowed = "提高效率" in args["actual_content"]
        return {
            "allowed": allowed,
            "kind": "evidence",
            "reason": "遗漏提高效率的目标" if not allowed else "",
            "checks": [
                {
                    "criterion": 0,
                    "status": "satisfied" if allowed else "violated",
                    "reason": "读回正文",
                }
            ],
        }

    store, task, broker = prepared(tmp_path, verifier)
    failed = broker.invoke("complete_task", {"summary": "文件已齐，完成"})
    assert (
        not failed["ok"] and failed["recovery"]["code"] == "delivery_acceptance_failed"
    )
    assert store.get(task)["phase"] != "complete"
    assert reviewed[0]["actual_content"].endswith("先核查线索，再改进转化。")
    artifact = broker.invoke("read_artifact", {"file_name": "简报.pptx"})
    block = next(
        b for b in artifact["editable_blocks"]["blocks"] if "线索" in b["text"]
    )
    assert broker.invoke(
        "revise_office_text",
        {
            "action_id": "repair",
            "file_name": "简报.pptx",
            "expected_sha256": artifact["receipt"]["sha256"],
            "changes": [
                {
                    "block_id": block["id"],
                    "expected": block["text"],
                    "text": "目标是提高效率：先核查线索，再改进转化。",
                }
            ],
        },
    )["ok"]
    complete = broker.invoke("complete_task", {"summary": "实际正文已核对"})
    assert complete["ok"]
    # A measured proposal is not necessarily the final published file. The
    # completion receipt supplies counts from the saved bytes after revision.
    saved = complete["saved_output_metrics"][0]
    assert saved["file_name"] == "简报.pptx"
    assert saved["sha256"] == store.get(task)["artifacts"]["简报.pptx"]["sha256"]
    assert saved["metrics"]["slide_body_characters"] == [
        len("目标是提高效率：先核查线索，再改进转化。")
    ]
    assert len(reviewed) == 2
    assert broker.invoke("complete_task", {"summary": "重复确认"})["ok"]
    assert (
        len(reviewed) == 2
    )  # Only the same accepted bytes and user context reuse a verdict.
    assert store.get(task)["phase"] == "complete"


def test_stop_during_final_review_cannot_record_complete(tmp_path):
    def verifier(turn, tool, args, state):
        if tool == "review_delivery":
            turn.cancelled.set()
        return {"allowed": True}

    store, task, broker = prepared(tmp_path, verifier)
    assert not broker.invoke("complete_task", {"summary": "完成"})["ok"]
    assert store.get(task)["phase"] != "complete"
    assert not store.get(task).get("delivery_acceptance")


def test_saved_verdict_survives_other_file_feedback_but_not_changed_obligations(
    tmp_path,
):
    from companion.agent_lab.delivery_acceptance import ensure
    from companion.agent_lab.tools import Turn
    import threading

    class Verifier:
        reviewed = []

        def prepare_acceptance(self, turn, document):
            pass

        def __call__(self, turn, tool, args, state):
            if tool != "review_delivery":
                return {"allowed": True}
            self.reviewed.append(args)
            return {
                "allowed": True,
                "checks": [{**c, "status": "satisfied"} for c in args["fixed_checks"]],
            }

    verifier = Verifier()
    store, task, broker = prepared(tmp_path, verifier)
    checks = [
        {
            "id": "order",
            "requirement": "先核查线索，再改进转化",
            "origins": [{"request_turn": 1}],
        }
    ]
    store.change(
        task, acceptance_plan={"version": 5, "files": {"简报.pptx": {"checks": checks}}}
    )
    ensure(broker)
    assert len(verifier.reviewed) == 1
    n, epoch = store.begin_turn(task, "只修改另一个Word文件的负责人。", "auto")
    broker.bind_turn(
        Turn(
            task, n, epoch, "只修改另一个Word文件的负责人。", "auto", threading.Event()
        )
    )
    ensure(broker)
    assert len(verifier.reviewed) == 1
    assert any(e["kind"] == "delivery_acceptance_reused" for e in store.events(task))
    changed = [
        {
            **checks[0],
            "requirement": "先改进转化，再核查线索",
            "origins": [{"request_turn": n}],
        }
    ]
    store.change(
        task,
        acceptance_plan={"version": 5, "files": {"简报.pptx": {"checks": changed}}},
    )
    ensure(broker)
    assert len(verifier.reviewed) == 2


def test_final_reviewer_requires_all_criteria_without_duplicate_indexes():
    class Client:
        config = SimpleNamespace(model="test")
        calls = 0

        def _request(self, *args):
            self.calls += 1
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "checks": [
                                        {
                                            "criterion": 0,
                                            "applicable": True,
                                            "assertions": [
                                                {
                                                    "requirement": "甲",
                                                    "quote": "甲",
                                                    "issue": "",
                                                }
                                            ],
                                            "reason": "只核对第一项",
                                        },
                                        {
                                            "criterion": 0,
                                            "applicable": True,
                                            "assertions": [
                                                {
                                                    "requirement": "甲",
                                                    "quote": "甲",
                                                    "issue": "",
                                                }
                                            ],
                                            "reason": "重复第一项",
                                        },
                                    ],
                                    "feedback_checks": [],
                                }
                            )
                        },
                    }
                ]
            }

    client = Client()
    with pytest.raises(CompanionError, match="完整结果"):
        review(
            client,
            SimpleNamespace(cancelled=None),
            {"criteria": ["甲", "乙"], "actual_content": "甲乙"},
        )
    assert client.calls == 2
