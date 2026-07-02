from app.core.agent.file_task_classification_state import (
    build_classification_pipeline_state,
)
from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest


def test_classification_pipeline_state_builds_signals_flow_and_planner_context():
    request = FileTaskRequest(
        task="分析这个长 PDF，分步总结并写入 docx，每一步等我继续",
        target_path="summary.docx",
        files=[FileTaskFile(path="large.pdf", name="large.pdf", type="pdf")],
    )

    state = build_classification_pipeline_state(
        classification_task=request.task,
        classification_request=request,
        files=request.files,
        followup_context={},
        resume_control={"policy": "confirm_each_step", "adapter": "generic_tool_loop"},
        planner_policy="native_only",
        planner_reason="",
        planner_backend="native",
        is_docx_annotation_request=lambda _request: False,
        is_docx_clear_review_request=lambda _request: False,
        is_diagnostic_request=lambda _task: False,
    )

    assert state.classification_task == request.task
    assert state.classification_request is request
    assert state.planner_policy == "native_only"
    assert state.planner_backend == "native"
    assert state.diagnostic_request is False
    assert state.signals.summary_request is True
    assert state.signals.target_file_type == "docx"
    assert state.flow.request_kind == "resume"
    assert state.flow.stepwise_pdf_docx_resume is True
    assert "workflow_checkpoint_resume" in state.flow.reason_codes


def test_classification_pipeline_state_preserves_followup_context():
    request = FileTaskRequest(
        task="继续优化上一轮批注",
        target_path="draft.docx",
        files=[FileTaskFile(path="draft.docx", name="draft.docx", type="docx")],
    )

    state = build_classification_pipeline_state(
        classification_task=request.task,
        classification_request=request,
        files=request.files,
        followup_context={
            "followup_action": "improve",
            "previous_task_family": "annotate",
            "previous_task_execution_mode": "doc_annotate_bridge",
        },
        resume_control={},
        planner_policy="",
        planner_reason="deferred_to_execution_brief",
        planner_backend="",
        is_docx_annotation_request=lambda _request: True,
        is_docx_clear_review_request=lambda _request: False,
        is_diagnostic_request=lambda _task: False,
    )

    assert state.flow.request_kind == "followup"
    assert state.flow.followup_action == "improve"
    assert state.flow.previous_task_family == "annotate"
    assert state.flow.previous_task_execution_mode == "doc_annotate_bridge"
    assert state.signals.docx_annotation_request is True
    assert state.planner_reason == "deferred_to_execution_brief"
