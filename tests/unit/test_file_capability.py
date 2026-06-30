"""Native file-capability matrix tests.

Tests for file_task_capability functions that drive the native-only runtime.
All external-planner tests have been removed — Koto no longer supports external
retired external planner backends.
"""

from app.core.agent import file_task_capability
from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest


def test_capability_matrix_matches_excel_to_docx_write_flow():
    request = FileTaskRequest(
        task="把这个 Excel 表格加入到当前 Word 文档里",
        current_file=FileTaskFile(path="report.docx", name="report.docx", type="docx"),
        files=[FileTaskFile(path="finance.xlsx", name="finance.xlsx", type="xlsx")],
        target_path="report.docx",
    )

    assert (
        "insert_excel_as_docx_table"
        in file_task_capability.matched_native_capability_names(request)
    )


def test_capability_matrix_matches_chart_task_to_sandbox_python():
    request = FileTaskRequest(
        task="根据当前表格生成一个柱状图并输出结果",
        current_file=FileTaskFile(
            path="metrics.xlsx", name="metrics.xlsx", type="xlsx"
        ),
    )

    assert "run_python_code" in file_task_capability.matched_native_capability_names(
        request
    )


def test_capability_matrix_matches_chart_into_docx_write_flow():
    request = FileTaskRequest(
        task="把当前表格画成图并加入到 report.docx",
        current_file=FileTaskFile(
            path="finance.xlsx", name="finance.xlsx", type="xlsx"
        ),
        files=[
            FileTaskFile(
                path="report.docx", name="report.docx", type="docx", target=True
            )
        ],
        target_path="report.docx",
    )

    matched = file_task_capability.matched_native_capability_names(request)

    assert "run_python_code" in matched
    assert "insert_image_into_docx" in matched


def test_capability_matrix_does_not_match_annotation_without_file_context():
    request = FileTaskRequest(task="帮我加批注")

    assert file_task_capability.matched_native_capability_names(request) == []


def test_native_tool_gap_for_request_uses_capability_matrix_for_excel_to_docx_flow(
    monkeypatch,
):
    request = FileTaskRequest(
        task="把这个 Excel 表格加入到当前 Word 文档里",
        current_file=FileTaskFile(path="report.docx", name="report.docx", type="docx"),
        files=[FileTaskFile(path="finance.xlsx", name="finance.xlsx", type="xlsx")],
        target_path="report.docx",
    )

    monkeypatch.setattr(
        file_task_capability,
        "_has_native_tool",
        lambda tool_name: False if tool_name == "insert_excel_as_docx_table" else True,
    )

    gap = file_task_capability.native_tool_gap_for_request(request)

    assert gap is not None
    assert gap["missing_capability"] == "insert_excel_as_docx_table"
    assert gap["proposed_tool"]["name"] == "insert_excel_as_docx_table"


def test_build_file_capability_profile_marks_pdf_ocr_and_annotation_as_best_effort():
    profile = file_task_capability.build_file_capability_profile(
        file_type="pdf", path="scan.pdf"
    )

    assert profile["format"] == "pdf"
    assert profile["workspace"]["edit_mode"] == "annotate_only"
    assert profile["task"]["analysis_mode"] == "native_with_ocr"
    assert profile["task"]["annotation_support"] == "best_effort"
    assert profile["ocr_mode"] == "fallback"


def test_build_request_capability_profiles_includes_target_path_contract():
    request = FileTaskRequest(
        task="把汇总写到新的文档里",
        current_file=FileTaskFile(
            path="metrics.xlsx", name="metrics.xlsx", type="xlsx"
        ),
        target_path="summary.docx",
    )

    profiles = file_task_capability.build_request_capability_profiles(request)

    assert len(profiles) == 2
    target = next(profile for profile in profiles if profile["target"])
    assert "target_path" in target["roles"]
    assert target["format"] == "docx"
    assert target["task"]["write_support"] == "native"
