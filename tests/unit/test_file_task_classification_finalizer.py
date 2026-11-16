from app.core.agent.file_task_classification_finalizer import (
    build_final_classification,
    classification_confidence,
    classification_target_file_type,
)
from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest


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


def test_build_final_classification_projects_resolved_policy_and_confidence():
    request = FileTaskRequest(
        task="为什么这里会触发写入",
        target_path="answer.docx",
        files=[FileTaskFile(path="answer.docx", name="answer.docx", type="docx")],
    )
    classification = build_final_classification(
        request=request,
        files=request.files,
        request_kind="new_task",
        task_family="analyze",
        operation_kind="read",
        execution_mode="generic_tool_loop",
        output_mode="answer",
        write_authorized=False,
        write_required=False,
        diagnostic_request=True,
        raw_write_signal=True,
        planner_policy="native_only",
        planner_reason="",
        planner_backend="native",
        known_gap_name="read_cad_file",
        reason_codes=["diagnostic_request"],
    )

    assert classification.output_mode == "answer"
    assert classification.confidence == 0.7
    assert classification.target_file_type == "docx"
    assert classification.file_types == ["docx"]
    assert classification.known_native_tool_gap == "read_cad_file"
    assert classification.selected_recipe == ""
    assert classification.recipe_candidates == []


def test_classification_confidence_marks_soft_diagnostic_as_higher_confidence():
    assert (
        classification_confidence(
            diagnostic_request=True,
            raw_write_signal=False,
        )
        == 0.9
    )
    assert (
        classification_confidence(
            diagnostic_request=False,
            raw_write_signal=True,
        )
        == 1.0
    )


def test_hybrid_mode_authorizes_write_without_requiring_file_change():
    request = FileTaskRequest(task="分析并按需应用", target_path="draft.docx")
    classification = build_final_classification(
        request=request,
        files=[],
        request_kind="new_task",
        task_family="analyze",
        operation_kind="read",
        execution_mode="generic_tool_loop",
        output_mode="hybrid",
        write_authorized=True,
        write_required=False,
        diagnostic_request=False,
        raw_write_signal=True,
        planner_policy="native_only",
        planner_reason="",
        planner_backend="native",
        known_gap_name="",
        reason_codes=[],
    )

    assert classification.write_authorized is True
    assert classification.write_required is False
