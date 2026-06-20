# -*- coding: utf-8 -*-
"""Stepwise PDF/DOCX helper functions extracted from file_task_runtime.py.

These stateless helpers detect stepwise task patterns and extract
window/page parameters from FileTaskRequest objects.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.agent.file_task_checkpoint_options import workflow_checkpoint_from_options
from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_recipes import request_file_types


def _workflow_resume_control(request: FileTaskRequest) -> Dict[str, Any]:
    options = request.options if isinstance(request.options, dict) else {}
    return workflow_checkpoint_from_options(options)


def file_task_suffix(file_info: FileTaskFile) -> str:
    explicit = str(getattr(file_info, "type", "") or "").strip().lower().lstrip(".")
    if explicit:
        return explicit
    candidate = str(
        getattr(file_info, "path", "") or getattr(file_info, "name", "") or ""
    )
    return Path(candidate).suffix.lower().lstrip(".")


def looks_like_windowed_pdf_task(
    request: FileTaskRequest, recipe_skeleton: Dict[str, Any]
) -> bool:
    recipe_id = str((recipe_skeleton or {}).get("recipe_id") or "").strip()
    if recipe_id == "long_pdf_stepwise_docx_summary":
        return True
    resume_control = _workflow_resume_control(request)
    text = "\n".join(
        part
        for part in (
            str(getattr(request, "task", "") or ""),
            str(resume_control.get("original_task") or ""),
        )
        if part
    )
    resume_source_path = str(resume_control.get("source_path") or "").strip().lower()
    if str(
        resume_control.get("policy") or ""
    ).strip().lower() == "confirm_each_step" and (
        "pdf" in request_file_types(request.files) or resume_source_path.endswith(".pdf")
    ):
        return True
    return bool(
        re.search(
            r"(?:分步|一步一步|每一步|继续|下一段|下一页|按页|分页|stepwise|chunk)",
            text,
            re.IGNORECASE,
        )
        and re.search(r"(?:pdf|长文|很长|大量内容)", text, re.IGNORECASE)
    )


def stepwise_docx_polish_window_paragraphs(request: FileTaskRequest) -> int:
    options = request.options if isinstance(request.options, dict) else {}
    resume_control = _workflow_resume_control(request)
    raw_value = (
        resume_control.get("window_paragraphs") or options.get("window_paragraphs") or 8
    )
    try:
        return max(1, min(int(raw_value), 24))
    except Exception:
        return 8


def stepwise_docx_polish_step_index(request: FileTaskRequest) -> int:
    resume_control = _workflow_resume_control(request)
    try:
        return max(0, int(resume_control.get("step_index") or 0))
    except Exception:
        return 0


def should_force_pdf_tool_read(
    request: FileTaskRequest,
    file_info: Optional[FileTaskFile] = None,
    recipe_skeleton: Optional[Dict[str, Any]] = None,
) -> bool:
    resume_control = _workflow_resume_control(request)
    should_force = (
        str(resume_control.get("policy") or "").strip().lower() == "confirm_each_step"
        or looks_like_windowed_pdf_task(request, recipe_skeleton or {})
    )
    if not should_force:
        return False
    if file_info is not None and file_task_suffix(file_info) != "pdf":
        return False
    return True


def pdf_context_read_args(
    request: FileTaskRequest,
    file_info: Optional[FileTaskFile] = None,
    recipe_skeleton: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    resume_control = _workflow_resume_control(request)
    window_pages = stepwise_pdf_window_pages(request)
    step_index = stepwise_pdf_step_index(request)
    start_page = step_index * window_pages + 1
    end_page = start_page + window_pages - 1
    source_path = str(
        resume_control.get("source_path")
        or getattr(file_info, "path", "")
        or ""
    ).strip()
    return {
        "window_pages": window_pages,
        "step_index": step_index,
        "start_page": start_page,
        "end_page": end_page,
        "path": source_path,
        "source_path": source_path,
    }


def stepwise_pdf_window_pages(request: FileTaskRequest) -> int:
    resume_control = _workflow_resume_control(request)
    try:
        return max(1, min(int(resume_control.get("window_pages") or 3), 20))
    except Exception:
        return 3


def stepwise_pdf_step_index(request: FileTaskRequest) -> int:
    resume_control = _workflow_resume_control(request)
    try:
        return max(0, int(resume_control.get("step_index") or 0))
    except Exception:
        return 0


def normalized_pdf_body(value: Any) -> str:
    text = re.sub(r"\[Page\s+\d+\]", " ", str(value or ""), flags=re.IGNORECASE)
    text = re.sub(r"\s+", "", text)
    return text.strip()


def pdf_text_quality(value: Any) -> Dict[str, Any]:
    body = normalized_pdf_body(value)
    if not body:
        return {
            "usable": False,
            "reason": "empty_pdf_text",
            "char_count": 0,
            "unique_chars": 0,
        }
    unique_chars = len(set(body))
    alpha_num = len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", body))
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", body))
    repeated_watermark = bool(
        re.fullmatch(r"(?:考参通海泰国供仅|仅供国泰海通参考|用使点原禾元供仅荐推苇一|-)+", body)
    )
    low_density = alpha_num < 80 or unique_chars < 18
    mostly_single_repeats = (
        cjk_chars >= 20
        and cjk_chars / max(alpha_num, 1) > 0.5
        and (unique_chars / max(len(body), 1)) < 0.08
    )
    usable = not repeated_watermark and not low_density and not mostly_single_repeats
    reason = ""
    if not usable:
        if repeated_watermark:
            reason = "watermark_only_pdf_text"
        elif low_density:
            reason = "low_density_pdf_text"
        else:
            reason = "repetitive_pdf_text"
    return {
        "usable": usable,
        "reason": reason,
        "char_count": len(body),
        "unique_chars": unique_chars,
        "alpha_num_chars": alpha_num,
        "cjk_chars": cjk_chars,
    }
