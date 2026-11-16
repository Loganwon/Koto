"""Repeated feedback must not multiply the same acceptance obligation."""

from companion.agent_lab.requirement_identity import consolidate
from companion.agent_lab.acceptance_plan import validate


def test_contract_and_feedback_share_one_check_without_losing_provenance():
    spec = {
        "files": [{"name": "摘要.docx", "criteria": ["保留金额"]}],
        "requests": [{"turn": 4, "message": "只改负责人，保留金额"}],
    }
    plan = {
        "files": [
            {
                "name": "摘要.docx",
                "literal_checks": [],
                "criteria": [
                    {"index": 0, "kind": "content", "items": ["保留金额"], "reason": ""}
                ],
                "requests": [
                    {
                        "index": 0,
                        "kind": "content",
                        "items": ["保留金额", "只改负责人"],
                        "reason": "",
                    }
                ],
            }
        ]
    }
    result = validate(plan, spec)["摘要.docx"]
    assert len(result["checks"]) == 2
    retained = result["checks"][0]
    assert retained["origins"] == [
        {"id": "criterion:0:0", "criterion": 0},
        {"id": "request:0:0", "request_turn": 4},
    ]
    assert len(result["groups"]) == 2
    assert consolidate(result["checks"]) == result["checks"]
    assert validate({"type": "json_object", **plan}, spec) == {"摘要.docx": result}
    import pytest

    with pytest.raises(ValueError, match="结构无效"):
        validate({"type": "json_object", "allowed": True, **plan}, spec)


def test_similar_wording_and_exact_output_formats_are_never_guessed_equivalent():
    values = [
        {"id": "a", "requirement": "保留全部金额"},
        {"id": "b", "requirement": "保留金额"},
        {"id": "c", "requirement": "负责人", "literal": "负责人：Alice"},
        {"id": "d", "requirement": "负责人", "literal": "负责人=Alice"},
    ]
    assert len(consolidate(values)) == 4


def test_persisted_old_plan_is_consolidated_without_recompiling_user_intent(tmp_path):
    import copy
    import hashlib
    import json
    import threading
    from types import SimpleNamespace

    from companion.agent_lab.acceptance_plan import prepare, specification, plan_key
    from companion.agent_lab.store import TaskStore

    store = TaskStore(tmp_path / "tasks.sqlite3")
    task = store.create("保留金额", expected_outputs=["摘要.docx"])
    store.change(
        task,
        contract_required=True,
        task_contract={
            "deliverables": [
                {"name": "摘要.docx", "kind": "create", "criteria": ["保留金额"]}
            ]
        },
        user_requests=[],
    )
    spec = specification(store.get(task))
    identity = plan_key(spec)
    old = {
        "version": 2,
        "key": identity,
        "revision": 1,
        "files": {
            "摘要.docx": {
                "groups": [{"origin": "criterion"}],
                "checks": [
                    {"id": "criterion:0:0", "requirement": "保留金额", "criterion": 0},
                    {"id": "request:0:0", "requirement": "保留金额", "request_turn": 1},
                ],
            }
        },
    }
    store.change(task, acceptance_plan=copy.deepcopy(old))
    # This object has no model method: migration must not make an API call.
    prepare(object(), SimpleNamespace(cancelled=threading.Event()), store, task)
    current = store.get(task)["acceptance_plan"]
    assert current["version"] == 4 and current["key"] == identity
    assert (
        current["files"]["摘要.docx"]["groups"] == old["files"]["摘要.docx"]["groups"]
    )
    assert len(current["files"]["摘要.docx"]["checks"]) == 1
    assert len(current["files"]["摘要.docx"]["checks"][0]["origins"]) == 2
    store.close()
