from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_review_intent import (
    REVIEW_MARKERS,
    SOURCE_MARKERS,
    TRANSLATION_MARKERS,
    has_any_marker,
    has_explicit_docx_review_intent,
    looks_like_multi_docx_compare_request,
    looks_like_pdf_docx_review_request,
)

_DOCX_CLEAR_REVIEW_REQUEST_PATTERNS = (
    re.compile(
        r"(?:删除|移除|去掉|清除|清空|取消|消除|remove|delete|clear).{0,12}(?:所有|全部|整篇|整个|全部的)?(?:.{0,8})?(?:批注|标注|评论|注释|评注|修订|审阅标记|修改痕迹|comments?|review marks?|tracked changes?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:所有|全部|整篇|整个)?(?:.{0,8})?(?:批注|标注|评论|注释|评注|修订|审阅标记|修改痕迹|comments?|review marks?|tracked changes?).{0,12}(?:删除|移除|去掉|清除|清空|取消|消除|remove|delete|clear)",
        re.IGNORECASE,
    ),
)

_DIRECT_DOCX_REWRITE_REVIEW_EXCLUSIONS = (
    "批注",
    "标注",
    "评论",
    "注释",
    "评注",
    "修改建议",
    "指出问题",
    "comment",
    "annotate",
)

_DIRECT_DOCX_REWRITE_PATTERNS = (
    re.compile(
        r"(?:润色|改写|重写|优化|修改|polish|rewrite).{0,24}(?:写回|保存|替换|更新|当前|原文|文档|docx|file)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:写回|保存|替换|更新|直接修改|save|replace|update).{0,24}(?:润色|改写|重写|优化|polish|rewrite)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:润色|改写|重写|优化|polish|rewrite).{0,12}(?:这篇|这份|这个|当前|整篇|全文|文章|稿件|文稿)",
        re.IGNORECASE,
    ),
)


def looks_like_docx_review_clear_request(task_text: str) -> bool:
    text = str(task_text or "").strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _DOCX_CLEAR_REVIEW_REQUEST_PATTERNS)


def looks_like_direct_docx_rewrite_request(task_text: str) -> bool:
    text = str(task_text or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if any(marker in lowered for marker in _DIRECT_DOCX_REWRITE_REVIEW_EXCLUSIONS):
        return False
    return any(pattern.search(text) for pattern in _DIRECT_DOCX_REWRITE_PATTERNS)


def looks_like_multi_file_compare_request(request: FileTaskRequest) -> bool:
    return looks_like_multi_docx_compare_request(request)


def should_use_doc_annotate_bridge_execution(request: FileTaskRequest) -> bool:
    options = request.options if isinstance(request.options, dict) else {}
    if bool(options.get("skip_doc_annotate_bridge")):
        return False
    if str(options.get("output_mode") or "").strip().lower() == "answer":
        return False

    continue_same_bridge = False
    followup_context = options.get("followup_context")
    if (
        isinstance(followup_context, dict)
        and str(followup_context.get("kind") or "").strip() == "review_last_task"
    ):
        continue_same_bridge = _should_continue_same_bridge(
            str(request.task or ""),
            followup_context,
        )
        if not continue_same_bridge:
            return False

    task_text = str(request.task or "").strip().lower()
    if not task_text:
        return False

    if looks_like_multi_file_compare_request(request):
        return False

    target_docx = _find_target_docx_path(request)
    if not target_docx:
        return False

    if continue_same_bridge:
        return True

    if looks_like_docx_review_clear_request(task_text):
        return False
    if looks_like_direct_docx_rewrite_request(task_text):
        return False

    if not _find_pdf_file(request):
        return has_explicit_docx_review_intent(task_text)

    if looks_like_pdf_docx_review_request(request):
        return True

    has_translation = any(marker in task_text for marker in TRANSLATION_MARKERS)
    has_source = any(marker in task_text for marker in SOURCE_MARKERS)
    has_review = any(marker in task_text for marker in REVIEW_MARKERS)
    return has_translation and has_source and has_review


def should_route_request(request: FileTaskRequest) -> bool:
    return should_use_doc_annotate_bridge_execution(request)


def _should_continue_same_bridge(
    task_text: str,
    followup_context: dict[str, Any],
) -> bool:
    followup_action = str(followup_context.get("followup_action") or "").strip().lower()
    previous_mode = (
        str(followup_context.get("previous_task_mode") or "").strip().lower()
    )
    if followup_action != "improve" or previous_mode != "doc_annotate_bridge":
        return False
    previous_request = str(followup_context.get("previous_task_request") or "")
    if has_explicit_docx_review_intent(task_text, previous_request):
        return True
    return (
        has_any_marker(previous_request, TRANSLATION_MARKERS)
        and has_any_marker(previous_request, SOURCE_MARKERS)
        and has_any_marker(previous_request, REVIEW_MARKERS)
    )


def _request_files(request: FileTaskRequest) -> list[FileTaskFile]:
    files: list[FileTaskFile] = []
    if isinstance(request.current_file, FileTaskFile):
        files.append(request.current_file)
    files.extend(file for file in request.files if isinstance(file, FileTaskFile))
    return files


def _file_type(file_info: FileTaskFile) -> str:
    explicit = str(file_info.type or "").strip().lower().lstrip(".")
    if explicit:
        return explicit
    suffix = (
        Path(str(file_info.path or file_info.name or "")).suffix.lower().lstrip(".")
    )
    return suffix


def _find_pdf_file(request: FileTaskRequest) -> Optional[str]:
    for file_info in _request_files(request):
        if _file_type(file_info) == "pdf":
            return file_info.path or file_info.name
    return None


def _find_target_docx_path(request: FileTaskRequest) -> Optional[str]:
    target_path = str(request.target_path or "").strip()
    if target_path.lower().endswith(".docx"):
        return target_path

    for file_info in _request_files(request):
        if _file_type(file_info) != "docx":
            continue
        if file_info.target:
            return file_info.path or file_info.name

    for file_info in _request_files(request):
        if _file_type(file_info) == "docx":
            return file_info.path or file_info.name
    return None
