"""Prewrite review uses versioned source text instead of guessing from prefixes."""

import pytest

from companion.tests.test_agent_lab import make_lab


@pytest.mark.parametrize("change_during_review", [False, True])
def test_late_page_evidence_reaches_prewrite_and_changes_block_publication(
    tmp_path, change_during_review
):
    captured = []
    source = tmp_path / "sources" / "资料.txt"

    def verifier(turn, tool, args, state):
        if tool == "create_word":
            evidence = state["write_evidence"]["source_evidence"]
            captured.append(evidence)
            assert "[第12页]沙箱隔离" in evidence["references"][0]["text"]
            if change_during_review:
                source.write_text("新版本，不允许旧提案发布", encoding="utf8")
        return {"allowed": True}

    store, task, broker, _ = make_lab(tmp_path, verifier, outputs=["摘要.docx"])
    source.write_text(
        "前言" * 1200 + "\n[第12页]沙箱隔离属于技术介绍。", encoding="utf8"
    )
    assert broker.invoke("read_reference", {"file_id": source.name})["ok"]
    assert "沙箱" not in broker.verification_reads[-1]["text"]
    result = broker.invoke(
        "create_word",
        {
            "action_id": "create",
            "file_name": "摘要.docx",
            "title": "资料摘要",
            "sections": [{"heading": "技术介绍", "text": "资料第12页介绍沙箱隔离。"}],
        },
    )
    assert bool(result["ok"]) != change_during_review
    assert (broker.outputs / "摘要.docx").exists() != change_during_review
    assert captured
    store.close()
