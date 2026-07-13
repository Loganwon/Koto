from app.core.agent.file_task_classification_followup import (
    apply_followup_annotation_overrides,
)
from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest


def test_followup_improve_from_previous_annotation_restores_docx_annotation():
    request = FileTaskRequest(
        task="继续优化上一轮结果",
        current_file=FileTaskFile(
            path="translation.docx",
            name="translation.docx",
            type="docx",
        ),
        target_path="translation.docx",
    )

    result = apply_followup_annotation_overrides(
        classification_request=request,
        request_kind="followup",
        followup_action="improve",
        previous_task_family="annotate",
        previous_task_execution_mode="annotate_tool_loop",
        previous_task_output_mode="write",
        previous_task_intent_can_apply="",
        resume_adapter="",
        docx_annotation_request=False,
        write_intent=False,
        execution_mode="followup_contextual",
        reason_codes=["followup_action:improve"],
    )

    assert result.docx_annotation_request is True
    assert result.write_intent is True
    assert result.execution_mode == "followup_contextual"
    assert "followup_previous_task_family:annotate" in result.reason_codes
    assert "followup_previous_execution_mode:annotate_tool_loop" in result.reason_codes
    assert "docx_annotation_request" in result.reason_codes
    assert "docx_annotation_forced_write_intent" in result.reason_codes


def test_followup_improve_from_doc_annotate_bridge_keeps_bridge_mode():
    request = FileTaskRequest(
        task="继续优化上一轮批注",
        files=[
            FileTaskFile(path="translation.docx", name="translation.docx", type="docx")
        ],
        target_path="translation.docx",
    )

    result = apply_followup_annotation_overrides(
        classification_request=request,
        request_kind="followup",
        followup_action="improve",
        previous_task_family="annotate",
        previous_task_execution_mode="doc_annotate_bridge",
        previous_task_output_mode="write",
        previous_task_intent_can_apply="true",
        resume_adapter="",
        docx_annotation_request=False,
        write_intent=True,
        execution_mode="followup_contextual",
        reason_codes=[],
    )

    assert result.docx_annotation_request is True
    assert result.write_intent is True
    assert result.execution_mode == "doc_annotate_bridge"
    assert "docx_annotation_forced_write_intent" not in result.reason_codes


def test_followup_apply_hybrid_output_restores_write_intent_without_annotation():
    request = FileTaskRequest(task="应用上一轮建议")

    result = apply_followup_annotation_overrides(
        classification_request=request,
        request_kind="followup",
        followup_action="apply",
        previous_task_family="analyze",
        previous_task_execution_mode="generic_tool_loop",
        previous_task_output_mode="hybrid",
        previous_task_intent_can_apply="true",
        resume_adapter="",
        docx_annotation_request=False,
        write_intent=False,
        execution_mode="followup_contextual",
        reason_codes=["followup_action:apply"],
    )

    assert result.docx_annotation_request is False
    assert result.write_intent is True
    assert result.execution_mode == "followup_contextual"
    assert "followup_apply_write_intent" in result.reason_codes
