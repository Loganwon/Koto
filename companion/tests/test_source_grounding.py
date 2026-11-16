"""A saved-file review sees real sources and cannot accept a changing source."""

import hashlib
import json
import threading
from types import SimpleNamespace

import pytest

from companion.agent_lab.source_grounding import collect, verify, CHECKS
from companion.contracts import DocumentConflict
from companion.tests.test_delivery_acceptance import prepared


def test_relation_only_batch_still_receives_actual_source_evidence():
    from companion.agent_lab.fixed_acceptance import review
    from companion.agent_lab.source_grounding import RELATIONS

    evidence = {
        "references": [{"file_id": "原文.txt", "text": "甲强于乙"}],
        "computed_facts": [],
    }

    class Client:
        config = SimpleNamespace(model="test")

        def _request(self, request, cancelled):
            actual = json.loads(request["messages"][1]["content"])
            assert actual["source_evidence"] == evidence
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "checks": [
                                        {
                                            "id": RELATIONS["id"],
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

    assert review(
        Client(),
        SimpleNamespace(cancelled=threading.Event()),
        {
            "file_name": "副本.docx",
            "fixed_checks": [RELATIONS],
            "actual_content": "原文说甲强于乙",
            "source_evidence": evidence,
        },
    )["allowed"]


def test_query_only_source_is_available_to_final_review_and_keeps_its_hash(tmp_path):
    from companion.tests.test_native_query_sources import setup, query

    broker, host, refs = setup(tmp_path)
    result = query(broker)
    assert result["ok"] and not broker.references.evidence()
    evidence = collect(broker, "采购核对.xlsx")
    proof = next(p for p in evidence["references"] if p["file_id"] == "采购.csv")
    assert proof["binding"] == "structured_query"
    assert "12.5" in proof["text"] and "8.25" in proof["text"]
    (refs / "采购.csv").write_text("项目,数量,单价\n设备,1,1\n", encoding="utf-8")
    with pytest.raises(DocumentConflict):
        collect(broker, "采购核对.xlsx")


@pytest.mark.parametrize("source_ok", [True, False])
def test_source_checks_are_separate_and_failure_keeps_other_checks_pending(source_ok):
    from companion.agent_lab.fixed_acceptance import review

    calls = []
    ordinary = [{"id": f"c{i}", "requirement": "保留内容"} for i in range(21)]

    class Client:
        config = SimpleNamespace(model="test")

        def _request(self, request, cancelled):
            payload = json.loads(request["messages"][1]["content"])
            group = payload.get("review_dimensions", payload.get("fixed_checks"))
            calls.append([c["id"] for c in group])
            is_source = group[0]["id"].startswith("quality:source_")
            if is_source:
                assert "review_dimensions" in payload and "fixed_checks" not in payload
                assert "不是文稿必须写进去的内容" in request["messages"][0]["content"]
            assert all(
                c["id"].startswith("quality:source_") == is_source for c in group
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
                                            "id": c["id"],
                                            "evidence": ["b0"],
                                            "issue": (
                                                "共同项范围错误"
                                                if is_source and not source_ok
                                                else ""
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
            "file_name": "简报.docx",
            "fixed_checks": ordinary + CHECKS,
            "actual_content": "仅有一项共同能力",
            "source_evidence": {"references": [{"text": "多项共同能力"}]},
        },
    )
    assert calls[0] == [c["id"] for c in CHECKS]
    assert result["allowed"] == source_ok
    if source_ok:
        assert {item for group in calls[1:] for item in group} == {
            c["id"] for c in ordinary
        }
        assert all(len(group) <= 6 for group in calls[1:])
        assert {c["id"] for c in result["checks"]} == {
            c["id"] for c in ordinary + CHECKS
        }
    else:
        assert len(calls) == 1
        assert result["pending_checks"] == [c["id"] for c in ordinary]
        assert all(c["status"] == "violated" for c in result["checks"])


def grounded(tmp_path, *, change_during_review=False):
    captured = []

    class Verifier:
        def prepare_acceptance(self, turn, document):
            store.change(
                task,
                acceptance_plan={
                    "files": {
                        "简报.pptx": {
                            "checks": [{"id": "c0", "requirement": "说明安排"}]
                        }
                    }
                },
            )

        def __call__(self, turn, tool, args, state):
            if tool == "review_delivery":
                captured.append(args)
                if change_during_review:
                    source.write_text("来源已改变", encoding="utf8")
            return {"allowed": True}

    store, task, broker = prepared(tmp_path, lambda *a: {"allowed": True})
    source = tmp_path / "sources" / "安排.txt"
    source.write_text("安排：先核查线索，再改进转化。", encoding="utf8")
    store.change(
        task,
        content_checks={
            "简报.pptx": {
                "sources": [
                    {
                        "file_id": source.name,
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    }
                ],
                "facts": [],
                "quotes": [],
                "terms": [],
            }
        },
    )
    # The real body must also retain a recognizable source citation.
    from pptx import Presentation
    from companion.file_actions import FileActions

    path = broker.outputs / "简报.pptx"
    deck = Presentation(path)
    next(
        s
        for s in deck.slides[0].shapes
        if s.has_text_frame and s != deck.slides[0].shapes.title
    ).text += "来源：安排.txt"
    deck.save(path)
    store.receipt(task, FileActions.receipt(path, "create_presentation"))
    broker.verifier = Verifier()
    return store, task, broker, captured, source


def test_source_text_and_host_check_reach_real_saved_file_review(tmp_path):
    _, _, broker, captured, _ = grounded(tmp_path)
    assert broker.invoke("complete_task", {"summary": "完成"})["ok"]
    payload = captured[0]
    assert all(c in payload["fixed_checks"] for c in CHECKS)
    evidence = payload["source_evidence"]["references"][0]
    assert evidence["text"] == "安排：先核查线索，再改进转化。"
    assert not evidence["truncated"]


def test_source_change_during_review_cannot_record_completed(tmp_path):
    store, task, broker, _, _ = grounded(tmp_path, change_during_review=True)
    result = broker.invoke("complete_task", {"summary": "完成"})
    assert not result["ok"] and "来源验收期间" in result["error"]
    assert store.get(task)["phase"] != "complete"


def observed_without_citation(tmp_path):
    store, task, broker, captured, source = grounded(tmp_path)
    state = store.get(task)
    state["content_checks"]["简报.pptx"]["sources"] = []
    store.change(task, content_checks=state["content_checks"])
    assert broker.invoke("read_reference", {"file_id": source.name})["ok"]
    return store, task, broker, captured, source


def test_actual_read_sources_are_reviewed_without_literal_citation_requirement(
    tmp_path,
):
    store, task, broker, captured, source = observed_without_citation(tmp_path)
    from pptx import Presentation
    from companion.file_actions import FileActions

    path = broker.outputs / "简报.pptx"
    deck = Presentation(path)
    body = next(
        s
        for s in deck.slides[0].shapes
        if s.has_text_frame and s != deck.slides[0].shapes.title
    )
    body.text = body.text.replace(source.name, "")
    deck.save(path)
    store.receipt(task, FileActions.receipt(path, "revise_office_text"))
    assert broker.invoke("complete_task", {"summary": "核对"})["ok"]
    payload = captured[0]
    assert payload["expected_source_files"] == []
    assert source.name not in payload["actual_content"]
    assert all(c in payload["fixed_checks"] for c in CHECKS)
    proof = payload["source_evidence"]["references"][0]
    assert proof["file_id"] == source.name
    assert proof["binding"] == "observed_read" and proof["role"] == "reference"


def test_observed_text_version_cannot_be_replaced_by_changed_saved_source(tmp_path):
    _, _, broker, _, source = observed_without_citation(tmp_path)
    source.write_text("另一个版本", encoding="utf8")
    with pytest.raises(DocumentConflict, match="观察版本"):
        collect(broker, "简报.pptx")


def test_search_only_source_gets_reviewed_without_declared_filename(tmp_path):
    store, task, broker, captured, source = grounded(tmp_path)
    store.change(task, content_checks={})
    found = broker.invoke("search_reference", {"file_id": source.name, "query": "线索"})
    assert found["ok"]
    assert not any(e["kind"] == "source_read" for e in store.events(task))
    assert broker.invoke("complete_task", {"summary": "核对搜索所得资料"})["ok"]
    proof = captured[0]["source_evidence"]["references"][0]
    assert proof["file_id"] == source.name
    assert proof["observed_methods"] == ["search"]
    assert proof["observed_ranges"]
    assert all(c in captured[0]["fixed_checks"] for c in CHECKS)
    source.write_text("用户改了资料", encoding="utf8")
    with pytest.raises(DocumentConflict):
        collect(broker, "简报.pptx")


def test_copied_draft_role_is_not_promoted_to_an_authoritative_fact_source(tmp_path):
    store, task, broker, _, source = observed_without_citation(tmp_path)
    store.event(
        task,
        "action_verified",
        {"result": {"action": "copy_reference", "copied_from": source.name}},
    )
    proof = collect(broker, "简报.pptx")["references"][0]
    assert proof["role"] == "copied_input"


def test_live_reference_is_checked_as_live_text_and_not_replaced_with_disk(tmp_path):
    from companion.reading import TextSnapshot

    store, task, broker, _, source = observed_without_citation(tmp_path)
    snapshot = TextSnapshot(source.name, "实时未保存内容")
    broker.live_reader = lambda _: snapshot
    store.event(
        task,
        "source_read",
        {"file_id": source.name, "version": snapshot.version, "start": 0, "end": 7},
    )
    evidence = collect(broker, "简报.pptx")
    proof = evidence["references"][0]
    assert proof["text"] == "实时未保存内容" and proof["origin"] == "native_live"
    assert source.read_text(encoding="utf8") != proof["text"]
    verify(broker, evidence)
    snapshot = TextSnapshot(source.name, "用户又改了实时内容")
    with pytest.raises(DocumentConflict, match="实时文档变化"):
        verify(broker, evidence)


def test_disconnected_live_source_cannot_be_accepted_against_unchanged_disk(tmp_path):
    from companion.reading import TextSnapshot

    store, task, broker, _, source = observed_without_citation(tmp_path)
    snapshot = TextSnapshot(source.name, "实时内容")
    broker.live_reader = lambda _: snapshot
    store.event(
        task,
        "source_read",
        {"file_id": source.name, "version": snapshot.version, "start": 0, "end": 4},
    )
    evidence = collect(broker, "简报.pptx")
    broker.live_reader = lambda _: None
    with pytest.raises(DocumentConflict, match="已断开"):
        verify(broker, evidence)


def test_large_source_excerpt_is_explicit_and_post_read_change_rejected(tmp_path):
    _, _, broker, _, source = grounded(tmp_path)
    original = "甲" * 23000
    source.write_text(original, encoding="utf8")
    state = broker.store.get(broker.task)
    state["content_checks"]["简报.pptx"]["sources"][0]["sha256"] = hashlib.sha256(
        source.read_bytes()
    ).hexdigest()
    broker.store.change(broker.task, content_checks=state["content_checks"])
    value = collect(broker, "简报.pptx")
    assert value["references"][0]["truncated"]
    assert len(value["references"][0]["text"]) == 20000
    source.write_text("后来改了", encoding="utf8")
    with pytest.raises(DocumentConflict):
        verify(broker, value)
