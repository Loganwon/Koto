# -*- coding: utf-8 -*-
"""Stepwise PDF/DOCX helper functions extracted from file_task_runtime.py.

These stateless helpers detect stepwise task patterns and extract
window/page parameters from FileTaskRequest objects.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.agent.file_task_runtime_utils import _compact_line
from app.core.agent.file_task_runtime_utils import workflow_checkpoint_from_options
from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_recipes import request_file_types


def _workflow_resume_control(request: FileTaskRequest) -> Dict[str, Any]:
    options = request.options if isinstance(request.options, dict) else {}
    return workflow_checkpoint_from_options(options)


def file_task_suffix(file_info: FileTaskFile) -> str:
    from app.core.agent.file_task_recipes import file_type_from_file_info

    return file_type_from_file_info(file_info)


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
        "pdf" in request_file_types(request.files)
        or resume_source_path.endswith(".pdf")
    ):
        return True
    if explicit_pdf_page_window(request) and (
        "pdf" in request_file_types(request.files)
        or resume_source_path.endswith(".pdf")
    ):
        return True
    if explicit_pdf_letter_window(request) and (
        "pdf" in request_file_types(request.files)
        or resume_source_path.endswith(".pdf")
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


_ROMAN_VALUES = {
    "I": 1,
    "V": 5,
    "X": 10,
    "L": 50,
    "C": 100,
    "D": 500,
    "M": 1000,
}
_CHINESE_DIGITS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _roman_to_int(value: str) -> int:
    total = 0
    prev = 0
    for char in reversed(str(value or "").upper()):
        current = _ROMAN_VALUES.get(char, 0)
        if current < prev:
            total -= current
        else:
            total += current
            prev = current
    return total


def _chinese_letter_to_int(value: str) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    if text == "十":
        return 10
    if text.startswith("十"):
        return 10 + _CHINESE_DIGITS.get(text[1:], 0)
    if "十" in text:
        head, tail = text.split("十", 1)
        return _CHINESE_DIGITS.get(head, 0) * 10 + _CHINESE_DIGITS.get(tail, 0)
    return _CHINESE_DIGITS.get(text, 0)


def _request_text_for_window_detection(request: FileTaskRequest) -> str:
    resume_control = _workflow_resume_control(request)
    texts = [
        str(getattr(request, "task", "") or ""),
        str(resume_control.get("current_task") or ""),
    ]
    # Keep original_task last so a resumed concrete instruction wins.
    texts.append(str(resume_control.get("original_task") or ""))
    return "\n".join(item for item in texts if item).strip()


def explicit_pdf_letter_window(request: FileTaskRequest) -> Optional[Dict[str, int]]:
    """Extract a Schiller-style letter/chapter window such as XI-XV."""
    source = _request_text_for_window_detection(request)
    if not source:
        return None

    roman = re.search(
        r"第\s*([IVXLCDM]+)\s*(?:[-－—–~至到]\s*([IVXLCDM]+))?\s*封(?:信)?",
        source,
        re.IGNORECASE,
    )
    if not roman:
        roman = re.search(
            r"\bletters?\s+([IVXLCDM]+)\s*(?:[-－—–~至to]+\s*([IVXLCDM]+))?\b",
            source,
            re.IGNORECASE,
        )
    if roman:
        start = _roman_to_int(roman.group(1))
        end = _roman_to_int(roman.group(2) or roman.group(1))
    else:
        arabic = re.search(
            r"第\s*(\d{1,2})\s*(?:[-－—–~至到]\s*(\d{1,2}))?\s*封(?:信)?",
            source,
            re.IGNORECASE,
        )
        if arabic:
            start = int(arabic.group(1))
            end = int(arabic.group(2) or arabic.group(1))
        else:
            chinese = re.search(
                r"第\s*([一二三四五六七八九十]{1,3})\s*(?:[-－—–~至到]\s*([一二三四五六七八九十]{1,3}))?\s*封(?:信)?",
                source,
                re.IGNORECASE,
            )
            if not chinese:
                return None
            start = _chinese_letter_to_int(chinese.group(1))
            end = _chinese_letter_to_int(chinese.group(2) or chinese.group(1))
    if start <= 0 or end <= 0:
        return None
    if end < start:
        start, end = end, start
    if end - start > 20:
        end = start + 20
    return {"start": start, "end": end}


def explicit_pdf_page_window(request: FileTaskRequest) -> Optional[Dict[str, int]]:
    """Extract an explicit PDF page window from the user task text.

    This covers research/read-only tasks like "OpenSpace PDF 第 19-21 页",
    which are not stepwise workflows but still require path-based PDF reading
    instead of trusting the frontend's short attachment preview.
    """
    source = _request_text_for_window_detection(request)
    if not source:
        return None

    patterns = (
        r"第\s*(\d{1,4})\s*(?:[-－—–~至到]\s*(\d{1,4}))?\s*页",
        r"\bpages?\s*(\d{1,4})\s*(?:[-－—–~至to]+\s*(\d{1,4}))?\b",
        r"\bp\.?\s*(\d{1,4})\s*(?:[-－—–~至to]+\s*(\d{1,4}))?\b",
    )
    for pattern in patterns:
        match = re.search(pattern, source, re.IGNORECASE)
        if not match:
            continue
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if start <= 0 or end <= 0:
            continue
        if end < start:
            start, end = end, start
        # Avoid accidentally reading a huge document when the wording is broad.
        if end - start > 49:
            end = start + 49
        return {"start": start, "end": end}
    return None


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
        or bool(explicit_pdf_letter_window(request))
        or bool(explicit_pdf_page_window(request))
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
    explicit_letter_window = explicit_pdf_letter_window(request)
    if explicit_letter_window:
        start_page = int(explicit_letter_window["start"])
        end_page = int(explicit_letter_window["end"])
        window_pages = max(1, end_page - start_page + 1)
        step_index = 0
        window_unit = "pdf_letter"
    elif explicit_window := explicit_pdf_page_window(request):
        window_unit = ""
        start_page = int(explicit_window["start"])
        end_page = int(explicit_window["end"])
        window_pages = max(1, end_page - start_page + 1)
        step_index = 0
    else:
        window_unit = ""
        window_pages = stepwise_pdf_window_pages(request)
        step_index = stepwise_pdf_step_index(request)
        start_page = step_index * window_pages + 1
        end_page = start_page + window_pages - 1
    source_path = str(
        resume_control.get("source_path") or getattr(file_info, "path", "") or ""
    ).strip()
    return {
        "window_pages": window_pages,
        "step_index": step_index,
        "start_page": start_page,
        "end_page": end_page,
        "path": source_path,
        "source_path": source_path,
        **(
            {"window_unit": window_unit, "start": start_page, "end": end_page}
            if window_unit
            else {}
        ),
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


def stepwise_docx_target_path(
    request: FileTaskRequest, files: list[FileTaskFile]
) -> str:
    raw_target = str(request.target_path or "").strip()
    if raw_target:
        return (
            raw_target if os.path.isabs(raw_target) else str(Path(raw_target).resolve())
        )
    docx_file = next(
        (
            file_info
            for file_info in files
            if file_task_suffix(file_info) == "docx" and file_info.target
        ),
        None,
    ) or next(
        (file_info for file_info in files if file_task_suffix(file_info) == "docx"),
        None,
    )
    if docx_file and docx_file.path:
        return docx_file.path
    pdf_file = next(
        (file_info for file_info in files if file_task_suffix(file_info) == "pdf"),
        None,
    )
    if pdf_file and pdf_file.path:
        pdf_path = Path(pdf_file.path)
        return str(pdf_path.with_name(f"{pdf_path.stem}_分步总结.docx"))
    return ""


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
        re.fullmatch(
            r"(?:考参通海泰国供仅|仅供国泰海通参考|用使点原禾元供仅荐推苇一|-)+", body
        )
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


def native_stepwise_pdf_text_quality_guard_payload(reason_text: str) -> Dict[str, Any]:
    return {
        "tool_name": "supervisor_guard",
        "success": False,
        "blocked": True,
        "native_stepwise": True,
        "result_preview": (
            "监管层阻止写入：当前 PDF 页窗文本质量不足"
            f"（{reason_text or 'low_quality_pdf_text'}），不能据此生成分步 DOCX 摘要。"
        ),
    }


def latest_pdf_snippet_quality(snippets: list[dict[str, Any]]) -> Dict[str, Any]:
    pdf_snippets = [
        item
        for item in snippets
        if isinstance(item, dict)
        and (
            str(item.get("source") or item.get("path") or "").lower().endswith(".pdf")
            or str(item.get("path") or "").lower().endswith(".pdf")
        )
    ]
    if not pdf_snippets:
        return {
            "usable": False,
            "reason": "missing_pdf_context",
            "char_count": 0,
            "unique_chars": 0,
        }
    text = str(
        pdf_snippets[-1].get("_raw_text") or pdf_snippets[-1].get("preview") or ""
    )
    return pdf_text_quality(text)


def tool_args_docx_paragraph_text(tool_args: dict[str, Any]) -> str:
    raw_paragraphs = tool_args.get("paragraphs")
    items: Any = []
    if isinstance(raw_paragraphs, str) and raw_paragraphs.strip():
        try:
            items = json.loads(raw_paragraphs)
        except Exception:
            items = []
    elif isinstance(raw_paragraphs, list):
        items = raw_paragraphs
    texts: list[str] = []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                texts.append(str(item.get("text") or ""))
            elif item is not None:
                texts.append(str(item))
    content = str(tool_args.get("content") or "").strip()
    if content:
        texts.append(content)
    return "\n".join(text for text in texts if text.strip())


def stepwise_docx_content_quality_block_message(
    snippets: list[dict[str, Any]], text: str
) -> str:
    latest_pdf_snippet = next(
        (
            item
            for item in reversed(snippets or [])
            if isinstance(item, dict)
            and (
                str(item.get("source") or item.get("path") or "")
                .lower()
                .endswith(".pdf")
                or str(item.get("path") or "").lower().endswith(".pdf")
            )
        ),
        {},
    )
    expected_start = int(latest_pdf_snippet.get("start_page") or 0)
    expected_end = int(latest_pdf_snippet.get("end_page") or 0)
    expected_range = (
        (expected_start, expected_end) if expected_start and expected_end else None
    )
    body = str(text or "").strip()
    if not body:
        return "监管层阻止写入：当前分步 DOCX 正文为空。请写入当前页窗的摘要、关键发现、结构/内容线索和来源页码。"
    if re.search(r"(^|\s)(?:\*\*[^*\n]+\*\*|__[^_\n]+__|[-*_]{3,})(\s|$)", body):
        return (
            "监管层阻止写入：分步 DOCX 正文不能包含 Markdown 标记（如 **加粗**、---）。"
            " 请用 Word 段落样式和纯文本标签写入。"
        )

    combined_label_patterns = (
        r"文档识别\s*/\s*核心要点",
        r"段落主题\s*/\s*关键发现",
        r"内容线索\s*/\s*案例线索",
    )
    if any(re.search(pattern, body) for pattern in combined_label_patterns):
        return (
            "监管层阻止写入：分步 DOCX 正文不能使用“文档识别/核心要点”这类合并标签。"
            " 请改用固定独立标签：文档识别、段落主题、结构线索、内容线索、来源页码。"
        )

    section_ranges: list[tuple[int, int]] = []
    declared_page_ranges: list[tuple[int, int]] = []
    for line in body.splitlines():
        match = re.match(
            r"^\s*【?\s*第\s*(\d+)\s*[-－—~至]\s*(\d+)\s*页[^。\n]{0,40}(?:】|[:：])",
            line,
        )
        if match:
            section_ranges.append((int(match.group(1)), int(match.group(2))))
        if re.search(r"(?:当前页窗摘要|来源页码)", line):
            for range_match in re.finditer(
                r"第\s*(\d+)\s*[-－—~至]\s*(\d+)\s*页",
                line,
            ):
                declared_page_ranges.append(
                    (int(range_match.group(1)), int(range_match.group(2)))
                )
    unique_section_ranges = list(dict.fromkeys(section_ranges))
    unique_declared_ranges = list(dict.fromkeys(declared_page_ranges))
    if len(unique_section_ranges) > 1:
        ranges = "、".join(
            f"第 {start}-{end} 页" for start, end in unique_section_ranges[:4]
        )
        return (
            "监管层阻止写入：单个分步窗口的 DOCX 正文不能同时覆盖多个页窗标题。"
            f" 检测到：{ranges}。请只写当前页窗内容，上一页窗内容不要重复写入。"
        )
    if section_ranges and section_ranges.count(section_ranges[0]) > 1:
        start, end = section_ranges[0]
        return (
            f"监管层阻止写入：第 {start}-{end} 页在本次写入中出现了重复小节标题。"
            " 请合并为一个小节，删除重复标题和重复要点。"
        )
    if (
        expected_range
        and unique_section_ranges
        and unique_section_ranges[0] != expected_range
    ):
        expected_label = f"第 {expected_start}-{expected_end} 页"
        actual_start, actual_end = unique_section_ranges[0]
        return (
            "监管层阻止写入：DOCX 小节页码与当前读取窗口不一致。"
            f" 当前窗口应为 {expected_label}，但正文标题写成第 {actual_start}-{actual_end} 页。"
        )
    if expected_range and unique_declared_ranges:
        mismatched = [item for item in unique_declared_ranges if item != expected_range]
        if mismatched:
            expected_label = f"第 {expected_start}-{expected_end} 页"
            actual_start, actual_end = mismatched[0]
            return (
                "监管层阻止写入：DOCX 页窗标签与当前读取窗口不一致。"
                f" 当前窗口应为 {expected_label}，但正文写成第 {actual_start}-{actual_end} 页。"
            )

    normalized_blocks: list[str] = []
    for line in body.splitlines():
        cleaned = re.sub(r"\s+", "", line)
        cleaned = re.sub(r"^[\-*•\d.、（）()]+", "", cleaned)
        if len(cleaned) >= 16:
            normalized_blocks.append(cleaned.lower())
    seen_blocks: set[str] = set()
    repeated_blocks: list[str] = []
    for block in normalized_blocks:
        if block in seen_blocks:
            repeated_blocks.append(block)
        seen_blocks.add(block)
    if repeated_blocks:
        return "监管层阻止写入：当前分步 DOCX 正文存在重复段落。请去重后再写入。"

    label_hits = sum(
        1
        for label in ("文档识别", "段落主题", "结构线索", "内容线索", "来源页码")
        if label in body
    )
    if label_hits < 4:
        return (
            "监管层阻止写入：当前分步摘要缺少稳定结构。"
            " 请按“当前页窗摘要 / 文档识别 / 段落主题 / 结构线索 / 内容线索 / 来源页码”重写。"
        )
    return ""


def stepwise_docx_write_block_message(
    *,
    request: FileTaskRequest,
    snippets: list[dict[str, Any]],
    recipe_skeleton: Dict[str, Any],
    tool_name: str,
    tool_args: dict[str, Any],
) -> str:
    if not looks_like_windowed_pdf_task(request, recipe_skeleton):
        return ""
    if tool_name == "create_file":
        target = str(tool_args.get("path") or "").strip().lower()
        if not target.endswith(".docx"):
            return ""
    elif tool_name != "write_docx_content":
        return ""
    quality = latest_pdf_snippet_quality(snippets)
    if not quality.get("usable"):
        return (
            "监管层阻止写入：当前 PDF 页窗的可提取文本质量不足，不能把水印、乱码或空内容写成总结。"
            f" 质量原因：{quality.get('reason') or 'unknown'}；"
            f"可用字符数：{quality.get('alpha_num_chars') or quality.get('char_count') or 0}；"
            f"唯一字符数：{quality.get('unique_chars') or 0}。"
            " 下一轮请改用新的 start_page/end_page 读取后续页窗；如果连续页窗仍不可读，应停止写入并提示需要 OCR/视觉解析。"
        )

    text = tool_args_docx_paragraph_text(tool_args)
    if tool_name != "create_file" and re.search(r"^\s*#{1,6}\s+", text, re.MULTILINE):
        return (
            "监管层阻止写入：write_docx_content 的 paragraphs 不能包含 Markdown 标题符号 #。"
            " 请使用 paragraph.style='Heading 1' 这类 Word 段落样式。"
        )
    progress_patterns = (
        r"^\s*步骤\s*\d+\s*[：:]",
        r"当前进度\s*[：:]",
        r"下一步(?:计划|继续|处理)",
        r"等待(?:用户|我|确认|继续)",
        r"请回复\s*[\"“]?继续",
        r"当前步骤已(?:成功)?(?:完成|写入)",
        r"状态\s*[：:]",
        r"file\.changed",
        r"目标\s*DOCX\s*文件已成功更新",
    )
    if any(
        re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        for pattern in progress_patterns
    ):
        return (
            "监管层阻止写入：DOCX 正文不能包含任务进度、等待确认、下一步计划或 file.changed 这类前端提示。"
            " 请重写 paragraphs：只写当前页窗的实质内容摘要、关键发现、证据/主题；"
            "页码只可作为“来源页码：第 x-y 页”这样的简短来源说明，不要写等待继续或下一步计划。"
        )
    return stepwise_docx_content_quality_block_message(snippets, text)


def stepwise_docx_wait_artifact(
    *,
    request: FileTaskRequest,
    files: list[FileTaskFile],
    snippets: list[dict[str, Any]],
    file_changes: list[dict[str, Any]],
    recipe_skeleton: Dict[str, Any],
    target_path_fallback: str = "",
) -> Optional[Dict[str, Any]]:
    if not looks_like_windowed_pdf_task(request, recipe_skeleton):
        return None
    docx_change = next(
        (
            change
            for change in file_changes
            if str(change.get("operation") or "") == "write_docx_content"
            and str(change.get("path") or change.get("file_path") or "")
            .lower()
            .endswith(".docx")
        ),
        None,
    )
    if not docx_change:
        return None
    target_path = str(
        docx_change.get("path")
        or docx_change.get("file_path")
        or request.target_path
        or target_path_fallback
        or ""
    ).strip()
    pdf_file = next(
        (file_info for file_info in files if file_task_suffix(file_info) == "pdf"), None
    )
    latest_pdf_snippet = next(
        (
            item
            for item in reversed(snippets or [])
            if isinstance(item, dict)
            and (
                str(item.get("source") or item.get("path") or "")
                .lower()
                .endswith(".pdf")
                or str(item.get("path") or "").lower().endswith(".pdf")
            )
        ),
        {},
    )
    window_pages = stepwise_pdf_window_pages(request)
    current_step_index = stepwise_pdf_step_index(request)
    current_start = int(
        latest_pdf_snippet.get("start_page") or (1 + current_step_index * window_pages)
    )
    current_end = int(
        latest_pdf_snippet.get("end_page") or (current_start + window_pages - 1)
    )
    next_step_index = current_step_index + 1
    next_start = current_end + 1
    next_end = next_start + window_pages - 1

    resume_files = [
        file_info.public_dict()
        for file_info in files
        if file_info and (file_info.path or file_info.name)
    ]
    for item in resume_files:
        if target_path and str(item.get("path") or "") == target_path:
            item["target"] = True
    original_task = (
        str(_workflow_resume_control(request).get("original_task") or "").strip()
        or str(request.task or "").strip()
    )
    resume_request = {
        "task": f"继续当前分步文件任务的下一步：处理 PDF 第 {next_start}-{next_end} 页，并把本段实质分析追加到同一个 DOCX。",
        "session_id": request.session_id,
        "model_mode": request.model_mode,
        "model_id": request.model_id,
        "target_path": target_path,
        "files": resume_files,
        "options": {
            "workflow_checkpoint": {
                "adapter": "generic_tool_loop",
                "policy": "confirm_each_step",
                "step_index": next_step_index,
                "window_pages": window_pages,
                "original_task": original_task,
                "source_path": pdf_file.path if pdf_file and pdf_file.path else "",
                "target_path": target_path,
            },
            "followup_context": {
                "kind": "stepwise_task_resume",
                "source": "koto_stepwise_resume_artifact",
                "followup_action": "resume",
                "stepwise": {
                    "policy": "confirm_each_step",
                    "completed_page_range": f"{current_start}-{current_end}",
                    "next_page_range": f"{next_start}-{next_end}",
                    "next_step_index": next_step_index,
                    "original_task": original_task,
                },
            },
        },
    }
    artifact: Dict[str, Any] = {
        "artifact_type": "koto_stepwise_resume_v1",
        "category": "stepwise_confirmation",
        "title": f"继续处理第 {next_start}-{next_end} 页",
        "summary": f"上一段（第 {current_start}-{current_end} 页）已写入 DOCX。可以继续处理第 {next_start}-{next_end} 页。",
        "suggested_next_step": f"点击继续处理第 {next_start}-{next_end} 页",
        "action_label": f"继续第 {next_start}-{next_end} 页",
        "route": "long_pdf_stepwise_docx_summary",
        "current_step_status": "written",
        "completed_page_range": f"{current_start}-{current_end}",
        "next_page_range": f"{next_start}-{next_end}",
        "next_start_page": next_start,
        "next_end_page": next_end,
        "next_step_index": next_step_index,
        "window_pages": window_pages,
        "original_task": original_task,
        "resume_request": resume_request,
    }
    if target_path:
        artifact["target_path"] = target_path
    if pdf_file and pdf_file.path:
        artifact["source_path"] = pdf_file.path
    return artifact


def _stepwise_pdf_body_lines(source_lines: list[str]) -> list[str]:
    def _is_running_header(line: str) -> bool:
        compact = re.sub(r"\s+", "", line)
        return bool(
            re.search(
                r"Annual Report on Digital Technology Application|Case Study in Chinese Museums",
                line,
                re.IGNORECASE,
            )
            or "中国博物馆数字技术应用及案例研究年度报告" in compact
            or re.fullmatch(r"(?:SUMMAR|ARTICLE|综|述|篇)", line, flags=re.IGNORECASE)
        )

    def _is_noise_line(line: str) -> bool:
        if not line or len(line) < 2:
            return True
        if line.isdigit() or re.fullmatch(r"\d+\s+\d+", line):
            return True
        if _is_running_header(line):
            return True
        return False

    blocks: list[str] = []
    buffer = ""

    def _flush() -> None:
        nonlocal buffer
        text = buffer.strip(" ；;，,")
        if len(text) >= 12:
            blocks.append(text)
        buffer = ""

    for line in source_lines:
        if _is_noise_line(line):
            _flush()
            continue
        if re.fullmatch(r"\d+\.\s+.+", line) and len(line) > 90:
            _flush()
            continue
        starts_new = bool(
            re.match(r"^[一二三四五六七八九十]+、", line)
            or re.match(r"^\d+[.、]\s*", line)
            or re.match(r"^《.+》", line)
            or re.match(r"^表\d+", line)
        )
        if starts_new:
            _flush()
            buffer = line
        elif buffer and len(buffer) + len(line) <= 260:
            separator = "" if re.search(r"[\u4e00-\u9fff]$", buffer) else " "
            buffer = f"{buffer}{separator}{line}"
        else:
            _flush()
            buffer = line
        if re.search(r"[。！？!?]$", line) or len(buffer) >= 220:
            _flush()
    _flush()

    deduped: list[str] = []
    seen_blocks: set[str] = set()
    for block in blocks:
        key = re.sub(r"\s+", "", block).lower()
        if key in seen_blocks:
            continue
        seen_blocks.add(key)
        deduped.append(block)
    return deduped


def stepwise_pdf_fallback_insights(preview: str) -> list[str]:
    cleaned = re.sub(r"\[Page\s+\d+\]", "\n", str(preview or ""), flags=re.IGNORECASE)
    raw_lines = [
        re.sub(r"\s+", " ", line).strip(" \t|-") for line in cleaned.splitlines()
    ]

    def _is_running_header(line: str) -> bool:
        compact = re.sub(r"\s+", "", line)
        return bool(
            re.search(
                r"Annual Report on Digital Technology Application|Case Study in Chinese Museums",
                line,
                re.IGNORECASE,
            )
            or "中国博物馆数字技术应用及案例研究年度报告" in compact
            or re.fullmatch(r"(?:SUMMAR|ARTICLE|综|述|篇)", line, flags=re.IGNORECASE)
        )

    def _is_noise_line(line: str) -> bool:
        if not line or len(line) < 2:
            return True
        if line.isdigit() or re.fullmatch(r"\d+\s+\d+", line):
            return True
        if _is_running_header(line):
            return True
        return False

    lines: list[str] = []
    seen: set[str] = set()
    for line in raw_lines:
        if _is_noise_line(line) or len(line) < 4:
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)
        if len(lines) >= 80:
            break

    annual_title = next(
        (
            line
            for line in raw_lines
            if line
            and (
                "Annual Report" in line
                or "年度报告" in line
                or "中国博物馆数字技术应用及案例研究年度报告"
                in re.sub(r"\s+", "", line)
            )
        ),
        "",
    )
    section_title = next(
        (
            line
            for line in lines
            if re.match(r"^[一二三四五六七八九十]+、", line)
            or line.startswith("关于")
            or re.match(r"^《.+》", line)
        ),
        "",
    )
    organizer = next(
        (
            line
            for line in lines
            if len(line) <= 120
            and not re.match(r"^\d+[.、]", line)
            and (
                re.search(
                    r"^(?:主\s*编|执行主编|副\s*主\s*编|专家顾问|编\s*辑|英文翻译|美术编辑)",
                    line,
                )
                or "委员会" in line
                or "中国博物馆协会资助项目" in line
                or re.search(r"中国博物馆协会.*(?:编|委员会)", line)
            )
        ),
        "",
    )
    editor_lines = [
        line
        for line in lines
        if re.search(r"(?:主\s*编|执行主编|副\s*主\s*编|专家顾问|编辑)", line)
    ][:3]
    toc_lines = [
        line
        for line in lines
        if len(line) <= 50
        and re.search(r"(?:目录|引言|综述篇|案例篇|参考文献|作者简介)", line)
    ][:4]
    body_blocks = _stepwise_pdf_body_lines(raw_lines)
    content_lines = [
        line
        for line in body_blocks
        if len(line) >= 18
        and line != annual_title
        and line != section_title
        and not (section_title and line.startswith(section_title))
        and line != organizer
        and line not in editor_lines
        and line not in toc_lines
        and not _is_running_header(line)
        and not re.search(
            r"^(?:主\s*编|执行主编|副\s*主\s*编|专家顾问|编\s*辑|英文翻译|美术编辑)",
            line,
        )
    ][:4]

    insights: list[str] = []
    if annual_title:
        insights.append(f"文档识别：当前页窗来自“{_compact_line(annual_title, 180)}”。")
    if section_title:
        insights.append(f"段落主题：{_compact_line(section_title, 180)}。")
    if organizer and organizer not in {annual_title, section_title}:
        insights.append(f"组织信息：{_compact_line(organizer, 180)}。")
    if editor_lines:
        insights.append(
            "编写线索："
            + "；".join(_compact_line(line, 120) for line in editor_lines)
            + "。"
        )
    if toc_lines:
        insights.append(
            "结构线索："
            + "；".join(_compact_line(line, 120) for line in toc_lines)
            + "。"
        )
    if content_lines:
        insights.append(
            "内容线索："
            + "；".join(_compact_line(line, 180) for line in content_lines)
            + "。"
        )
    if not insights:
        excerpt_lines = [_compact_line(line, 140) for line in lines[:4]]
        if excerpt_lines:
            insights.append(
                "当前页窗可读内容集中在：" + "；".join(excerpt_lines) + "。"
            )
    if not insights:
        insights.append("当前页窗未提取到足够正文，暂不能形成可靠内容摘要。")
    return insights


def stepwise_pdf_fallback_paragraphs(
    pdf_snippet: Dict[str, Any],
    exc: Exception,
) -> list[dict[str, str]]:
    del exc
    preview = str(
        pdf_snippet.get("_raw_text") or pdf_snippet.get("preview") or ""
    ).strip()
    pages = [int(match.group(1)) for match in re.finditer(r"\[Page\s+(\d+)\]", preview)]
    start_page = int(pdf_snippet.get("start_page") or 0)
    end_page = int(pdf_snippet.get("end_page") or 0)
    if start_page and end_page:
        page_range = (
            f"第 {start_page}-{end_page} 页"
            if start_page != end_page
            else f"第 {start_page} 页"
        )
    elif pages:
        page_range = (
            f"第 {min(pages)}-{max(pages)} 页"
            if min(pages) != max(pages)
            else f"第 {pages[0]} 页"
        )
    else:
        page_range = "当前页窗口"
    insights = stepwise_pdf_fallback_insights(preview)
    cleaned_preview = re.sub(r"\[Page\s+\d+\]", " ", preview, flags=re.IGNORECASE)
    cleaned_preview = re.sub(r"\s+", " ", cleaned_preview).strip(" ；;，,")

    def _field(label: str) -> str:
        prefix = f"{label}："
        for item in insights:
            text = str(item or "").strip()
            if text.startswith(prefix):
                return text[len(prefix) :].strip()
        return ""

    source_name = _compact_line(
        Path(
            str(pdf_snippet.get("source") or pdf_snippet.get("path") or "PDF 文档")
        ).stem,
        160,
    )
    document_value = _field("文档识别") or f"当前页窗来自“{source_name}”。"
    topic_value = _field("段落主题")
    structure_value = _field("结构线索")
    content_value = _field("内容线索")

    supplemental = [
        str(item or "").strip()
        for item in insights
        if item
        and not str(item).startswith(
            ("文档识别：", "段落主题：", "结构线索：", "内容线索：", "来源页码：")
        )
    ]
    if not topic_value:
        topic_seed = (
            content_value
            or (supplemental[0] if supplemental else "")
            or cleaned_preview
        )
        topic_value = (
            _compact_line(topic_seed, 180)
            or "当前页窗文本较短，主题需结合后续页窗继续确认。"
        )
    if not structure_value:
        structure_seed = "；".join(supplemental[:2])
        structure_value = (
            _compact_line(structure_seed, 220)
            if structure_seed
            else "当前页窗作为本步骤材料，记录可提取的结构与上下文线索，供后续页窗衔接。"
        )
    if not content_value:
        content_seed = (
            cleaned_preview or "当前页窗未提取到足够正文，暂不能形成可靠内容摘要。"
        )
        content_value = _compact_line(content_seed, 260)
    return [
        {"text": f"当前页窗摘要（{page_range}）", "style": "Heading 1"},
        {"text": f"文档识别：{document_value}"},
        {"text": f"段落主题：{topic_value}"},
        {"text": f"结构线索：{structure_value}"},
        {"text": f"内容线索：{content_value}"},
        {"text": f"来源页码：{page_range}"},
    ]
