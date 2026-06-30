# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import re
from typing import Any, Dict, List

from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskRequest,
)
from app.core.agent.file_task_recipes import (
    request_file_types,
    request_target_file_type,
    semantic_markers,
)
from app.core.agent.file_task_tool_catalog import is_write_tool


def file_types(files: List[FileTaskFile]) -> set[str]:
    return request_file_types(files)


def looks_like_chart_request(task: str) -> bool:
    return semantic_markers(task).get("chart_request", False)


def looks_like_problem_analysis_request(task: str) -> bool:
    return semantic_markers(task).get("problem_analysis_request", False)


def looks_like_financial_request(task: str) -> bool:
    return semantic_markers(task).get("financial_request", False)


def looks_like_table_request(task: str) -> bool:
    return semantic_markers(task).get("table_request", False)


def looks_like_summary_request(task: str) -> bool:
    return semantic_markers(task).get("summary_request", False)


def looks_like_translation_request(task: str) -> bool:
    return semantic_markers(task).get("translation_request", False)


def looks_like_polish_request(task: str) -> bool:
    return semantic_markers(task).get("polish_request", False)


def looks_like_ppt_request(task: str, files: List[FileTaskFile]) -> bool:
    return semantic_markers(task, file_types=file_types(files)).get(
        "ppt_request", False
    )


def looks_like_ppt_slide_write_request(
    request: FileTaskRequest, files: List[FileTaskFile]
) -> bool:
    return semantic_markers(request.task, file_types=file_types(files)).get(
        "ppt_slide_write_request", False
    )


def looks_like_docx_report_request(
    request: FileTaskRequest, files: List[FileTaskFile]
) -> bool:
    return semantic_markers(
        request.task,
        file_types=file_types(files),
        target_file_type=request_target_file_type(request, files),
    ).get("docx_report_request", False)


def looks_like_financial_xlsx_docx_chart_report_task(
    request: FileTaskRequest, files: List[FileTaskFile]
) -> bool:
    return semantic_markers(
        request.task,
        file_types=file_types(files),
        target_file_type=request_target_file_type(request, files),
    ).get("financial_xlsx_docx_chart_report", False)


def looks_like_pdf_python_text_read(code: Any) -> bool:
    text = str(code or "").lower()
    if not text.strip():
        return False

    pdf_markers = (
        "pypdf2",
        "from pypdf import",
        "pdfreader",
        "pdfplumber",
        "pymupdf",
        "fitz",
        ".pdf",
        "pdf_path",
    )
    read_markers = (
        "extract_text(",
        "get_text(",
        "reader.pages",
        "page.get_text",
        "page.extract_text",
        "pdf.pages",
    )
    return any(marker in text for marker in pdf_markers) and any(
        marker in text for marker in read_markers
    )


def blocked_run_python_message(
    *,
    tool_name: str,
    tool_args: Dict[str, Any],
    request: FileTaskRequest,
    files: List[FileTaskFile],
) -> str:
    if tool_name != "run_python_code":
        return ""

    current_file_types = file_types(files)
    code = tool_args.get("code")
    if "pdf" not in current_file_types and ".pdf" not in str(code or "").lower():
        return ""
    if not looks_like_pdf_python_text_read(code):
        return ""

    message = (
        "不要用 run_python_code 直接读取 PDF 文本。"
        "请改用 parse_file_to_text(path, max_chars, start_page, end_page)；"
        "长文或原文对照任务必须按页窗口分段读取。"
    )
    if "docx" in current_file_types:
        message += " 读取完 PDF 分段后，再用 read_docx_content 读取 DOCX 译稿。"
    if request.target_path:
        message += f" 当前目标文件是：{request.target_path}。"
    return message


def should_prompt_for_write_after_tool_round(
    *,
    request: FileTaskRequest,
    files: List[FileTaskFile],
    tool_calls: List[Dict[str, Any]],
    round_index: int,
) -> bool:
    if not tool_calls:
        return False
    if any(
        is_write_tool(str(call.get("name") or ""))
        and str(call.get("name") or "") != "run_python_code"
        for call in tool_calls
    ):
        return False
    if looks_like_financial_xlsx_docx_chart_report_task(request, files):
        return True
    return round_index >= 2


def write_retry_message(request: FileTaskRequest, files: List[FileTaskFile]) -> str:
    target = request.target_path or next(
        (file_info.path for file_info in files if file_info.target and file_info.path),
        "",
    )
    current_file_types = file_types(files)
    task_text = str(request.task or "")
    hint = (
        "你还没有完成真实文件写入。不要只总结或结束，下一轮必须调用会修改文件的工具。"
    )
    if looks_like_financial_xlsx_docx_chart_report_task(request, files):
        hint += (
            " 当前是 Excel 财务预测图表+问题写入 DOCX 任务：不要只插入 Excel 原表，也不要只输出 Python stdout。"
            " 先用 run_python_code 生成真实 PNG/JPG 图表并输出 KOTO_CREATED 路径；"
            "再调用 write_docx_content 写入问题清单/分析结论；"
            "最后调用 insert_image_into_docx 把生成的真实图片插入目标 DOCX。"
            " 解析 P&L 时不要依赖 pandas 默认列名；如果列名是 Unnamed，应扫描每一行找到 2025E/2026E/2027E/2028E 等年份头，再按这些列抽取收入、毛利、费用、净利润等指标。"
        )
    elif "xlsx" in current_file_types and "docx" in current_file_types:
        hint += " 对于把 Excel 加入 Word，优先调用 insert_excel_as_docx_table；如果已经读到真实工作表名，就用真实 sheet 写入目标 docx。"
    if "docx" in current_file_types and re.search(
        r"(?:图表|可视化|绘图|画图|画.{0,4}图|图片|chart|plot|graph|image)",
        task_text,
        re.IGNORECASE,
    ):
        hint += " 如果用户要求把图表或图片加入 DOCX，先用 run_python_code 生成真实 PNG/JPG 文件，再调用 insert_image_into_docx；不要用 write_docx_content 把图片描述文字写进文档代替真实插图。"
    if {"txt", "md", "csv", "json", "py", "js", "html", "css"}.intersection(
        current_file_types
    ):
        hint += " 对于 TXT/MD/CSV/JSON 或代码文本文件，如果用户提供了选区并要求润色/改写/替换后写回，优先调用 replace_file_selection，用 original_selection=用户选区原文、new_content=改写结果；不要为了单个选区改写去 run_python_code 整文件覆写。没有选区时，先用 read_file_range 或 parse_file_to_text 读取必要内容，再选择 replace_file_selection 或 run_python_code 写回；如果只是批注/审校可用 annotate_file。不要只输出润色后的文本而不落盘。"
    if "pdf" in current_file_types:
        hint += " 读取 PDF 原文必须调用 parse_file_to_text；长文必须用 start_page/end_page 分段读取，不要用 run_python_code、PyPDF2、pdfplumber 或 fitz 直接解析 PDF。"
    if "pdf" in current_file_types and "docx" in current_file_types:
        hint += " 对于 PDF 原文和 DOCX 译稿对照任务，先分页读取 PDF，再读取 DOCX；不要试图一次性抽取整本 PDF。"
    if "pptx" in current_file_types:
        hint += " 对于 PPT，读取内容优先用 parse_file_to_text；如果要整体风格、主题、版式、美化或配色，调用 design_pptx_theme_layout；如果要新增总结页，调用 add_pptx_slides；如果是改现有页文本，用 write_pptx_slides。不要对 PPTX 调用 read_docx_content。"
    if target:
        hint += f" 当前目标文件是：{target}。"
    return hint


def duplicate_supervisor_retry_message(
    *,
    request: FileTaskRequest,
    files: List[FileTaskFile],
    classification: FileTaskClassification,
    intent_plan: FileTaskIntentPlan,
    tool_calls: List[Dict[str, Any]],
) -> str:
    repeated_tools = (
        ", ".join(
            str(call.get("name") or "").strip()
            for call in tool_calls
            if str(call.get("name") or "").strip()
        )
        or "上一轮工具"
    )
    lines = [
        "监管层检测到你正在重复上一轮相同工具调用，但当前任务仍未产生任何 file.changed。",
        f"重复工具：{repeated_tools}",
        "不要继续重复读取同一批内容；下一轮必须回到计划主线，改变工具参数或推进到写入/生成/插入步骤。",
    ]
    selected_recipe = str(classification.selected_recipe or "").strip()
    if selected_recipe:
        lines.append(f"当前任务路线：{selected_recipe}")
    if intent_plan.dynamic_steps:
        lines.append("计划账本：")
        for index, step in enumerate(intent_plan.dynamic_steps[:8], start=1):
            if not isinstance(step, dict):
                continue
            title = str(step.get("title") or step.get("id") or f"步骤 {index}").strip()
            description = str(step.get("description") or "").strip()
            if title:
                lines.append(
                    f"{index}. {title}" + (f"：{description}" if description else "")
                )
    current_file_types = file_types(files)
    if "pdf" in current_file_types:
        lines.append(
            "PDF 长文任务：如已读取当前页窗，下一轮要么换 start_page/end_page 读取下一段，要么把当前步骤要点写入目标 DOCX；不要再次读取同一页窗。"
        )
    if (
        "docx" in current_file_types
        or "docx" in str(request.task or "").lower()
        or "word" in str(request.task or "").lower()
    ):
        lines.append(
            "DOCX 输出任务：必须调用 write_docx_content 写入本步骤发现；如果没有明确目标路径，就在源文件同目录创建清晰命名的 DOCX 输出文件。"
        )
    if "xlsx" in current_file_types:
        lines.append(
            "Excel 任务：如果已完成结构读取，下一轮必须进入真实分析/制图/写回，不要重复打印同一张表。"
        )
    target = request.target_path or next(
        (file_info.path for file_info in files if file_info.target and file_info.path),
        "",
    )
    if target:
        lines.append(f"目标文件：{target}")
    lines.append("只有在本轮已经产生真实文件变更，或任务确实是只读答复时，才允许结束。")
    return "\n".join(lines)
