# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import re
from typing import List

from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_recipes import semantic_markers
from app.core.agent.file_task_runtime_patterns import (
    _ADVICE_CUE_WORDS,
    _ANALYSIS_ADVICE_PATTERNS,
    _ANALYSIS_CUE_WORDS,
    _ARTIFACT_CREATION_INTENT_PATTERNS,
    _DIAGNOSTIC_NEW_TASK_PATTERNS,
    _DIAGNOSTIC_REQUEST_PATTERNS,
    _EXPLICIT_WRITE_INTENT_WORDS,
    _GLOBAL_READONLY_WRITE_NEGATION_PATTERNS,
    _IMPERATIVE_WRITE_PATTERNS,
    _READONLY_WRITE_NEGATION_PATTERNS,
    _SOFT_WRITE_ACTION_WORDS,
    _SOURCE_SCOPED_WRITE_NEGATION_PATTERNS,
    _TASK_TEXT_FILE_REFERENCE_PATTERN,
    _WRITE_INTENT_PATTERNS,
    _WRITE_INTENT_WORDS,
    _WRITE_TARGET_HINT_WORDS,
)


_TARGETED_FILE_WRITE_CONTEXT_PATTERN = re.compile(
    r"(?:继续优化|优化|修改|更新|保存|写入|写回|追加|添加|插入|落盘|"
    r"continue|improve|modify|edit|update|save|write|append|insert|copy|put|place)",
    re.IGNORECASE,
)
_PATH_SCOPED_PROTECTION_PATTERN = re.compile(
    r"(?:不要|不用|无需|不需要|不必|别|不|do not|don't|dont|no need to|without)"
    r".{0,18}(?:修改|改动|编辑|覆盖|替换|删除|写入|写回|更新|modify|edit|overwrite|replace|delete|write|update)",
    re.IGNORECASE,
)
_PAST_ARTIFACT_REFERENCE_PATTERN = re.compile(
    r"(?:刚才|之前|上次|上一轮|前面|已|已经|already|previously).{0,18}"
    r"(?:生成|创建|导出|保存|created|generated|exported|saved)(?:的|好)?",
    re.IGNORECASE,
)
_READONLY_FOLLOWUP_VERB_PATTERN = re.compile(
    r"(?:读取|阅读|查看|分析|确认|指出|说明|总结|审阅|检查|read|analy[sz]e|review|summari[sz]e|check)",
    re.IGNORECASE,
)


def has_write_intent(task: str) -> bool:
    if is_diagnostic_request(task):
        return False
    if is_readonly_existing_artifact_followup(task):
        return False
    if has_readonly_write_negation(task):
        return False
    strong_write_intent = has_strong_write_intent(task)
    explicit_write_intent = has_explicit_write_intent(task)
    if is_advisory_analysis_request(task) and not strong_write_intent:
        return False
    return explicit_write_intent or strong_write_intent


def has_strong_write_intent(task: str) -> bool:
    if has_readonly_write_negation(task):
        return False
    lowered = (task or "").lower()
    task_text = task or ""
    if any(word in lowered for word in _EXPLICIT_WRITE_INTENT_WORDS):
        return True
    if any(pattern.search(task_text) for pattern in _WRITE_INTENT_PATTERNS):
        return True
    if any(pattern.search(task_text) for pattern in _IMPERATIVE_WRITE_PATTERNS):
        return True
    markers = semantic_markers(task_text)
    if (
        markers.get("docx_write_phrase")
        or markers.get("docx_create_phrase")
        or markers.get("ppt_slide_write_request")
        or markers.get("ppt_design_request")
        or markers.get("docx_template_fill_request")
        or markers.get("docx_pdf_export_request")
        or markers.get("file_format_convert_request")
        or markers.get("spreadsheet_write_request")
        or markers.get("text_selection_replace_request")
        or markers.get("file_copy_request")
        or markers.get("cross_file_extract_request")
    ):
        return True
    return bool(
        re.search(
            r"(?:加入|添加|插入|放入|写入).{0,18}(?:docx|word|文档|pptx?|幻灯片|slides?)",
            task_text,
            re.IGNORECASE,
        )
    )


def has_explicit_write_intent(task: str) -> bool:
    if is_readonly_existing_artifact_followup(task):
        return False
    if has_readonly_write_negation(task):
        return False
    lowered = (task or "").lower()
    task_text = task or ""
    if any(word in lowered for word in _EXPLICIT_WRITE_INTENT_WORDS):
        return True
    if any(pattern.search(task_text) for pattern in _WRITE_INTENT_PATTERNS):
        return True
    if any(pattern.search(task_text) for pattern in _IMPERATIVE_WRITE_PATTERNS):
        return True
    has_soft_action = any(word in lowered for word in _SOFT_WRITE_ACTION_WORDS)
    has_target_hint = any(word in lowered for word in _WRITE_TARGET_HINT_WORDS)
    if has_soft_action and has_target_hint:
        return True
    markers = semantic_markers(task_text)
    if (
        markers.get("docx_write_phrase")
        or markers.get("docx_create_phrase")
        or markers.get("ppt_design_request")
        or markers.get("docx_template_fill_request")
        or markers.get("docx_pdf_export_request")
        or markers.get("file_format_convert_request")
        or markers.get("spreadsheet_write_request")
        or markers.get("text_selection_replace_request")
        or markers.get("file_copy_request")
        or markers.get("cross_file_extract_request")
    ):
        return True
    return any(word in lowered for word in _WRITE_INTENT_WORDS)


def has_readonly_write_negation(task: str) -> bool:
    task_text = str(task or "").strip()
    if not task_text:
        return False
    if (
        has_artifact_creation_intent(task_text)
        and has_source_scoped_write_negation(task_text)
        and not has_global_readonly_write_negation(task_text)
    ):
        return False
    if _has_disjoint_target_write_and_path_protection(task_text):
        return False
    if has_global_readonly_write_negation(task_text):
        return True
    return any(pattern.search(task_text) for pattern in _READONLY_WRITE_NEGATION_PATTERNS)


def has_global_readonly_write_negation(task: str) -> bool:
    task_text = str(task or "").strip()
    if not task_text:
        return False
    return any(
        pattern.search(task_text)
        for pattern in _GLOBAL_READONLY_WRITE_NEGATION_PATTERNS
    )


def has_source_scoped_write_negation(task: str) -> bool:
    task_text = str(task or "").strip()
    if not task_text:
        return False
    return any(
        pattern.search(task_text)
        for pattern in _SOURCE_SCOPED_WRITE_NEGATION_PATTERNS
    )


def has_artifact_creation_intent(task: str) -> bool:
    task_text = str(task or "").strip()
    if not task_text:
        return False
    if is_readonly_existing_artifact_followup(task_text):
        return False
    if any(pattern.search(task_text) for pattern in _ARTIFACT_CREATION_INTENT_PATTERNS):
        return True
    markers = semantic_markers(task_text)
    return bool(
        markers.get("docx_create_phrase")
        or markers.get("ppt_slide_write_request")
        or markers.get("ppt_design_request")
        or markers.get("docx_template_fill_request")
        or markers.get("docx_pdf_export_request")
        or markers.get("file_format_convert_request")
        or markers.get("spreadsheet_write_request")
        or markers.get("text_selection_replace_request")
        or markers.get("file_copy_request")
        or markers.get("cross_file_extract_request")
    )


def is_readonly_existing_artifact_followup(task: str) -> bool:
    task_text = str(task or "").strip()
    if not task_text:
        return False
    if not _PAST_ARTIFACT_REFERENCE_PATTERN.search(task_text):
        return False
    if not _READONLY_FOLLOWUP_VERB_PATTERN.search(task_text):
        return False
    if re.search(
        r"(?:保存为|另存为|输出到|写入到|写入|创建|新建|导出到|save as|export to|write to|create)",
        task_text,
        re.IGNORECASE,
    ):
        return False
    return True


def is_advisory_analysis_request(task: str) -> bool:
    task_text = str(task or "").strip()
    if not task_text:
        return False
    lowered = task_text.lower()
    if any(pattern.search(task_text) for pattern in _ANALYSIS_ADVICE_PATTERNS):
        return True
    has_analysis_cue = any(word in lowered for word in _ANALYSIS_CUE_WORDS)
    has_advice_cue = any(word in lowered for word in _ADVICE_CUE_WORDS)
    return (
        has_analysis_cue
        and has_advice_cue
        and not has_explicit_write_intent(task_text)
    )


def is_diagnostic_request(task: str) -> bool:
    task_text = str(task or "").strip()
    if not task_text:
        return False
    if any(pattern.search(task_text) for pattern in _DIAGNOSTIC_NEW_TASK_PATTERNS):
        return False
    return any(pattern.search(task_text) for pattern in _DIAGNOSTIC_REQUEST_PATTERNS)


def explicit_output_mode(request: FileTaskRequest) -> str:
    options = request.options if isinstance(request.options, dict) else {}
    normalized = str(options.get("output_mode") or "").strip().lower()
    if normalized in {"answer", "write", "hybrid"}:
        return normalized
    return ""


def has_target_context(request: FileTaskRequest, files: List[FileTaskFile]) -> bool:
    if str(request.target_path or "").strip():
        return True
    if request.current_file is not None:
        return True
    return any(bool(file_info and file_info.target) for file_info in files)


def infer_output_mode(
    request: FileTaskRequest,
    files: List[FileTaskFile],
    *,
    write_intent: bool,
    diagnostic_request: bool,
    docx_annotation_request: bool,
    advisory_analysis_request: bool,
) -> str:
    explicit_mode = explicit_output_mode(request)
    if explicit_mode:
        if explicit_mode == "answer" and not diagnostic_request and write_intent:
            return "write"
        return explicit_mode
    if diagnostic_request:
        return "answer"
    if write_intent or docx_annotation_request:
        return "write"
    if advisory_analysis_request and has_target_context(request, files):
        return "hybrid"
    return "answer"


def quick_action_mode(request: FileTaskRequest) -> str:
    options = request.options if isinstance(request.options, dict) else {}
    return str(options.get("quick_action_mode") or "").strip().lower()


def _has_disjoint_target_write_and_path_protection(task: str) -> bool:
    write_paths = _target_write_paths(task)
    protected_paths = _protected_paths(task)
    if not write_paths or not protected_paths:
        return False
    return write_paths.isdisjoint(protected_paths)


def _target_write_paths(task: str) -> set[str]:
    result: set[str] = set()
    for match in _TASK_TEXT_FILE_REFERENCE_PATTERN.finditer(task):
        raw_path = match.group("path").strip(" \t\r\n,，。；;、!?！？()（）[]【】\"'")
        start, end = match.span("path")
        before = task[max(0, start - 80) : start]
        after = task[end : min(len(task), end + 80)]
        near = f"{before}{after}"
        if _PATH_SCOPED_PROTECTION_PATTERN.search(before):
            continue
        if _TARGETED_FILE_WRITE_CONTEXT_PATTERN.search(near) or re.search(
            r"(?:同一个|当前|目标).{0,16}(?:docx|word|xlsx|excel|pptx|ppt|pdf|文档|表格|幻灯片|文件)",
            near,
            re.IGNORECASE,
        ):
            result.add(raw_path.replace("\\", "/").rstrip("/").casefold())
    return result


def _protected_paths(task: str) -> set[str]:
    result: set[str] = set()
    for match in _TASK_TEXT_FILE_REFERENCE_PATTERN.finditer(task):
        raw_path = match.group("path").strip(" \t\r\n,，。；;、!?！？()（）[]【】\"'")
        start, _ = match.span("path")
        before = task[max(0, start - 100) : start]
        if _PATH_SCOPED_PROTECTION_PATTERN.search(before):
            result.add(raw_path.replace("\\", "/").rstrip("/").casefold())
    return result
