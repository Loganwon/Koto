from app.core.agent.file_task_classification_flow import build_classification_flow


def test_classification_flow_marks_followup_with_previous_task_metadata():
    flow = build_classification_flow(
        followup_context={
            "followup_action": "improve",
            "previous_task_family": "annotate",
            "previous_task_execution_mode": "doc_annotate_bridge",
            "previous_task_output_mode": "write",
            "previous_task_intent_can_apply": "true",
        },
        resume_control={},
        semantic={},
        file_types=["docx"],
        target_file_type="docx",
    )

    assert flow.request_kind == "followup"
    assert flow.execution_mode == "followup_contextual"
    assert flow.followup_action == "improve"
    assert flow.previous_task_family == "annotate"
    assert flow.previous_task_execution_mode == "doc_annotate_bridge"
    assert flow.previous_task_output_mode == "write"
    assert flow.previous_task_intent_can_apply == "true"
    assert flow.reason_codes == ["followup_action:improve"]


def test_classification_flow_marks_stepwise_pdf_docx_resume():
    flow = build_classification_flow(
        followup_context={},
        resume_control={
            "adapter": "generic_tool_loop",
            "policy": "confirm_each_step",
        },
        semantic={},
        file_types=["pdf"],
        target_file_type="docx",
    )

    assert flow.request_kind == "resume"
    assert flow.execution_mode == "awaiting_confirmation_resume"
    assert flow.resume_adapter == "generic_tool_loop"
    assert flow.stepwise_pdf_docx_resume is True
    assert "workflow_checkpoint_resume" in flow.reason_codes
    assert "workflow_adapter:generic_tool_loop" in flow.reason_codes
    assert "stepwise_resume_forced_write_intent" in flow.reason_codes


def test_classification_flow_marks_long_pdf_docx_stepwise_write():
    flow = build_classification_flow(
        followup_context={},
        resume_control={},
        semantic={
            "pdf_source": True,
            "summary_request": True,
            "stepwise_confirmation_request": True,
            "docx_target": True,
        },
        file_types=["pdf", "docx"],
        target_file_type="docx",
    )

    assert flow.request_kind == "new_task"
    assert flow.force_long_pdf_docx_write is True
    assert flow.reason_codes == ["long_pdf_stepwise_docx_forced_write_intent"]
