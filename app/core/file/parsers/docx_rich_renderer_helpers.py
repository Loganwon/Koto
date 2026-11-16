# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import base64
import html
import io
import logging
import math
import mimetypes
import os
import re
from typing import Any

from app.core.file.image_utils import compress_image_bytes as _compress_image_bytes

logger = logging.getLogger(__name__)
_DOCX_PREVIEW_TARGET_PAGES = 3
_DOCX_PREVIEW_UNITS_PER_PAGE = 34
_DOCX_PREVIEW_MAX_TABLE_ROWS = 18


def _twips_to_pt(twips: int | None) -> float | None:
    """Convert EMU twips (1/20 pt) to pt."""
    if twips is None:
        return None
    return round(twips / 20, 2)


def _pt_to_twips(pt_value: float | None) -> int | None:
    if pt_value is None:
        return None
    return int(round(float(pt_value) * 20))


def _emu_to_px(emu: int) -> int:
    """Convert EMU to pixels (96 dpi)."""
    return max(1, round(emu / 914400 * 96))


def _quote_css_font_family(name: str) -> str:
    _name = str(name or "").strip().strip("'\"")
    return "'" + _name.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _norm_style_key(val: str | None) -> str:
    """Normalise style key text for robust cross-language matching."""
    if not val:
        return ""
    return str(val).strip().lower().replace(" ", "").replace("_", "")


def _extract_toc_level_from_style(val: str | None) -> str:
    """Extract TOC level from style-like text, defaulting to "1"."""
    if not val:
        return "1"
    _s = str(val)
    for _ch in _s:
        if _ch.isdigit():
            return _ch
    return "1"


def _slugify_heading_anchor(text: str) -> str:
    """Create a stable HTML id for structural headings without bookmarks."""
    _slug = re.sub("[^0-9A-Za-z\\u4e00-\\u9fff_-]+", "-", (text or "").strip().lower())
    _slug = re.sub("-{2,}", "-", _slug).strip("-_")
    return _slug or "heading"


def _is_toc_style_key(val: str | None) -> bool:
    """Return True only for explicit Word/WPS TOC style keys."""
    _k = _norm_style_key(val)
    if not _k:
        return False
    if _k in {"toc", "tocheading", "tableofcontents", "目录", "目录标题"}:
        return True
    if re.fullmatch("toc[1-9]", _k):
        return True
    if re.fullmatch("tableofcontents[1-9]?", _k):
        return True
    if re.fullmatch("目录[一二三四五六七八九十0-9]?", _k):
        return True
    return False


def _looks_like_structural_heading_prefix(text: str) -> bool:
    """Best-effort prefix check for numbered or chapter-like headings."""
    _text = re.sub("\\s+", "", str(text or ""))
    if not _text:
        return False
    return (
        re.match(
            "^(?:第[0-9一二三四五六七八九十百千万零两]+[章节部分篇卷]|[0-9]+(?:\\.[0-9]+){0,3}[、.．]?|[一二三四五六七八九十百千万零两]+[、.．]|[(（]?[0-9一二三四五六七八九十百千万零两]+[)）][、.．]?)",
            _text,
        )
        is not None
    )


def _looks_like_outline_only_body_sentence(text: str) -> bool:
    """Reject short clause-style prose that only carries outline metadata."""
    _text = re.sub("\\s+", "", str(text or ""))
    if not _text:
        return False
    if re.match("^(?:19|20)\\d{2}年\\d{1,2}月\\d{1,2}日", _text):
        return True
    if re.search("(?:\\.\\.\\.|…+)$", _text):
        return True
    if re.search("[。；;，,]", _text):
        return not _looks_like_structural_heading_prefix(_text)
    return False


def _resolve_para_style_ref(para):
    try:
        return para.style if para.style else None
    except Exception:
        return None


def _parse_int_prop(value) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _docx_revision_data_attrs(
    review_id: str, action: str, author: str = "", date: str = ""
) -> str:
    attrs = [
        ("data-koto-review-id", str(review_id or "").strip()),
        ("data-koto-review-source", "docx_revision"),
        ("data-koto-review-action", str(action or "").strip()),
    ]
    author_text = str(author or "").strip()
    date_text = str(date or "").strip()
    if author_text:
        attrs.append(("data-koto-review-author", author_text))
    if date_text:
        attrs.append(("data-koto-review-date", date_text))
    return "".join(
        (
            f' {name}="{html.escape(value, quote=True)}"'
            for name, value in attrs
            if value
        )
    )


def _estimate_paragraph_units(para) -> int:
    text = (getattr(para, "text", "") or "").strip()
    if not text:
        lines = 1
    else:
        lines = max(1, math.ceil(len(text) / 42))
    try:
        xml = para._element.xml if hasattr(para, "_element") else ""
        if "w:drawing" in xml or "pic:pic" in xml:
            lines += 6
    except Exception:
        pass
    return max(1, min(18, lines + (1 if len(text) > 90 else 0)))
