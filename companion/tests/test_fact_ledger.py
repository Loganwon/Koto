"""No model-authored citation text can enter a host-anchored fact ledger."""

from types import SimpleNamespace
import json
import threading

import pytest

from companion.agent_lab.fact_ledger import blocks, source_blocks, validate
from companion.agent_lab.fixed_acceptance import review
from companion.agent_lab.source_grounding import CHECKS, collect
from companion.tests.test_agent_lab import make_lab


def fixture():
    body = blocks("原稿说收入240万元。\n以上属于示例，未经审计。")
    refs = source_blocks(
        {
            "references": [
                {
                    "file_id": "资料.xlsx",
                    "sha256": "realhash",
                    "snapshot_version": "v1",
                    "start": 20,
                    "text": "收入!B2\t240万元\n收入!C2\t示例且未经审计",
                }
            ]
        }
    )
    claims = [
        {
            "blocks": [b],
            "kind": "source_fact",
            "sources": [s],
            "request_turn": 0,
            "request_quote": "",
            "issue": "",
        }
        for b, s in zip(body, refs)
    ]
    return body, refs, claims


def test_source_and_body_quotes_are_restored_from_real_blocks():
    body, refs, claims = fixture()
    result = validate(claims, body, refs, [])
    assert result[0]["sources"][0]["quote"] == "收入!B2\t240万元\n"
    assert result[0]["sources"][0]["start"] == 20
    assert result[0]["sources"][0]["sha256"] == "realhash"
    assert result[0]["body"][0]["quote"] == body["b0"]


@pytest.mark.parametrize("mutation", ["omitted", "invented", "copied", "user"])
def test_missing_or_ungrounded_claims_do_not_pass(mutation):
    body, refs, claims = fixture()
    if mutation == "omitted":
        claims.pop()
    if mutation == "invented":
        claims[0]["sources"] = ["s999"]
    if mutation == "copied":
        refs["s0"]["role"] = "copied_input"
    if mutation == "user":
        claims[0]["kind"] = "user_supplied"
    if mutation == "copied":
        assert validate(claims, body, refs, [])[0]["issue"]
    else:
        with pytest.raises(ValueError):
            validate(claims, body, refs, [])


def test_claim_defect_overrides_a_model_dimension_pass():
    class Client:
        config = SimpleNamespace(model="test")

        def _request(self, request, cancelled):
            data = json.loads(request["messages"][1]["content"])
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "checks": [
                                        {"id": c["id"], "evidence": ["b0"], "issue": ""}
                                        for c in data["review_dimensions"]
                                    ],
                                    "claims": [
                                        {
                                            "blocks": ["b0"],
                                            "kind": "source_fact",
                                            "sources": [],
                                            "request_turn": 0,
                                            "request_quote": "",
                                            "issue": "",
                                        }
                                    ],
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
            "file_name": "矩阵.xlsx",
            "fixed_checks": CHECKS,
            "actual_content": "核查!C2\t来源原文",
            "source_evidence": {"references": []},
            "claim_ledger_required": True,
        },
    )
    assert not result["allowed"] and "事实资料" in result["reason"]


def test_observed_workbook_text_reaches_source_review_with_cell_addresses(tmp_path):
    import openpyxl

    store, task, broker, _ = make_lab(tmp_path)
    path = tmp_path / "sources" / "资料.xlsx"
    book = openpyxl.Workbook()
    book.active["A1"] = "待核实的原始公告"
    book.save(path)
    book.close()
    assert broker.invoke("read_reference", {"file_id": path.name})["ok"]
    proof = collect(broker, "矩阵.xlsx")["references"][0]
    assert "Sheet!A1" in proof["text"] and "待核实" in proof["text"]
    store.close()


def test_saved_xlsx_content_must_pass_the_production_final_guard(tmp_path):
    import openpyxl
    from companion.file_actions import FileActions
    from companion.agent_lab.delivery_acceptance import ensure
    from companion.agent_lab.execution_errors import ToolDiagnosticError

    store, task, broker, _ = make_lab(tmp_path, outputs=("矩阵.xlsx",))
    source = tmp_path / "sources" / "原始.txt"
    source.write_text("原文明确：尚未核实公告。", encoding="utf-8")
    assert broker.invoke("read_reference", {"file_id": source.name})["ok"]
    path = broker.outputs / "矩阵.xlsx"
    book = openpyxl.Workbook()
    book.active["A1"] = "公告已经核实"
    book.save(path)
    book.close()
    store.receipt(task, FileActions.receipt(path, "create_workbook"))
    store.change(
        task,
        contract_required=True,
        task_contract={
            "deliverables": [
                {"kind": "create", "name": path.name, "criteria": ["准确引用原文"]}
            ]
        },
        acceptance_plan={
            "version": 5,
            "files": {
                path.name: {"checks": [{"id": "c", "requirement": "准确引用原文"}]}
            },
        },
    )

    class Verifier:
        def prepare_acceptance(self, turn, document):
            pass

        def __call__(self, turn, tool, payload, state):
            assert (
                payload["file_name"] == "矩阵.xlsx"
                and "Sheet!A1" in payload["actual_content"]
            )
            assert payload["claim_ledger_required"]
            claims = validate(
                [
                    {
                        "blocks": list(blocks(payload["actual_content"])),
                        "kind": "source_fact",
                        "sources": ["s0"],
                        "request_turn": 0,
                        "request_quote": "",
                        "issue": "将尚未核实改成已经核实",
                    }
                ],
                blocks(payload["actual_content"]),
                source_blocks(payload["source_evidence"]),
                [],
            )
            return {
                "allowed": False,
                "reason": "来源方向相反",
                "checks": [
                    {
                        "id": "quality:source_fidelity",
                        "status": "violated",
                        "claims": claims,
                    }
                ],
            }

    broker.verifier = Verifier()
    with pytest.raises(ToolDiagnosticError, match="来源方向相反"):
        ensure(broker)
    assert not store.get(task)["fact_ledger"][path.name]["allowed"]
    assert store.get(task)["phase"] != "complete"
    store.close()
