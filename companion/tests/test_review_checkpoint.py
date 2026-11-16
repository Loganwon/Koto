"""Interrupted semantic review resumes only with unchanged evidence and scope."""

import copy
import json
from types import SimpleNamespace

import pytest

from companion.agent_lab.fixed_acceptance import review
from companion.agent_lab.review_checkpoint import restore, save
from companion.agent_lab.requirement_identity import consolidate
from companion.tests.test_agent_lab import make_lab


def test_interrupted_batches_resume_after_reopen_without_approving_pending_checks(
    tmp_path,
):
    store, task, broker, _ = make_lab(tmp_path)
    payload = {
        "file_name": "摘要.docx",
        "actual_content": "保留金额与限定。",
        "document_context": "摘要\n保留金额与限定。",
        "criteria": ["保留金额与限定"],
        "feedback_requests": [],
        "fixed_checks": consolidate(
            [{"id": str(n), "requirement": f"独立内容条件{n}"} for n in range(21)]
        ),
    }
    calls = []

    class Client:
        config = SimpleNamespace(model="test")

        def _request(self, request, cancelled):
            checks = json.loads(request["messages"][1]["content"])["fixed_checks"]
            calls.append([c["id"] for c in checks])
            if len(calls) == 2:
                raise RuntimeError("模拟验收到第二批时进程中断")
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "checks": [
                                        {"id": c["id"], "evidence": ["b0"], "issue": ""}
                                        for c in checks
                                    ]
                                }
                            )
                        },
                    }
                ]
            }

    checkpoint = lambda checks: save(store, task, broker.turn, payload, checks)
    with pytest.raises(RuntimeError, match="进程中断"):
        review(Client(), broker.turn, payload, checkpoint=checkpoint)
    assert {c["id"] for c in restore(store, task, payload)} == set(calls[0])
    assert 0 < len(calls[0]) < len(payload["fixed_checks"])
    assert store.get(task)["phase"] != "complete"
    path = tmp_path / "tasks.sqlite3"
    store.close()
    from companion.agent_lab.store import TaskStore

    restored = TaskStore(path)
    reusable = restore(restored, task, payload)
    result = review(Client(), broker.turn, payload, reusable=reusable)
    assert result["allowed"] and len(result["checks"]) == 21
    assert {c["id"] for c in result["checks"]} == {str(n) for n in range(21)}
    assert not set(calls[0]).intersection(item for group in calls[2:] for item in group)
    restored.close()


@pytest.mark.parametrize(
    "field",
    [
        "actual_content",
        "document_context",
        "criteria",
        "feedback_requests",
        "native_fragments",
        "editing_baseline",
        "source_evidence",
    ],
)
def test_any_changed_semantic_input_invalidates_saved_review(tmp_path, field):
    store, task, broker, _ = make_lab(tmp_path)
    checks = consolidate([{"id": "c", "requirement": "保留金额"}])
    payload = {
        "file_name": "摘要.docx",
        "actual_content": "金额120元",
        "fixed_checks": checks,
    }
    save(
        store,
        task,
        broker.turn,
        payload,
        [{**checks[0], "status": "satisfied", "issue": ""}],
    )
    assert restore(store, task, payload)
    changed = copy.deepcopy(payload)
    changed[field] = "changed"
    assert restore(store, task, changed) == []
    store.close()


def test_failed_checks_and_cancelled_work_are_not_reused(tmp_path):
    store, task, broker, _ = make_lab(tmp_path)
    checks = consolidate([{"id": "c", "requirement": "保留金额"}])
    payload = {
        "file_name": "摘要.docx",
        "actual_content": "缺金额",
        "fixed_checks": checks,
    }
    save(store, task, broker.turn, payload, [{**checks[0], "status": "violated"}])
    assert not restore(store, task, payload)
    broker.turn.cancelled.set()
    save(store, task, broker.turn, payload, [{**checks[0], "status": "satisfied"}])
    assert not restore(store, task, payload)
    store.close()


def test_internal_review_evidence_does_not_bloat_the_agent_task_read(tmp_path):
    store, task, broker, _ = make_lab(tmp_path)
    store.change(
        task,
        acceptance_checkpoints={
            "摘要.docx": {
                "scope": "version",
                "checks": {"c": {"quote": "庞大验收缓存" * 1000}},
            }
        },
    )
    value = broker.invoke("read_task", {})
    assert value["ok"]
    assert "庞大验收缓存" not in str(value)
    assert "acceptance_checkpoint_summary" in str(value)
    assert store.get(task)["acceptance_checkpoints"]["摘要.docx"]["checks"]
    store.close()


def test_unrelated_edit_reuses_only_unchanged_local_proof_and_rechecks_globals(
    tmp_path,
):
    store, task, broker, _ = make_lab(tmp_path)
    checks = [
        {"id": "amount", "requirement": "保留240万元"},
        {"id": "quality:consistency", "requirement": "全稿没有冲突"},
    ]
    payload = {
        "file_name": "摘要.docx",
        "actual_content": "金额240万元\n未经审计\n分隔段\n旧结尾",
        "fixed_checks": checks,
        "incremental_review": True,
        "semantic_context": {"title": "项目"},
    }
    proofs = [
        {
            **check,
            "status": "satisfied",
            "scope_kind": "local",
            "evidence": [{"id": "b0", "quote": "金额240万元\n"}],
        }
        for check in checks
    ]
    save(store, task, broker.turn, payload, proofs)
    changed = {**payload, "actual_content": "金额240万元\n未经审计\n分隔段\n新结尾"}
    restored = restore(store, task, changed)
    assert [c["id"] for c in restored] == ["amount"]
    assert restored[0]["reused_incrementally"]
    # Saving a new global batch cannot re-label an old whole-document proof as
    # checked against the changed text on a subsequent Continue.
    save(store, task, broker.turn, changed, [])
    assert [c["id"] for c in restore(store, task, changed)] == ["amount"]
    adjacent = {
        **changed,
        "actual_content": changed["actual_content"].replace("未经审计", "已经审计"),
    }
    assert restore(store, task, adjacent) == []
    source_changed = {**changed, "source_evidence": {"version": "new"}}
    assert restore(store, task, source_changed) == []
    store.close()


def test_a_failed_recheck_removes_an_older_local_success(tmp_path):
    store, task, broker, _ = make_lab(tmp_path)
    check = {"id": "c", "requirement": "金额正确"}
    payload = {
        "file_name": "摘要.docx",
        "actual_content": "240万元",
        "fixed_checks": [check],
    }
    save(store, task, broker.turn, payload, [{**check, "status": "satisfied"}])
    save(store, task, broker.turn, payload, [{**check, "status": "violated"}])
    assert restore(store, task, payload) == []
    store.close()
