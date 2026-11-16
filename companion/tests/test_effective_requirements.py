"""Semantic slots retain obligations and require auditable replacement edges."""

import copy

import pytest

from companion.agent_lab.effective_requirements import validate


def candidate(cid, text, turn=1, **extra):
    return {"id": cid, "requirement": text, "request_turn": turn, **extra}


def slot(check):
    return {
        "slot_id": "stable",
        "check": check,
        "status": "active",
        "created_turn": 1,
        "last_turn": 1,
    }


def test_semantic_merge_preserves_all_origins_and_stable_identity():
    old = slot(candidate("stable", "营收240万元"))
    checks = [candidate("a", "保留240万元收入"), candidate("b", "营收为240万元", 2)]
    raw = {
        "slots": [{"members": ["a", "b"], "retain": ["stable"], "replaces": []}],
        "discard": [],
    }
    result = validate(raw, "结果.docx", checks, [old], [], 2)
    assert len(result) == 1 and result[0]["slot_id"] == "stable"
    assert len(result[0]["check"]["origins"]) == 3


def test_newer_feedback_replaces_only_old_literal_and_keeps_other_fact():
    old = slot(candidate("stable", "旧负责人格式", literal="负责人：Alice"))
    new = candidate("new", "新负责人格式", 2, literal="负责人=Alice")
    requests = [{"turn": 2, "message": "把负责人格式改为负责人=Alice"}]
    raw = {
        "slots": [
            {
                "members": ["new"],
                "retain": [],
                "replaces": [
                    {"slot_id": "stable", "turn": 2, "quote": requests[0]["message"]}
                ],
            }
        ],
        "discard": [],
    }
    result = validate(raw, "结果.docx", [new], [old], requests, 2)
    assert [s["status"] for s in result] == ["active", "replaced"]
    assert result[1]["replaced_by"] == result[0]["slot_id"]
    assert result[0]["check"]["literal"] == "负责人=Alice"


@pytest.mark.parametrize(
    "mutation", ["omit", "duplicate", "fake_quote", "old_turn", "read_only"]
)
def test_invalid_replacement_cannot_drop_an_existing_obligation(mutation):
    old = slot(candidate("stable", "保留审计限定"))
    raw = {
        "slots": [
            {
                "members": ["new"],
                "retain": [],
                "replaces": [{"slot_id": "stable", "turn": 2, "quote": "改成新要求"}],
            }
        ],
        "discard": [],
    }
    requests = [{"turn": 2, "message": "改成新要求"}]
    if mutation == "omit":
        raw["slots"][0]["replaces"] = []
    if mutation == "duplicate":
        raw["slots"][0]["retain"] = ["stable"]
    if mutation == "fake_quote":
        raw["slots"][0]["replaces"][0]["quote"] = "用户没说"
    if mutation == "old_turn":
        raw["slots"][0]["replaces"][0]["turn"] = 1
    if mutation == "read_only":
        requests[0]["mode"] = "read"
    with pytest.raises(ValueError):
        validate(raw, "结果.docx", [candidate("new", "新要求", 2)], [old], requests, 2)


def test_compiler_omission_keeps_old_fact_as_an_active_slot():
    old = slot(candidate("stable", "数据未经审计"))
    raw = {
        "slots": [{"members": [], "retain": ["stable"], "replaces": []}],
        "discard": [],
    }
    result = validate(raw, "结果.docx", [], [old], [], 2)
    assert result[0]["check"]["requirement"] == "数据未经审计"


def test_optional_empty_edges_and_a_suggested_id_have_no_authority():
    old = slot(candidate("stable", "数据未经审计"))
    raw = {
        "slots": [{"slot_id": "model-chosen", "members": ["a"], "retain": ["stable"]}],
        "discard": [],
    }
    result = validate(raw, "结果.docx", [candidate("a", "未经审计")], [old], [], 2)
    assert result[0]["slot_id"] == "stable"
    raw["slots"][0].pop("retain")
    with pytest.raises(ValueError, match="遗漏"):
        validate(raw, "结果.docx", [candidate("a", "未经审计")], [old], [], 2)


def test_observed_source_proofs_do_not_recompile_human_requirements(tmp_path):
    import json
    from types import SimpleNamespace
    from companion.agent_lab.acceptance_plan import prepare
    from companion.tests.test_agent_lab import make_lab

    store, task, broker, _ = make_lab(tmp_path, outputs=("摘要.docx",))
    store.change(
        task,
        contract_required=True,
        task_contract={
            "deliverables": [
                {"name": "摘要.docx", "kind": "create", "criteria": ["保留金额"]}
            ]
        },
    )

    class Client:
        config = SimpleNamespace(model="test")

        def _request(self, request, cancelled):
            value = {
                "files": [
                    {
                        "name": "摘要.docx",
                        "literal_checks": [],
                        "criteria": [
                            {
                                "index": 0,
                                "kind": "content",
                                "items": ["保留金额"],
                                "reason": "",
                            }
                        ],
                        "requests": [
                            {
                                "index": 0,
                                "kind": "host",
                                "items": [],
                                "reason": "原文操作",
                            }
                        ],
                    }
                ]
            }
            return {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": json.dumps(value)}}
                ]
            }

    prepare(Client(), broker.turn, store, task)
    before = store.get(task)["acceptance_plan"]
    store.change(
        task,
        content_checks={
            "摘要.docx": {"sources": [{"file_id": "新观察.txt", "sha256": "hash"}]}
        },
    )
    prepare(object(), broker.turn, store, task)
    assert store.get(task)["acceptance_plan"] == before
    store.close()


def test_feedback_compiles_only_new_request_and_retains_old_slots(tmp_path):
    import json
    import threading
    from types import SimpleNamespace
    from companion.agent_lab.acceptance_plan import prepare
    from companion.tests.test_agent_lab import make_lab

    store, task, broker, _ = make_lab(tmp_path, outputs=("摘要.docx",))
    store.change(
        task,
        contract_required=True,
        task_contract={
            "id": "unchanged",
            "deliverables": [
                {"name": "摘要.docx", "kind": "create", "criteria": ["保留金额"]}
            ],
        },
    )
    compiled = []

    class Client:
        config = SimpleNamespace(model="test")

        def _request(self, request, cancelled):
            data = json.loads(request["messages"][1]["content"])
            if "current" in data:
                value = {
                    "slots": [
                        *[
                            {"members": [], "retain": [s["slot_id"]], "replaces": []}
                            for s in data["previous"]
                        ],
                        *[
                            {"members": [c["id"]], "retain": [], "replaces": []}
                            for c in data["current"]
                        ],
                    ],
                    "discard": [],
                }
            else:
                compiled.append(data)
                file = data["template"]["files"][0]
                for g in file["criteria"]:
                    g.update(kind="content", items=["金额240万元"])
                for g in file["requests"]:
                    if len(compiled) == 1:
                        g.update(kind="host", items=[], reason="原文要求")
                    else:
                        g.update(kind="content", items=["新增负责人Alice"])
                value = {"files": [file]}
            return {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": json.dumps(value)}}
                ]
            }

    client = Client()
    prepare(client, broker.turn, store, task)
    original = next(
        s["slot_id"]
        for s in store.get(task)["effective_requirements"]["files"]["摘要.docx"]
        if s["status"] == "active"
    )
    n, e = store.begin_turn(task, "增加负责人Alice", "auto")
    turn = SimpleNamespace(number=n, epoch=e, cancelled=threading.Event())
    prepare(client, turn, store, task)
    assert compiled[1]["files"][0]["criteria"] == []
    assert compiled[1]["background_requests"] == []
    assert set(compiled[1]["compiler_terms"]) == {"摘要.docx"}
    assert [r["message"] for r in compiled[1]["requests"]] == ["增加负责人Alice"]
    slots = store.get(task)["effective_requirements"]["files"]["摘要.docx"]
    assert any(s.get("slot_id") == original and s["status"] == "active" for s in slots)
    assert any(s["check"]["requirement"] == "新增负责人Alice" for s in slots)
    store.close()


def test_different_literals_cannot_be_silently_merged():
    raw = {
        "slots": [{"members": ["a", "b"], "retain": [], "replaces": []}],
        "discard": [],
    }
    with pytest.raises(ValueError, match="字面"):
        validate(
            raw,
            "结果.docx",
            [
                candidate("a", "负责人", literal="Alice"),
                candidate("b", "负责人", literal="Bob"),
            ],
            [],
            [],
            2,
        )


def test_contract_can_drop_estimated_native_edit_but_not_a_required_create():
    from companion.agent_lab.task_requirements import validate as contract

    context = {
        "sources": [],
        "request": "只生成摘要，不改原文",
        "previous_requests": [],
        "require_edit_authorization": True,
    }
    estimate = {
        "deliveries": [
            {"kind": "create", "name": "摘要.docx"},
            {"kind": "edit", "name": "当前.docx"},
        ]
    }
    created = {
        "kind": "create",
        "name": "摘要.docx",
        "criteria": ["只生成摘要"],
        "limits": {},
        "required_sources": [],
        "required_terms": [],
        "workbook_schema": None,
    }
    result = contract({"deliverables": [created]}, context, estimate)
    assert len(result["deliverables"]) == 1
    with pytest.raises(ValueError, match="缺少交付"):
        contract({"deliverables": []}, context, estimate)
    unauthorized = {**created, "kind": "edit", "name": "当前.docx"}
    with pytest.raises(ValueError, match="肯定修改"):
        contract({"deliverables": [created, unauthorized]}, context, estimate)
