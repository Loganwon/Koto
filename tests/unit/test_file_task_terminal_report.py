from app.core.agent.file_task_terminal_report import (
    apply_terminal_check_overrides,
    build_terminal_run_summary,
    terminal_completed_task,
)


def test_terminal_check_overrides_rejects_readonly_without_required_context():
    payload = apply_terminal_check_overrides(
        check_payload={"passed": True, "summary": "已完成只读任务。"},
        write_intent=False,
        file_changes=[],
        final_summary="",
        output_mode="answer",
        tool_gap=None,
        snippets=[],
        readonly_tool_outputs=[],
        requires_file_context=True,
        missing_read_refs=[],
    )

    assert payload["passed"] is False
    assert payload["status"] == "quality_gate_failed"
    assert payload["criteria_results"][0]["criterion"] == "explicit_file_context_read"


def test_terminal_run_summary_appends_contract_risks_once():
    summary = build_terminal_run_summary(
        check_payload={"passed": True, "summary": "合同审查已完成。"},
        final_summary="",
        write_intent=True,
        tool_gap=None,
        selected_recipe="docx_contract_compare_review",
        file_changes=[
            {
                "path": "contract.docx",
                "contract_risk_summary": ["付款义务表述不清", "解除条款缺少通知期"],
            }
        ],
    )

    assert "合同审查已完成。" in summary
    assert "风险关注点" in summary
    assert "付款义务表述不清" in summary

    repeated = build_terminal_run_summary(
        check_payload={"passed": True, "summary": summary},
        final_summary="",
        write_intent=True,
        tool_gap=None,
        selected_recipe="docx_contract_compare_review",
        file_changes=[
            {
                "path": "contract.docx",
                "contract_risk_summary": ["付款义务表述不清"],
            }
        ],
    )
    assert repeated.count("风险关注点") == 1


def test_terminal_completed_task_keeps_write_tasks_tied_to_file_changes():
    assert (
        terminal_completed_task(
            check_payload={"passed": True},
            completed_task=False,
            write_intent=True,
            file_changes=[],
        )
        is False
    )
    assert (
        terminal_completed_task(
            check_payload={"passed": True},
            completed_task=False,
            write_intent=True,
            file_changes=[{"path": "report.docx"}],
        )
        is True
    )
