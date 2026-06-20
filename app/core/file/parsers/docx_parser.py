# -*- coding: utf-8 -*-
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


def _extract_table_styles(docx_path: str) -> list[dict]:
    """
    Extract table cell formatting metadata from a DOCX file using python-docx.

    Returns a list — one entry per table, positionally indexed:
        [
          {  # table 0
            (row, col): {
              "bg":      "RRGGBB" | None,   # cell background fill
              "colspan": int,               # w:gridSpan value
              "rowspan": int,               # logical rowspan (from w:vMerge analysis)
              "bold":    bool,              # header-row bold hint
            },
            ...
          },
          ...  # table 1, table 2, …
        ]

    Falls back to [] silently if python-docx or lxml is unavailable.
    """
    try:
        from docx import Document
        from lxml import etree
    except ImportError:
        return []

    WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    def _w(tag: str) -> str:
        return f"{{{WNS}}}{tag}"

    try:
        doc = Document(docx_path)
    except Exception as exc:
        logger.warning("[_extract_table_styles] 无法打开文件: %s", exc)
        return []

    result = []
    for tbl in doc.tables:
        tbl_data: dict = {}

        # ── Column widths from w:tblGrid/w:gridCol (twips → percentages) ──
        # tbl._tbl is the lxml element for the <w:tbl> node.
        tbl_xml = tbl._tbl
        grid_cols = tbl_xml.findall(f".//{_w('gridCol')}")
        if grid_cols:
            raw_widths = []
            for gc in grid_cols:
                w_val = gc.get(_w("w"))
                try:
                    raw_widths.append(max(1, int(w_val or 0)))
                except (ValueError, TypeError):
                    raw_widths.append(1)
            total_w = sum(raw_widths) or 1
            # Store as percentages rounded to 1 decimal; sum ≈ 100 %
            tbl_data["__col_pcts"] = [round(w / total_w * 100, 1) for w in raw_widths]

        for ri, row in enumerate(tbl.rows):
            for ci, cell in enumerate(row.cells):
                tc = cell._tc

                # ── Background colour (w:shd w:fill) ────────────────────
                shd = tc.find(f".//{_w('shd')}")
                bg = None
                if shd is not None:
                    fill = shd.get(_w("fill"))
                    if fill and fill.upper() not in ("AUTO", "FFFFFF", ""):
                        bg = fill.upper()

                # ── Colspan (w:gridSpan) ─────────────────────────────────
                grid_span_el = tc.find(f".//{_w('gridSpan')}")
                colspan = int(grid_span_el.get(_w("val"), 1)) if grid_span_el is not None else 1

                # ── Rowspan: count how many rows below start with w:vMerge (no val attr) ──
                # The first cell of a vertical merge has w:vMerge val="restart";
                # continuation cells have w:vMerge with no val.
                v_merge_el = tc.find(f".//{_w('vMerge')}")
                is_merge_start = (
                    v_merge_el is not None
                    and v_merge_el.get(_w("val"), "") == "restart"
                )
                rowspan = 1
                if is_merge_start:
                    # Count how many rows below continue this merge at the same col
                    for future_ri in range(ri + 1, len(tbl.rows)):
                        if ci >= len(tbl.rows[future_ri].cells):
                            break
                        future_tc = tbl.rows[future_ri].cells[ci]._tc
                        future_vm = future_tc.find(f".//{_w('vMerge')}")
                        if future_vm is not None and future_vm.get(_w("val"), "") == "":
                            rowspan += 1
                        else:
                            break

                # ── Skip continuation vMerge cells (they'll be expressed via rowspan) ──
                is_merge_continuation = (
                    v_merge_el is not None
                    and v_merge_el.get(_w("val"), "") == ""
                )
                if is_merge_continuation:
                    continue  # nothing to write; the HTML rowspan covers it

                tbl_data[(ri, ci)] = {
                    "bg": bg,
                    "colspan": colspan,
                    "rowspan": rowspan,
                }

        result.append(tbl_data)

    return result


def _inject_table_styles(html: str, table_styles: list[dict]) -> str:
    """
    Post-process mammoth's HTML to inject cell background colours, colspan,
    and rowspan attributes that mammoth discards.

    Only modifies cells for which _extract_table_styles() found metadata;
    leaves everything else untouched.
    """
    if not table_styles:
        return html

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return html

    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")

    for ti, tbl_tag in enumerate(tables):
        if ti >= len(table_styles):
            break
        style_map = table_styles[ti]
        if not style_map:
            continue

        # ── Inject <colgroup> for proportional column widths ──────────────────
        col_pcts: list[float] = style_map.get("__col_pcts", [])  # type: ignore[assignment]
        if col_pcts and not tbl_tag.find("colgroup"):
            colgroup = soup.new_tag("colgroup")
            for pct in col_pcts:
                col = soup.new_tag("col")
                col["style"] = f"width:{pct:.1f}%"
                colgroup.append(col)
            tbl_tag.insert(0, colgroup)

        rows = tbl_tag.find_all("tr")

        # ── Also inject width% on first-row cells (colgroup may be stripped by
        #    the editor's deserializer; inline td widths survive reliably) ──
        if col_pcts and rows:
            first_row_cells = rows[0].find_all(["td", "th"])
            for ci_col, cell_tag in enumerate(first_row_cells):
                if ci_col < len(col_pcts):
                    existing = cell_tag.get("style", "")
                    w_css = f"width:{col_pcts[ci_col]:.1f}%;"
                    # Don't double-inject
                    if "width:" not in existing:
                        cell_tag["style"] = (existing.rstrip(";") + ";" + w_css).lstrip(";")

        for ri, row_tag in enumerate(rows):
            cells = row_tag.find_all(["td", "th"])
            for ci, cell_tag in enumerate(cells):
                meta = style_map.get((ri, ci))
                if not meta:
                    continue

                # colspan / rowspan
                if meta.get("colspan", 1) > 1:
                    cell_tag["colspan"] = str(meta["colspan"])
                if meta.get("rowspan", 1) > 1:
                    cell_tag["rowspan"] = str(meta["rowspan"])

                # background colour
                bg = meta.get("bg")
                if bg:
                    existing = cell_tag.get("style", "")
                    bg_css = f"background-color:#{bg.lower()};"
                    cell_tag["style"] = (existing.rstrip(";") + ";" + bg_css).lstrip(";")

    # ── Remove entirely-empty trailing columns ─────────────────────────────
    # The editor sometimes pads rows with phantom empty cells; stripping
    # them here (Python side) avoids reconciler issues on the frontend.
    for tbl_tag in soup.find_all("table"):
        rows = tbl_tag.find_all("tr")
        if not rows:
            continue
        max_cols = max(
            (len(r.find_all(["td", "th"], recursive=False)) for r in rows),
            default=0,
        )
        if max_cols < 2:
            continue
        for ci in range(max_cols - 1, 0, -1):
            all_empty = all(
                len(cells) <= ci
                or (not cells[ci].get_text(strip=True) and not cells[ci].find("img"))
                for cells in (r.find_all(["td", "th"], recursive=False) for r in rows)
            )
            if all_empty:
                for row in rows:
                    cells = row.find_all(["td", "th"], recursive=False)
                    if ci < len(cells):
                        cells[ci].decompose()
            else:
                break

    return str(soup)


def _get_floating_image_srcs(docx_path: str) -> list[str]:
    """
    Return base64 data URIs for floating (anchor-positioned) images in a DOCX.

    mammoth only converts <wp:inline> images; <wp:anchor> images (floated to a
    fixed page position, e.g. a resume photo) are silently skipped.
    Uses namespace-aware ElementTree parsing so attribute order never matters.
    """
    import zipfile as _zipfile
    import xml.etree.ElementTree as _ET

    # Full OOXML namespace URIs — must match exactly (not prefix aliases)
    IMG_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
    WP_NS    = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
    A_NS     = "http://schemas.openxmlformats.org/drawingml/2006/main"
    R_NS     = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

    result: list[str] = []
    try:
        with _zipfile.ZipFile(docx_path, "r") as z:
            file_list = z.namelist()

            # Locate document.xml and its rels (case-insensitive for robustness)
            doc_name = next(
                (n for n in file_list if n.lower() == "word/document.xml"), None
            )
            rels_name = next(
                (n for n in file_list if n.lower() == "word/_rels/document.xml.rels"), None
            )
            if not doc_name or not rels_name:
                return result

            # ── rel_id → media path via ElementTree (handles ANY attribute order) ──
            rels_root = _ET.fromstring(z.read(rels_name))
            rel_map: dict[str, str] = {}
            for rel in rels_root:
                rid   = rel.get("Id", "")
                rtype = rel.get("Type", "")
                tgt   = rel.get("Target", "")
                if rid and IMG_TYPE in rtype and tgt:
                    rel_map[rid] = tgt if tgt.startswith("word/") else f"word/{tgt}"

            # ── Walk document.xml, separate inline vs anchor image embed IDs ──
            doc_root = _ET.fromstring(z.read(doc_name))

            inline_ids: set[str] = set()
            floating_ids: list[str] = []

            for inline in doc_root.iter(f"{{{WP_NS}}}inline"):
                for blip in inline.iter(f"{{{A_NS}}}blip"):
                    eid = blip.get(f"{{{R_NS}}}embed")
                    if eid:
                        inline_ids.add(eid)

            for anchor in doc_root.iter(f"{{{WP_NS}}}anchor"):
                for blip in anchor.iter(f"{{{A_NS}}}blip"):
                    eid = blip.get(f"{{{R_NS}}}embed")
                    if eid:
                        floating_ids.append(eid)

            seen: set[str] = set()
            for rel_id in floating_ids:
                if rel_id in inline_ids or rel_id in seen:
                    continue
                seen.add(rel_id)
                media_path = rel_map.get(rel_id)
                if not media_path:
                    logger.debug(
                        "[floating_imgs] no media path for rel_id=%s; rel_map keys=%s",
                        rel_id, list(rel_map)[:8],
                    )
                    continue
                try:
                    img_bytes = z.read(media_path)
                    mime = mimetypes.guess_type(media_path)[0] or "image/png"
                    img_bytes, mime = _compress_image_bytes(img_bytes, mime)
                    b64 = base64.b64encode(img_bytes).decode("ascii")
                    result.append(f"data:{mime};base64,{b64}")
                except Exception as e:
                    logger.debug("[floating_imgs] failed to read %s: %s", media_path, e)
    except Exception as exc:
        logger.warning("[_get_floating_image_srcs] %s", exc)
    return result


def _unwrap_layout_tables(html: str) -> str:
    """
    Unwrap single-column layout tables into flat content sections.

    Many Word documents (especially resumes) wrap *all* content in a 1-column
    table purely for layout control.  When rendered in the editor these tables
    show ugly borders and break natural page flow.

    Criteria for "layout table":
      - Every row has exactly 1 cell (colspan is OK — still single visual column)
      - No rowspan > 1 (vertical merges indicate a multi-row data table)
      - Table has >= 3 rows (prevents stripping intentional single-row tables)
      - No header row (<th>)

    Each cell's inner HTML is extracted and wrapped in
    ``<div class="koto-layout-section">...</div>`` to preserve grouping.
    Empty cells (spacer rows) become ``<div class="koto-layout-spacer"></div>``.
    """
    try:
        from bs4 import BeautifulSoup, Tag
    except ImportError:
        return html

    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    changed = False

    for tbl in tables:
        rows = tbl.find_all("tr", recursive=False)
        if len(rows) < 3:
            continue  # too small — probably a real data table

        # Check: is every row single-cell with no <th>?
        is_layout = True
        for row in rows:
            cells = row.find_all(["td", "th"], recursive=False)
            if len(cells) != 1:
                is_layout = False
                break
            cell = cells[0]
            if cell.name == "th":
                is_layout = False
                break
            # colspan is fine (cell just spans full width) — but rowspan > 1
            # means a complex multi-row structure, not pure layout.
            rs = int(cell.get("rowspan", 1) or 1)
            if rs > 1:
                is_layout = False
                break

        if not is_layout:
            continue

        # Skip tables that have visible borders (inline style from rich renderer)
        tbl_style = tbl.get("style", "")
        if "border:" in tbl_style and "border:none" not in tbl_style:
            continue

        fragments = []
        for row in rows:
            cell = row.find(["td", "th"], recursive=False)
            if not cell:
                continue
            inner = cell.decode_contents().strip()
            if not inner or inner in ("<br/>", "<br>", "<br >"):
                div = soup.new_tag("div")
                div["class"] = "koto-layout-spacer"
                fragments.append(div)
            else:
                div = soup.new_tag("div")
                div["class"] = "koto-layout-section"
                # Preserve cell background colour as section background
                cell_style = cell.get("style", "")
                if "background" in cell_style:
                    div["style"] = cell_style
                div.append(BeautifulSoup(inner, "html.parser"))
                fragments.append(div)

        # Replace the <table> in-place
        for frag in reversed(fragments):
            tbl.insert_after(frag)
        tbl.decompose()
        changed = True

    return str(soup) if changed else html


def _deduplicate_images(html: str) -> str:
    """
    Remove duplicate inline base64 images from HTML.

    Compares the first 200 chars of each data URI.  If two <img> tags share
    the same base64 prefix (i.e. are the same image), only the first is kept.
    """
    # Quick check — fewer than 2 images means nothing to deduplicate
    if html.count("<img") < 2:
        return html

    seen_prefixes: set[str] = set()
    result_parts: list[str] = []
    pos = 0

    for m in re.finditer(r"<img\s[^>]*>", html, re.IGNORECASE):
        img_tag = m.group()
        src_m = re.search(r'src="(data:[^"]{0,200})', img_tag)
        if src_m:
            prefix = src_m.group(1)
            if prefix in seen_prefixes:
                # Duplicate — skip this <img> tag
                result_parts.append(html[pos:m.start()])
                pos = m.end()
                continue
            seen_prefixes.add(prefix)

        result_parts.append(html[pos:m.end()])
        pos = m.end()

    result_parts.append(html[pos:])
    return "".join(result_parts)


def _docx_to_rich_html(
    file_path: str,
    *,
    progressive_preview: bool = False,
) -> tuple[str, list[dict], list[dict], dict[str, Any]]:
    """
    将 DOCX 转换为保留完整 Word 格式的内联样式 HTML。

    使用 python-docx 直接读取 OOXML，提取:
      - 段落对齐/缩进/行距/段前段后
      - 标题级别 (Heading 1-6 / 标题 1-6) → <h1>-<h6>
      - 行内字体名称、大小、颜色、粗体、斜体、下划线、删除线、上下标
      - 超链接 → <a href="...">
      - 有序/无序列表 → <ol>/<ul> 按 numId 分组
      - 表格: 列宽、合并单元格、边框、单元格背景色、垂直对齐
      - 内联图片 (wp:inline) 和浮动图片 (wp:anchor) → base64 <img>
      - 页眉/页脚 → <div class="koto-header">/<div class="koto-footer">
    """
    try:
        from docx import Document
        from docx.oxml.ns import qn
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.enum.table import WD_ROW_HEIGHT_RULE, WD_CELL_VERTICAL_ALIGNMENT
        from docx.shared import Pt, RGBColor
    except ImportError:
        raise RuntimeError("python-docx 未安装，请执行: pip install python-docx")

    # ── Heading style name → tag map ────────────────────────────────────────
    _HEADING_MAP: dict[str, str] = {
        "heading 1": "h1", "heading 2": "h2", "heading 3": "h3",
        "heading 4": "h4", "heading 5": "h5", "heading 6": "h6",
        # Some documents use style IDs/names without spaces.
        "heading1": "h1", "heading2": "h2", "heading3": "h3",
        "heading4": "h4", "heading5": "h5", "heading6": "h6",
        "标题 1": "h1", "标题 2": "h2", "标题 3": "h3",
        "标题 4": "h4", "标题 5": "h5", "标题 6": "h6",
        # WPS / Word Chinese no-space variants (e.g. "标题1" not "标题 1")
        "标题1": "h1", "标题2": "h2", "标题3": "h3",
        "标题4": "h4", "标题5": "h5", "标题6": "h6",
        # Common alternative Chinese heading names
        "一级标题": "h1", "二级标题": "h2", "三级标题": "h3",
        # subheading
        "subheading 1": "h2", "subheading 2": "h3",
    }

    _VISUAL_TITLE_STYLE_KEYS: set[str] = {
        "title",
        "subtitle",
        "标题",
        "副标题",
        "封面标题",
        "封面副标题",
    }

    _HEADING_TYPOGRAPHY_FALLBACKS: dict[str, dict[str, str]] = {
        "h1": {"font-size": "16.0pt", "font-weight": "bold"},
        "h2": {"font-size": "14.0pt", "font-weight": "bold"},
        "h3": {"font-size": "12.0pt", "font-weight": "bold"},
        "h4": {"font-size": "11.0pt", "font-weight": "bold"},
        "h5": {"font-size": "10.5pt", "font-weight": "bold"},
        "h6": {"font-size": "10.5pt", "font-weight": "bold"},
    }

    _ALIGN_MAP = {
        WD_ALIGN_PARAGRAPH.LEFT: "left",
        WD_ALIGN_PARAGRAPH.CENTER: "center",
        WD_ALIGN_PARAGRAPH.RIGHT: "right",
        WD_ALIGN_PARAGRAPH.JUSTIFY: "justify",
        WD_ALIGN_PARAGRAPH.DISTRIBUTE: "justify",
    }

    _CN_FONT_MAP_P: dict[str, str] = {
        "黑体": "SimHei", "宋体": "SimSun", "楷体": "KaiTi",
        "仿宋": "FangSong", "微软雅黑": "Microsoft YaHei",
        "华文中宋": "STZhongsong", "华文宋体": "STSong",
        "华文黑体": "STHeiti", "华文楷体": "STKaiti",
        "华文仿宋": "STFangsong",
        "方正书宋": "FZShuSong-Z01", "方正黑体": "FZHei-B01",
    }
    _CN_FONT_EQUIVALENTS: dict[str, tuple[str, ...]] = {}
    for _cn_name, _ascii_name in _CN_FONT_MAP_P.items():
        _CN_FONT_EQUIVALENTS[_cn_name] = (_cn_name, _ascii_name)
        _CN_FONT_EQUIVALENTS[_ascii_name] = (_cn_name, _ascii_name)

    _EMPTY_STYLE_DEFAULTS: dict[str, Any] = {
        "style_name": "",
        "style_id": "",
        "text_align": None,
        "space_before": None,
        "space_after": None,
        "line_height": None,
        "line_spacing_rule": None,
        "line_spacing_twips": None,
        "font_size": None,
        "font_family": None,
        "first_line_indent_twips": None,
        "left_indent_twips": None,
        "keep_with_next": None,
        "keep_together": None,
        "page_break_before": None,
        "widow_control": None,
    }
    _style_defaults_cache: dict[object, dict[str, Any]] = {}
    _heading_manifest: list[dict[str, Any]] = []
    _generated_heading_id_counts: dict[str, int] = {}

    # ── Helpers ─────────────────────────────────────────────────────────────
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

    def _rgb_to_hex(rgb: RGBColor | None) -> str | None:
        if rgb is None:
            return None
        try:
            return "#{:02X}{:02X}{:02X}".format(int(rgb.red), int(rgb.green), int(rgb.blue))
        except Exception:
            return None

    def _quote_css_font_family(name: str) -> str:
        _name = str(name or "").strip().strip("'\"")
        return "'" + _name.replace("\\", "\\\\").replace("'", "\\'") + "'"

    def _build_css_font_family_stack(*names: str | None) -> str | None:
        _tokens: list[str] = []
        _seen: set[str] = set()
        for _name in names:
            _raw = str(_name or "").strip().strip("'\"")
            if not _raw:
                continue
            for _candidate in _CN_FONT_EQUIVALENTS.get(_raw, (_raw,)):
                _norm = _candidate.lower()
                if _norm in _seen:
                    continue
                _seen.add(_norm)
                _tokens.append(_candidate)
        if not _tokens:
            return None
        return ",".join(_quote_css_font_family(_token) for _token in _tokens)

    def _norm_style_key(val: str | None) -> str:
        """Normalise style key text for robust cross-language matching."""
        if not val:
            return ""
        return str(val).strip().lower().replace(" ", "").replace("_", "")

    def _is_heading_style_key(val: str | None) -> str | None:
        """Return h1..h6 if the style key represents a heading style."""
        if not val:
            return None
        _raw = str(val).strip().lower()
        if _raw in _HEADING_MAP:
            return _HEADING_MAP[_raw]
        _k = _norm_style_key(val)
        # heading1 / heading2 / ...
        if _k.startswith("heading") and len(_k) > 7 and _k[7:].isdigit():
            _lv = int(_k[7:])
            if 1 <= _lv <= 6:
                return f"h{_lv}"
        # 标题1 / 标题2 / ...
        if _k.startswith("标题"):
            _digits = "".join(ch for ch in _k if ch.isdigit())
            if _digits:
                _lv = int(_digits)
                if 1 <= _lv <= 6:
                    return f"h{_lv}"
        return None

    def _is_visual_title_style_key(val: str | None) -> bool:
        """Return True for title-like paragraph styles that are visual, not structural."""
        _k = _norm_style_key(val)
        if not _k:
            return False
        return _k in _VISUAL_TITLE_STYLE_KEYS

    def _style_chain_has_visual_title(style_ref) -> bool:
        """Return True when any style in the base-style chain is title-like."""
        _visited_ids: set[int] = set()
        _style_iter = style_ref
        while _style_iter is not None:
            _eid = id(getattr(_style_iter, "_element", None))
            if _eid in _visited_ids:
                break
            _visited_ids.add(_eid)
            try:
                _sname = getattr(_style_iter, "name", "") or ""
                _sid = getattr(_style_iter, "style_id", "") or ""
                if _is_visual_title_style_key(_sname) or _is_visual_title_style_key(_sid):
                    return True
            except Exception:
                pass
            try:
                _style_iter = _style_iter.base_style
            except Exception:
                break

    def _style_chain_has_heading(style_ref) -> bool:
        """Return True when any style in the base-style chain resolves to a heading."""
        _visited_ids: set[int] = set()
        _style_iter = style_ref
        while _style_iter is not None:
            _eid = id(getattr(_style_iter, "_element", None))
            if _eid in _visited_ids:
                break
            _visited_ids.add(_eid)
            try:
                _sname = getattr(_style_iter, "name", "") or ""
                _sid = getattr(_style_iter, "style_id", "") or ""
                if _is_heading_style_key(_sname) or _is_heading_style_key(_sid):
                    return True
            except Exception:
                pass
            try:
                _style_iter = _style_iter.base_style
            except Exception:
                break
        return False
        return False

    def _extract_toc_level_from_style(val: str | None) -> str:
        """Extract TOC level from style-like text, defaulting to "1"."""
        if not val:
            return "1"
        _s = str(val)
        for _ch in _s:
            if _ch.isdigit():
                return _ch
        return "1"

    def _apply_heading_typography_fallback(tag: str, css: dict[str, str], inner_html: str) -> None:
        """Keep semantic headings readable when DOCX outline metadata has no font props."""
        _fallback = _HEADING_TYPOGRAPHY_FALLBACKS.get((tag or "").lower())
        if not _fallback:
            return

        _inner_lower = inner_html.lower()
        if "font-size" not in css and "font-size:" not in _inner_lower:
            css["font-size"] = _fallback["font-size"]
        if "font-weight" not in css and "font-weight:" not in _inner_lower:
            css["font-weight"] = _fallback["font-weight"]

    def _p_elem_has_toc_anchor(p_el) -> bool:
        """True when paragraph has internal TOC hyperlink targets like #_Toc*."""
        if p_el is None:
            return False
        try:
            for _hl in p_el.findall(qn("w:hyperlink")):
                _a = (_hl.get(qn("w:anchor")) or "").lower()
                if _a.startswith("_toc"):
                    return True
        except Exception:
            return False
        return False

    def _p_elem_has_toc_field(p_el) -> bool:
        """True when paragraph carries a TOC/PAGEREF field code."""
        if p_el is None:
            return False
        try:
            _instr = " ".join(
                (_node.text or "")
                for _node in p_el.iter(qn("w:instrText"))
            )
            _instr_norm = re.sub(r"\s+", " ", _instr).strip().upper()
            if not _instr_norm:
                return False
            return (
                " TOC " in f" {_instr_norm} "
                or (" PAGEREF " in f" {_instr_norm} " and "_TOC" in _instr_norm)
            )
        except Exception:
            return False

    def _p_elem_text_content(p_el) -> str:
        """Extract visible paragraph text from runs for structural heuristics."""
        if p_el is None:
            return ""
        try:
            _text = "".join((_node.text or "") for _node in p_el.iter(qn("w:t")))
            return re.sub(r"\s+", " ", _text).strip()
        except Exception:
            return ""

    def _find_bookmark_id(p_el) -> str:
        """Return the first visible bookmark id attached to a paragraph element."""
        if p_el is None:
            return ""
        try:
            for _bm in p_el.findall(qn("w:bookmarkStart")):
                _name = (_bm.get(qn("w:name"), "") or "").strip()
                if _name and not _name.startswith("_GoBack"):
                    return _name
        except Exception:
            return ""
        return ""

    def _slugify_heading_anchor(text: str) -> str:
        """Create a stable HTML id for structural headings without bookmarks."""
        _slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", (text or "").strip().lower())
        _slug = re.sub(r"-{2,}", "-", _slug).strip("-_")
        return _slug or "heading"

    def _make_generated_heading_anchor(text: str) -> str:
        """Generate a unique synthetic anchor id for a body heading."""
        _base = f"koto-heading-{_slugify_heading_anchor(text)}"
        _count = _generated_heading_id_counts.get(_base, 0)
        _generated_heading_id_counts[_base] = _count + 1
        return _base if _count == 0 else f"{_base}-{_count + 1}"

    def _resolve_body_heading_anchor(p_el, tag: str | None, block_role: str) -> str:
        """Return a stable DOM id for structural headings even when excluded from nav manifest."""
        if block_role != "structural_heading":
            return ""
        if not tag or not re.fullmatch(r"h[1-6]", (tag or "").lower()):
            return ""

        _text = _p_elem_text_content(p_el)
        if not _text:
            return ""

        return _find_bookmark_id(p_el) or _make_generated_heading_anchor(_text)

    def _record_body_heading(p_el, tag: str | None, anchor_id: str | None = None) -> str:
        """Append a parser-owned body heading manifest entry and return its anchor id."""
        if not tag or not re.fullmatch(r"h[1-6]", (tag or "").lower()):
            return ""

        _text = _p_elem_text_content(p_el)
        if not _text:
            return ""

        _anchor_id = (anchor_id or "").strip() or _find_bookmark_id(p_el) or _make_generated_heading_anchor(_text)
        _heading_manifest.append({
            "level": int(tag[1]),
            "text": _text,
            "id": _anchor_id,
        })
        return _anchor_id

    def _should_emit_heading_manifest_entry(tag: str | None, block_role: str, p_el=None, style_defaults=None, style_ref=None) -> bool:
        """Populate the navigation manifest for structural headings with durable title signals."""
        if block_role != "structural_heading":
            return False
        if not tag or not re.fullmatch(r"h[1-6]", str(tag).lower()):
            return False
        _style_defaults = style_defaults or {}
        try:
            _style_name = _style_defaults.get("style_name") or ""
        except Exception:
            _style_name = ""
        try:
            _style_id = _style_defaults.get("style_id") or ""
        except Exception:
            _style_id = ""
        if _is_heading_style_key(_style_name) or _is_heading_style_key(_style_id):
            return True
        if _style_chain_has_heading(style_ref):
            return True

        _text = _p_elem_text_content(p_el)
        return bool(_text and _looks_like_structural_heading_prefix(_text))

    def _p_elem_looks_like_toc_line(p_el) -> bool:
        """Heuristic for field-updated TOC lines that only keep visible text."""
        _text = _p_elem_text_content(p_el)
        if not _text or len(_text) > 160:
            return False
        if re.search(r"[。！？；;，,]", _text):
            return False
        if re.search(r"(?:\.{2,}|…{2,})\s*\d{1,4}$", _text):
            return True
        return re.match(r"^.{1,80}\s+\d{1,4}$", _text) is not None

    def _is_toc_style_key(val: str | None) -> bool:
        """Return True only for explicit Word/WPS TOC style keys."""
        _k = _norm_style_key(val)
        if not _k:
            return False
        if _k in {"toc", "tocheading", "tableofcontents", "目录", "目录标题"}:
            return True
        if re.fullmatch(r"toc[1-9]", _k):
            return True
        if re.fullmatch(r"tableofcontents[1-9]?", _k):
            return True
        if re.fullmatch(r"目录[一二三四五六七八九十0-9]?", _k):
            return True
        return False

    def _looks_like_structural_heading_prefix(text: str) -> bool:
        """Best-effort prefix check for numbered or chapter-like headings."""
        _text = re.sub(r"\s+", "", str(text or ""))
        if not _text:
            return False
        return re.match(
            r"^(?:"
            r"第[0-9一二三四五六七八九十百千万零两]+[章节部分篇卷]"
            r"|[0-9]+(?:\.[0-9]+){0,3}[、.．]?"
            r"|[一二三四五六七八九十百千万零两]+[、.．]"
            r"|[(（]?[0-9一二三四五六七八九十百千万零两]+[)）][、.．]?"
            r")",
            _text,
        ) is not None

    def _looks_like_outline_only_body_sentence(text: str) -> bool:
        """Reject short clause-style prose that only carries outline metadata."""
        _text = re.sub(r"\s+", "", str(text or ""))
        if not _text:
            return False
        if re.match(r"^(?:19|20)\d{2}年\d{1,2}月\d{1,2}日", _text):
            return True
        if re.search(r"(?:\.\.\.|…+)$", _text):
            return True
        if re.search(r"[。；;，,]", _text):
            return not _looks_like_structural_heading_prefix(_text)
        return False

    def _should_promote_outline_heading(para, p_el, tag: str | None) -> bool:
        """Reject outlineLvl-only body-like paragraphs from becoming structural headings."""
        if not tag:
            return False

        _text = _p_elem_text_content(p_el)
        if not _text:
            return False

        _max_len = 90 if tag == "h1" else 60
        if len(_text) > _max_len:
            return False

        if _looks_like_outline_only_body_sentence(_text):
            return False

        try:
            _first_line_indent = para.paragraph_format.first_line_indent
            if _first_line_indent is not None and getattr(_first_line_indent, "twips", 0):
                return False
        except Exception:
            pass

        return True

    def _classify_paragraph_block(para, p_el, style_ref=None, style_defaults=None) -> tuple[str, str]:
        """Classify a body paragraph once into structural heading, visual title, TOC line, or body.

        Returns (html_tag, role), where role is one of:
        - structural_heading
        - visual_title
        - toc_line
        - body

        This is the parser-owned single source of truth for the heading
        manifest and emitted heading tags. Callers must not re-canonicalize the
        result in a second pass.
        """
        _sr = style_ref if style_ref is not None else _resolve_para_style_ref(para)
        _style_defaults = style_defaults if style_defaults is not None else _resolve_style_defaults(_sr)

        try:
            _style_name = _style_defaults.get("style_name") or ""
        except Exception:
            _style_name = ""
        try:
            _style_id = _style_defaults.get("style_id") or ""
        except Exception:
            _style_id = ""

        _is_toc_para, _ = _detect_toc_info(
            para=para,
            p_el=p_el,
            style_ref=_sr,
        )
        if _is_toc_para:
            return "p", "toc_line"

        if _is_visual_title_style_key(_style_name) or _is_visual_title_style_key(_style_id):
            return "p", "visual_title"

        _direct_heading_tag = _is_heading_style_key(_style_name) or _is_heading_style_key(_style_id)
        if _direct_heading_tag:
            return _direct_heading_tag, "structural_heading"

        if _style_chain_has_visual_title(_sr):
            return "p", "visual_title"

        _outline_tag, _via_outlinelvl = _detect_outline_level(para, p_el)
        if _via_outlinelvl and _outline_tag and _should_promote_outline_heading(para, p_el, _outline_tag):
            return _outline_tag, "structural_heading"

        return "p", "body"

    def _line_spacing_to_css(ls, ls_rule) -> str | None:
        from docx.enum.text import WD_LINE_SPACING

        if ls is None:
            return None

        _FIXED_MULT = {
            WD_LINE_SPACING.SINGLE: 1.0,
            WD_LINE_SPACING.ONE_POINT_FIVE: 1.5,
            WD_LINE_SPACING.DOUBLE: 2.0,
        }
        if ls_rule in _FIXED_MULT:
            return f"{_FIXED_MULT[ls_rule]}"
        if ls_rule in (WD_LINE_SPACING.MULTIPLE, None):
            try:
                mult = round(float(ls), 4)
                # Browsers visibly overlap wrapped lines when pathological
                # DOCX multiple spacing values such as 0.25 are preserved
                # literally. Clamp preview HTML to at least single spacing.
                if 0 < mult < 1.0:
                    mult = 1.0
                return f"{mult}"
            except (TypeError, ValueError):
                pass
            try:
                return f"{round(ls.pt, 2)}pt"
            except Exception:
                return None
        try:
            return f"{round(ls.pt, 2)}pt"
        except Exception:
            return None

    def _resolve_para_style_ref(para):
        try:
            return para.style if para.style else None
        except Exception:
            return None

    def _read_on_off_prop(el) -> bool | None:
        """Return OOXML on/off state for elements like <w:b/> or <w:i w:val="0"/>."""
        if el is None:
            return None
        try:
            _val = el.get(qn("w:val"))
        except Exception:
            _val = None
        if _val is None or str(_val).strip() == "":
            return True
        _norm = str(_val).strip().lower()
        if _norm in ("0", "false", "off", "no"):
            return False
        return True

    def _parse_int_prop(value) -> int | None:
        if value is None:
            return None
        try:
            return int(str(value).strip())
        except Exception:
            return None

    def _read_paragraph_layout_props_from_ppr(p_pr) -> dict[str, Any]:
        layout = {
            "space_before_twips": None,
            "space_after_twips": None,
            "line_spacing_rule": None,
            "line_spacing_twips": None,
            "first_line_indent_twips": None,
            "left_indent_twips": None,
            "keep_with_next": None,
            "keep_together": None,
            "page_break_before": None,
            "widow_control": None,
        }
        if p_pr is None:
            return layout

        try:
            spacing_el = p_pr.find(qn("w:spacing"))
            if spacing_el is not None:
                layout["space_before_twips"] = _parse_int_prop(spacing_el.get(qn("w:before")))
                layout["space_after_twips"] = _parse_int_prop(spacing_el.get(qn("w:after")))
                layout["line_spacing_twips"] = _parse_int_prop(spacing_el.get(qn("w:line")))
                line_rule = str(spacing_el.get(qn("w:lineRule")) or "").strip()
                if line_rule:
                    layout["line_spacing_rule"] = line_rule
                elif layout["line_spacing_twips"] is not None:
                    layout["line_spacing_rule"] = "auto"
        except Exception:
            pass

        try:
            ind_el = p_pr.find(qn("w:ind"))
            if ind_el is not None:
                layout["first_line_indent_twips"] = _parse_int_prop(ind_el.get(qn("w:firstLine")))
                layout["left_indent_twips"] = _parse_int_prop(ind_el.get(qn("w:left")))
        except Exception:
            pass

        for tag_name, key in (
            ("w:keepNext", "keep_with_next"),
            ("w:keepLines", "keep_together"),
            ("w:pageBreakBefore", "page_break_before"),
            ("w:widowControl", "widow_control"),
        ):
            try:
                layout[key] = _read_on_off_prop(p_pr.find(qn(tag_name)))
            except Exception:
                pass

        return layout

    def _read_bold_state_from_rpr(rpr_el) -> bool | None:
        """Read effective bold state from a run-property element, including CJK bCs."""
        if rpr_el is None:
            return None
        _bold_state = _read_on_off_prop(rpr_el.find(qn("w:b")))
        if _bold_state is None:
            _bold_state = _read_on_off_prop(rpr_el.find(qn("w:bCs")))
        return _bold_state

    def _read_rpr_font_props(rpr_el) -> dict[str, Any]:
        """Extract default font props from a run-properties XML element."""
        _props: dict[str, Any] = {
            "font_size": None,
            "font_family": None,
            "font_weight": None,
            "font_weight_set": False,
            "font_style": None,
            "font_style_set": False,
        }
        if rpr_el is None:
            return _props

        try:
            _sz = rpr_el.find(qn("w:sz"))
            if _sz is None:
                _sz = rpr_el.find(qn("w:szCs"))
            if _sz is not None:
                _raw = _sz.get(qn("w:val")) or _sz.get("val") or ""
                if _raw:
                    _props["font_size"] = round(int(_raw) / 2, 1)
        except Exception:
            pass

        try:
            _rFonts = rpr_el.find(qn("w:rFonts"))
            if _rFonts is not None:
                for _key in ("w:eastAsia", "w:ascii", "w:hAnsi", "w:cs"):
                    _font_name = _rFonts.get(qn(_key), "") or ""
                    if _font_name:
                        _props["font_family"] = _build_css_font_family_stack(_font_name)
                        break
        except Exception:
            pass

        try:
            _bold_state = _read_bold_state_from_rpr(rpr_el)
            if _bold_state is not None:
                _props["font_weight_set"] = True
                _props["font_weight"] = "bold" if _bold_state else "normal"
        except Exception:
            pass

        try:
            _italic_state = _read_on_off_prop(rpr_el.find(qn("w:i")))
            if _italic_state is None:
                _italic_state = _read_on_off_prop(rpr_el.find(qn("w:iCs")))
            if _italic_state is not None:
                _props["font_style_set"] = True
                _props["font_style"] = "italic" if _italic_state else "normal"
        except Exception:
            pass

        return _props

    def _resolve_style_defaults(style_ref) -> dict[str, Any]:
        if style_ref is None or not hasattr(style_ref, "_element"):
            return _EMPTY_STYLE_DEFAULTS

        try:
            _style_id_key = style_ref.style_id or ""
        except Exception:
            _style_id_key = ""
        try:
            _style_name_key = style_ref.name or ""
        except Exception:
            _style_name_key = ""

        if _style_id_key or _style_name_key:
            _cache_key: object = (_style_id_key, _style_name_key)
        else:
            _cache_key = id(style_ref._element)

        _cached = _style_defaults_cache.get(_cache_key)
        if _cached is not None:
            return _cached

        _resolved = dict(_EMPTY_STYLE_DEFAULTS)
        try:
            _resolved["style_name"] = style_ref.name or ""
        except Exception:
            pass
        try:
            _resolved["style_id"] = style_ref.style_id or ""
        except Exception:
            pass

        _style = style_ref
        while _style:
            try:
                _spf = _style.paragraph_format
            except Exception:
                _spf = None

            try:
                _pPr = _style._element.find(qn("w:pPr"))
            except Exception:
                _pPr = None
            _layout_props = _read_paragraph_layout_props_from_ppr(_pPr)

            try:
                _rPr = _style._element.find(qn("w:rPr"))
            except Exception:
                _rPr = None
            _rpr_props = _read_rpr_font_props(_rPr)

            if _spf is not None:
                if _resolved["text_align"] is None:
                    try:
                        _align = _ALIGN_MAP.get(_spf.alignment)
                        if _align:
                            _resolved["text_align"] = _align
                    except Exception:
                        pass
                if _resolved["space_before"] is None:
                    try:
                        _val = _spf.space_before
                        if _val is not None:
                            _resolved["space_before"] = _twips_to_pt(_val.twips)
                    except Exception:
                        pass
                    if _resolved["space_before"] is None and _layout_props["space_before_twips"] is not None:
                        _resolved["space_before"] = _twips_to_pt(_layout_props["space_before_twips"])
                if _resolved["space_after"] is None:
                    try:
                        _val = _spf.space_after
                        if _val is not None:
                            _resolved["space_after"] = _twips_to_pt(_val.twips)
                    except Exception:
                        pass
                    if _resolved["space_after"] is None and _layout_props["space_after_twips"] is not None:
                        _resolved["space_after"] = _twips_to_pt(_layout_props["space_after_twips"])
                if _resolved["line_height"] is None:
                    try:
                        _line_height = _line_spacing_to_css(
                            _spf.line_spacing,
                            _spf.line_spacing_rule,
                        )
                        if _line_height is not None:
                            _resolved["line_height"] = _line_height
                    except Exception:
                        pass

            if _resolved["line_spacing_rule"] is None and _layout_props["line_spacing_rule"] is not None:
                _resolved["line_spacing_rule"] = _layout_props["line_spacing_rule"]
            if _resolved["line_spacing_twips"] is None and _layout_props["line_spacing_twips"] is not None:
                _resolved["line_spacing_twips"] = _layout_props["line_spacing_twips"]
            if _resolved["first_line_indent_twips"] is None and _layout_props["first_line_indent_twips"] is not None:
                _resolved["first_line_indent_twips"] = _layout_props["first_line_indent_twips"]
            if _resolved["left_indent_twips"] is None and _layout_props["left_indent_twips"] is not None:
                _resolved["left_indent_twips"] = _layout_props["left_indent_twips"]
            if _resolved["keep_with_next"] is None and _layout_props["keep_with_next"] is not None:
                _resolved["keep_with_next"] = _layout_props["keep_with_next"]
            if _resolved["keep_together"] is None and _layout_props["keep_together"] is not None:
                _resolved["keep_together"] = _layout_props["keep_together"]
            if _resolved["page_break_before"] is None and _layout_props["page_break_before"] is not None:
                _resolved["page_break_before"] = _layout_props["page_break_before"]
            if _resolved["widow_control"] is None and _layout_props["widow_control"] is not None:
                _resolved["widow_control"] = _layout_props["widow_control"]

            if _resolved["font_size"] is None:
                try:
                    _fsize = _style.font.size
                    if _fsize is not None:
                        _resolved["font_size"] = round(_fsize.pt, 1)
                except Exception:
                    pass
                if _resolved["font_size"] is None and _rpr_props["font_size"] is not None:
                    _resolved["font_size"] = _rpr_props["font_size"]

            if _resolved["font_family"] is None:
                try:
                    if _rpr_props["font_family"]:
                        _resolved["font_family"] = _rpr_props["font_family"]
                    if _resolved["font_family"] is None:
                        _fn = _style.font.name
                        if _fn:
                            _resolved["font_family"] = _build_css_font_family_stack(_fn)
                except Exception:
                    pass

            if _resolved["text_align"] is None:
                try:
                    _pPr = _style._element.find(qn("w:pPr"))
                    if _pPr is not None:
                        _jc = _pPr.find(qn("w:jc"))
                        if _jc is not None:
                            _align = _jc.get(qn("w:val"), "")
                            if _align in ("left", "center", "right", "justify"):
                                _resolved["text_align"] = _align
                            elif _align == "distribute":
                                _resolved["text_align"] = "justify"
                except Exception:
                    pass

            if (
                _resolved["space_before"] is not None
                and _resolved["space_after"] is not None
                and _resolved["line_height"] is not None
                and _resolved["font_size"] is not None
                and _resolved["font_family"] is not None
            ):
                break

            try:
                _style = _style.base_style
            except Exception:
                _style = None

        _style_defaults_cache[_cache_key] = _resolved
        return _resolved

    def _extract_paragraph_layout_semantics(para, style_ref=None) -> dict[str, Any]:
        style_ref = style_ref if style_ref is not None else _resolve_para_style_ref(para)
        style_defaults = _resolve_style_defaults(style_ref)

        try:
            p_pr = para._element.find(qn("w:pPr"))
        except Exception:
            p_pr = None
        direct_layout = _read_paragraph_layout_props_from_ppr(p_pr)

        return {
            "space_before_twips": (
                direct_layout["space_before_twips"]
                if direct_layout["space_before_twips"] is not None
                else _pt_to_twips(style_defaults.get("space_before"))
            ),
            "space_after_twips": (
                direct_layout["space_after_twips"]
                if direct_layout["space_after_twips"] is not None
                else _pt_to_twips(style_defaults.get("space_after"))
            ),
            "line_spacing_rule": direct_layout["line_spacing_rule"] or style_defaults.get("line_spacing_rule"),
            "line_spacing_twips": (
                direct_layout["line_spacing_twips"]
                if direct_layout["line_spacing_twips"] is not None
                else style_defaults.get("line_spacing_twips")
            ),
            "first_line_indent_twips": (
                direct_layout["first_line_indent_twips"]
                if direct_layout["first_line_indent_twips"] is not None
                else style_defaults.get("first_line_indent_twips")
            ),
            "left_indent_twips": (
                direct_layout["left_indent_twips"]
                if direct_layout["left_indent_twips"] is not None
                else style_defaults.get("left_indent_twips")
            ),
            "keep_with_next": (
                direct_layout["keep_with_next"]
                if direct_layout["keep_with_next"] is not None
                else style_defaults.get("keep_with_next")
            ),
            "keep_together": (
                direct_layout["keep_together"]
                if direct_layout["keep_together"] is not None
                else style_defaults.get("keep_together")
            ),
            "page_break_before": (
                direct_layout["page_break_before"]
                if direct_layout["page_break_before"] is not None
                else style_defaults.get("page_break_before")
            ),
            "widow_control": (
                direct_layout["widow_control"]
                if direct_layout["widow_control"] is not None
                else style_defaults.get("widow_control")
            ),
        }

    def _paragraph_layout_data_attrs(para, style_ref=None) -> dict[str, str]:
        semantics = _extract_paragraph_layout_semantics(para, style_ref=style_ref)
        attrs: dict[str, str] = {}

        for key, attr_name in (
            ("space_before_twips", "data-koto-space-before-twips"),
            ("space_after_twips", "data-koto-space-after-twips"),
            ("line_spacing_twips", "data-koto-line-twips"),
            ("first_line_indent_twips", "data-koto-first-line-indent-twips"),
            ("left_indent_twips", "data-koto-left-indent-twips"),
        ):
            value = semantics.get(key)
            if value is not None:
                attrs[attr_name] = str(value)

        line_rule = semantics.get("line_spacing_rule")
        if line_rule:
            attrs["data-koto-line-rule"] = str(line_rule)

        for key, attr_name in (
            ("keep_with_next", "data-koto-keep-next"),
            ("keep_together", "data-koto-keep-lines"),
            ("page_break_before", "data-koto-page-break-before"),
            ("widow_control", "data-koto-widow-control"),
        ):
            value = semantics.get(key)
            if value is not None:
                attrs[attr_name] = "1" if bool(value) else "0"

        return attrs

    def _detect_toc_info(para=None, p_el=None, style_ref=None) -> tuple[bool, str]:
        """Detect whether a paragraph is a TOC entry and return (is_toc, level)."""
        level = "1"
        style_candidates: list[str] = []

        if para is not None:
            _style_defaults = _resolve_style_defaults(
                style_ref if style_ref is not None else _resolve_para_style_ref(para)
            )
            try:
                style_candidates.append(_style_defaults.get("style_name") or "")
            except Exception:
                pass
            try:
                style_candidates.append(_style_defaults.get("style_id") or "")
            except Exception:
                pass
            try:
                if p_el is None:
                    p_el = para._element
            except Exception:
                pass

        if p_el is not None:
            try:
                _pPr = p_el.find(qn("w:pPr"))
                if _pPr is not None:
                    _pSt = _pPr.find(qn("w:pStyle"))
                    if _pSt is not None:
                        style_candidates.append(_pSt.get(qn("w:val")) or "")
            except Exception:
                pass

        _has_toc_anchor = _p_elem_has_toc_anchor(p_el)
        _has_toc_field = _p_elem_has_toc_field(p_el)
        _has_tab = False
        if p_el is not None:
            try:
                _has_tab = p_el.find(".//" + qn("w:tab")) is not None
            except Exception:
                _has_tab = False
        _looks_like_toc_line = _p_elem_looks_like_toc_line(p_el)
        _has_toc_signal = _has_toc_anchor or _has_toc_field or _has_tab or _looks_like_toc_line

        for _sv in style_candidates:
            if _is_toc_style_key(_sv):
                if not _has_toc_signal:
                    continue
                level = _extract_toc_level_from_style(_sv)
                return True, level

        # Fallback for custom style names: require real TOC anchors/fields.
        if p_el is not None:
            try:
                if _has_tab and (_has_toc_anchor or _has_toc_field):
                    return True, "1"
            except Exception:
                pass

        return False, level

    def _color_from_xml(elem) -> str | None:
        """Extract theme/RGB color from a w:color XML element."""
        if elem is None:
            return None
        val = elem.get(qn("w:val"))
        if val and val.lower() not in ("auto", "none", ""):
            if len(val) == 6:
                return "#" + val.upper()
        return None

    def _encode_image_part(part) -> str:
        """Encode an image relationship part to base64 data URI."""
        try:
            img_bytes = part.blob
            content_type = part.content_type or "image/png"
            img_bytes, content_type = _compress_image_bytes(img_bytes, content_type)
            b64 = base64.b64encode(img_bytes).decode("ascii")
            return f"data:{content_type};base64,{b64}"
        except Exception as exc:
            logger.debug("[RichHtml] image encode failed: %s", exc)
            return ""

    def _inline_img_html(drawing_elem, doc) -> str:
        """Render wp:inline drawing as <img> HTML."""
        try:
            blipFill = drawing_elem.find(".//" + qn("a:blip"))
            if blipFill is None:
                return ""
            rId = blipFill.get(qn("r:embed"))
            if not rId:
                return ""
            # Navigate to the part that owns this drawing
            # drawing_elem is inside a <w:r> inside document body
            part = doc.part.related_parts.get(rId)
            if part is None:
                return ""
            src = _encode_image_part(part)
            if not src:
                return ""
            # Get display size — width only; height omitted so the browser
            # preserves the image's natural aspect ratio.
            ext = drawing_elem.find(".//" + qn("wp:extent"))
            style = ""
            if ext is not None:
                cx = int(ext.get("cx", 0))
                if cx:
                    w_px = _emu_to_px(cx)
                    style = f' style="width:{w_px}px;max-width:100%"'
            return f'<img src="{src}" alt=""{style} />'
        except Exception as exc:
            logger.debug("[RichHtml] inline img failed: %s", exc)
            return ""

    def _anchor_img_html(drawing_elem, doc) -> str:
        """Render wp:anchor (floating) drawing as <img> HTML.

        Reads OOXML positioning attributes to reproduce Word's layout:
          - wp:positionH / wp:positionV  → CSS float or margin
          - wp:wrapSquare/Tight          → float (left / right)
          - wp:wrapTopAndBottom          → display:block, centred
          - wp:wrapNone                  → inline-block (behind/in-front)
        Falls back to float:right when no positioning info is present.
        """
        try:
            blipFill = drawing_elem.find(".//" + qn("a:blip"))
            if blipFill is None:
                return ""
            rId = blipFill.get(qn("r:embed"))
            if not rId:
                return ""
            part = doc.part.related_parts.get(rId)
            if part is None:
                return ""
            src = _encode_image_part(part)
            if not src:
                return ""

            # ── Size (width only; height omitted to preserve natural ratio) ──
            ext = drawing_elem.find(".//" + qn("wp:extent"))
            size_style = ""
            if ext is not None:
                cx = int(ext.get("cx", 0))
                if cx:
                    w_px = _emu_to_px(cx)
                    size_style = f"width:{w_px}px;"

            # ── Horizontal alignment ───────────────────────────────────────
            # Read <wp:positionH> / <wp:positionV> to determine layout intent.
            pos_h = drawing_elem.find(qn("wp:positionH"))
            h_align = None
            if pos_h is not None:
                align_el = pos_h.find(qn("wp:align"))
                if align_el is not None and align_el.text:
                    h_align = align_el.text.strip().lower()  # left | center | right | inside | outside

            # ── Wrap mode ─────────────────────────────────────────────────
            # Determine CSS positioning from wrap type.
            has_wrap_square  = drawing_elem.find(qn("wp:wrapSquare"))  is not None
            has_wrap_tight   = drawing_elem.find(qn("wp:wrapTight"))   is not None
            has_wrap_none    = drawing_elem.find(qn("wp:wrapNone"))    is not None
            has_wrap_tb      = drawing_elem.find(qn("wp:wrapTopAndBottom")) is not None

            # ── Build CSS ─────────────────────────────────────────────────
            if has_wrap_none:
                # Behind/in-front of text: render as inline-block centered
                pos_style = "display:inline-block;vertical-align:middle;margin:4px 8px;"
            elif has_wrap_tb:
                # Top-and-bottom wrap: block element, centred on the page
                pos_style = "display:block;margin:10px auto;"
            elif has_wrap_square or has_wrap_tight:
                # Float based on declared horizontal alignment
                if h_align in ("left", "inside"):
                    pos_style = "float:left;margin:0 14px 10px 0;"
                else:
                    # right / outside / unspecified → float right (Word default)
                    pos_style = "float:right;margin:0 0 10px 14px;"
            elif h_align == "center":
                pos_style = "display:block;margin:10px auto;"
            elif h_align == "left":
                pos_style = "float:left;margin:0 14px 10px 0;"
            else:
                # No meaningful positioning data — use float:right as default
                pos_style = "float:right;margin:0 0 10px 14px;"

            full_style = pos_style + size_style + "max-width:100%;"
            return f'<img src="{src}" alt="" style="{full_style}" />'
        except Exception as exc:
            logger.debug("[RichHtml] anchor img failed: %s", exc)
            return ""

    def _run_html(run, doc) -> str:
        """Convert a single w:r run to HTML span(s), handling images and hyperlinks."""
        # Check for drawing (inline image)
        drawing = run._element.find(qn("w:drawing"))
        if drawing is not None:
            inline = drawing.find(qn("wp:inline"))
            anchor = drawing.find(qn("wp:anchor"))
            if inline is not None:
                return _inline_img_html(inline, doc)
            if anchor is not None:
                return _anchor_img_html(anchor, doc)

        def _note_reference_html() -> str:
            markers: list[str] = []
            for tag_name, data_attr in (("w:footnoteReference", "data-koto-footnote-ref"), ("w:endnoteReference", "data-koto-endnote-ref")):
                for ref_el in run._element.findall(qn(tag_name)):
                    note_id = str(ref_el.get(qn("w:id")) or "").strip()
                    if not note_id:
                        continue
                    cls_name = "koto-footnote-ref" if "footnote" in tag_name else "koto-endnote-ref"
                    escaped_id = html.escape(note_id, quote=True)
                    markers.append(
                        f'<sup class="{cls_name}" {data_attr}="{escaped_id}">{escaped_id}</sup>'
                    )
            return "".join(markers)

        note_ref_html = _note_reference_html()
        text = run.text or ""
        if not text:
            deleted_text_nodes = [node.text or "" for node in run._element.findall(qn("w:delText"))]
            if deleted_text_nodes:
                text = "".join(deleted_text_nodes)

        # Resolve enclosing paragraph element once; needed for robust TOC/tab detection.
        _p_el = run._element.getparent()
        while _p_el is not None:
            _local = _p_el.tag.split("}")[-1] if "}" in _p_el.tag else _p_el.tag
            if _local == "p":
                break
            _p_el = _p_el.getparent()

        _is_toc_run, _ = _detect_toc_info(p_el=_p_el)

        _has_tab_elem = run._element.find(qn("w:tab")) is not None
        _has_tab_char = "\t" in text
        _tab_html = ""
        if _has_tab_elem or _has_tab_char:
            _tab_html = '<span class="koto-toc-tab"></span>' if _is_toc_run else ('\u00a0' * 6)

        if not text:
            # Tab character → render appropriately based on context.
            # In TOC entries, render the tab as a CSS flex-spacer span so
            # the page number sits at the right margin (Word dot-leader effect).
            if _has_tab_elem:
                return _tab_html + note_ref_html
            return note_ref_html

        def _esc(_t: str) -> str:
            return (_t.replace("&", "&amp;")
                      .replace("<", "&lt;")
                      .replace(">", "&gt;")
                      .replace('"', "&quot;"))

        tab_segments: list[str] | None = None
        if _has_tab_char:
            # Keep tab placeholders as direct siblings between text fragments,
            # otherwise flex layout (dot leaders + right page number) breaks.
            tab_segments = [_esc(seg) for seg in text.split("\t")]
            text = ""
        else:
            text = _esc(text)

        # Collect inline styles
        styles: list[str] = []
        f = run.font

        # Font family
        # python-docx's run.font.name only returns the Latin/ASCII font.
        # East-Asian font names are stored in w:rFonts w:eastAsia and must
        # be read directly from the XML.  Keep both the localized family name
        # and its ASCII alias in CSS so Chromium can resolve the installed font
        # more like Word does.
        fn = f.name
        ea_font: str = ""
        try:
            _rPr = run._element.find(qn("w:rPr"))
            if _rPr is not None:
                _rFonts = _rPr.find(qn("w:rFonts"))
                if _rFonts is not None:
                    ea_font = _rFonts.get(qn("w:eastAsia"), "") or \
                               _rFonts.get(qn("w:cs"), "") or ""
        except Exception:
            pass
        _font_family_stack = _build_css_font_family_stack(fn, ea_font)
        if _font_family_stack:
            styles.append(f"font-family:{_font_family_stack}")

        # Font size (Pt object → float pt value)
        # Skip for TOC runs — CSS normalizes sizes per-level to avoid inconsistency
        if not _is_toc_run:
            try:
                fsize = f.size
                if fsize is not None:
                    pt_val = round(fsize.pt, 1)
                    styles.append(f"font-size:{pt_val}pt")
            except Exception:
                pass

        # Color
        try:
            color_xml = run._element.find(qn("w:rPr") + "/" + qn("w:color"))
            if color_xml is None:
                # try direct rPr child
                rpr = run._element.find(qn("w:rPr"))
                if rpr is not None:
                    color_xml = rpr.find(qn("w:color"))
            hex_color = _color_from_xml(color_xml)
            if hex_color:
                styles.append(f"color:{hex_color}")
        except Exception:
            try:
                rgb = f.color.rgb
                if rgb:
                    styles.append(f"color:#{rgb}")
            except Exception:
                pass

        # Bold — only explicit run-level bold should style body text here.
        # <w:pPr><w:rPr> is paragraph-mark formatting, not paragraph text styling,
        # so projecting it onto the block makes ordinary body paragraphs look bold.
        # Skip bold entirely for TOC runs — CSS normalizes per-level.
        decorations: list[str] = []
        _run_rpr = run._element.find(qn("w:rPr"))
        _run_bold_state = _read_bold_state_from_rpr(_run_rpr)
        if _run_bold_state is not None and not _is_toc_run:
            styles.append("font-weight:bold" if bool(_run_bold_state) else "font-weight:normal")
        if f.italic:
            styles.append("font-style:italic")
        if f.underline and not _is_toc_run:
            decorations.append("underline")
        if f.strike:
            decorations.append("line-through")
        if decorations:
            styles.append(f"text-decoration:{' '.join(decorations)}")

        # Superscript / Subscript
        if f.superscript:
            styles.append("vertical-align:super;font-size:smaller")
        elif f.subscript:
            styles.append("vertical-align:sub;font-size:smaller")

        # Highlight color (background)
        try:
            highlight_xml = None
            rpr2 = run._element.find(qn("w:rPr"))
            if rpr2 is not None:
                highlight_xml = rpr2.find(qn("w:highlight"))
            if highlight_xml is not None:
                hval = highlight_xml.get(qn("w:val"), "")
                _HL_MAP = {
                    "yellow": "#FFFF00", "green": "#00FF00", "cyan": "#00FFFF",
                    "magenta": "#FF00FF", "blue": "#0000FF", "red": "#FF0000",
                    "darkBlue": "#00008B", "darkCyan": "#008B8B",
                    "darkGreen": "#006400", "darkMagenta": "#8B008B",
                    "darkRed": "#8B0000", "darkYellow": "#808000",
                    "darkGray": "#A9A9A9", "lightGray": "#D3D3D3",
                }
                if hval in _HL_MAP:
                    styles.append(f"background-color:{_HL_MAP[hval]}")
        except Exception:
            pass

        if tab_segments is not None:
            if styles:
                style_str = ";".join(styles)
                _styled = [f'<span style="{style_str}">{seg}</span>' if seg else '' for seg in tab_segments]
                return _tab_html.join(_styled) + note_ref_html
            return _tab_html.join(tab_segments) + note_ref_html

        if styles:
            style_str = ";".join(styles)
            return f'<span style="{style_str}">{text}</span>' + note_ref_html
        return text + note_ref_html

    def _render_inline_hyperlink_html(hyperlink_el, para, doc, toc_class: str = "") -> str:
        from docx.text.run import Run

        rId = hyperlink_el.get(qn("r:id"))
        url = ""
        if rId:
            try:
                url = para.part.relationships[rId].target_ref
            except Exception:
                pass
        if not url:
            anchor_val = hyperlink_el.get(qn("w:anchor"), "")
            if anchor_val:
                url = "#" + anchor_val

        link_inner = ""
        for r_elem in hyperlink_el.findall(qn("w:r")):
            link_inner += _run_html(Run(r_elem, para), doc)
        if not link_inner:
            return ""

        esc_url = url.replace('"', "&quot;")
        target_attr = '' if url.startswith('#') else ' target="_blank"'
        if toc_class:
            link_style = 'display:flex;align-items:baseline;flex:1;min-width:0;color:#1155CC;'
        else:
            link_style = 'color:#1155CC;text-decoration:underline;'
        return (
            f'<a href="{esc_url}"{target_attr} '
            f'style="{link_style}">'
            f'{link_inner}</a>'
        )

    def _docx_revision_data_attrs(review_id: str, action: str, author: str = "", date: str = "") -> str:
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
            f' {name}="{html.escape(value, quote=True)}"'
            for name, value in attrs
            if value
        )

    def _render_docx_revision_html(change_el, para, doc, *, action: str, review_id: str, toc_class: str = "", paired_insert_el=None) -> str:
        deleted_html = _render_inline_children_html(change_el, para, doc, toc_class=toc_class) if change_el is not None else ""
        inserted_html = _render_inline_children_html(paired_insert_el, para, doc, toc_class=toc_class) if paired_insert_el is not None else ""
        author_text = str(
            (paired_insert_el.get(qn("w:author")) if paired_insert_el is not None else "")
            or (change_el.get(qn("w:author")) if change_el is not None else "")
            or ""
        ).strip()
        date_text = str(
            (paired_insert_el.get(qn("w:date")) if paired_insert_el is not None else "")
            or (change_el.get(qn("w:date")) if change_el is not None else "")
            or ""
        ).strip()
        wrapper_attrs = _docx_revision_data_attrs(review_id, action, author_text, date_text)
        if action == "replace":
            if not deleted_html and not inserted_html:
                return ""
            return (
                f'<span class="koto-docx-track-change koto-docx-track-change-replace"{wrapper_attrs}>'
                f'<span class="koto-docx-track-change-delete">{deleted_html}</span>'
                f'<span class="koto-docx-track-change-insert">{inserted_html}</span>'
                '</span>'
            )
        if action == "delete":
            if not deleted_html:
                return ""
            return (
                f'<span class="koto-docx-track-change koto-docx-track-change-delete-only"{wrapper_attrs}>'
                f'<span class="koto-docx-track-change-delete">{deleted_html}</span>'
                '</span>'
            )
        if not inserted_html:
            return ""
        return (
            f'<span class="koto-docx-track-change koto-docx-track-change-insert-only"{wrapper_attrs}>'
            f'<span class="koto-docx-track-change-insert">{inserted_html}</span>'
            '</span>'
        )

    def _render_inline_children_html(container_el, para, doc, toc_class: str = "") -> str:
        from docx.text.run import Run

        parts: list[str] = []
        children = list(container_el)
        index = 0
        skip_tags = {
            "bookmarkStart",
            "bookmarkEnd",
            "proofErr",
            "permStart",
            "permEnd",
            "commentRangeStart",
            "commentRangeEnd",
        }

        while index < len(children):
            child = children[index]
            tag_name = child.tag.split("}")[-1] if "}" in child.tag else child.tag

            if tag_name == "hyperlink":
                parts.append(_render_inline_hyperlink_html(child, para, doc, toc_class=toc_class))
                index += 1
                continue

            if tag_name == "r":
                parts.append(_run_html(Run(child, para), doc))
                index += 1
                continue

            if tag_name == "del":
                change_id = child.get(qn("w:id"), "") or f"inline-del-{index}"
                next_index = index + 1
                while next_index < len(children):
                    next_tag = children[next_index].tag.split("}")[-1] if "}" in children[next_index].tag else children[next_index].tag
                    if next_tag in skip_tags:
                        next_index += 1
                        continue
                    break
                if next_index < len(children):
                    next_child = children[next_index]
                    next_tag = next_child.tag.split("}")[-1] if "}" in next_child.tag else next_child.tag
                    if next_tag == "ins":
                        parts.append(
                            _render_docx_revision_html(
                                child,
                                para,
                                doc,
                                action="replace",
                                review_id=f"docx-revision-{change_id}",
                                toc_class=toc_class,
                                paired_insert_el=next_child,
                            )
                        )
                        index = next_index + 1
                        continue
                parts.append(
                    _render_docx_revision_html(
                        child,
                        para,
                        doc,
                        action="delete",
                        review_id=f"docx-revision-{change_id}",
                        toc_class=toc_class,
                    )
                )
                index += 1
                continue

            if tag_name == "ins":
                change_id = child.get(qn("w:id"), "") or f"inline-ins-{index}"
                parts.append(
                    _render_docx_revision_html(
                        child,
                        para,
                        doc,
                        action="insert",
                        review_id=f"docx-revision-{change_id}",
                        toc_class=toc_class,
                    )
                )
                index += 1
                continue

            index += 1

        return "".join(parts)

    def _para_style(para, style_ref=None) -> dict[str, str]:
        """Extract paragraph CSS properties as a dict."""
        css: dict[str, str] = {}
        pf = para.paragraph_format
        _p_pPr = None
        _para_rpr_props = _read_rpr_font_props(None)
        try:
            _p_pPr = para._element.find(qn("w:pPr"))
            if _p_pPr is not None:
                _para_rpr_props = _read_rpr_font_props(_p_pPr.find(qn("w:rPr")))
        except Exception:
            _p_pPr = None
            _para_rpr_props = _read_rpr_font_props(None)
        _style_defaults = _resolve_style_defaults(
            style_ref if style_ref is not None else _resolve_para_style_ref(para)
        )

        # Alignment — read from paragraph XML directly, then immediate style XML only.
        # Avoid walking the full style inheritance chain: a distant ancestor
        # style (e.g. a title/heading base style) with "center" would otherwise
        # propagate to all body text paragraphs that happen to inherit from it.
        _align_val = None
        try:
            if _p_pPr is not None:
                _p_jc = _p_pPr.find(qn("w:jc"))
                if _p_jc is not None:
                    _align_val = _p_jc.get(qn("w:val"), "")
        except Exception:
            pass
        if not _align_val:
            # Check immediate style only (no inheritance walk)
            _sr = style_ref if style_ref is not None else _resolve_para_style_ref(para)
            if _sr is not None and hasattr(_sr, "_element"):
                try:
                    _st_pPr = _sr._element.find(qn("w:pPr"))
                    if _st_pPr is not None:
                        _st_jc = _st_pPr.find(qn("w:jc"))
                        if _st_jc is not None:
                            _align_val = _st_jc.get(qn("w:val"), "")
                except Exception:
                    pass
        if _align_val in ("center", "right", "justify", "distribute"):
            css["text-align"] = "justify" if _align_val == "distribute" else _align_val
        # "left" is the CSS/browser default; no need to explicitly set it.

        # Space before/after (twips → pt)
        # First try paragraph-level XML; fall back to named style
        def _resolve_spacing(attr_name):
            """Return pt value or None, walking paragraph → style → base_style chain."""
            try:
                val = getattr(pf, attr_name)
                if val is not None:
                    return _twips_to_pt(val.twips)
            except Exception:
                pass
            return _style_defaults.get(attr_name)

        sb = _resolve_spacing("space_before")
        sa = _resolve_spacing("space_after")
        if sb is not None:
            css["margin-top"] = f"{sb}pt"
        if sa is not None:
            css["margin-bottom"] = f"{sa}pt"

        # Line spacing — paragraph XML first, then named style
        _line_height = None
        try:
            _line_height = _line_spacing_to_css(pf.line_spacing, pf.line_spacing_rule)
        except Exception:
            pass
        if _line_height is None:
            _line_height = _style_defaults.get("line_height")
        if _line_height is not None:
            css["line-height"] = _line_height

        # ── Font-size from paragraph style chain ─────────────────────
        # When runs have no explicit font-size, they inherit from the
        # paragraph's block-level style.  Setting font-size on the <p>/<h>
        # tag ensures correct inheritance without bloating every <span>.
        # Also prevents browser-default heading sizes (h1=2em etc.) from
        # overriding the DOCX style's intended size.
        _fs = _para_rpr_props.get("font_size")
        if _fs is None:
            _fs = _style_defaults.get("font_size")
        if _fs is not None:
            css["font-size"] = f"{_fs}pt"

        # ── Font-family from paragraph style chain ────────────────────
        _ff = _para_rpr_props.get("font_family") or _style_defaults.get("font_family")
        if _ff:
            css["font-family"] = _ff

        # Treat paragraph-mark bold asymmetrically:
        # - explicit normal cancels inherited paragraph style bold
        # - explicit bold does not force the whole paragraph bold on import
        # This avoids widespread phantom bold in body/table paragraphs while
        # still honoring explicit unbold overrides from OOXML.
        _fw = None
        if _para_rpr_props.get("font_weight_set") and _para_rpr_props.get("font_weight") == "normal":
            _fw = "normal"
        _direct_sr = style_ref if style_ref is not None else _resolve_para_style_ref(para)
        if _fw is None and _direct_sr is not None:
            _direct_rpr_props = _read_rpr_font_props(None)
            try:
                if hasattr(_direct_sr, "_element"):
                    _direct_rpr_props = _read_rpr_font_props(_direct_sr._element.find(qn("w:rPr")))
            except Exception:
                _direct_rpr_props = _read_rpr_font_props(None)
            if _direct_rpr_props.get("font_weight_set"):
                _fw = _direct_rpr_props.get("font_weight")
            if _fw is None:
                try:
                    _direct_bold = _direct_sr.font.bold
                    if _direct_bold is True:
                        _fw = "bold"
                    elif _direct_bold is False:
                        _fw = "normal"
                except Exception:
                    pass

        if _fw:
            css["font-weight"] = _fw

        _fi = None
        if _para_rpr_props.get("font_style_set") and _para_rpr_props.get("font_style") == "normal":
            _fi = "normal"
        _direct_sr_fi = style_ref if style_ref is not None else _resolve_para_style_ref(para)
        if _fi is None and _direct_sr_fi is not None:
            _direct_rpr_props = _read_rpr_font_props(None)
            try:
                if hasattr(_direct_sr_fi, "_element"):
                    _direct_rpr_props = _read_rpr_font_props(_direct_sr_fi._element.find(qn("w:rPr")))
            except Exception:
                _direct_rpr_props = _read_rpr_font_props(None)
            if _direct_rpr_props.get("font_style_set"):
                _fi = _direct_rpr_props.get("font_style")
            if _fi is None:
                try:
                    _direct_italic = _direct_sr_fi.font.italic
                    if _direct_italic is True:
                        _fi = "italic"
                    elif _direct_italic is False:
                        _fi = "normal"
                except Exception:
                    pass
        if _fi:
            css["font-style"] = _fi

        # First-line indent
        try:
            fli = pf.first_line_indent
            if fli is not None and fli != 0:
                pt_val = _twips_to_pt(fli.twips)
                if pt_val is not None:
                    css["text-indent"] = f"{pt_val}pt"
        except Exception:
            pass

        # Left indent
        try:
            li = pf.left_indent
            if li is not None and li != 0:
                pt_val = _twips_to_pt(li.twips)
                if pt_val is not None:
                    css["padding-left"] = f"{pt_val}pt"
        except Exception:
            pass

        return css

    def _para_html(
        para,
        doc,
        tag: str = "p",
        style_ref=None,
        anchor_id: str | None = None,
        extra_class: str | None = None,
        extra_role: str | None = None,
    ) -> str:
        """Render a paragraph to an HTML block element."""
        style_ref = style_ref if style_ref is not None else _resolve_para_style_ref(para)
        css = _para_style(para, style_ref=style_ref)
        layout_attrs = _paragraph_layout_data_attrs(para, style_ref=style_ref)

        # ── Scan for bookmark IDs (used as TOC link targets) ─────────
        bm_id = (anchor_id or _find_bookmark_id(para._element) or "").strip() or None

        # ── Detect TOC style → CSS class for front-end styling ───────
        toc_class = ""
        _is_toc, _toc_level = _detect_toc_info(
            para=para,
            p_el=para._element,
            style_ref=style_ref,
        )
        if _is_toc:
            toc_class = f"koto-toc-{_toc_level}"

        inner = _render_inline_children_html(para._element, para, doc, toc_class=toc_class)
        if not inner.strip():
            inner = "<br/>"

        _apply_heading_typography_fallback(tag, css, inner)

        style_str = ";".join(f"{k}:{v}" for k, v in css.items())
        # For TOC entries: strip per-paragraph font-size, font-weight, and
        # line-height — the global CSS normalizes these per level so inconsistent
        # Word style inheritance doesn't make entries look different from each other.
        # Keep only font-family and spacing. Then inject display:flex.
        if toc_class:
            # Rebuild style without the properties CSS will normalize
            _skip = {"font-size", "font-weight", "line-height", "margin-top",
                     "margin-bottom", "display", "align-items"}
            toc_parts = [p for p in css.items() if p[0] not in _skip]
            style_str = "display:flex;align-items:baseline;" + ";".join(f"{k}:{v}" for k, v in toc_parts)
        style_attr = f' style="{style_str}"' if style_str else ""
        id_attr = f' id="{bm_id}"' if bm_id else ""
        role_attr = f' data-koto-role="{extra_role}"' if extra_role else ""
        layout_attr = "".join(
            f' {attr_name}="{html.escape(str(attr_value), quote=True)}"'
            for attr_name, attr_value in layout_attrs.items()
        )
        _class_tokens: list[str] = []
        if toc_class:
            _class_tokens.extend(tok for tok in toc_class.split() if tok)
        if extra_class:
            _class_tokens.extend(tok for tok in str(extra_class).split() if tok)
        if _class_tokens:
            _class_tokens = list(dict.fromkeys(_class_tokens))
        class_attr = f' class="{" ".join(_class_tokens)}"' if _class_tokens else ""
        return f"<{tag}{id_attr}{class_attr}{role_attr}{layout_attr}{style_attr}>{inner}</{tag}>"

    def _table_has_visible_borders(tbl_elem) -> bool:
        """Check if a table has any non-nil visible border in w:tblBorders or its table style."""
        tblPr = tbl_elem.find(qn("w:tblPr"))
        if tblPr is None:
            return False
        # Check explicit tblBorders first
        tblBorders = tblPr.find(qn("w:tblBorders"))
        if tblBorders is not None:
            border_tags = ["w:top", "w:left", "w:bottom", "w:right",
                           "w:insideH", "w:insideV"]
            for bt in border_tags:
                b_elem = tblBorders.find(qn(bt))
                if b_elem is not None:
                    val = b_elem.get(qn("w:val"), "none")
                    if val not in ("none", "nil", ""):
                        return True
        # Also check the referenced table style for border definitions
        tblStyle_el = tblPr.find(qn("w:tblStyle"))
        if tblStyle_el is not None:
            # We can't access doc.styles here, but we'll trust _get_tblStyle_border_defaults
            # to resolve this in _table_html. Return True conservatively so CSS is not suppressed.
            return True
        return False

    def _border_elem_to_css(b_el) -> str:
        """Convert a single w:top/w:left/etc. border element to a CSS border value.
        Returns 'none' if explicitly disabled, or a string like '0.5pt solid #000'.
        Returns '' (empty) if the element is missing (meaning: no explicit override).
        """
        if b_el is None:
            return ""
        val = b_el.get(qn("w:val"), "none")
        if val in ("none", "nil", ""):
            return "none"
        sz = b_el.get(qn("w:sz"), "4")
        clr = b_el.get(qn("w:color"), "auto")
        try:
            sz_pt = round(int(sz) / 8, 2)
        except (TypeError, ValueError):
            sz_pt = 0.5
        clr_css = f"#{clr}" if (clr and clr.lower() != "auto") else "#000"
        return f"{sz_pt}pt solid {clr_css}"

    def _get_table_border_defaults(tbl_elem) -> dict:
        """Extract table-level border defaults from w:tblBorders.

        Returns a dict with keys: top, bottom, left, right, insideH, insideV.
        Each value is a CSS border string like '0.5pt solid #000', 'none',
        or None when the element is absent.
        """
        defaults = {"top": None, "bottom": None, "left": None, "right": None,
                    "insideH": None, "insideV": None}
        tblPr = tbl_elem.find(qn("w:tblPr"))
        if tblPr is None:
            return defaults
        tblBorders = tblPr.find(qn("w:tblBorders"))
        if tblBorders is None:
            return defaults
        for key, wtag in (("top", "w:top"), ("bottom", "w:bottom"),
                          ("left", "w:left"), ("right", "w:right"),
                          ("insideH", "w:insideH"), ("insideV", "w:insideV")):
            b_el = tblBorders.find(qn(wtag))
            css = _border_elem_to_css(b_el)
            if css != "":   # only store when element actually exists
                defaults[key] = css
        return defaults

    def _get_tblStyle_border_defaults(tbl_elem, doc) -> dict:
        """Look up the table's referenced style (w:tblStyle) and return its
        tblBorders as a border-defaults dict (same format as _get_table_border_defaults).
        Returns all-None dict if no style, no borders, or any error.
        """
        defaults = {"top": None, "bottom": None, "left": None, "right": None,
                    "insideH": None, "insideV": None}
        try:
            tblPr = tbl_elem.find(qn("w:tblPr"))
            if tblPr is None:
                return defaults
            tblStyle_el = tblPr.find(qn("w:tblStyle"))
            if tblStyle_el is None:
                return defaults
            style_id = tblStyle_el.get(qn("w:val"))
            if not style_id or doc is None:
                return defaults
            # Find the matching style object in the document
            target_style = None
            for st in doc.styles:
                if st.style_id == style_id:
                    target_style = st
                    break
            if target_style is None:
                return defaults
            # Read w:tblBorders from the style's XML element
            style_tblBorders = target_style._element.find(".//" + qn("w:tblBorders"))
            if style_tblBorders is None:
                return defaults
            for key, wtag in (("top", "w:top"), ("bottom", "w:bottom"),
                              ("left", "w:left"), ("right", "w:right"),
                              ("insideH", "w:insideH"), ("insideV", "w:insideV")):
                b_el = style_tblBorders.find(qn(wtag))
                css = _border_elem_to_css(b_el)
                if css != "":
                    defaults[key] = css
        except Exception:
            pass
        return defaults

    def _table_html(tbl, doc, *, max_rows: int | None = None) -> str:
        """Render a docx Table to an HTML <table>."""
        tbl_elem = tbl._tbl

        # Detect border style (check style-level too)
        has_borders = _table_has_visible_borders(tbl_elem)

        # Collect column widths from <w:tblGrid>
        tblGrid = tbl_elem.find(qn("w:tblGrid"))
        col_widths_twips: list[int] = []
        if tblGrid is not None:
            for gc in tblGrid.findall(qn("w:gridCol")):
                w_val = gc.get(qn("w:w"))
                try:
                    col_widths_twips.append(int(w_val))
                except (TypeError, ValueError):
                    col_widths_twips.append(0)

        total_w = sum(col_widths_twips) or 1

        # Extract table-level border defaults for per-cell inheritance
        tbl_border_defs = _get_table_border_defaults(tbl_elem)
        # If the table has no explicit tblBorders, inherit from the referenced table style
        if all(v is None for v in tbl_border_defs.values()):
            style_borders = _get_tblStyle_border_defaults(tbl_elem, doc)
            if any(v is not None for v in style_borders.values()):
                tbl_border_defs = style_borders
        all_row_elems = tbl_elem.findall(qn("w:tr"))
        table_is_truncated = bool(max_rows and len(all_row_elems) > max_rows)
        render_row_elems = all_row_elems[:max_rows] if table_is_truncated else all_row_elems
        num_rows = len(render_row_elems)
        num_cols_grid = len(col_widths_twips) or 1

        # Pre-compute pixel widths per grid column (for ProseMirror colwidth).
        # ProseMirror expects absolute pixel values.  1 twip = 1/20 pt; 1 pt = 96/72 px → px = twips/15.
        col_widths_px: list[int] = [max(1, round(t / 15)) for t in col_widths_twips] if col_widths_twips else []

        # Table-level default cell margins (OOXML defaults: 0pt vert, 5.4pt horiz)
        _WORD_DEFAULT_CELL_MAR = {"top": 0.0, "bottom": 0.0, "left": 5.4, "right": 5.4}
        _tbl_cell_mar: dict[str, float] = dict(_WORD_DEFAULT_CELL_MAR)
        _tblPr = tbl_elem.find(qn("w:tblPr"))
        if _tblPr is not None:
            _tblCellMar = _tblPr.find(qn("w:tblCellMar"))
            if _tblCellMar is not None:
                for _side in ("top", "bottom", "left", "right"):
                    _el = _tblCellMar.find(qn(f"w:{_side}"))
                    if _el is None and _side == "left":
                        _el = _tblCellMar.find(qn("w:start"))
                    if _el is None and _side == "right":
                        _el = _tblCellMar.find(qn("w:end"))
                    if _el is not None:
                        try:
                            _tbl_cell_mar[_side] = round(int(_el.get(qn("w:w"), 0)) / 20, 2)
                        except (TypeError, ValueError):
                            pass

        parts: list[str] = ["<table"]
        # border-collapse:collapse is always needed so cell borders merge cleanly.
        # Don't set a table-level border — all borders are expressed per-cell.
        parts.append(' class="koto-docx-table" style="border-collapse:collapse;width:100%;">')

        # Emit <colgroup>/<col> for visual percentage widths (non-TipTap renderers).
        # TipTap strips these, so we also emit data-colwidth on each <td> below.
        if col_widths_twips:
            parts.append("<colgroup>")
            for w_twips in col_widths_twips:
                pct = round(w_twips / total_w * 100, 2)
                parts.append(f'<col style="width:{pct}%">')
            parts.append("</colgroup>")

        # Track merged cells: set of (row_idx, col_idx) that are "occupied"
        # We use raw XML iteration to avoid python-docx's grid-filling behaviour:
        # row.cells repeats the same _Cell object for each grid column it spans,
        # causing duplicate <td> entries for horizontally merged cells.
        # row_elem.findall(qn("w:tc")) returns exactly one element per cell definition.
        for ri, row_elem in enumerate(render_row_elems):
            row_h_rule = None
            row_h = None
            try:
                trPr = row_elem.find(qn("w:trPr"))
                if trPr is not None:
                    trH = trPr.find(qn("w:trHeight"))
                    if trH is not None:
                        row_h = trH.get(qn("w:val"))
                        row_h_rule = trH.get(qn("w:hRule"), "auto")
            except Exception:
                pass

            row_style = ""
            if row_h and row_h_rule == "exact":
                try:
                    h_pt = _twips_to_pt(int(row_h))
                    # Browser table layout handles Word's exact row heights poorly:
                    # once imported widths/fonts differ slightly, fixed <tr> heights
                    # make cell text overflow into adjacent rows. Keep the metadata for
                    # future export/debugging, but let the browser size the row naturally.
                    row_style = f' data-koto-row-height="{h_pt}pt"'
                except Exception:
                    pass

            parts.append(f"<tr{row_style}>")
            tc_elems = row_elem.findall(qn("w:tc"))
            for ci, cell_elem in enumerate(tc_elems):

                # Skip vertically merged continuation cells
                tcPr = cell_elem.find(qn("w:tcPr"))
                vmerge = tcPr.find(qn("w:vMerge")) if tcPr is not None else None
                if vmerge is not None and vmerge.get(qn("w:val")) != "restart":
                    continue

                # colspan / rowspan
                colspan = 1
                rowspan = 1
                cell_style_parts: list[str] = []

                if tcPr is not None:
                    # colspan via gridSpan
                    gs = tcPr.find(qn("w:gridSpan"))
                    if gs is not None:
                        try:
                            colspan = int(gs.get(qn("w:val"), 1))
                        except (TypeError, ValueError):
                            colspan = 1

                    # rowspan: count how many rows below have vMerge (continue)
                    try:
                        col_idx_in_grid = 0
                        # Find this cell's column index in the grid
                        for prev_tc in tc_elems:
                            if prev_tc is cell_elem:
                                break
                            prev_gs_elem = prev_tc.find(qn("w:tcPr") + "/" + qn("w:gridSpan"))
                            if prev_gs_elem is not None:
                                try:
                                    col_idx_in_grid += int(prev_gs_elem.get(qn("w:val"), 1))
                                except (TypeError, ValueError):
                                    col_idx_in_grid += 1
                            else:
                                col_idx_in_grid += 1

                        # Walk subsequent rows looking for vMerge continuation
                        for next_row_elem in render_row_elems[ri + 1:]:
                            next_cells = next_row_elem.findall(qn("w:tc"))
                            target_ci = 0
                            found_continue = False
                            for nc in next_cells:
                                if target_ci == col_idx_in_grid:
                                    nc_vmerge = nc.find(qn("w:tcPr") + "/" + qn("w:vMerge"))
                                    if nc_vmerge is not None and nc_vmerge.get(qn("w:val")) != "restart":
                                        rowspan += 1
                                        found_continue = True
                                    break
                                nc_gs = nc.find(qn("w:tcPr") + "/" + qn("w:gridSpan"))
                                try:
                                    target_ci += int(nc_gs.get(qn("w:val"), 1)) if nc_gs is not None else 1
                                except (TypeError, ValueError):
                                    target_ci += 1
                            if not found_continue:
                                break
                    except Exception:
                        pass

                    # Background color
                    shd = tcPr.find(qn("w:shd"))
                    if shd is not None:
                        fill = shd.get(qn("w:fill"), "")
                        if fill and fill.upper() not in ("AUTO", "FFFFFF", ""):
                            cell_style_parts.append(f"background-color:#{fill}")

                    # Cell width (convert dxa twips → percentage of table width)
                    tcW = tcPr.find(qn("w:tcW"))
                    if tcW is not None:
                        w_val = tcW.get(qn("w:w"))
                        w_type = tcW.get(qn("w:type"), "dxa")
                        try:
                            if w_type == "pct" and w_val:
                                pct = round(int(w_val) / 5000 * 100, 2)
                                cell_style_parts.append(f"width:{pct}%")
                            elif w_type == "dxa" and w_val and total_w > 1:
                                pct = round(int(w_val) / total_w * 100, 2)
                                cell_style_parts.append(f"width:{pct}%")
                        except (TypeError, ValueError):
                            pass

                    # Vertical alignment
                    vAlign = tcPr.find(qn("w:vAlign"))
                    if vAlign is not None:
                        v_val = vAlign.get(qn("w:val"), "")
                        _VA_MAP = {"top": "top", "center": "middle", "bottom": "bottom"}
                        va_css = _VA_MAP.get(v_val)
                        if va_css:
                            cell_style_parts.append(f"vertical-align:{va_css}")

                # Cell borders — compute effective border per side by combining
                # cell-level overrides with table-level defaults.
                # Mirrors Word's border resolution order:
                #   1. Explicit tcBorders override → use as-is
                #   2. Outer edges (first/last row/col) → table top/bottom/left/right default
                #   3. Inner edges → table insideH / insideV default
                #   4. No definition anywhere → emit 'none' to suppress CSS fallback
                tcBorders = tcPr.find(qn("w:tcBorders")) if tcPr is not None else None

                # Determine this cell's grid column index for outer-edge detection
                try:
                    _cell_grid_col = 0
                    for _prev in tc_elems:
                        if _prev is cell_elem:
                            break
                        _prev_gs = _prev.find(qn("w:tcPr") + "/" + qn("w:gridSpan"))
                        _cell_grid_col += int(_prev_gs.get(qn("w:val"), 1)) if _prev_gs is not None else 1
                    _cell_grid_end_col = _cell_grid_col + colspan - 1
                except Exception:
                    _cell_grid_col = ci
                    _cell_grid_end_col = ci

                _is_first_row = (ri == 0)
                _is_last_row  = (ri == num_rows - 1)
                _is_first_col = (_cell_grid_col == 0)
                _is_last_col  = (_cell_grid_end_col >= num_cols_grid - 1)

                _side_map = {
                    "top":    ("w:top",    "insideH" if not _is_first_row else "top"),
                    "bottom": ("w:bottom", "insideH" if not _is_last_row  else "bottom"),
                    "left":   ("w:left",   "insideV" if not _is_first_col else "left"),
                    "right":  ("w:right",  "insideV" if not _is_last_col  else "right"),
                }
                _border_css_values: list[str] = []
                for side, (wtag, tbl_def_key) in _side_map.items():
                    # 1. Cell-level explicit override
                    cell_b = None
                    if tcBorders is not None:
                        cell_b = _border_elem_to_css(tcBorders.find(qn(wtag)))
                    # 2. Table-level default (fallback when no cell border or sub-element absent)
                    if cell_b is None or cell_b == "":
                        cell_b = tbl_border_defs.get(tbl_def_key)
                    # 3. Emit (including 'none' to suppress CSS fallback border)
                    if cell_b:
                        _border_css_values.append(cell_b)
                        cell_style_parts.append(f"border-{side}:{cell_b}")
                    else:
                        _border_css_values.append("none")
                        cell_style_parts.append(f"border-{side}:none")

                # Cell padding — per-cell <w:tcMar> overrides table-level <w:tblCellMar>,
                # which itself overrides the OOXML default (0pt top/bottom, 5.4pt left/right).
                _cell_pad = dict(_tbl_cell_mar)
                _tcMar = tcPr.find(qn("w:tcMar")) if tcPr is not None else None
                if _tcMar is not None:
                    for _side in ("top", "bottom", "left", "right"):
                        _el = _tcMar.find(qn(f"w:{_side}"))
                        if _el is None and _side == "left":
                            _el = _tcMar.find(qn("w:start"))
                        if _el is None and _side == "right":
                            _el = _tcMar.find(qn("w:end"))
                        if _el is not None:
                            try:
                                _cell_pad[_side] = round(int(_el.get(qn("w:w"), 0)) / 20, 2)
                            except (TypeError, ValueError):
                                pass
                _pt = _cell_pad["top"]; _pb = _cell_pad["bottom"]
                _pl = _cell_pad["left"]; _pr = _cell_pad["right"]
                if _pt == _pb == 0 and _pl == _pr:
                    cell_style_parts.append(f"padding:0 {_pr}pt")
                elif _pt == _pb and _pl == _pr:
                    cell_style_parts.append(f"padding:{_pt}pt {_pr}pt")
                else:
                    cell_style_parts.append(f"padding:{_pt}pt {_pr}pt {_pb}pt {_pl}pt")

                cell_style = ";".join(cell_style_parts)
                td_attrs = f' style="{cell_style}"'
                if _border_css_values and all(_val.strip().lower() == "none" for _val in _border_css_values):
                    td_attrs += ' data-koto-borderless-cell="true"'
                if colspan > 1:
                    td_attrs += f' colspan="{colspan}"'
                if rowspan > 1:
                    td_attrs += f' rowspan="{rowspan}"'

                # Emit data-colwidth for ProseMirror table column resize.
                # colwidth is an array of pixel values, one per grid column the cell spans.
                if col_widths_px:
                    try:
                        _cw_start = 0
                        for _prev in tc_elems:
                            if _prev is cell_elem:
                                break
                            _prev_gs = _prev.find(qn("w:tcPr") + "/" + qn("w:gridSpan"))
                            _cw_start += int(_prev_gs.get(qn("w:val"), 1)) if _prev_gs is not None else 1
                        _cw_vals = col_widths_px[_cw_start:_cw_start + colspan]
                        if _cw_vals:
                            td_attrs += f' data-colwidth="{",".join(str(v) for v in _cw_vals)}"'
                    except Exception:
                        pass

                # Inner cell content: paragraphs (iterate raw XML to avoid
                # table-in-cell issues with python-docx's Paragraph() objects)
                cell_inner: list[str] = []
                for p_elem in cell_elem.findall(qn("w:p")):
                    from docx.text.paragraph import Paragraph as _Paragraph
                    cell_para = _Paragraph(p_elem, doc)
                    cell_inner.append(_para_html(cell_para, doc, "p"))
                # Ensure every cell has at least one child so ProseMirror
                # normalisation does not create phantom empty cells.
                if not cell_inner:
                    cell_inner = ["<p></p>"]
                parts.append(f"<td{td_attrs}>{''.join(cell_inner)}</td>")

            parts.append("</tr>")
        if table_is_truncated:
            remaining_rows = max(0, len(all_row_elems) - len(render_row_elems))
            parts.append(
                "<tr data-koto-preview-more=\"true\">"
                f"<td colspan=\"{num_cols_grid}\" "
                'style="padding:6pt 5.4pt;border-top:1px dashed #aeb7c6;'
                'border-bottom:none;border-left:none;border-right:none;'
                'background:#f6f8fb;color:#5f6b7a;font-style:italic;">'
                f"表格其余 {remaining_rows} 行正在后台加载…"
                "</td></tr>"
            )
        parts.append("</table>")
        return "".join(parts)

    def _section_html(section_obj, doc, cls: str) -> str:
        """Render a header or footer to HTML.

        Handles:
        - Multi-paragraph headers/footers
        - Tab-based left/center/right alignment converted to flex layout
        - PAGE/NUMPAGES field codes replaced by dynamic placeholder spans
          (the TipTap NodeView updates .koto-hdr-page-num per page)
        - Paragraphs that contain only field chars but no literal text
        """
        try:
            paras = section_obj.paragraphs
            if not paras:
                return ""

            def _has_content(p) -> bool:
                """True if the paragraph has visible text OR field chars."""
                if p.text.strip():
                    return True
                xml = p._element.xml if hasattr(p._element, "xml") else ""
                return ("fldChar" in xml or "instrText" in xml)

            def _tabs_to_flex(p_html: str) -> str:
                """Convert tab-based header/footer to a flex row.

                Word headers commonly use tabs for left/center/right alignment.
                We detect <span> elements that contain only tab characters and
                use them as separators to create a flex layout.
                """
                import re as _re
                # Check if it contains tab characters at all
                if '\t' not in p_html:
                    return p_html
                m = _re.match(r'(<p[^>]*>)(.*)(</p>)$', p_html, _re.DOTALL)
                if not m:
                    return p_html
                open_tag, inner, close_tag = m.group(1), m.group(2), m.group(3)
                # Replace <span ...>\t</span> with a special marker
                _TAB_MARKER = '\x00TAB\x00'
                # Match spans containing only a tab (with optional trailing whitespace)
                inner = _re.sub(r'<span[^>]*>\s*\t\s*</span>', _TAB_MARKER, inner)
                # Also handle bare tab characters between spans
                inner = inner.replace('\t', _TAB_MARKER)
                parts = inner.split(_TAB_MARKER)
                parts = [p.strip() for p in parts]
                if len(parts) < 2:
                    return p_html
                # Build flex container
                flex_style = 'display:flex;justify-content:space-between;align-items:baseline;width:100%'
                if 'style="' in open_tag:
                    open_tag = open_tag.replace('style="', f'style="{flex_style};', 1)
                else:
                    open_tag = open_tag[:-1] + f' style="{flex_style}">'
                spans = []
                for i, part in enumerate(parts):
                    if not part:
                        part = '&nbsp;'
                    align = 'left' if i == 0 else ('right' if i == len(parts) - 1 else 'center')
                    spans.append(f'<span class="koto-hdr-col" style="text-align:{align};flex-shrink:0">{part}</span>')
                return open_tag + ''.join(spans) + close_tag

            def _build_field_aware_inner(p) -> str:
                """Build the inner HTML for a header/footer paragraph.

                Unlike _para_html (which renders all w:t text), this function
                handles complex field sequences (PAGE, NUMPAGES) by:
                  - Skipping the cached result runs between fldChar/separate
                    and fldChar/end
                  - Injecting a koto-hdr-page-num / koto-hdr-num-pages span
                    in their place so the TipTap NodeView can update them

                Non-field runs are delegated to _run_html.
                """
                from docx.text.run import Run as _Run
                from docx.text.paragraph import Paragraph as _Para

                parts: list[str] = []
                # Complex-field tracking state
                _in_field = False
                _after_sep = False
                _cur_instr: list[str] = []

                for child in p._element:
                    tag_name = child.tag.split("}")[-1] if "}" in child.tag else child.tag

                    if tag_name == "hyperlink":
                        # Hyperlinks are rare in headers/footers; render normally.
                        rId = child.get(qn("r:id"))
                        url = ""
                        if rId:
                            try:
                                url = p.part.relationships[rId].target_ref
                            except Exception:
                                pass
                        if not url:
                            anchor_val = child.get(qn("w:anchor"), "")
                            if anchor_val:
                                url = "#" + anchor_val
                        link_inner = ""
                        for r_elem in child.findall(qn("w:r")):
                            run_obj = _Run(r_elem, p)
                            link_inner += _run_html(run_obj, doc)
                        if link_inner:
                            esc_url = url.replace('"', "&quot;")
                            target_attr = '' if url.startswith('#') else ' target="_blank"'
                            parts.append(
                                f'<a href="{esc_url}"{target_attr} '
                                f'style="color:#1155CC;text-decoration:underline;">'
                                f'{link_inner}</a>'
                            )
                        continue

                    if tag_name != "r":
                        continue

                    # --- Handle w:r run ---
                    fldChar_el = child.find(qn("w:fldChar"))
                    instrText_el = child.find(qn("w:instrText"))

                    if fldChar_el is not None:
                        ftype = fldChar_el.get(qn("w:fldCharType"), "")
                        if ftype == "begin":
                            _in_field = True
                            _after_sep = False
                            _cur_instr = []
                        elif ftype == "separate" and _in_field:
                            _after_sep = True
                        elif ftype == "end" and _in_field:
                            # Emit the appropriate dynamic span
                            instr = " ".join(_cur_instr).strip().upper()
                            instr_words = set(instr.split())
                            if "PAGE" in instr_words and "NUMPAGES" not in instr_words:
                                parts.append(
                                    '<span class="koto-hdr-page-num" '
                                    'style="font-size:inherit;color:inherit" '
                                    'contenteditable="false">1</span>'
                                )
                            elif "NUMPAGES" in instr_words or "SECTIONPAGES" in instr_words:
                                parts.append(
                                    '<span class="koto-hdr-num-pages" '
                                    'style="font-size:inherit;color:inherit" '
                                    'contenteditable="false">1</span>'
                                )
                            _in_field = False
                            _after_sep = False
                        # fldChar runs never contain visible text — skip rendering
                        continue

                    if instrText_el is not None:
                        # instrText runs: collect instruction, no visible output
                        if _in_field and not _after_sep:
                            _cur_instr.append(instrText_el.text or "")
                        continue

                    if _in_field and _after_sep:
                        # Cached field result — suppress: dynamic span was injected above
                        continue

                    # Regular run — delegate to normal renderer
                    run_obj = _Run(child, p)
                    parts.append(_run_html(run_obj, doc))

                return "".join(parts)

            texts = []
            for p in paras:
                if not _has_content(p):
                    continue
                # Build inner HTML with field-aware rendering
                inner = _build_field_aware_inner(p)
                if not inner.strip():
                    inner = "<br/>"

                # Build block-level CSS (alignment, spacing, font) via _para_style
                css = _para_style(p)
                style_str = ";".join(f"{k}:{v}" for k, v in css.items())
                style_attr = f' style="{style_str}"' if style_str else ""

                p_html = f'<p class="{cls}"{style_attr}>{inner}</p>'

                # _run_html replaces w:tab with 6 × &nbsp; for non-TOC runs,
                # but we need actual \t characters for _tabs_to_flex detection.
                _nbsp6 = '\u00a0' * 6
                p_html = p_html.replace(_nbsp6, '\t')
                # Convert tab-based alignment to flex layout
                p_html = _tabs_to_flex(p_html)
                texts.append(p_html)
            if not texts:
                return ""
            return "".join(texts)
        except Exception:
            return ""

    def _detect_outline_level(para, p_el, style_ref=None) -> tuple[str | None, bool]:
        """Detect heading level only from paragraph-level w:outlineLvl metadata.

        Direct heading styles are handled separately by `_classify_paragraph_block`.
        Returning `via_outlinelvl=True` means callers must still validate that the
        paragraph is short-form structural content rather than body prose that only
        carries outline metadata.
        """
        # 1) Check paragraph-level pPr/outlineLvl (most authoritative).
        #    Word writes this on each heading paragraph.  We trust it directly;
        #    the caller applies a length guard for h2–h6.
        try:
            pPr = p_el.find(qn("w:pPr"))
            if pPr is not None:
                olvl = pPr.find(qn("w:outlineLvl"))
                if olvl is not None:
                    val = olvl.get(qn("w:val"))
                    if val is not None:
                        lvl = int(val)
                        if lvl == 9:
                            return None, False  # 9 = body text
                        if 0 <= lvl <= 5:
                            return f"h{lvl + 1}", True  # True = caller applies length guard
        except Exception:
            pass
        return None, False

    # ── List tracking ────────────────────────────────────────────────────────
    # We process the document body as a flat list of block elements.
    # When we encounter paragraphs with numPr (list items), we group
    # consecutive same-numId items into <ul>/<ol>.

    from docx.oxml.ns import qn as _qn  # already imported as qn above

    doc = Document(file_path)
    body_parts: list[str] = []
    preview_units_limit = (
        _DOCX_PREVIEW_TARGET_PAGES * _DOCX_PREVIEW_UNITS_PER_PAGE
        if progressive_preview
        else None
    )
    preview_units_used = 0
    preview_truncated = False

    # NOTE: Header no longer prepended to body — rendered per-page by NodeView.

    # ── Iterate body elements ─────────────────────────────────────────────
    # Use document.element.body children to interleave paragraphs and tables
    from docx.text.paragraph import Paragraph
    from docx.table import Table

    # Buffer for list grouping
    current_list_id: int | None = None
    current_list_tag: str = "ul"
    current_list_items: list[str] = []

    def _record_preview_units(units: int) -> None:
        nonlocal preview_units_used
        if preview_units_limit is not None:
            preview_units_used += max(1, units)

    def _would_exceed_preview(units: int) -> bool:
        if preview_units_limit is None:
            return False
        if not body_parts:
            return False
        return (preview_units_used + max(1, units)) > preview_units_limit

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

    def _estimate_table_units(tbl_el) -> int:
        row_count = len(tbl_el.findall(qn("w:tr")))
        cell_count = len(tbl_el.findall(".//" + qn("w:tc")))
        return max(6, min(220, row_count * 2 + math.ceil(cell_count / 24)))

    def _flush_list() -> bool:
        nonlocal current_list_id, current_list_tag, current_list_items
        if current_list_items:
            _list_units = max(2, min(24, len(current_list_items) * 2))
            if _would_exceed_preview(_list_units):
                return False
            body_parts.append(
                f"<{current_list_tag}>"
                + "".join(f"<li>{item}</li>" for item in current_list_items)
                + f"</{current_list_tag}>"
            )
            _record_preview_units(_list_units)
        current_list_id = None
        current_list_items = []
        return True

    stop_render = False
    body_elem = doc.element.body
    current_section_idx = 0
    for child_elem in body_elem:
        if stop_render:
            break
        tag_local = child_elem.tag.split("}")[-1] if "}" in child_elem.tag else child_elem.tag

        if tag_local == "p":
            para = Paragraph(child_elem, doc)
            style_ref = _resolve_para_style_ref(para)
            style_defaults = _resolve_style_defaults(style_ref)

            # Check for list (numPr)
            numPr = child_elem.find(qn("w:pPr") + "/" + qn("w:numPr"))
            if numPr is None:
                pPr = child_elem.find(qn("w:pPr"))
                if pPr is not None:
                    numPr = pPr.find(qn("w:numPr"))

            if numPr is not None:
                numId_elem = numPr.find(qn("w:numId"))
                ilvl_elem = numPr.find(qn("w:ilvl"))
                num_id = int(numId_elem.get(qn("w:val"), 0)) if numId_elem is not None else 0
                ilvl = int(ilvl_elem.get(qn("w:val"), 0)) if ilvl_elem is not None else 0

                # Determine list type from numbering.xml (best-effort)
                list_tag = "ul"
                try:
                    numbering_part = doc.part.numbering_part
                    if numbering_part is not None:
                        num_elem = numbering_part._element.find(
                            f'.//{qn("w:num")}[@{qn("w:numId")}="{num_id}"]'
                        )
                        if num_elem is not None:
                            abstractNumId_elem = num_elem.find(qn("w:abstractNumId"))
                            if abstractNumId_elem is not None:
                                abs_id = abstractNumId_elem.get(qn("w:val"), "")
                                abs_num = numbering_part._element.find(
                                    f'.//{qn("w:abstractNum")}[@{qn("w:abstractNumId")}="{abs_id}"]'
                                )
                                if abs_num is not None:
                                    lvl = abs_num.find(
                                        f'.//{qn("w:lvl")}[@{qn("w:ilvl")}="{ilvl}"]'
                                    )
                                    if lvl is not None:
                                        numFmt = lvl.find(qn("w:numFmt"))
                                        if numFmt is not None:
                                            fmt_val = numFmt.get(qn("w:val"), "")
                                            if fmt_val in (
                                                "decimal", "lowerLetter", "upperLetter",
                                                "lowerRoman", "upperRoman", "chineseCounting",
                                            ):
                                                list_tag = "ol"
                except Exception:
                    pass

                if num_id != current_list_id or list_tag != current_list_tag:
                    if not _flush_list():
                        preview_truncated = True
                        stop_render = True
                        break
                    current_list_id = num_id
                    current_list_tag = list_tag

                # Render list item content (without block tag wrapper)
                current_list_items.append(_render_inline_children_html(child_elem, para, doc) or "&nbsp;")
                continue

            # Not a list item — flush pending list
            if not _flush_list():
                preview_truncated = True
                stop_render = True
                break

            # Check for an explicit page break (<w:br w:type="page"/>) inside
            # any run of this paragraph.  These are emitted as a block-level
            # separator *after* the paragraph so the frontend can position
            # the page-break overlay exactly at the right spot.
            _has_explicit_pb = any(
                br.get(qn("w:type"), "") == "page"
                for br in child_elem.findall(".//" + qn("w:br"))
            )

            # Also detect section breaks embedded in this paragraph's
            # properties (<w:pPr><w:sectPr>...<w:type w:val="nextPage"/>).
            # Word uses these to end a section on a new page (e.g. TOC boundary).
            # Sections with type="continuous" do NOT force a new page.
            _has_section_pb = False
            try:
                _pPr = child_elem.find(qn("w:pPr"))
                if _pPr is not None:
                    _sectPr = _pPr.find(qn("w:sectPr"))
                    if _sectPr is not None:
                        # OOXML: section type is a CHILD element, not an attribute:
                        #   <w:sectPr><w:type w:val="nextPage"/></w:sectPr>
                        _type_el = _sectPr.find(qn("w:type"))
                        _stype = _type_el.get(qn("w:val"), "nextPage") if _type_el is not None else "nextPage"
                        if _stype != "continuous":
                            _has_section_pb = True
            except Exception:
                pass

            block_tag, block_role = _classify_paragraph_block(
                para,
                child_elem,
                style_ref=style_ref,
                style_defaults=style_defaults,
            )

            _para_units = _estimate_paragraph_units(para)
            if _would_exceed_preview(_para_units):
                preview_truncated = True
                stop_render = True
                break

            heading_anchor_id = _resolve_body_heading_anchor(child_elem, block_tag, block_role)
            if _should_emit_heading_manifest_entry(block_tag, block_role, child_elem, style_defaults, style_ref):
                heading_anchor_id = _record_body_heading(child_elem, block_tag, anchor_id=heading_anchor_id)
            body_parts.append(
                _para_html(
                    para,
                    doc,
                    block_tag,
                    style_ref=style_ref,
                    anchor_id=heading_anchor_id,
                    extra_class="koto-visual-title" if block_role == "visual_title" else None,
                    extra_role=None if block_role == "body" else block_role,
                )
            )
            _record_preview_units(_para_units)

            # Emit page-break marker (hard break or section break).
            if _has_explicit_pb or _has_section_pb:
                if _would_exceed_preview(1):
                    preview_truncated = True
                    stop_render = True
                    break
                next_section_idx = current_section_idx + 1 if _has_section_pb else current_section_idx
                body_parts.append(
                    '<div data-page-break="true" '
                    f'data-section-idx="{next_section_idx}" '
                    f'data-current-section-idx="{current_section_idx}" '
                    f'data-next-section-idx="{next_section_idx}" '
                    'class="koto-page-break" '
                    'contenteditable="false"></div>'
                )
                _record_preview_units(1)
                current_section_idx = next_section_idx

        elif tag_local == "tbl":
            if not _flush_list():
                preview_truncated = True
                stop_render = True
                break
            _table_units = _estimate_table_units(child_elem)
            _table_row_limit = None
            if preview_units_limit is not None:
                _remaining_units = max(0, preview_units_limit - preview_units_used)
                if body_parts and _remaining_units < _table_units:
                    preview_truncated = True
                    stop_render = True
                    break
                if not body_parts and _remaining_units <= _table_units:
                    _table_row_limit = max(4, min(_DOCX_PREVIEW_MAX_TABLE_ROWS, max(4, _remaining_units // 2 or 4)))
                    preview_truncated = True
            tbl = Table(child_elem, doc)
            body_parts.append(_table_html(tbl, doc, max_rows=_table_row_limit))
            if _table_row_limit is not None:
                _record_preview_units(max(6, _table_row_limit * 2))
                stop_render = True
            else:
                _record_preview_units(_table_units)

        elif tag_local == "sdt":
            # Structured Document Tag — render inner content
            if not _flush_list():
                preview_truncated = True
                stop_render = True
                break
            # Detect TOC SDT for semantic wrapper
            _is_toc_sdt = False
            try:
                _sdtPr = child_elem.find(qn("w:sdtPr"))
                if _sdtPr is not None:
                    _dpg = _sdtPr.find(".//" + qn("w:docPartGallery"))
                    if _dpg is not None:
                        _gval = _dpg.get(qn("w:val"), "")
                        if "Table of Contents" in _gval or "目录" in _gval:
                            _is_toc_sdt = True
            except Exception:
                pass
            if _is_toc_sdt:
                body_parts.append('<div class="koto-toc">')
                _record_preview_units(1)
            sdtContent = child_elem.find(qn("w:sdtContent"))
            if sdtContent is not None:
                for sdt_child in sdtContent:
                    sdt_tag = sdt_child.tag.split("}")[-1] if "}" in sdt_child.tag else sdt_child.tag
                    if sdt_tag == "p":
                        para = Paragraph(sdt_child, doc)
                        style_ref = _resolve_para_style_ref(para)
                        style_defaults = _resolve_style_defaults(style_ref)
                        _btag, _block_role = _classify_paragraph_block(
                            para,
                            sdt_child,
                            style_ref=style_ref,
                            style_defaults=style_defaults,
                        )
                        _para_units = _estimate_paragraph_units(para)
                        if _would_exceed_preview(_para_units):
                            preview_truncated = True
                            stop_render = True
                            break
                        heading_anchor_id = _resolve_body_heading_anchor(sdt_child, _btag, _block_role)
                        if _should_emit_heading_manifest_entry(_btag, _block_role, sdt_child, style_defaults, style_ref):
                            heading_anchor_id = _record_body_heading(sdt_child, _btag, anchor_id=heading_anchor_id)
                        body_parts.append(
                            _para_html(
                                para,
                                doc,
                                _btag,
                                style_ref=style_ref,
                                anchor_id=heading_anchor_id,
                                extra_class="koto-visual-title" if _block_role == "visual_title" else None,
                                extra_role=None if _block_role == "body" else _block_role,
                            )
                        )
                        _record_preview_units(_para_units)
                    elif sdt_tag == "tbl":
                        _table_units = _estimate_table_units(sdt_child)
                        _table_row_limit = None
                        if preview_units_limit is not None:
                            _remaining_units = max(0, preview_units_limit - preview_units_used)
                            if body_parts and _remaining_units < _table_units:
                                preview_truncated = True
                                stop_render = True
                                break
                            if not body_parts and _remaining_units <= _table_units:
                                _table_row_limit = max(4, min(_DOCX_PREVIEW_MAX_TABLE_ROWS, max(4, _remaining_units // 2 or 4)))
                                preview_truncated = True
                        tbl = Table(sdt_child, doc)
                        body_parts.append(_table_html(tbl, doc, max_rows=_table_row_limit))
                        if _table_row_limit is not None:
                            _record_preview_units(max(6, _table_row_limit * 2))
                            stop_render = True
                            break
                        _record_preview_units(_table_units)
            if _is_toc_sdt:
                body_parts.append('</div>')
            if stop_render:
                break

        elif tag_local == "sectPr":
            # Direct body-level <w:sectPr> — the final section of the document.
            # In DOCX this is always the last child of <w:body> and represents
            # the document-level defaults (not a break). Do NOT emit a page
            # break here; it would add an extra blank page at the end.
            pass

    if not stop_render and not _flush_list():
        preview_truncated = True
        stop_render = True

    # NOTE: Footer no longer appended to body — rendered per-page by NodeView.

    # ── Extract per-section header/footer and page dimension metadata ─────
    # _section_html depends on _para_html (local function), so we extract
    # section data HERE (still inside _docx_to_rich_html) to avoid scope issues.
    sections_data: list[dict] = []
    try:
        _emu_px = lambda e: round(e / 914400 * 96) if e else 0
        _twips_px = lambda t: round((t / 20.0) / 72.0 * 96.0, 2) if t else 0

        def _parse_int_attr(value) -> int:
            try:
                return int(value)
            except Exception:
                return 0

        def _extract_section_doc_grid(section) -> dict[str, Any]:
            grid_info = {
                "enabled": False,
                "type": "",
                "line_pitch_twips": 0,
                "line_pitch_px": 0,
                "char_space": 0,
            }
            try:
                sect_pr = getattr(section, "_sectPr", None)
                if sect_pr is None:
                    return grid_info
                doc_grid = sect_pr.find(qn("w:docGrid"))
                if doc_grid is None:
                    return grid_info

                line_pitch = _parse_int_attr(doc_grid.get(qn("w:linePitch")))
                char_space = _parse_int_attr(doc_grid.get(qn("w:charSpace")))
                grid_info.update({
                    "enabled": True,
                    "type": str(doc_grid.get(qn("w:type")) or ""),
                    "line_pitch_twips": line_pitch,
                    "line_pitch_px": _twips_px(line_pitch),
                    "char_space": char_space,
                })
            except Exception:
                return grid_info
            return grid_info

        for sec in doc.sections:
            sec_info: dict = {
                "page_width_px":  _emu_px(sec.page_width),
                "page_height_px": _emu_px(sec.page_height),
                "margin_top_px":  _emu_px(sec.top_margin),
                "margin_bottom_px": _emu_px(sec.bottom_margin),
                "margin_left_px": _emu_px(sec.left_margin),
                "margin_right_px": _emu_px(sec.right_margin),
                "doc_grid": _extract_section_doc_grid(sec),
            }
            # Default header / footer
            try:
                sec_info["header_html"] = _section_html(sec.header, doc, "koto-header")
            except Exception:
                sec_info["header_html"] = ""
            try:
                sec_info["footer_html"] = _section_html(sec.footer, doc, "koto-footer")
            except Exception:
                sec_info["footer_html"] = ""
            # First-page header / footer (Word's "Different First Page")
            try:
                sec_info["first_header_html"] = _section_html(sec.first_page_header, doc, "koto-header") if sec.different_first_page_header_footer else ""
            except Exception:
                sec_info["first_header_html"] = ""
            try:
                sec_info["first_footer_html"] = _section_html(sec.first_page_footer, doc, "koto-footer") if sec.different_first_page_header_footer else ""
            except Exception:
                sec_info["first_footer_html"] = ""
            # Even-page header / footer
            try:
                sec_info["even_header_html"] = _section_html(sec.even_page_header, doc, "koto-header")
            except Exception:
                sec_info["even_header_html"] = ""
            try:
                sec_info["even_footer_html"] = _section_html(sec.even_page_footer, doc, "koto-footer")
            except Exception:
                sec_info["even_footer_html"] = ""
            sections_data.append(sec_info)
    except Exception as sec_exc:
        import logging as _log
        _log.getLogger(__name__).debug("[DocxParser] 节段信息提取失败 (非致命): %s", sec_exc)

    preview_meta = {
        "pending": bool(progressive_preview and preview_truncated),
        "target_pages": _DOCX_PREVIEW_TARGET_PAGES if progressive_preview else None,
    }
    return "\n".join(body_parts), sections_data, _heading_manifest, preview_meta


def _extract_images_from_paragraphs(html: str) -> str:
    """将 <p> 标签内的 <img> 元素移到段落外部，避免编辑器路径错误。

    TipTap/ProseMirror 不允许图片 void 元素嵌套在段落块元素中，否则在
    规范化时会抛出路径错误。

    规则：
    - 若段落只包含一个 <img>（忽略空白），则整个 <p>...</p> 替换为裸 <img>。
    - 若段落混合了文字和图片，则将 <img> 提取出来放在段落之后。
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return html

    def _has_visible_paragraph_content(tag) -> bool:
        for child in tag.children:
            if getattr(child, "name", None) == "img":
                continue
            if getattr(child, "name", None) == "br":
                continue
            text = str(child).strip()
            if text:
                return True
        return False

    soup = BeautifulSoup(html, "html.parser")
    changed = False

    def _extract_paragraph_images(p_tag, *, wrap_in_paragraph: bool) -> None:
        nonlocal changed
        imgs = list(p_tag.find_all("img"))
        if not imgs:
            return

        insert_after = p_tag
        for img in imgs:
            extracted_img = img.extract()
            if wrap_in_paragraph:
                extracted_img["data-koto-layout"] = extracted_img.get("data-koto-layout") or "top-bottom"
                img_row = soup.new_tag("p")
                img_row["class"] = "koto-docx-image-row"
                img_row.append(extracted_img)
                insert_after.insert_after(img_row)
                insert_after = img_row
            else:
                insert_after.insert_after(extracted_img)
                insert_after = extracted_img
            changed = True

        if not _has_visible_paragraph_content(p_tag):
            p_tag.decompose()

    for p_tag in list(soup.find_all("p")):
        if "koto-docx-image-row" in (p_tag.get("class") or []):
            continue
        if getattr(p_tag.parent, "name", "") in ("td", "th"):
            continue
        imgs = list(p_tag.find_all("img"))
        if not imgs:
            continue
        _extract_paragraph_images(p_tag, wrap_in_paragraph=False)

    return str(soup) if changed else html


def _xml_local_name(tag: Any) -> str:
    text = str(tag or "")
    return text.split("}", 1)[-1] if "}" in text else text


def _xml_attr_by_local_name(el: Any, attr_name: str) -> str:
    if el is None:
        return ""
    target = str(attr_name or "").strip()
    if not target:
        return ""
    for key, value in getattr(el, "attrib", {}).items():
        if _xml_local_name(key) == target and value not in (None, ""):
            return str(value)
    return ""


def _coerce_docx_comment_flag(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "on", "yes"}:
        return True
    if normalized in {"0", "false", "off", "no"}:
        return False
    return None


def _merge_docx_comment_extension_parts(zf: Any, comments_map: dict[str, dict]) -> None:
    from xml.etree import ElementTree as ET

    if not comments_map:
        return

    names = set(zf.namelist())
    comment_order = list(comments_map.values())

    def _merge_extended_entry(comment: dict[str, Any], entry: dict[str, Any]) -> None:
        para_id = str(entry.get("para_id") or "").strip()
        if para_id:
            comment["para_id"] = para_id
        parent_para_id = str(entry.get("parent_para_id") or "").strip()
        if parent_para_id:
            comment["parent_para_id"] = parent_para_id
        durable_id = str(entry.get("durable_id") or "").strip()
        if durable_id:
            comment["durable_id"] = durable_id
        if "done" in entry and entry.get("done") is not None:
            comment["done"] = bool(entry.get("done"))
        if "resolved" in entry and entry.get("resolved") is not None:
            comment["resolved"] = bool(entry.get("resolved"))

    def _has_same_para_id(entry: dict[str, Any], comment: dict[str, Any]) -> bool:
        entry_para_id = str(entry.get("para_id") or "").strip()
        comment_para_id = str(comment.get("para_id") or "").strip()
        return bool(entry_para_id and comment_para_id and entry_para_id == comment_para_id)

    ext_by_para: dict[str, dict[str, Any]] = {}
    ext_sequence: list[dict[str, Any]] = []
    ext_name = "word/commentsExtended.xml" if "word/commentsExtended.xml" in names else ""
    if ext_name:
        try:
            ext_tree = ET.fromstring(zf.read(ext_name))
            for ext_el in ext_tree.iter():
                if _xml_local_name(getattr(ext_el, "tag", "")) != "commentEx":
                    continue
                entry: dict[str, Any] = {}
                para_id = _xml_attr_by_local_name(ext_el, "paraId").strip()
                parent_para_id = _xml_attr_by_local_name(ext_el, "paraIdParent").strip()
                done_state = _coerce_docx_comment_flag(_xml_attr_by_local_name(ext_el, "done"))
                resolved_state = _coerce_docx_comment_flag(_xml_attr_by_local_name(ext_el, "resolved"))
                if para_id:
                    entry["para_id"] = para_id
                if parent_para_id:
                    entry["parent_para_id"] = parent_para_id
                if done_state is not None:
                    entry["done"] = done_state
                if resolved_state is not None:
                    entry["resolved"] = resolved_state
                if not entry:
                    continue
                ext_sequence.append(entry)
                if para_id:
                    ext_by_para[para_id] = entry
        except Exception:
            pass

    matched_comment_ids: set[str] = set()
    for comment in comment_order:
        para_id = str(comment.get("para_id") or "").strip()
        if para_id and para_id in ext_by_para:
            _merge_extended_entry(comment, ext_by_para[para_id])
            matched_comment_ids.add(str(comment.get("id") or "").strip())

    unmatched_ext_entries = [
        entry
        for entry in ext_sequence
        if not any(_has_same_para_id(entry, comment) for comment in comment_order)
    ]
    unmatched_comments_for_ext = [
        comment
        for comment in comment_order
        if str(comment.get("id") or "").strip() not in matched_comment_ids
    ]
    if unmatched_ext_entries and len(unmatched_ext_entries) == len(unmatched_comments_for_ext):
        for comment, entry in zip(unmatched_comments_for_ext, unmatched_ext_entries):
            _merge_extended_entry(comment, entry)

    ids_by_para: dict[str, dict[str, Any]] = {}
    ids_sequence: list[dict[str, Any]] = []
    ids_name = "word/commentsIds.xml" if "word/commentsIds.xml" in names else ""
    if ids_name:
        try:
            ids_tree = ET.fromstring(zf.read(ids_name))
            for id_el in ids_tree.iter():
                if _xml_local_name(getattr(id_el, "tag", "")) != "commentId":
                    continue
                para_id = _xml_attr_by_local_name(id_el, "paraId").strip()
                durable_id = (
                    _xml_attr_by_local_name(id_el, "durableId").strip()
                    or _xml_attr_by_local_name(id_el, "val").strip()
                    or _xml_attr_by_local_name(id_el, "id").strip()
                )
                if not durable_id:
                    continue
                entry = {"durable_id": durable_id}
                if para_id:
                    entry["para_id"] = para_id
                    ids_by_para[para_id] = entry
                ids_sequence.append(entry)
        except Exception:
            pass

    matched_durable_comment_ids: set[str] = set()
    for comment in comment_order:
        para_id = str(comment.get("para_id") or "").strip()
        if para_id and para_id in ids_by_para:
            _merge_extended_entry(comment, ids_by_para[para_id])
            matched_durable_comment_ids.add(str(comment.get("id") or "").strip())

    unmatched_id_entries = [
        entry
        for entry in ids_sequence
        if not any(_has_same_para_id(entry, comment) for comment in comment_order)
    ]
    unmatched_comments_for_ids = [
        comment
        for comment in comment_order
        if str(comment.get("id") or "").strip() not in matched_durable_comment_ids
        and not str(comment.get("durable_id") or "").strip()
    ]
    if unmatched_id_entries and len(unmatched_id_entries) == len(unmatched_comments_for_ids):
        for comment, entry in zip(unmatched_comments_for_ids, unmatched_id_entries):
            _merge_extended_entry(comment, entry)

    para_to_comment_id = {
        str(comment.get("para_id") or "").strip(): str(comment.get("id") or "").strip()
        for comment in comment_order
        if str(comment.get("para_id") or "").strip() and str(comment.get("id") or "").strip()
    }
    for comment in comment_order:
        parent_para_id = str(comment.get("parent_para_id") or "").strip()
        if parent_para_id and parent_para_id in para_to_comment_id:
            comment["parent_id"] = para_to_comment_id[parent_para_id]


def _extract_docx_comments(file_path: str) -> list[dict[str, Any]]:
    """
    从 DOCX 的 word/comments.xml 提取批注信息。

    Returns:
        [{id, author, initials, date, text, anchor_text, para_id, parent_id, durable_id, done}]
        若无批注或解析失败返回空列表。
    """
    import zipfile
    from xml.etree import ElementTree as ET

    ns = {
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
    }

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            # ── 解析 comments.xml ────────────────────────────────────
            if "word/comments.xml" not in zf.namelist():
                return []
            comments_xml = zf.read("word/comments.xml")
            comments_tree = ET.fromstring(comments_xml)
            comments_map: dict[str, dict] = {}
            for c in comments_tree.findall(".//w:comment", ns):
                cid = c.get(f"{{{ns['w']}}}id", "")
                author = c.get(f"{{{ns['w']}}}author", "")
                date = c.get(f"{{{ns['w']}}}date", "")
                initials = _xml_attr_by_local_name(c, "initials").strip()
                para_id = _xml_attr_by_local_name(c, "paraId").strip()
                parent_para_id = _xml_attr_by_local_name(c, "paraIdParent").strip()
                done_state = _coerce_docx_comment_flag(_xml_attr_by_local_name(c, "done"))
                resolved_state = _coerce_docx_comment_flag(_xml_attr_by_local_name(c, "resolved"))
                # 拼接所有 <w:t> 文本
                texts = [t.text or "" for t in c.findall(".//w:t", ns)]
                comment_payload = {
                    "id": cid,
                    "author": author,
                    "initials": initials,
                    "date": date,
                    "text": "".join(texts).strip(),
                    "anchor_text": "",
                    "anchor_start_offset": None,
                    "anchor_end_offset": None,
                    "para_id": para_id,
                    "parent_para_id": parent_para_id,
                    "parent_id": "",
                    "durable_id": "",
                }
                if done_state is not None:
                    comment_payload["done"] = done_state
                if resolved_state is not None:
                    comment_payload["resolved"] = resolved_state
                comments_map[cid] = comment_payload

            if not comments_map:
                return []

            _merge_docx_comment_extension_parts(zf, comments_map)

            # ── 从 document.xml 提取批注锚定原文 ────────────────────
            if "word/document.xml" in zf.namelist():
                doc_xml = zf.read("word/document.xml")
                doc_tree = ET.fromstring(doc_xml)
                # 构建 commentRangeStart id → 对应的 body 元素范围
                body = doc_tree.find(".//w:body", ns)
                if body is not None:
                    _extract_anchor_texts(body, comments_map, ns)

            return list(comments_map.values())
    except Exception as exc:
        logger.debug("[DocxParser] 批注提取失败 (非致命): %s", exc)
        return []


def _collect_docx_text_from_element(el: Any, *, include_deleted: bool = True) -> str:
    parts: list[str] = []

    def _walk(node: Any, *, deleted: bool = False) -> None:
        tag = _xml_local_name(getattr(node, "tag", ""))
        if tag == "del":
            deleted = True
        if deleted and not include_deleted:
            return
        if tag == "instrText":
            return
        if tag in {"t", "delText"} and getattr(node, "text", None):
            parts.append(str(node.text))
        elif tag in {"tab", "br", "cr"}:
            parts.append(" ")
        elif tag in {"noBreakHyphen", "softHyphen"}:
            parts.append("-")
        for child in list(node):
            _walk(child, deleted=deleted)

    _walk(el)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _format_docx_revision_rationale(change_kind: str, author: str, date: str) -> str:
    label_map = {
        "replace": "原生修订",
        "delete": "原生删除",
        "insert": "原生插入",
    }
    parts = [label_map.get(change_kind, "原生修订")]
    author_text = str(author or "").strip()
    date_text = str(date or "").strip()
    if author_text:
        parts.append(author_text)
    if date_text:
        parts.append(date_text)
    return " · ".join(parts)


def _extract_docx_revisions(file_path: str) -> list[dict[str, Any]]:
    import zipfile
    from xml.etree import ElementTree as ET

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    skip_tags = {
        "bookmarkStart",
        "bookmarkEnd",
        "proofErr",
        "permStart",
        "permEnd",
        "commentRangeStart",
        "commentRangeEnd",
    }

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            if "word/document.xml" not in zf.namelist():
                return []

            doc_tree = ET.fromstring(zf.read("word/document.xml"))
            body = doc_tree.find(".//w:body", ns)
            if body is None:
                return []

            revisions: list[dict[str, Any]] = []
            for paragraph_index, p_el in enumerate(body.findall(".//w:p", ns), start=1):
                paragraph_text = _collect_docx_text_from_element(p_el, include_deleted=False)
                children = list(p_el)
                child_index = 0

                while child_index < len(children):
                    child = children[child_index]
                    tag = _xml_local_name(getattr(child, "tag", ""))
                    if tag not in {"del", "ins"}:
                        child_index += 1
                        continue

                    author = child.get(f"{{{ns['w']}}}author", "")
                    date = child.get(f"{{{ns['w']}}}date", "")
                    change_id = child.get(f"{{{ns['w']}}}id", "") or f"{paragraph_index}-{child_index}"

                    if tag == "del":
                        deleted_text = _collect_docx_text_from_element(child, include_deleted=True)
                        if not deleted_text:
                            child_index += 1
                            continue

                        next_index = child_index + 1
                        while next_index < len(children) and _xml_local_name(getattr(children[next_index], "tag", "")) in skip_tags:
                            next_index += 1

                        if next_index < len(children) and _xml_local_name(getattr(children[next_index], "tag", "")) == "ins":
                            ins_child = children[next_index]
                            inserted_text = _collect_docx_text_from_element(ins_child, include_deleted=True)
                            ins_author = ins_child.get(f"{{{ns['w']}}}author", "") or author
                            ins_date = ins_child.get(f"{{{ns['w']}}}date", "") or date
                            revisions.append({
                                "id": f"docx-revision-{change_id}",
                                "source": "docx_revision",
                                "action": "replace",
                                "original_text": deleted_text,
                                "proposed_text": inserted_text,
                                "anchor_text": paragraph_text or inserted_text or deleted_text,
                                "rationale": _format_docx_revision_rationale("replace", ins_author, ins_date),
                                "author": ins_author,
                                "date": ins_date,
                                "read_only": True,
                                "apply_disabled": True,
                            })
                            child_index = next_index + 1
                            continue

                        revisions.append({
                            "id": f"docx-revision-{change_id}",
                            "source": "docx_revision",
                            "action": "delete",
                            "original_text": deleted_text,
                            "proposed_text": "",
                            "anchor_text": paragraph_text or deleted_text,
                            "rationale": _format_docx_revision_rationale("delete", author, date),
                            "author": author,
                            "date": date,
                            "read_only": True,
                            "apply_disabled": True,
                        })
                        child_index += 1
                        continue

                    inserted_text = _collect_docx_text_from_element(child, include_deleted=True)
                    if inserted_text:
                        revisions.append({
                            "id": f"docx-revision-{change_id}",
                            "source": "docx_revision",
                            "action": "insert",
                            "original_text": "",
                            "proposed_text": inserted_text,
                            "anchor_text": paragraph_text or inserted_text,
                            "rationale": _format_docx_revision_rationale("insert", author, date),
                            "author": author,
                            "date": date,
                            "read_only": True,
                            "apply_disabled": True,
                        })
                    child_index += 1

            return revisions
    except Exception as exc:
        logger.debug("[DocxParser] 修订提取失败 (非致命): %s", exc)
        return []


def _extract_docx_footnotes(file_path: str) -> list[dict[str, Any]]:
    """Extract referenced DOCX footnotes from word/footnotes.xml."""
    import zipfile
    from xml.etree import ElementTree as ET

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

    def _local_name(tag: str) -> str:
        return tag.split("}", 1)[-1] if "}" in tag else tag

    def _collect_note_text(note_el: Any) -> str:
        parts: list[str] = []
        for child in note_el.iter():
            tag = _local_name(getattr(child, "tag", ""))
            if tag == "t" and child.text:
                parts.append(child.text)
            elif tag in {"tab", "br", "cr"}:
                parts.append(" ")
        return re.sub(r"\s+", " ", "".join(parts)).strip()

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            if "word/footnotes.xml" not in zf.namelist():
                return []

            ref_counts: dict[str, int] = {}
            if "word/document.xml" in zf.namelist():
                doc_tree = ET.fromstring(zf.read("word/document.xml"))
                for ref_el in doc_tree.findall(".//w:footnoteReference", ns):
                    note_id = str(ref_el.get(f"{{{ns['w']}}}id") or "").strip()
                    if note_id:
                        ref_counts[note_id] = ref_counts.get(note_id, 0) + 1

            footnotes_tree = ET.fromstring(zf.read("word/footnotes.xml"))
            footnotes: list[dict[str, Any]] = []
            for footnote_el in footnotes_tree.findall(".//w:footnote", ns):
                note_id = str(footnote_el.get(f"{{{ns['w']}}}id") or "").strip()
                if not note_id:
                    continue

                reference_count = ref_counts.get(note_id, 0)
                if reference_count <= 0:
                    continue

                footnotes.append({
                    "id": note_id,
                    "text": _collect_note_text(footnote_el),
                    "type": str(footnote_el.get(f"{{{ns['w']}}}type") or "footnote"),
                    "reference_count": reference_count,
                })

            return footnotes
    except Exception as exc:
        logger.debug("[DocxParser] 脚注提取失败 (非致命): %s", exc)
        return []


def count_docx_visible_chars(file_path: str) -> int:
    """Approximate Word/WPS-style count from visible main-document text.

    This intentionally counts only visible text in ``word/document.xml`` so the
    result is not limited by AI preview truncation and does not pull in header,
    footer, comment, or field-instruction text.
    """
    import zipfile
    from xml.etree import ElementTree as ET

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

    def _local_name(tag: str) -> str:
        return tag.split("}", 1)[-1] if "}" in tag else tag

    parts: list[str] = []

    def _walk(el: Any, *, deleted: bool = False) -> None:
        tag = _local_name(getattr(el, "tag", ""))
        if tag == "del":
            deleted = True
        if deleted:
            for child in el:
                _walk(child, deleted=True)
            return
        if tag == "instrText":
            return
        if tag == "t" and el.text:
            parts.append(el.text)
        elif tag in {"tab", "br", "cr"}:
            parts.append(" ")
        elif tag in {"noBreakHyphen", "softHyphen"}:
            parts.append("-")
        for child in el:
            _walk(child, deleted=deleted)

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            if "word/document.xml" not in zf.namelist():
                return 0
            doc_tree = ET.fromstring(zf.read("word/document.xml"))
            body = doc_tree.find(".//w:body", ns)
            if body is None:
                return 0
            _walk(body)
    except Exception as exc:
        logger.debug("[DocxParser] DOCX 可见文字统计失败 (非致命): %s", exc)
        return 0

    return len(re.sub(r"\s+", "", "".join(parts)))


def _extract_anchor_texts(
    body_el: Any, comments_map: dict[str, dict], ns: dict[str, str]
) -> None:
    """遍历 document.xml body，提取批注锚点文本与稳定定位元数据。"""

    events: list[tuple[str, str]] = []

    def _walk(el: Any) -> None:
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag == "commentRangeStart":
            cid = el.get(f"{{{ns['w']}}}id", "")
            events.append(("start", cid))
        elif tag == "commentRangeEnd":
            cid = el.get(f"{{{ns['w']}}}id", "")
            events.append(("end", cid))
        elif tag == "t" and el.text:
            events.append(("text", el.text))
        elif tag in {"tab", "br", "cr"}:
            events.append(("text", " "))
        elif tag in {"noBreakHyphen", "softHyphen"}:
            events.append(("text", "-"))
        for child in el:
            _walk(child)
        if tag == "p":
            events.append(("paragraph_break", "\n"))

    _walk(body_el)

    active_ids: set[str] = set()
    full_text_parts: list[str] = []
    cursor = 0

    for etype, val in events:
        if etype == "start":
            if val in comments_map and comments_map[val].get("anchor_start_offset") is None:
                comments_map[val]["anchor_start_offset"] = cursor
            active_ids.add(val)
            continue
        if etype == "end":
            if val in comments_map and comments_map[val].get("anchor_end_offset") is None:
                comments_map[val]["anchor_end_offset"] = cursor
            active_ids.discard(val)
            continue
        if etype == "paragraph_break":
            full_text_parts.append(val)
            cursor += len(val)
            continue
        if etype == "text" and active_ids:
            for cid in active_ids:
                if cid in comments_map:
                    comments_map[cid]["anchor_text"] += val
        if etype == "text":
            full_text_parts.append(val)
            cursor += len(val)

    full_text = "".join(full_text_parts)
    for cid in active_ids:
        if cid in comments_map and comments_map[cid].get("anchor_end_offset") is None:
            comments_map[cid]["anchor_end_offset"] = cursor

    for comment in comments_map.values():
        start_offset = comment.get("anchor_start_offset")
        end_offset = comment.get("anchor_end_offset")
        if not isinstance(start_offset, int) or not isinstance(end_offset, int):
            continue
        if end_offset < start_offset:
            continue

        comment["anchor_context_before"] = full_text[max(0, start_offset - 48):start_offset]
        comment["anchor_context_after"] = full_text[end_offset:end_offset + 48]

        anchor_text = str(comment.get("anchor_text") or "")
        if not anchor_text:
            continue

        occurrence = 0
        search_from = 0
        while search_from < start_offset:
            hit = full_text.find(anchor_text, search_from)
            if hit == -1 or hit >= start_offset:
                break
            occurrence += 1
            search_from = hit + max(len(anchor_text), 1)
        comment["anchor_occurrence"] = occurrence


def parse_docx(file_path: str, *, progressive_preview: bool = False) -> dict[str, Any]:
    """
    将 DOCX 转换为保留完整 Word 格式的内联样式 HTML。

    首先尝试 _docx_to_rich_html()（python-docx 全格式管线）；
    若失败则回退到 mammoth 语义化管线（含后处理 Pass）。

    Returns:
        {"html": str, "messages": list[str]}

    When ``progressive_preview`` is true, only the initial preview chunk is
    rendered and the result includes ``progressive.pending`` so the frontend can
    fetch the full document in the background before enabling editing.
    """
    messages_out: list[str] = []

    # ── Primary path: rich python-docx renderer ───────────────────────────
    try:
        rich_html, sections_data, headings, preview_meta = _docx_to_rich_html(
            file_path,
            progressive_preview=progressive_preview,
        )

        # strip <style>/<script> just in case
        rich_html = re.sub(
            r"<style[^>]*>.*?</style>|<script[^>]*>.*?</script>",
            "",
            rich_html,
            flags=re.DOTALL | re.IGNORECASE,
        )

        # Unwrap single-column layout tables that have no visible borders
        try:
            rich_html = _unwrap_layout_tables(rich_html)
        except Exception as exc:
            logger.warning("[DocxParser] 布局表格展开失败 (非致命): %s", exc)

        # Deduplicate images
        try:
            rich_html = _deduplicate_images(rich_html)
        except Exception as exc:
            logger.warning("[DocxParser] 图片去重失败 (非致命): %s", exc)

        # Extract <img> from <p> tags to prevent editor path errors
        try:
            rich_html = _extract_images_from_paragraphs(rich_html)
        except Exception as exc:
            logger.warning("[DocxParser] 图片段落提取失败 (非致命): %s", exc)

        # ── Extract page dimensions for frontend page-break overlay ───
        page_meta: dict[str, Any] = {}
        try:
            if sections_data:
                _sec0 = sections_data[0]
                page_meta = {
                    "page_width_px":    _sec0.get("page_width_px", 0),
                    "page_height_px":   _sec0.get("page_height_px", 0),
                    "margin_top_px":    _sec0.get("margin_top_px", 0),
                    "margin_bottom_px": _sec0.get("margin_bottom_px", 0),
                    "margin_left_px":   _sec0.get("margin_left_px", 0),
                    "margin_right_px":  _sec0.get("margin_right_px", 0),
                    "doc_grid":         _sec0.get("doc_grid", {}),
                    "header_html":      _sec0.get("header_html", ""),
                    "footer_html":      _sec0.get("footer_html", ""),
                }
                page_meta["sections"] = sections_data
        except Exception as meta_exc:
            logger.debug("[DocxParser] 页面元数据提取失败 (非致命): %s", meta_exc)

        result = {"html": rich_html, "messages": messages_out, "headings": headings}
        result.update(page_meta)
        if progressive_preview:
            result["progressive"] = {
                "pending": bool(preview_meta.get("pending")),
                "target_pages": preview_meta.get("target_pages") or _DOCX_PREVIEW_TARGET_PAGES,
            }
        # ── 提取 DOCX 批注 ──────────────────────────────────────────
        try:
            comments = _extract_docx_comments(file_path)
            if comments:
                result["comments"] = comments
        except Exception:
            pass
        try:
            proposals = _extract_docx_revisions(file_path)
            if proposals:
                result["proposals"] = proposals
        except Exception:
            pass
        try:
            footnotes = _extract_docx_footnotes(file_path)
            if footnotes:
                result["footnotes"] = footnotes
                result["footnote_reference_count"] = sum(
                    int(note.get("reference_count") or 0)
                    for note in footnotes
                    if isinstance(note, dict)
                )
        except Exception:
            pass
        return result

    except Exception as primary_exc:
        logger.warning(
            "[DocxParser] 富格式渲染失败，回退到 mammoth: %s", primary_exc
        )

    # ── Fallback path: mammoth semantic renderer ──────────────────────────
    try:
        import mammoth
    except ImportError:
        raise RuntimeError("python-docx 和 mammoth 均未安装，请执行: pip install python-docx mammoth")

    def _img_handler(image: Any) -> dict[str, str]:
        """将图片转换为内联 base64 data URI，自动压缩大图。"""
        try:
            with image.open() as f:
                img_bytes = f.read()
            content_type = image.content_type or "image/png"
            img_bytes, content_type = _compress_image_bytes(img_bytes, content_type)
            b64 = base64.b64encode(img_bytes).decode("ascii")
            return {"src": f"data:{content_type};base64,{b64}"}
        except Exception as e:
            logger.warning(f"[DocxParser] 图片内联失败: {e}")
            return {"src": ""}

    try:
        with open(file_path, "rb") as f:
            result = mammoth.convert_to_html(
                f,
                convert_image=mammoth.images.img_element(_img_handler),
            )
        for msg in result.messages:
            messages_out.append(str(msg))

        clean_html = re.sub(
            r"<style[^>]*>.*?</style>|<script[^>]*>.*?</script>",
            "",
            result.value,
            flags=re.DOTALL | re.IGNORECASE,
        )
        clean_html = re.sub(
            r"(<p[^>]*>)(?:(?:body|h[1-6]|blockquote|strong|em|code|pre|table|td|th|ul|ol|li)\s*\{[^{}]*\})+",
            r"\1",
            clean_html,
            flags=re.IGNORECASE,
        )
        clean_html = re.sub(r"<p[^>]*>\s*</p>", "", clean_html)

        try:
            tbl_styles = _extract_table_styles(file_path)
            clean_html = _inject_table_styles(clean_html, tbl_styles)
        except Exception as exc:
            logger.warning("[DocxParser] 表格样式注入失败 (非致命): %s", exc)

        try:
            clean_html = _unwrap_layout_tables(clean_html)
        except Exception as exc:
            logger.warning("[DocxParser] 布局表格展开失败 (非致命): %s", exc)

        try:
            floating_srcs = _get_floating_image_srcs(file_path)
            if floating_srcs:
                imgs_html = "".join(
                    f'<img src="{src}" '
                    'style="float:right;max-width:28%;max-height:180px;'
                    'margin:0 0 10px 14px;object-fit:contain;border-radius:2px;" '
                    'alt="" />'
                    for src in floating_srcs
                )
                first_block = re.search(
                    r"<(?:p|h[1-6]|table|ul|ol|blockquote)\b", clean_html
                )
                if first_block:
                    clean_html = (
                        clean_html[: first_block.start()]
                        + imgs_html
                        + clean_html[first_block.start() :]
                    )
                else:
                    clean_html = imgs_html + clean_html
        except Exception as exc:
            logger.warning("[DocxParser] 浮动图片注入失败 (非致命): %s", exc)

        try:
            clean_html = _deduplicate_images(clean_html)
        except Exception as exc:
            logger.warning("[DocxParser] 图片去重失败 (非致命): %s", exc)

        fallback_result = {"html": clean_html, "messages": messages_out}
        try:
            comments = _extract_docx_comments(file_path)
            if comments:
                fallback_result["comments"] = comments
        except Exception:
            pass
        try:
            proposals = _extract_docx_revisions(file_path)
            if proposals:
                fallback_result["proposals"] = proposals
        except Exception:
            pass
        try:
            footnotes = _extract_docx_footnotes(file_path)
            if footnotes:
                fallback_result["footnotes"] = footnotes
                fallback_result["footnote_reference_count"] = sum(
                    int(note.get("reference_count") or 0)
                    for note in footnotes
                    if isinstance(note, dict)
                )
        except Exception:
            pass
        return fallback_result
    except Exception as e:
        logger.error(f"[DocxParser] 解析失败: {e}")
        raise


# ─────────────────────────────────────────────────────────────────────────────
# XLSX → Univer Sheets IWorkbookData JSON
# ─────────────────────────────────────────────────────────────────────────────

__all__ = [
    "count_docx_visible_chars",
    "parse_docx",
    "_extract_docx_comments",
    "_extract_docx_revisions",
    "_extract_docx_footnotes",
]
