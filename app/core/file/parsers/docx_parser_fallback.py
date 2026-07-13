# -*- coding: utf-8 -*-
"""Mammoth fallback metadata and heading normalization for DOCX parsing."""
from __future__ import annotations

import html
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def empty_docx_grid_metadata() -> dict[str, Any]:
    return {"enabled": False, "type": "", "line_pitch_twips": 0, "line_pitch_px": 0, "char_space": 0}


def _fallback_story_html(story: Any) -> str:
    parts: list[str] = []
    for paragraph in getattr(story, "paragraphs", []) or []:
        text = str(getattr(paragraph, "text", "") or "").strip()
        if text:
            parts.append(f"<p>{html.escape(text).replace(chr(9), '&emsp;')}</p>")
    return "".join(parts)


def extract_fallback_docx_metadata(file_path: str) -> dict[str, Any]:
    """Return the rich-renderer page-layout contract for Mammoth fallback HTML."""
    empty_metadata: dict[str, Any] = {
        "page_width_px": 0,
        "page_height_px": 0,
        "margin_top_px": 0,
        "margin_bottom_px": 0,
        "margin_left_px": 0,
        "margin_right_px": 0,
        "doc_grid": empty_docx_grid_metadata(),
        "header_html": "",
        "footer_html": "",
        "sections": [],
    }
    try:
        from docx import Document
        from docx.oxml.ns import qn
    except ImportError:
        return empty_metadata

    def emu_to_px(value: Any) -> int:
        try:
            return round(int(value or 0) / 914400 * 96)
        except (TypeError, ValueError):
            return 0

    def section_grid(section: Any) -> dict[str, Any]:
        grid = empty_docx_grid_metadata()
        try:
            section_props = getattr(section, "_sectPr", None)
            doc_grid = section_props.find(qn("w:docGrid")) if section_props is not None else None
            if doc_grid is None:
                return grid
            line_pitch = int(doc_grid.get(qn("w:linePitch")) or 0)
            grid.update({
                "enabled": True,
                "type": str(doc_grid.get(qn("w:type")) or ""),
                "line_pitch_twips": line_pitch,
                "line_pitch_px": round((line_pitch / 20.0) / 72.0 * 96.0, 2),
                "char_space": int(doc_grid.get(qn("w:charSpace")) or 0),
            })
        except (AttributeError, TypeError, ValueError):
            return grid
        return grid

    try:
        document = Document(file_path)
        sections: list[dict[str, Any]] = []
        for section in document.sections:
            sections.append({
                "page_width_px": emu_to_px(section.page_width),
                "page_height_px": emu_to_px(section.page_height),
                "margin_top_px": emu_to_px(section.top_margin),
                "margin_bottom_px": emu_to_px(section.bottom_margin),
                "margin_left_px": emu_to_px(section.left_margin),
                "margin_right_px": emu_to_px(section.right_margin),
                "doc_grid": section_grid(section),
                "header_html": _fallback_story_html(section.header),
                "footer_html": _fallback_story_html(section.footer),
                "first_header_html": _fallback_story_html(section.first_page_header) if section.different_first_page_header_footer else "",
                "first_footer_html": _fallback_story_html(section.first_page_footer) if section.different_first_page_header_footer else "",
                "even_header_html": _fallback_story_html(section.even_page_header),
                "even_footer_html": _fallback_story_html(section.even_page_footer),
            })
    except Exception as exc:
        logger.warning("[DocxParser] 降级渲染的页面元数据提取失败: %s", exc)
        return empty_metadata

    if not sections:
        return empty_metadata
    first_section = sections[0]
    return {**{key: first_section.get(key) for key in empty_metadata if key != "sections"}, "sections": sections}


def normalize_mammoth_heading_contract(html_text: str) -> tuple[str, list[dict[str, Any]]]:
    """Give Mammoth headings the same navigation contract as rich HTML."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return html_text, []

    soup = BeautifulSoup(html_text, "html.parser")
    headings: list[dict[str, Any]] = []
    for index, heading in enumerate(soup.find_all(re.compile(r"^h[1-6]$", re.I)), start=1):
        text = " ".join(heading.get_text(" ", strip=True).split())
        if not text:
            continue
        heading_id = str(heading.get("id") or f"koto-fallback-heading-{index}")
        heading["id"] = heading_id
        heading["data-koto-role"] = "structural_heading"
        headings.append({"id": heading_id, "level": int(str(heading.name)[1]), "text": text})
    return str(soup), headings
