"""Structured file capability-profile tests."""

from app.core.agent import file_task_capability
from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest


def test_capability_module_has_no_task_text_routing_matrix():
    assert not hasattr(file_task_capability, "matched_native_capability_names")
    assert not hasattr(file_task_capability, "native_tool_gap_for_request")
    assert not hasattr(file_task_capability, "NativeCapabilitySpec")


def test_build_file_capability_profile_uses_format_catalog_only():
    profile = file_task_capability.build_file_capability_profile(
        file_type="xlsx", path="metrics.xlsx"
    )

    assert profile["format"] == "xlsx"
    assert profile["family"] == "spreadsheet"
    assert "read_sheet_data" in profile["tool_names"]
    assert "write_sheet_data" in profile["write_tool_names"]


def test_build_file_capability_profile_reports_actual_pdf_surface():
    profile = file_task_capability.build_file_capability_profile(
        file_type="pdf", path="scan.pdf"
    )

    assert profile["format"] == "pdf"
    assert profile["workspace"]["edit_mode"] == "annotate_only"
    assert profile["task"]["analysis_mode"] == "native_with_ocr"
    assert profile["task"]["annotation_support"] == "none"
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


def test_request_wording_does_not_change_capability_profiles():
    files = [FileTaskFile(path="metrics.xlsx", name="metrics.xlsx", type="xlsx")]
    chart_request = FileTaskRequest(task="生成图表", files=files)
    translation_request = FileTaskRequest(task="翻译表格", files=files)

    chart_profiles = file_task_capability.build_request_capability_profiles(
        chart_request
    )
    translation_profiles = file_task_capability.build_request_capability_profiles(
        translation_request
    )

    assert chart_profiles == translation_profiles
