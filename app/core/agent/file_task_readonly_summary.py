# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

from typing import Any, Callable, Dict, List

from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_runtime_utils import _compact_line, _json_payload
from app.core.agent.file_task_tool_catalog import stringify_result


DisplayPath = Callable[[Any], str]


def fallback_readonly_summary(
    *,
    request: FileTaskRequest,
    snippets: List[Dict[str, Any]],
    files: List[FileTaskFile],
    exc: Exception,
    display_path: DisplayPath,
) -> str:
    if not snippets:
        return ""

    lines = [
        "模型暂不可用，Koto 已先基于显式上下文整理可见内容（非模型推理）：",
    ]
    used_sources: set[str] = set()
    for index, snippet in enumerate(snippets[:5], start=1):
        source = str(
            snippet.get("source") or snippet.get("path") or f"上下文 {index}"
        ).strip()
        if not source and index <= len(files):
            source = files[index - 1].name or files[index - 1].path
        source_label = display_path(source) or f"上下文 {index}"
        preview = _compact_line(snippet.get("preview"), 320)
        if not preview:
            continue
        dedupe_key = f"{source_label}:{preview}"
        if dedupe_key in used_sources:
            continue
        used_sources.add(dedupe_key)
        lines.append(f"{index}. {source_label}：{preview}")

    if len(lines) == 1:
        return ""

    lines.append("恢复模型后可以继续生成更完整的总结、改写或写入文件。")
    lines.append(f"模型错误：{_compact_line(exc, 160)}")
    return "\n".join(lines)


def readonly_answer_required_message(
    *,
    request: FileTaskRequest,
    snippets: List[Dict[str, Any]],
    readonly_tool_outputs: List[Dict[str, Any]],
    display_path: DisplayPath,
) -> str:
    lines = [
        "你已经完成了只读文件读取，但还没有给用户可见答案。本轮必须直接输出分析结果，不要空回复。",
        f"用户任务：{request.task}",
        "要求：基于已读取内容给出结构化结论；如果信息不足，也要明确说明已读取到什么、缺什么、下一步怎么做。",
    ]
    source_lines = readonly_context_source_lines(
        snippets=snippets,
        readonly_tool_outputs=readonly_tool_outputs,
        display_path=display_path,
        limit=5,
    )
    if source_lines:
        lines.append("已读取内容摘录：")
        lines.extend(source_lines)
    return "\n".join(lines)


def readonly_context_source_lines(
    *,
    snippets: List[Dict[str, Any]],
    readonly_tool_outputs: List[Dict[str, Any]],
    display_path: DisplayPath,
    limit: int = 5,
) -> List[str]:
    lines: List[str] = []
    seen: set[str] = set()
    for item in readonly_tool_outputs:
        if not isinstance(item, dict):
            continue
        source = readonly_tool_source_label(item, display_path=display_path)
        for point in readonly_tool_points(item):
            text = _compact_line(point, 260)
            if not text:
                continue
            key = f"{source}:{text}"
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- {source}：{text}")
            if len(lines) >= limit:
                return lines
    for index, snippet in enumerate(snippets, start=1):
        if not isinstance(snippet, dict):
            continue
        source = str(
            snippet.get("source") or snippet.get("path") or f"上下文 {index}"
        ).strip()
        text = _compact_line(snippet.get("preview"), 260)
        if not text:
            continue
        key = f"{source}:{text}"
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {display_path(source) or source}：{text}")
        if len(lines) >= limit:
            break
    return lines


def readonly_context_summary(
    *,
    request: FileTaskRequest,
    snippets: List[Dict[str, Any]],
    readonly_tool_outputs: List[Dict[str, Any]],
    display_path: DisplayPath,
) -> str:
    source_lines = readonly_context_source_lines(
        snippets=snippets,
        readonly_tool_outputs=readonly_tool_outputs,
        display_path=display_path,
        limit=7,
    )
    if not source_lines:
        return ""
    lines = [
        "已完成文件读取，但模型没有返回进一步自然语言分析。以下是 Koto 基于已读取内容整理的可见结果：",
        f"任务：{request.task}",
        "已读取内容：",
        *source_lines,
        "结论：本轮为只读分析，没有写入或修改文件。可以继续追问，让模型基于上述内容做更深入的总结、风险识别或访谈提纲整理。",
    ]
    return "\n".join(lines)


def readonly_tool_source_label(
    item: Dict[str, Any],
    *,
    display_path: DisplayPath,
) -> str:
    args = item.get("args") if isinstance(item.get("args"), dict) else {}
    raw_path = str(
        args.get("path") or args.get("file_path") or item.get("path") or ""
    ).strip()
    if raw_path:
        return display_path(raw_path) or raw_path
    tool_name = str(item.get("tool_name") or "").strip()
    return tool_name or "读取结果"


def readonly_tool_points(item: Dict[str, Any]) -> List[str]:
    result = item.get("result")
    payload = result if isinstance(result, dict) else _json_payload(result)
    points: List[str] = []
    if isinstance(payload, dict):
        paragraphs = (
            payload.get("paragraphs")
            if isinstance(payload.get("paragraphs"), list)
            else []
        )
        tables = payload.get("tables") if isinstance(payload.get("tables"), list) else []
        total_paragraphs = payload.get("total_paragraphs")
        total_tables = payload.get("total_tables")
        if total_paragraphs is not None or total_tables is not None:
            points.append(
                f"Word 内容包含 {int(total_paragraphs or len(paragraphs) or 0)} 段文本、{int(total_tables or len(tables) or 0)} 个表格。"
            )
        for paragraph in paragraphs:
            if not isinstance(paragraph, dict):
                continue
            text = str(paragraph.get("text") or "").strip()
            if text:
                points.append(text)
            if len(points) >= 6:
                break
        if not points and payload.get("text"):
            points.append(str(payload.get("text") or ""))
    if not points:
        preview = str(item.get("preview") or "").strip()
        if preview:
            points.append(preview)
    if not points and result is not None:
        points.append(stringify_result(result))
    return points
