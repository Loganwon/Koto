import json

from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_system_prompt_payload import (
    build_file_task_system_prompt_payload,
    capability_profiles_text,
    explicit_file_list,
    known_tool_gap_text,
)


def test_explicit_file_list_uses_paths_and_falls_back_to_none():
    files = [
        FileTaskFile(path="source.pdf", name="source.pdf", type="pdf"),
        FileTaskFile(path="", name="draft.docx", type="docx"),
    ]

    assert explicit_file_list(files) == "source.pdf, draft.docx"
    assert explicit_file_list([]) == "none"


def test_capability_profiles_text_serializes_profiles():
    text = capability_profiles_text(
        [{"file_type": "docx", "read": True, "write": True}]
    )

    assert text.startswith("文件能力概览：")
    assert '"file_type": "docx"' in text
    assert text.endswith("\n")
    assert capability_profiles_text([]) == ""


def test_known_tool_gap_text_serializes_gap_with_header():
    text = known_tool_gap_text({"tool": "missing_native_docx_writer"})

    assert text.startswith("\n已知原生工具缺口：\n")
    assert '"tool": "missing_native_docx_writer"' in text
    assert text.endswith("\n")
    assert known_tool_gap_text({}) == ""
    assert known_tool_gap_text(None) == ""


def test_build_file_task_system_prompt_payload_includes_workflows_and_capabilities():
    request = FileTaskRequest(
        task="请总结这个 docx",
        files=[FileTaskFile(path="draft.docx", name="draft.docx", type="docx")],
    )

    payload = build_file_task_system_prompt_payload(
        request=request,
        files=request.files,
        known_tool_gap={"missing": "native"},
    )

    assert payload.file_list == "draft.docx"
    assert "文件能力概览：" in payload.capability_text
    assert "已知原生工具缺口" in payload.known_gap_text
    workflows = json.loads(payload.workflows)
    assert "docx" in workflows
