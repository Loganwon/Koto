from app.core.agent.file_task_classification_recipes import (
    apply_recipe_classification,
    recipe_request_for_classification,
)
from app.core.agent.file_task_contract import (
    FileTaskFile,
    FileTaskRequest,
    FileTaskRoutingDecision,
)


def test_apply_recipe_classification_syncs_selected_recipe_capabilities_and_mode():
    request = FileTaskRequest(
        task="请根据 PDF 审校 Word 文档，把建议批注到 docx 里",
        target_path="reviewed.docx",
        files=[
            FileTaskFile(path="source.pdf", name="source.pdf", type="pdf"),
            FileTaskFile(
                path="reviewed.docx",
                name="reviewed.docx",
                type="docx",
                target=True,
            ),
        ],
    )

    result = apply_recipe_classification(
        classification_request=request,
        classification_task=request.task,
        files=request.files,
        write_intent=True,
        stepwise_pdf_docx_resume=False,
        matched_capabilities=["read_docx_content"],
        execution_mode="generic_tool_loop",
        reason_codes=["write_intent"],
    )

    assert result.selected is not None
    assert result.selected.recipe.id == "pdf_docx_review_bridge"
    assert result.execution_mode == "doc_annotate_bridge"
    assert result.matched_capabilities.count("read_docx_content") == 1
    assert "annotate_file" in result.matched_capabilities
    assert "write_intent" in result.reason_codes
    assert "recipe:pdf_docx_review_bridge" in result.reason_codes


def test_stepwise_recipe_request_preserves_route_decision_and_enables_summary_match():
    routing_decision = FileTaskRoutingDecision(
        route="file_task",
        task_type="FILE_TASK",
        confidence=0.93,
        route_source="model_primary_intent",
    )
    request = FileTaskRequest(
        task="继续",
        target_path="summary.docx",
        files=[FileTaskFile(path="large.pdf", name="large.pdf", type="pdf")],
        routing_decision=routing_decision,
    )

    recipe_request = recipe_request_for_classification(
        classification_request=request,
        classification_task=request.task,
        stepwise_pdf_docx_resume=True,
    )
    result = apply_recipe_classification(
        classification_request=request,
        classification_task=request.task,
        files=request.files,
        write_intent=True,
        stepwise_pdf_docx_resume=True,
        matched_capabilities=[],
        execution_mode="awaiting_confirmation_resume",
        reason_codes=["stepwise_resume_forced_write_intent"],
    )

    assert recipe_request is not request
    assert recipe_request.routing_decision is routing_decision
    assert "分步 长PDF DOCX 总结" in recipe_request.task
    assert result.selected is not None
    assert result.selected.recipe.id == "long_pdf_stepwise_docx_summary"
    assert "stepwise_resume_forced_write_intent" in result.reason_codes
