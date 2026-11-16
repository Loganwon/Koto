"""The task oracle must reject plausible-looking but incorrect persisted work."""

from __future__ import annotations

import json
import socket
from types import SimpleNamespace

import pytest

from scripts.office_live_probe import probe_worker, run_probe
from scripts.office_task_cases import fixed_cases
from scripts.office_task_scoring import artifact_snapshot, score_case
from scripts.standalone_office_eval import (
    ScriptedModel,
    create_office_fixtures,
    metrics_from_events,
)


def _case(case_id):
    return next(case for case in fixed_cases() if case["id"] == case_id)


def _finished():
    return [{"type": "run.finished", "payload": {"completed_task": True}}]


def test_catalog_has_24_fixed_cases_and_all_four_task_categories():
    cases = fixed_cases()
    assert len(cases) == len({case["id"] for case in cases}) == 24
    assert {
        group: sum(case["group"] == group for case in cases)
        for group in {case["group"] for case in cases}
    } == {
        "read": 6,
        "modify": 6,
        "generate_followup": 6,
        "recovery": 6,
    }


def test_fixture_stream_counts_one_call_and_defers_tool_to_final_chunk(tmp_path):
    model = ScriptedModel(_case("M04")["phases"][0], tmp_path)
    chunks = list(
        model.stream_call(messages=[{"role": "user", "content": "fixture"}], tools=[])
    )
    assert len(model.calls) == 1 and model.calls[0]["stream"] is True
    assert any(chunk.get("delta") for chunk in chunks[:-1])
    assert all(not chunk["tool_calls"] for chunk in chunks[:-1])
    assert chunks[-1]["stream_final"] is True
    assert chunks[-1]["tool_calls"][0]["name"] == "write_docx_content"
    assert chunks[-1]["usage"] is None


def test_success_claim_without_persisted_edit_is_not_task_success(tmp_path):
    folder = tmp_path / "task"
    create_office_fixtures(folder)
    before = artifact_snapshot(folder)
    assert not score_case(_case("M01"), folder, before, _finished())["passed"]


def test_matching_required_numbers_does_not_hide_an_unsupported_extra_claim(tmp_path):
    folder = tmp_path / "task"
    create_office_fixtures(folder)
    before = artifact_snapshot(folder)
    events = [
        {
            "type": "message.finished",
            "payload": {
                "content": "source.txt营收240万元，同比增长20%，另有999万元。",
            },
        }
    ] + _finished()
    result = score_case(_case("R01"), folder, before, events)
    assert not result["passed"]
    assert not next(
        check for check in result["checks"] if check["kind"] == "grounded_numbers"
    )["passed"]


def test_docx_oracle_rejects_lost_bold_even_if_text_and_append_are_correct(tmp_path):
    from docx import Document

    folder = tmp_path / "task"
    create_office_fixtures(folder)
    before = artifact_snapshot(folder)
    document = Document(folder / "brief.docx")
    document.paragraphs[1].runs[0].bold = False
    document.add_paragraph("复核结论：2026-12-31前完成。")
    document.save(folder / "brief.docx")
    result = score_case(_case("M04"), folder, before, _finished())
    assert not next(
        item for item in result["checks"] if item["kind"] == "docx_prefix_preserved"
    )["passed"]


def test_docx_oracle_detects_duplicate_logical_append(tmp_path):
    from docx import Document

    folder = tmp_path / "task"
    create_office_fixtures(folder)
    before = artifact_snapshot(folder)
    document = Document(folder / "brief.docx")
    for _ in range(2):
        document.add_paragraph("复核结论：2026-12-31前完成。")
    document.save(folder / "brief.docx")
    assert not score_case(_case("M04"), folder, before, _finished())["passed"]


def test_xlsx_oracle_detects_unrelated_formula_or_style_damage(tmp_path):
    from openpyxl import load_workbook

    folder = tmp_path / "task"
    create_office_fixtures(folder)
    before = artifact_snapshot(folder)
    workbook = load_workbook(folder / "budget.xlsx")
    workbook.active["B2"] = 125
    workbook.active["B5"] = 245
    workbook.save(folder / "budget.xlsx")
    workbook.close()
    result = score_case(_case("M05"), folder, before, _finished())
    assert not next(item for item in result["checks"] if item["kind"] == "xlsx_scope")[
        "passed"
    ]


def test_generated_output_allows_exact_safety_backup_but_rejects_second_copy(tmp_path):
    folder = tmp_path / "task"
    create_office_fixtures(folder)
    before = artifact_snapshot(folder)
    content = "# 季度结论\n240万元，同比增长20%。来源：source.txt\n"
    (folder / "report.md").write_text(content, encoding="utf-8")
    (folder / "report.md.bak").write_text("# 初稿\n", encoding="utf-8")
    completed = _finished() + _finished()
    assert score_case(_case("G02"), folder, before, completed)["passed"]
    (folder / "report-copy.md").write_text(content, encoding="utf-8")
    assert not score_case(_case("G02"), folder, before, completed)["passed"]


def test_final_followup_success_cannot_hide_failed_generation_phase(tmp_path):
    folder = tmp_path / "task"
    create_office_fixtures(folder)
    before = artifact_snapshot(folder)
    (folder / "report.md").write_text(
        "# 季度结论\n240万元，同比增长20%。来源：source.txt\n", encoding="utf-8"
    )
    events = [
        {"type": "run.finished", "payload": {"completed_task": False}}
    ] + _finished()
    result = score_case(_case("G02"), folder, before, events)
    assert not result["passed"]
    terminal = next(
        check for check in result["checks"] if check["kind"] == "completed_terminal"
    )
    assert terminal["observed_terminals"] == terminal["expected_phases"] == 2


def test_generated_csv_accepts_native_newlines_but_not_unrequested_rows(tmp_path):
    folder = tmp_path / "task"
    create_office_fixtures(folder)
    before = artifact_snapshot(folder)
    path = folder / "summary.csv"
    path.write_bytes(
        "部门,金额(万元)\r\n产品,120\r\n运营,80\r\n市场,45\r\n".encode("utf-8")
    )
    assert score_case(_case("G03"), folder, before, _finished() + _finished())["passed"]
    with path.open("ab") as output:
        output.write("额外部门,999\r\n".encode("utf-8"))
    assert not score_case(_case("G03"), folder, before, _finished() + _finished())[
        "passed"
    ]


def test_missing_provider_usage_is_not_filled_with_context_estimate():
    result = metrics_from_events(
        [
            {
                "type": "model.metrics",
                "payload": {
                    "usage": {
                        "provider_reported": False,
                        "input_tokens": None,
                        "output_tokens": None,
                    },
                    "context_estimate": {
                        "estimated_input_tokens": 1200,
                        "billing_usage": False,
                    },
                    "first_text_ms": 8,
                },
            }
        ]
    )
    assert result["actual_usage"] == []
    assert result["token_usage_available"] is False
    assert result["first_text_p50_ms"] == 8


def test_provider_reported_flag_alone_does_not_invent_token_usage():
    result = metrics_from_events(
        [
            {
                "type": "model.metrics",
                "payload": {
                    "usage": {
                        "provider_reported": True,
                        "input_tokens": None,
                        "output_tokens": None,
                    },
                },
            }
        ]
    )
    assert result["token_usage_available"] is False


def test_zero_provider_tokens_remain_actual_reported_numbers():
    result = metrics_from_events(
        [
            {
                "type": "model.metrics",
                "payload": {
                    "usage": {
                        "provider_reported": True,
                        "input_tokens": 8,
                        "output_tokens": 0,
                    },
                },
            }
        ]
    )
    assert result["actual_usage"] == [
        {"provider_reported": True, "input_tokens": 8, "output_tokens": 0}
    ]


def test_live_probe_reuses_report_without_another_network_attempt(
    tmp_path, monkeypatch
):
    report = tmp_path / "probe.json"
    report.write_text('{"status":"blocked"}', encoding="utf-8")
    monkeypatch.setattr(
        "scripts.office_live_probe.subprocess.run",
        lambda *args, **kwargs: pytest.fail("must not retry an existing probe"),
    )
    assert run_probe(report) == {"status": "blocked"}


def test_live_probe_has_hard_call_timeout_cap_and_never_serializes_secret(
    tmp_path, monkeypatch
):
    import app.core.llm.runtime_gateway as gateway

    class Provider:
        base_url = "https://provider.invalid/chat?api_key=synthetic-secret"

        def generate_content(self, **kwargs):
            assert kwargs["max_tokens"] == 16 and kwargs["timeout"] == 6
            assert kwargs["stream"] is False and self.MAX_RETRIES == 1
            raise ConnectionError("synthetic-secret") from socket.gaierror(
                11001, "synthetic-secret"
            )

    monkeypatch.setattr(
        gateway,
        "create_runtime_llm_gateway",
        lambda: SimpleNamespace(_provider=Provider(), model_id="fixture-public-model"),
    )
    output = tmp_path / "probe.json"
    probe_worker(output)
    raw = output.read_text(encoding="utf-8")
    assert "synthetic-secret" not in raw
    result = json.loads(raw)
    assert result["status"] == "blocked" and result["requests_attempted"] == 1
    assert result["host"] == "provider.invalid"
    assert result["live_group_action"] == "stopped_after_probe"
    assert result["actual_usage"] is None
