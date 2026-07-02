from app.core.agent.file_task_classification_reasons import (
    build_classification_reason_codes,
)


def test_classification_reasons_adds_planner_gap_capability_and_semantic_markers():
    result = build_classification_reason_codes(
        reason_codes=["write_intent"],
        planner_policy="native_only",
        planner_reason="",
        planner_backend="native",
        known_tool_gap={"missing_capability": "read_cad_file"},
        matched_capabilities=[
            "read_docx_content",
            "annotate_file",
            "run_python_code",
            "write_docx_content",
            "ignored_after_limit",
        ],
        chart_request=True,
        table_request=False,
        summary_request=True,
        translation_request=False,
        polish_request=False,
        financial_request=True,
        ppt_slide_write_request=False,
        ppt_design_request=False,
        docx_report_request=True,
    )

    assert result.known_gap_name == "read_cad_file"
    assert result.reason_codes[:5] == [
        "write_intent",
        "planner_policy:native_only",
        "planner_backend:native",
        "native_tool_gap:read_cad_file",
        "capability:read_docx_content",
    ]
    assert "capability:write_docx_content" in result.reason_codes
    assert "capability:ignored_after_limit" not in result.reason_codes
    assert "chart_request" in result.reason_codes
    assert "summary_request" in result.reason_codes
    assert "financial_request" in result.reason_codes
    assert "docx_report_request" in result.reason_codes


def test_classification_reasons_records_deferred_planner_when_policy_is_absent():
    result = build_classification_reason_codes(
        reason_codes=[],
        planner_policy="",
        planner_reason="deferred_to_execution_brief",
        planner_backend="",
        known_tool_gap=None,
        matched_capabilities=[],
        chart_request=False,
        table_request=False,
        summary_request=False,
        translation_request=False,
        polish_request=False,
        financial_request=False,
        ppt_slide_write_request=False,
        ppt_design_request=False,
        docx_report_request=False,
    )

    assert result.known_gap_name == ""
    assert result.reason_codes == ["planner_deferred:model_first"]
