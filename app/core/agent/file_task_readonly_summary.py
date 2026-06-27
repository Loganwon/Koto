# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import html
import re
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

    article_summary = _build_readonly_content_summary(
        request=request,
        snippets=snippets,
        readonly_tool_outputs=[],
        display_path=display_path,
        note=f"说明：模型暂不可用，本摘要由 Koto 基于已读取文本生成。模型错误：{_compact_line(exc, 160)}",
    )
    if article_summary:
        return article_summary

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
    summary = _build_readonly_content_summary(
        request=request,
        snippets=snippets,
        readonly_tool_outputs=readonly_tool_outputs,
        display_path=display_path,
        note="说明：本轮为只读总结，没有写入或修改文件；由于模型未返回完整自然语言答案，Koto 使用已读取文本生成这份摘要。",
    )
    if summary:
        return summary
    source_lines = readonly_context_source_lines(
        snippets=snippets,
        readonly_tool_outputs=readonly_tool_outputs,
        display_path=display_path,
        limit=7,
    )
    if not source_lines:
        return ""
    return "\n".join(
        [
            "## 文件内容总结",
            "",
            "已读取文件，但可用于归纳的正文较少。以下是可见内容：",
            *source_lines,
            "",
            "说明：本轮为只读总结，没有写入或修改文件。",
        ]
    )


def _build_readonly_content_summary(
    *,
    request: FileTaskRequest,
    snippets: List[Dict[str, Any]],
    readonly_tool_outputs: List[Dict[str, Any]],
    display_path: DisplayPath,
    note: str,
) -> str:
    sources = _readonly_source_names(
        snippets=snippets,
        readonly_tool_outputs=readonly_tool_outputs,
        display_path=display_path,
    )
    paragraphs = _readonly_content_paragraphs(
        snippets=snippets,
        readonly_tool_outputs=readonly_tool_outputs,
    )
    if not paragraphs:
        return ""
    title = "文章总结" if _looks_like_summary_task(request.task) else "文件内容总结"
    overview = _compact_line(_first_substantial_sentence(paragraphs), 220)
    thesis = _compact_line(_extract_thesis(paragraphs) or overview, 260)
    structure_points = _select_structure_points(paragraphs, limit=5)
    overall = _compose_overall_summary(overview, thesis, structure_points)
    key_points = _select_key_points(
        paragraphs,
        limit=4,
        exclude=[overview, thesis, *structure_points],
    )

    lines = [f"## {title}", ""]
    if sources:
        lines.append(f"已读取：{', '.join(sources[:3])}")
        lines.append("")
    lines.extend(
        [
            "总体概括：",
            overall,
            "",
            "核心观点：",
            f"- {_clean_claim_text(thesis)}",
            "",
            "论证脉络：",
        ]
    )
    for index, point in enumerate(structure_points, start=1):
        lines.append(f"{index}. {point}")
    if key_points:
        lines.extend(["", "补充要点："])
        for point in key_points:
            lines.append(f"- {point}")
    lines.extend(["", note])
    return "\n".join(lines)


def _looks_like_summary_task(task: Any) -> bool:
    text = str(task or "").lower()
    return any(token in text for token in ("总结", "摘要", "概括", "summar", "article", "文章", "文档"))


def _readonly_source_names(
    *,
    snippets: List[Dict[str, Any]],
    readonly_tool_outputs: List[Dict[str, Any]],
    display_path: DisplayPath,
) -> List[str]:
    names: List[str] = []
    seen: set[str] = set()
    for item in readonly_tool_outputs:
        if not isinstance(item, dict):
            continue
        label = readonly_tool_source_label(item, display_path=display_path)
        if label and label not in seen:
            seen.add(label)
            names.append(label)
    for index, snippet in enumerate(snippets, start=1):
        if not isinstance(snippet, dict):
            continue
        source = str(snippet.get("source") or snippet.get("path") or f"上下文 {index}").strip()
        label = display_path(source) or source
        if label and label not in seen:
            seen.add(label)
            names.append(label)
    return names


def _readonly_content_paragraphs(
    *,
    snippets: List[Dict[str, Any]],
    readonly_tool_outputs: List[Dict[str, Any]],
) -> List[str]:
    paragraphs: List[str] = []
    seen: set[str] = set()

    def add_text(value: Any) -> None:
        for part in _split_candidate_paragraphs(value):
            normalized = _normalize_article_text(part)
            if not _is_substantial_article_text(normalized):
                continue
            key = normalized[:180]
            if key in seen:
                continue
            seen.add(key)
            paragraphs.append(normalized)

    for item in readonly_tool_outputs:
        if not isinstance(item, dict):
            continue
        result = item.get("result")
        payload = result if isinstance(result, dict) else _json_payload(result)
        if isinstance(payload, dict):
            raw_paragraphs = payload.get("paragraphs") if isinstance(payload.get("paragraphs"), list) else []
            for paragraph in raw_paragraphs:
                if isinstance(paragraph, dict):
                    add_text(paragraph.get("text"))
                else:
                    add_text(paragraph)
            add_text(payload.get("text"))
        else:
            for point in readonly_tool_points(item):
                add_text(point)
    for snippet in snippets:
        if not isinstance(snippet, dict):
            continue
        add_text(snippet.get("_raw_text") or snippet.get("preview"))
    return paragraphs[:18]


def _split_candidate_paragraphs(value: Any) -> List[str]:
    text = str(value or "").strip()
    if not text:
        return []
    text = html.unescape(text)
    pieces = re.split(r"(?:\r?\n)+|(?<=。)\s+(?=[\u4e00-\u9fff])", text)
    return [piece.strip() for piece in pieces if piece and piece.strip()]


def _normalize_article_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^[-•\d.、\s]+", "", text)
    return text


def _is_substantial_article_text(text: str) -> bool:
    if len(text) < 24:
        return False
    lowered = text.lower()
    if lowered.startswith("word 内容包含") or "word 内容包含" in lowered:
        return False
    if re.fullmatch(r"section\s+\d+.*", lowered):
        return False
    if text.startswith("Section "):
        return False
    return True


def _sentence_candidates(paragraphs: List[str]) -> List[str]:
    sentences: List[str] = []
    seen: set[str] = set()
    for paragraph in paragraphs:
        for sentence in re.split(r"(?<=[。！？!?])\s*", paragraph):
            sentence = _normalize_article_text(sentence)
            if len(sentence) < 18:
                continue
            key = sentence[:120]
            if key in seen:
                continue
            seen.add(key)
            sentences.append(sentence)
    return sentences


def _first_substantial_sentence(paragraphs: List[str]) -> str:
    sentences = _sentence_candidates(paragraphs)
    if sentences:
        return sentences[0]
    return paragraphs[0]


def _extract_thesis(paragraphs: List[str]) -> str:
    text = " ".join(paragraphs[:6])
    for pattern in (
        r"(我的论点是[^。！？!?]+[。！？!?]?)",
        r"(本文的论点是[^。！？!?]+[。！？!?]?)",
        r"(核心观点是[^。！？!?]+[。！？!?]?)",
        r"(其论点是[^。！？!?]+[。！？!?]?)",
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    for sentence in _sentence_candidates(paragraphs):
        if any(token in sentence for token in ("论点", "主张", "核心", "认为", "不是", "而是")):
            return sentence
    return ""


def _select_structure_points(paragraphs: List[str], *, limit: int) -> List[str]:
    points: List[str] = []
    for paragraph in paragraphs:
        sentence = _first_sentence_from_paragraph(paragraph)
        compact = _compact_line(sentence, 180)
        if compact and not _near_duplicate(compact, points):
            points.append(compact)
        if len(points) >= limit:
            break
    return points


def _select_key_points(paragraphs: List[str], *, limit: int, exclude: List[str] | None = None) -> List[str]:
    keywords = ("论点", "关系", "身体", "技术", "艺术", "游戏", "电影", "观众", "主体", "框架", "失败", "条件")
    points: List[str] = []
    excluded = [item for item in (exclude or []) if item]
    for sentence in _sentence_candidates(paragraphs):
        if not any(keyword in sentence for keyword in keywords):
            continue
        compact = _compact_line(sentence, 190)
        if compact and not _near_duplicate(compact, points) and not _near_duplicate(compact, excluded):
            points.append(compact)
        if len(points) >= limit:
            break
    return points


def _compose_overall_summary(overview: str, thesis: str, structure_points: List[str]) -> str:
    lead = _strip_sentence_end(overview)
    claim = _clean_claim_text(_strip_sentence_end(thesis))
    if claim and claim != lead and claim not in lead:
        base = f"文章首先提出：{_without_leading_topic_marker(lead)}。核心主张是：{claim}。"
    else:
        base = f"文章首先提出：{_without_leading_topic_marker(lead)}。"
    if len(structure_points) >= 3:
        second = _strip_sentence_end(structure_points[1])
        third = _strip_sentence_end(structure_points[2])
        if second and third:
            base += f"随后转向{_without_leading_topic_marker(second)}，并借助 {_without_leading_topic_marker(third)}这一理论背景展开论证。"
    return _compact_line(base, 360)


def _strip_sentence_end(text: str) -> str:
    return str(text or "").strip().rstrip("。！？!?；; ")


def _without_leading_topic_marker(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"^(这篇内容主要讨论|本文主要讨论|文章主要讨论)[：:，,]?", "", value)
    return value


def _clean_claim_text(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"^(我的论点是|本文的论点是|核心观点是|其论点是)[：:，,]?", "", value)
    return value.strip()


def _near_duplicate(candidate: str, existing: List[str]) -> bool:
    normalized = _dedupe_key(candidate)
    if not normalized:
        return False
    for item in existing:
        other = _dedupe_key(item)
        if not other:
            continue
        if normalized == other or normalized in other or other in normalized:
            return True
        overlap = len(set(normalized) & set(other)) / max(len(set(normalized)), 1)
        if overlap >= 0.82 and abs(len(normalized) - len(other)) <= 24:
            return True
    return False


def _dedupe_key(text: str) -> str:
    return re.sub(r"[\s，。！？；：:,.!?;、\"“”'‘’（）()\[\]《》<>]+", "", str(text or "").lower())


def _first_sentence_from_paragraph(paragraph: str) -> str:
    candidates = re.split(r"(?<=[。！？!?])\s*", paragraph)
    for candidate in candidates:
        text = _normalize_article_text(candidate)
        if len(text) >= 18:
            return text
    return _normalize_article_text(paragraph)


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
