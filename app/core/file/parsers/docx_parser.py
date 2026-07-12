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
from app.core.file.parsers.docx_rich_renderer import _docx_to_rich_html
from app.core.file.parsers.docx_parser_review import (
    _extract_docx_comments,
    _extract_docx_footnotes,
    _extract_docx_revisions,
    count_docx_visible_chars,
)

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
                colspan = (
                    int(grid_span_el.get(_w("val"), 1))
                    if grid_span_el is not None
                    else 1
                )

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
                    v_merge_el is not None and v_merge_el.get(_w("val"), "") == ""
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
                        cell_tag["style"] = (existing.rstrip(";") + ";" + w_css).lstrip(
                            ";"
                        )

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
                    cell_tag["style"] = (existing.rstrip(";") + ";" + bg_css).lstrip(
                        ";"
                    )

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
    import xml.etree.ElementTree as _ET
    import zipfile as _zipfile

    # Full OOXML namespace URIs — must match exactly (not prefix aliases)
    IMG_TYPE = (
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
    )
    WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
    A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
    R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

    result: list[str] = []
    try:
        with _zipfile.ZipFile(docx_path, "r") as z:
            file_list = z.namelist()

            # Locate document.xml and its rels (case-insensitive for robustness)
            doc_name = next(
                (n for n in file_list if n.lower() == "word/document.xml"), None
            )
            rels_name = next(
                (n for n in file_list if n.lower() == "word/_rels/document.xml.rels"),
                None,
            )
            if not doc_name or not rels_name:
                return result

            # ── rel_id → media path via ElementTree (handles ANY attribute order) ──
            rels_root = _ET.fromstring(z.read(rels_name))
            rel_map: dict[str, str] = {}
            for rel in rels_root:
                rid = rel.get("Id", "")
                rtype = rel.get("Type", "")
                tgt = rel.get("Target", "")
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
                        rel_id,
                        list(rel_map)[:8],
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
                result_parts.append(html[pos : m.start()])
                pos = m.end()
                continue
            seen_prefixes.add(prefix)

        result_parts.append(html[pos : m.end()])
        pos = m.end()

    result_parts.append(html[pos:])
    return "".join(result_parts)




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
                extracted_img["data-koto-layout"] = (
                    extracted_img.get("data-koto-layout") or "top-bottom"
                )
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
                    "page_width_px": _sec0.get("page_width_px", 0),
                    "page_height_px": _sec0.get("page_height_px", 0),
                    "margin_top_px": _sec0.get("margin_top_px", 0),
                    "margin_bottom_px": _sec0.get("margin_bottom_px", 0),
                    "margin_left_px": _sec0.get("margin_left_px", 0),
                    "margin_right_px": _sec0.get("margin_right_px", 0),
                    "doc_grid": _sec0.get("doc_grid", {}),
                    "header_html": _sec0.get("header_html", ""),
                    "footer_html": _sec0.get("footer_html", ""),
                }
                page_meta["sections"] = sections_data
        except Exception as meta_exc:
            logger.debug("[DocxParser] 页面元数据提取失败 (非致命): %s", meta_exc)

        result = {"html": rich_html, "messages": messages_out, "headings": headings}
        result.update(page_meta)
        if progressive_preview:
            result["progressive"] = {
                "pending": bool(preview_meta.get("pending")),
                "target_pages": preview_meta.get("target_pages")
                or _DOCX_PREVIEW_TARGET_PAGES,
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
        logger.warning("[DocxParser] 富格式渲染失败，回退到 mammoth: %s", primary_exc)

    # ── Fallback path: mammoth semantic renderer ──────────────────────────
    try:
        import mammoth
    except ImportError:
        raise RuntimeError(
            "python-docx 和 mammoth 均未安装，请执行: pip install python-docx mammoth"
        )

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
