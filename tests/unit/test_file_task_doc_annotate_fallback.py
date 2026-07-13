from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskRequest,
)
from app.core.agent.file_task_doc_annotate_fallback import (
    apply_doc_annotate_bridge_fallback,
)


def test_doc_annotate_bridge_fallback_applies_with_boundary_and_contract(monkeypatch):
    request = FileTaskRequest(task="annotate this docx")
    files = [FileTaskFile(path="review.docx", name="review.docx", type="docx")]
    classification = FileTaskClassification(matched_capabilities=["existing"])

    monkeypatch.setattr(
        "app.core.agent.file_task_doc_annotate_fallback."
        "file_task_doc_annotate_boundary.should_use_bridge_execution",
        lambda incoming_request: incoming_request is request,
    )
    monkeypatch.setattr(
        "app.core.agent.file_task_doc_annotate_fallback."
        "file_task_doc_annotate_boundary.bridge_recipe_id",
        lambda incoming_request: "docx_bridge_recipe",
    )

    result = apply_doc_annotate_bridge_fallback(
        request=request,
        files=files,
        classification=classification,
        write_intent=False,
        docx_annotation_has_contract=lambda incoming_request, incoming_files, incoming_classification: (
            incoming_request is request
            and incoming_files == files
            and incoming_classification is classification
        ),
    )

    assert result.classification is classification
    assert result.write_intent is True
    assert classification.execution_mode == "doc_annotate_bridge"
    assert classification.task_family == "annotate"
    assert classification.operation_kind == "annotate"
    assert classification.output_mode == "write"
    assert classification.write_intent is True
    assert classification.docx_annotation_request is True
    assert classification.selected_recipe == "docx_bridge_recipe"
    assert "existing" in classification.matched_capabilities
    assert "annotate_file" in classification.matched_capabilities
    assert "read_docx_content" in classification.matched_capabilities
    assert "doc_annotate_bridge_execution_fallback" in classification.reason_codes


def test_doc_annotate_bridge_fallback_preserves_existing_bridge(monkeypatch):
    request = FileTaskRequest(task="annotate this docx")
    classification = FileTaskClassification(
        execution_mode="doc_annotate_bridge",
        selected_recipe="existing_recipe",
    )

    monkeypatch.setattr(
        "app.core.agent.file_task_doc_annotate_fallback."
        "file_task_doc_annotate_boundary.should_use_bridge_execution",
        lambda incoming_request: False,
    )

    result = apply_doc_annotate_bridge_fallback(
        request=request,
        files=[],
        classification=classification,
        write_intent=True,
        docx_annotation_has_contract=lambda *_args: False,
    )

    assert result.classification is classification
    assert result.write_intent is True
    assert classification.execution_mode == "doc_annotate_bridge"
    assert classification.selected_recipe == "existing_recipe"
    assert classification.reason_codes == []


def test_doc_annotate_bridge_fallback_skips_without_contract(monkeypatch):
    request = FileTaskRequest(task="annotate this docx")
    classification = FileTaskClassification()

    monkeypatch.setattr(
        "app.core.agent.file_task_doc_annotate_fallback."
        "file_task_doc_annotate_boundary.should_use_bridge_execution",
        lambda incoming_request: True,
    )

    result = apply_doc_annotate_bridge_fallback(
        request=request,
        files=[],
        classification=classification,
        write_intent=False,
        docx_annotation_has_contract=lambda *_args: False,
    )

    assert result.classification is classification
    assert result.write_intent is False
    assert classification.execution_mode == "generic_tool_loop"
    assert classification.reason_codes == []
