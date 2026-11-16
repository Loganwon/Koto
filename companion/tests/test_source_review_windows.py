"""Large claim ledgers cover every actual cell, using bounded global-id windows."""

import json
import threading
from types import SimpleNamespace

from companion.agent_lab.fact_ledger import blocks
from companion.agent_lab.fixed_acceptance import review
from companion.agent_lab.source_grounding import CHECKS
from companion.agent_lab.source_review import windows


def test_windows_cover_all_blocks_without_resetting_global_ids():
    body = blocks("".join(f"Sheet!A{i}\t{n}\n" for i, n in enumerate(range(37))))
    groups = list(windows(body))
    assert len(groups) == 4
    assert [k for group in groups for k in group] == list(body)
    assert all(len(group) <= 10 for group in groups)


def test_production_review_chunks_claims_without_dropping_global_dimensions():
    class Client:
        config = SimpleNamespace(model="test")
        calls = []

        def _request(self, request, cancelled):
            data = json.loads(request["messages"][1]["content"])
            self.calls.append(data)
            evidence = [b["id"] for b in data["evidence_blocks"]]
            value = {
                "checks": [
                    {"id": c["id"], "evidence": evidence, "issue": ""}
                    for c in data["review_dimensions"]
                ]
            }
            if data["review_dimensions"][0]["id"] == "quality:source_fidelity":
                assert len(evidence) <= 10
                value["claims"] = [
                    {
                        "blocks": [bid],
                        "kind": "source_fact",
                        "sources": ["s0"],
                        "request_turn": 0,
                        "request_quote": "",
                        "issue": "",
                    }
                    for bid in evidence
                ]
            return {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": json.dumps(value)}}
                ]
            }

    client = Client()
    text = "".join(f"单元格{i}:事实\n" for i in range(26))
    decision = review(
        client,
        SimpleNamespace(cancelled=threading.Event()),
        {
            "file_name": "核对.xlsx",
            "actual_content": text,
            "document_context": text,
            "fixed_checks": CHECKS,
            "claim_ledger_required": True,
            "claim_windowed_review": True,
            "source_evidence": {
                "references": [
                    {"file_id": "原表.xlsx", "text": "真实事实", "role": "reference"}
                ]
            },
        },
    )
    assert decision["allowed"] and len(client.calls) == 4
    assert {c["id"] for c in decision["checks"]} == {c["id"] for c in CHECKS}
    source = decision["checks"][0]
    assert {b["id"] for c in source["claims"] for b in c["body"]} == set(blocks(text))
