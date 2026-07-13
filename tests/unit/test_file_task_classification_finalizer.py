from types import SimpleNamespace

from app.core.agent.file_task_classification_finalizer import (
    build_final_classification,
    classification_confidence,
    classification_target_file_type,
)
from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest


class _RecipeCandidate:
    def __init__(self, recipe_id: str) -> None:
        self.recipe = SimpleNamespace(id=recipe_id)

    def public_dict(self) -> dict[str, str]:
        return {"recipe_id": self.recipe.id}


def test_classification_target_file_type_prefers_target_path_then_target_file():
    explicit = FileTaskRequest(task="生成报告", target_path="report.docx")
    fallback = FileTaskRequest(
        task="更新目标",
        files=[
            FileTaskFile(path="source.xlsx", name="source.xlsx", type="xlsx"),
            FileTaskFile(path="target.pdf", name="target.pdf", type="pdf", target=True),
        ],
    )

    assert classification_target_file_type(explicit, []) == "docx"
    assert classification_target_file_type(fallback, fallback.files) == "pdf"


def test_build_final_classification_applies_output_and_confidence_contracts():
    request = FileTaskRequest(
        task="为什么这里会触发写入",
        target_path="answer.docx",
        files=[FileTaskFile(path="answer.docx", name="answer.docx", type="docx")],
    )
    selected = _RecipeCandidate("docx_chart_report")
    candidates = [
        selected,
        _RecipeCandidate("other_1"),
        _RecipeCandidate("other_2"),
        _RecipeCandidate("other_3"),
        _RecipeCandidate("other_4"),
        _RecipeCandidate("other_5"),
    ]

    classification = build_final_classification(
        request=request,
        files=request.files,
        output_mode_resolver=lambda _request, _files: "write",
        request_kind="new_task",
        task_family="analyze",
        operation_kind="read",
        execution_mode="generic_tool_loop",
        write_intent=True,
        diagnostic_request=True,
        docx_annotation_request=False,
        advisory_analysis_request=False,
        readonly_write_negation=True,
        raw_write_intent=True,
        raw_docx_annotation_request=False,
        planner_policy="native_only",
        planner_reason="",
        planner_backend="native",
        known_gap_name="read_cad_file",
        matched_capabilities=["read_docx_content"],
        reason_codes=["diagnostic_request"],
        selected_recipe_match=selected,
        recipe_candidates=candidates,
    )

    assert classification.output_mode == "answer"
    assert classification.confidence == 0.7
    assert classification.target_file_type == "docx"
    assert classification.file_types == ["docx"]
    assert classification.known_native_tool_gap == "read_cad_file"
    assert classification.selected_recipe == "docx_chart_report"
    assert len(classification.recipe_candidates) == 5


def test_classification_confidence_marks_soft_diagnostic_as_higher_confidence():
    assert (
        classification_confidence(
            diagnostic_request=True,
            raw_write_intent=False,
            raw_docx_annotation_request=False,
        )
        == 0.9
    )
    assert (
        classification_confidence(
            diagnostic_request=False,
            raw_write_intent=True,
            raw_docx_annotation_request=True,
        )
        == 1.0
    )
