from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest


TRANSLATION_MARKERS = (
    "翻译",
    "译稿",
    "译文",
    "translation",
    "translated",
)

SOURCE_MARKERS = (
    "原文",
    "原著",
    "source",
    "对照",
    "参照",
    "参考",
    "pdf",
)

REVIEW_MARKERS = (
    "润色",
    "审校",
    "校对",
    "批注",
    "标注",
    "comment",
    "annotate",
    "术语",
    "用词",
    "翻译腔",
    "学界",
    "忠实",
    "删减",
    "添加",
)

DOCX_REVIEW_INTENT_MARKERS = (
    "批注",
    "标注",
    "标出",
    "指出",
    "审校",
    "校对",
    "审阅",
    "校阅",
    "审稿",
    "修订",
    "批改",
    "评注",
    "修改建议",
    "修改意见",
    "写得不好的地方",
    "有问题的地方",
    "不通顺",
    "不自然",
    "comment on",
    "comment",
    "annotate",
    "proofread",
    "review comments",
    "track changes",
)

COMPARE_MARKERS = (
    "对比",
    "比较",
    "比对",
    "差异",
    "区别",
    "不同",
    "compare",
    "comparison",
    "diff",
    "difference",
)


def has_any_marker(text: Any, markers: Iterable[str]) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    return any(str(marker).lower() in lowered for marker in markers)


def has_explicit_docx_review_intent(*texts: Any) -> bool:
    combined = "\n".join(
        str(text or "") for text in texts if str(text or "").strip()
    )
    return has_any_marker(combined, DOCX_REVIEW_INTENT_MARKERS)


def file_task_suffix(file_info: FileTaskFile) -> str:
    explicit = str(getattr(file_info, "type", "") or "").strip().lower().lstrip(".")
    if explicit:
        return "docx" if explicit == "doc" else explicit
    candidate = str(
        getattr(file_info, "path", "") or getattr(file_info, "name", "") or ""
    )
    suffix = Path(candidate).suffix.lower().lstrip(".")
    return "docx" if suffix == "doc" else suffix


def request_files(request: FileTaskRequest) -> list[FileTaskFile]:
    files: list[FileTaskFile] = []
    if isinstance(request.current_file, FileTaskFile):
        files.append(request.current_file)
    files.extend(file for file in request.files if isinstance(file, FileTaskFile))
    return files


def request_has_file_type(request: FileTaskRequest, file_type: str) -> bool:
    normalized = str(file_type or "").strip().lower().lstrip(".")
    if normalized == "doc":
        normalized = "docx"
    if not normalized:
        return False
    if Path(str(request.target_path or "")).suffix.lower().lstrip(".") in {
        normalized,
        "doc" if normalized == "docx" else "",
    }:
        return True
    return any(
        file_task_suffix(file_info) == normalized
        for file_info in request_files(request)
    )


def looks_like_pdf_docx_review_request(request: FileTaskRequest) -> bool:
    task_text = str(request.task or "")
    return (
        request_has_file_type(request, "pdf")
        and request_has_file_type(request, "docx")
        and has_any_marker(task_text, REVIEW_MARKERS)
    )


def looks_like_multi_docx_compare_request(request: FileTaskRequest) -> bool:
    task_text = str(request.task or "").strip().lower()
    if not task_text or not has_any_marker(task_text, COMPARE_MARKERS):
        return False
    return (
        sum(
            1
            for file_info in request_files(request)
            if file_task_suffix(file_info) == "docx"
        )
        >= 2
    )
