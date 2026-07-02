from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskRequest,
)
from app.core.agent.file_task_system_prompt_guidance import (
    build_file_task_system_prompt_guidance,
)


def _display_path(value):
    return str(value or "").replace("\\", "/").rstrip("/").split("/")[-1]


def _first_file_name(files, types, *, target=False):
    for file_info in files:
        file_type = (file_info.type or "").lower()
        if target and not file_info.target:
            continue
        if types and file_type not in types:
            continue
        return file_info.name or _display_path(file_info.path)
    return ""


def test_system_prompt_guidance_combines_followup_financial_and_docx_sections():
    request = FileTaskRequest(
        task="把 Excel 财务预测数据做成图，并加入 docx",
        target_path="report.docx",
        files=[
            FileTaskFile(path="forecast.xlsx", name="forecast.xlsx", type="xlsx"),
            FileTaskFile(path="report.docx", name="report.docx", type="docx", target=True),
        ],
    )
    classification = FileTaskClassification(docx_annotation_request=True)

    guidance = build_file_task_system_prompt_guidance(
        request=request,
        files=request.files,
        classification=classification,
        followup_context={"kind": "review_last_task", "followup_action": "improve"},
        financial_chart_docx_enabled=True,
        display_path=_display_path,
        first_file_name=_first_file_name,
    )

    assert "继续优化" in guidance.followup_guidance
    assert "Excel 财务预测图表写入 DOCX 任务规则" in guidance.financial_chart_docx_guidance
    assert "DOCX 审校/批注任务规则" in guidance.single_docx_annotate_guidance
    assert "- 目标 DOCX：report.docx" in guidance.single_docx_annotate_guidance


def test_system_prompt_guidance_keeps_disabled_sections_empty():
    request = FileTaskRequest(
        task="总结这个文件",
        files=[FileTaskFile(path="notes.txt", name="notes.txt", type="txt")],
    )

    guidance = build_file_task_system_prompt_guidance(
        request=request,
        files=request.files,
        classification=FileTaskClassification(),
        followup_context={},
        financial_chart_docx_enabled=False,
        display_path=_display_path,
        first_file_name=_first_file_name,
    )

    assert guidance.followup_guidance == ""
    assert guidance.financial_chart_docx_guidance == ""
    assert guidance.docx_compare_annotate_guidance == ""
    assert guidance.clear_docx_review_guidance == ""
    assert guidance.single_docx_annotate_guidance == ""
