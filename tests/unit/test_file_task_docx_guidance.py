from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskRequest,
)
from app.core.agent.file_task_docx_guidance import build_docx_prompt_guidance


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


def test_docx_prompt_guidance_builds_single_annotation_guidance():
    request = FileTaskRequest(
        task="请批注这份文稿",
        target_path="C:/docs/draft.docx",
        files=[FileTaskFile(path="C:/docs/draft.docx", name="draft.docx", type="docx")],
    )
    classification = FileTaskClassification(docx_annotation_request=True)

    guidance = build_docx_prompt_guidance(
        request=request,
        files=request.files,
        classification=classification,
        display_path=_display_path,
        first_file_name=_first_file_name,
    )

    assert "DOCX 审校/批注任务规则" in guidance.single_docx_annotate_guidance
    assert "- 目标 DOCX：draft.docx" in guidance.single_docx_annotate_guidance
    assert guidance.clear_docx_review_guidance == ""
    assert guidance.docx_compare_annotate_guidance == ""


def test_docx_prompt_guidance_builds_clear_review_guidance_for_clear_request():
    request = FileTaskRequest(
        task="取消docx里面所有批注",
        files=[
            FileTaskFile(
                path="interview.docx", name="interview.docx", type="docx", target=True
            )
        ],
    )
    classification = FileTaskClassification(docx_annotation_request=False)

    guidance = build_docx_prompt_guidance(
        request=request,
        files=request.files,
        classification=classification,
        display_path=_display_path,
        first_file_name=_first_file_name,
    )

    assert "DOCX 批注/修订清理任务规则" in guidance.clear_docx_review_guidance
    assert "- 目标 DOCX：interview.docx" in guidance.clear_docx_review_guidance
    assert guidance.single_docx_annotate_guidance == ""


def test_docx_prompt_guidance_builds_compare_annotation_guidance():
    request = FileTaskRequest(
        task="对比这两份文件并标注差异",
        target_path="revised.docx",
        files=[
            FileTaskFile(path="original.docx", name="original.docx", type="docx"),
            FileTaskFile(
                path="revised.docx", name="revised.docx", type="docx", target=True
            ),
        ],
    )
    classification = FileTaskClassification(
        matched_capabilities=["compare_docx_and_annotate"]
    )

    guidance = build_docx_prompt_guidance(
        request=request,
        files=request.files,
        classification=classification,
        display_path=_display_path,
        first_file_name=_first_file_name,
    )

    assert "DOCX 双文件对比标注任务规则" in guidance.docx_compare_annotate_guidance
    assert "original.docx, revised.docx" in guidance.docx_compare_annotate_guidance
