"""Frozen obligation identities prevent silently omitting a compound subcondition."""

import json
import threading
from types import SimpleNamespace

import pytest

from companion.agent_lab.fixed_acceptance import validate, review
from companion.agent_lab.acceptance_plan import validate as validate_plan, prepare
from companion.agent_lab.acceptance_plan import specification
from companion.agent_lab.store import TaskStore
from companion.agent_lab.working_context import build, recovery_context
from companion.contracts import CompanionError

CHECKS = [
    {"id": "criterion:0:0", "requirement": "保留营收", "criterion": 0},
    {"id": "criterion:0:1", "requirement": "保留效率目标", "criterion": 0},
]


def test_truncated_batch_is_split_without_dropping_a_late_failure():
    calls, saved, diagnostics = [], [], []
    checks = [{"id": str(n), "requirement": f"条件{n}"} for n in range(4)]

    class Client:
        config = SimpleNamespace(model="test")

        def _request(self, request, cancelled):
            group = json.loads(request["messages"][1]["content"])["fixed_checks"]
            calls.append([c["id"] for c in group])
            if len(group) == 4:
                return {
                    "choices": [
                        {
                            "finish_reason": "length",
                            "message": {"content": '{"checks":'},
                        }
                    ]
                }
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "checks": [
                                        {
                                            "id": c["id"],
                                            "evidence": ["b0"],
                                            "issue": (
                                                "缺少最后条件" if c["id"] == "3" else ""
                                            ),
                                        }
                                        for c in group
                                    ]
                                }
                            )
                        },
                    }
                ]
            }

    result = review(
        Client(),
        SimpleNamespace(cancelled=threading.Event()),
        {
            "file_name": "摘要.docx",
            "actual_content": "实际业务正文",
            "fixed_checks": checks,
        },
        record=diagnostics.append,
        checkpoint=lambda values: saved.extend(values),
    )
    assert calls == [["0", "1", "2", "3"], ["0", "1"], ["2", "3"]]
    assert not result["allowed"]
    assert {c["id"] for c in result["checks"]} == {"0", "1", "2", "3"}
    assert any(c["id"] == "0" for c in saved)
    assert diagnostics[0]["event"] == "review_batch_split"


def test_title_context_cannot_satisfy_an_explicit_body_literal():
    class Client:
        config = SimpleNamespace(model="test")

        def _request(self, request, cancelled):
            payload = json.loads(request["messages"][1]["content"])
            assert "负责人=Alice" in payload["document_context"]
            assert all(
                "负责人=Alice" not in b["text"] for b in payload["evidence_blocks"]
            )
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "checks": [
                                        {
                                            "id": "literal:0",
                                            "evidence": ["b0"],
                                            "issue": "",
                                        }
                                    ]
                                }
                            )
                        },
                    }
                ]
            }

    result = review(
        Client(),
        SimpleNamespace(cancelled=threading.Event()),
        {
            "file_name": "摘要.pptx",
            "actual_content": "业务内容",
            "document_context": "页标题：负责人=Alice\n正文：业务内容",
            "fixed_checks": [
                {
                    "id": "literal:0",
                    "requirement": "正文加入准确文字",
                    "literal": "负责人=Alice",
                }
            ],
        },
    )
    assert not result["allowed"] and "正文缺少准确文字" in result["reason"]


def test_omitted_compound_subcondition_cannot_be_hidden_by_a_shorter_checklist():
    with pytest.raises(ValueError, match="全部固定检查"):
        validate(
            {"checks": [{"id": CHECKS[0]["id"], "quote": "营收240万元", "issue": ""}]},
            CHECKS,
            "营收240万元",
        )


def test_fixed_ids_and_actual_quotes_allow_a_goal_omission_to_block_completion():
    result = validate(
        {
            "checks": [
                {"id": CHECKS[0]["id"], "quote": "营收240万元", "issue": ""},
                {"id": CHECKS[1]["id"], "quote": "", "issue": "遗漏效率目标"},
            ]
        },
        CHECKS,
        "营收240万元",
    )
    assert not result["allowed"] and result["reason"] == "遗漏效率目标"


@pytest.mark.parametrize(
    "bad",
    [
        {"id": "unknown", "quote": "营收", "issue": ""},
        {"id": "criterion:0:1", "quote": "提高效率", "issue": ""},
        {"id": "criterion:0:1", "quote": "", "issue": "", "applicable": False},
    ],
)
def test_fixed_reviewer_cannot_invent_skip_or_rename_an_obligation(bad):
    with pytest.raises(ValueError):
        validate(
            {"checks": [{"id": CHECKS[0]["id"], "quote": "营收", "issue": ""}, bad]},
            CHECKS,
            "营收",
        )


def spec():
    return {
        "files": [{"name": "摘要.docx", "criteria": ["保留营收和效率目标"]}],
        "requests": [
            {"turn": 2, "message": "写负责人：Alice"},
            {"turn": 4, "message": "改成负责人=Alice"},
        ],
    }


def plan():
    return {
        "files": [
            {
                "name": "摘要.docx",
                "literal_checks": [],
                "criteria": [
                    {
                        "index": 0,
                        "kind": "content",
                        "items": ["保留营收", "保留效率目标"],
                        "reason": "",
                    }
                ],
                "requests": [
                    {
                        "index": 0,
                        "kind": "superseded",
                        "items": [],
                        "reason": "被新要求替代",
                        "replacement": {"turn": 4, "quote": "负责人=Alice"},
                    },
                    {
                        "index": 1,
                        "kind": "content",
                        "items": ["写负责人=Alice"],
                        "reason": "",
                    },
                ],
            }
        ]
    }


def test_verbatim_candidates_need_separate_intent_instead_of_syntax_guessing():
    count = "Word正文最多300字（含小标题，不含总标题和换行）"
    data, value = spec(), plan()
    data["files"][0]["criteria"] = [count + "；"]
    data["requests"][1]["message"] += "，" + count
    file = value["files"][0]
    file["criteria"][0].update(kind="host", items=[], reason="宿主计数")
    file["literal_checks"] = [{"turn": 4, "text": count}]
    # It is a grounded candidate, not yet an approved exact-output obligation.
    # Dedicated intent review makes that decision before the plan is committed.
    assert any(
        c.get("literal") == count
        for c in validate_plan(value, data)["摘要.docx"]["checks"]
    )
    file["literal_checks"] = [{"turn": 4, "text": "负责人=Alice"}]
    checks = validate_plan(value, data)["摘要.docx"]["checks"]
    assert any(c.get("literal") == "负责人=Alice" for c in checks)
    # A user can also deliberately quote a rule while retaining the numeric
    # constraint. Equal strings in two roles are not themselves a contradiction.
    file["criteria"][0].update(kind="content", items=["引用规则说明"], reason="")
    file["literal_checks"] = [{"turn": 4, "text": count}]
    assert any(
        c.get("literal") == count
        for c in validate_plan(value, data)["摘要.docx"]["checks"]
    )


def test_plan_keeps_all_indexes_and_requires_real_newer_feedback_for_supersession():
    value = validate_plan(plan(), spec())
    assert len(value["摘要.docx"]["checks"]) == 3
    bad = plan()
    bad["files"][0]["requests"][0]["replacement"]["quote"] = "用户从未说过"
    with pytest.raises(ValueError, match="真实用户要求"):
        validate_plan(bad, spec())
    missing = plan()
    missing["files"][0]["requests"].pop()
    with pytest.raises(ValueError, match="原始组"):
        validate_plan(missing, spec())


def test_revised_contract_does_not_resurrect_archived_chapters_or_readonly_questions():
    value = specification(
        {
            "expected_outputs": ["短版.docx"],
            "task_contract": {
                "accepted_at_turn": 3,
                "deliverables": [
                    {
                        "kind": "create",
                        "name": "短版.docx",
                        "criteria": ["保留示例限定与金额"],
                    }
                ],
            },
            "user_requests": [
                {"turn": 1, "message": "初稿列所有章节"},
                {"turn": 3, "message": "换短版，只保留金额与示例限定"},
                {"turn": 4, "mode": "read", "message": "解释限定，不修改"},
                {"turn": 5, "message": "两份正文加入负责人=Alice"},
            ],
        }
    )
    assert [r["turn"] for r in value["requests"]] == [3, 5]
    assert value["background_requests"][0]["message"] == "初稿列所有章节"
    assert value["files"][0]["criteria"] == ["保留示例限定与金额"]


def test_user_literal_is_grounded_and_semantic_equivalence_cannot_override_it():
    raw = plan()
    raw["files"][0]["literal_checks"] = [{"turn": 4, "text": "负责人=Alice"}]
    checks = validate_plan(raw, spec())["摘要.docx"]["checks"]
    literal = next(c for c in checks if c.get("literal"))
    verdict = validate(
        {"checks": [{"id": literal["id"], "quote": "负责人：Alice", "issue": ""}]},
        [literal],
        "负责人：Alice",
    )
    assert not verdict["allowed"] and "准确文字" in verdict["reason"]
    raw["files"][0]["literal_checks"][0]["text"] = "从未要求的内容"
    with pytest.raises(ValueError, match="真实修改要求"):
        validate_plan(raw, spec())


def test_frozen_plan_reused_after_store_reopen_continue_and_native_paragraph_change(
    tmp_path,
):
    path = tmp_path / "tasks.sqlite3"
    store = TaskStore(path)
    task = store.create("生成摘要", expected_outputs=["摘要.docx"])
    store.change(
        task,
        contract_required=True,
        task_contract={
            "deliverables": [
                {
                    "name": "摘要.docx",
                    "kind": "create",
                    "criteria": spec()["files"][0]["criteria"],
                }
            ]
        },
        user_requests=spec()["requests"],
    )
    turn = SimpleNamespace(number=4, cancelled=threading.Event())

    class Client:
        config = SimpleNamespace(model="test")
        calls = 0

        def _request(self, *args):
            self.calls += 1
            assert "native_fragments" not in json.loads(
                args[0]["messages"][1]["content"]
            )
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "slots": [
                                        {
                                            "members": [c["id"]],
                                            "retain": [],
                                            "replaces": [],
                                        }
                                        for c in json.loads(
                                            args[0]["messages"][1]["content"]
                                        )["current"]
                                    ],
                                    "discard": [],
                                }
                                if "current"
                                in json.loads(args[0]["messages"][1]["content"])
                                else plan()
                            )
                        },
                    }
                ]
            }

    client = Client()
    prepare(client, turn, store, task, {"0": "修改之前"})
    expected = store.get(task)["acceptance_plan"]
    store.close()
    restored = TaskStore(path)
    restored.begin_turn(task, "继续", "auto", True, interaction="continue")
    prepare(client, turn, restored, task, {"0": "修改之后"})
    assert restored.get(task)["acceptance_plan"] == expected and client.calls == 2
    restored.close()


def test_different_file_group_counts_are_compiled_separately_and_commit_together(
    tmp_path,
):
    store = TaskStore(tmp_path / "tasks.sqlite3")
    task = store.create("生成两份摘要", expected_outputs=["甲.docx", "乙.pptx"])
    store.change(
        task,
        contract_required=True,
        task_contract={
            "deliverables": [
                {"kind": "create", "name": "甲.docx", "criteria": ["保留营收"]},
                {
                    "kind": "create",
                    "name": "乙.pptx",
                    "criteria": ["保留营收", "保留效率目标"],
                },
            ]
        },
    )

    class Client:
        config = SimpleNamespace(model="test")
        counts = []

        def _request(self, request, *args):
            data = json.loads(request["messages"][1]["content"])
            assert len(data["files"]) == 1
            entry = data["template"]["files"][0]
            self.counts.append(len(entry["criteria"]))
            assert not store.get(task).get("acceptance_plan")
            for group in entry["criteria"]:
                group["items"] = ["必须保留的独立事实"]
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps({"files": [entry]})},
                    }
                ]
            }

    client = Client()
    prepare(client, SimpleNamespace(number=1, cancelled=threading.Event()), store, task)
    assert client.counts == [1, 2]
    assert set(store.get(task)["acceptance_plan"]["files"]) == {"甲.docx", "乙.pptx"}
    assert all(
        sum(c["id"] == "quality:consistency" for c in f["checks"]) == 1
        for f in store.get(task)["acceptance_plan"]["files"].values()
    )
    store.close()


def test_real_production_reviewer_rejects_incomplete_fixed_response_after_bounded_retry():
    class Client:
        config = SimpleNamespace(model="test")
        calls = 0

        def _request(self, *args):
            self.calls += 1
            return {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": '{"checks":[]}'}}
                ]
            }

    client = Client()
    with pytest.raises(CompanionError, match="响应不完整"):
        review(
            client,
            SimpleNamespace(cancelled=threading.Event()),
            {
                "file_name": "摘要.docx",
                "fixed_checks": CHECKS,
                "actual_content": "营收240万元",
            },
        )
    assert client.calls == 2


def test_large_fixed_review_batches_every_id_and_keeps_late_failure():
    checks = [{"id": str(i), "requirement": "保留目标"} for i in range(45)]

    class Client:
        config = SimpleNamespace(model="test")
        batches = []

        def _request(self, request, *args):
            batch = json.loads(request["messages"][1]["content"])["fixed_checks"]
            self.batches.append([c["id"] for c in batch])
            response = {
                "checks": [
                    {
                        "id": c["id"],
                        "evidence": ["b0"],
                        "issue": "末项未满足" if c["id"] == "44" else "",
                    }
                    for c in batch
                ]
            }
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(response)},
                    }
                ]
            }

    client = Client()
    result = review(
        client,
        SimpleNamespace(cancelled=threading.Event()),
        {
            "file_name": "摘要.docx",
            "fixed_checks": checks,
            "actual_content": "目标",
        },
    )
    assert all(0 < len(batch) <= 6 for batch in client.batches)
    assert [item for batch in client.batches for item in batch] == [
        str(i) for i in range(45)
    ]
    assert [c["id"] for c in result["checks"]] == [c["id"] for c in checks]
    assert not result["allowed"] and result["reason"] == "末项未满足"


def test_one_requirement_can_cite_more_than_six_real_paragraphs():
    class Client:
        config = SimpleNamespace(model="test")

        def _request(self, request, *args):
            data = json.loads(request["messages"][1]["content"])
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "checks": [
                                        {
                                            "id": "all",
                                            "evidence": [
                                                b["id"] for b in data["evidence_blocks"]
                                            ],
                                            "issue": "",
                                        }
                                    ]
                                }
                            )
                        },
                    }
                ]
            }

    result = review(
        Client(),
        SimpleNamespace(cancelled=threading.Event()),
        {
            "file_name": "摘要.docx",
            "fixed_checks": [{"id": "all", "requirement": "列出全部七个问题"}],
            "actual_content": "\n".join(f"问题{i}" for i in range(7)),
        },
    )
    assert result["allowed"] and len(result["checks"][0]["evidence"]) == 7


def test_invalid_evidence_id_is_repaired_and_quote_is_resolved_by_host():
    class Client:
        config = SimpleNamespace(model="test")
        calls = 0

        def _request(self, request, *args):
            self.calls += 1
            if self.calls == 2:
                error = request["messages"][-1]["content"]
                assert "真实块id" in error and "b0,b1" in error
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "checks": [
                                        {
                                            "id": "one",
                                            "evidence": [
                                                "invented" if self.calls == 1 else "b1"
                                            ],
                                            "issue": "",
                                        }
                                    ]
                                }
                            )
                        },
                    }
                ]
            }

    events = []
    value = review(
        Client(),
        SimpleNamespace(cancelled=threading.Event()),
        {
            "file_name": "摘要.docx",
            "fixed_checks": [{"id": "one", "requirement": "列来源"}],
            "actual_content": "来源：\n第一项",
        },
        record=events.append,
    )
    assert value["allowed"] and len(events) == 1 and events[0]["check_ids"] == ["one"]


def test_large_recovery_is_bounded_and_pending_feedback_is_still_addressable():
    state = {
        "id": "task",
        "goal": "完成资料处理",
        "phase": "active",
        "artifacts": {},
        "edits": [],
        "analyses": [{"id": str(i), "rows": ["很长的数据" * 20000]} for i in range(30)],
        "user_requests": [
            {"turn": 9, "message": "保留新的交付方向" + "详细要求" * 2000}
        ],
        "accepted_request_turn": 8,
    }
    context = build(state)
    assert len(json.dumps(context, ensure_ascii=False)) <= 24000
    assert (
        context["user_requests"][0]["turn"] == 9
        and context["user_requests"][0]["truncated"]
    )
    recovered = recovery_context(
        state, {"result": "旧内容" * 100000}, [{"text": "参考" * 100000}]
    )
    assert len(json.dumps(recovered, ensure_ascii=False)) <= 30000
    assert recovered["task"]["user_requests"][0]["turn"] == 9
    assert recovered["full_state_tool"]["name"] == "read_task"
