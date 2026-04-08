# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Koto 全格式文件解析模块 — Phase 1 BFF 管线核心
支持格式: DOCX / XLSX / PPTX / PDF
每个解析函数接收文件路径或字节流,输出标准化 JSON 供前端多态渲染器消费。
"""

from __future__ import annotations

import base64
import io
import logging
import mimetypes
import os
import re
import uuid
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# DOCX → Semantic HTML
# ─────────────────────────────────────────────────────────────────────────────


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
        tbl_data: dict[tuple[int, int], dict] = {}

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

        rows = tbl_tag.find_all("tr")
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
    # Slate/WangEditor sometimes pads rows with phantom empty cells; stripping
    # them here (Python side) avoids the Slate reconciler reverting any JS fix.
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
                    b64 = base64.b64encode(img_bytes).decode("ascii")
                    result.append(f"data:{mime};base64,{b64}")
                except Exception as e:
                    logger.debug("[floating_imgs] failed to read %s: %s", media_path, e)
    except Exception as exc:
        logger.warning("[_get_floating_image_srcs] %s", exc)
    return result


def parse_docx(file_path: str) -> dict[str, Any]:
    """
    使用 mammoth 将 DOCX 转换为语义 HTML。
    图片以 base64 data URI 内联，保证前端渲染自包含。
    额外通过 python-docx 提取单元格颜色和合并信息，注入 HTML。

    Returns:
        {"html": str, "messages": list[str]}
    """
    try:
        import mammoth
    except ImportError:
        raise RuntimeError("mammoth 未安装，请执行: pip install mammoth")

    messages_out: list[str] = []

    def _img_handler(image: Any) -> dict[str, str]:
        """将图片转换为内联 base64 data URI。"""
        try:
            with image.open() as f:
                img_bytes = f.read()
            content_type = image.content_type or "image/png"
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

        # ── Pass 1: strip <style>/<script> tags emitted by mammoth ──────────
        # WangEditor v5 strips the <style> tag itself but leaks the CSS text
        # content as visible document text.
        clean_html = re.sub(
            r"<style[^>]*>.*?</style>|<script[^>]*>.*?</script>",
            "",
            result.value,
            flags=re.DOTALL | re.IGNORECASE,
        )

        # ── Pass 2: strip CSS-as-text (auto-save corruption artifact) ────────
        # If this DOCX was previously auto-saved while CSS text was visible in
        # the editor, the CSS strings get baked into the DOCX as real paragraph
        # text, e.g.: <p>body{font-family:...}h1{font-size:20pt}文档标题</p>
        # Remove any CSS rule blocks (selector{props}) at the START of a <p>.
        # The [^{}]* inner match is safe because mammoth CSS rules are flat.
        clean_html = re.sub(
            r"(<p[^>]*>)(?:(?:body|h[1-6]|blockquote|strong|em|code|pre|table|td|th|ul|ol|li)\s*\{[^{}]*\})+",
            r"\1",
            clean_html,
            flags=re.IGNORECASE,
        )
        # Remove empty paragraphs left after the above strip
        clean_html = re.sub(r"<p[^>]*>\s*</p>", "", clean_html)

        # ── Pass 3: inject cell colours / colspan / rowspan from python-docx ──
        # mammoth deliberately strips all tcPr/tblPr XML; we recover it here
        # by reading the original DOCX with python-docx and matching cells
        # positionally.
        try:
            tbl_styles = _extract_table_styles(file_path)
            clean_html = _inject_table_styles(clean_html, tbl_styles)
        except Exception as exc:
            logger.warning("[DocxParser] 表格样式注入失败 (非致命): %s", exc)

        # ── Pass 4: inject floating images mammoth cannot handle ─────────────
        # <wp:anchor> images (floating/positioned in the page margin) are
        # silently discarded by mammoth.  The most common case is a resume
        # profile photo floated to the top-right of the page.  We recover these
        # images and inject them right-floated at the very start of the body so
        # they appear near their original visual position.
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
                # Insert before the first block-level element so the float
                # wraps naturally around following text content
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

        return {"html": clean_html, "messages": messages_out}
    except Exception as e:
        logger.error(f"[DocxParser] 解析失败: {e}")
        raise


# ─────────────────────────────────────────────────────────────────────────────
# XLSX → Univer Sheets IWorkbookData JSON
# ─────────────────────────────────────────────────────────────────────────────

# Univer CellValueType constants (must match @univerjs/core CellValueType enum)
_UNIVER_TYPE_STRING = 1
_UNIVER_TYPE_NUMBER = 2
_UNIVER_TYPE_BOOLEAN = 3

# Horizontal alignment: Univer HorizontalAlign enum
_ALIGN_H_MAP = {
    "general": 0,
    "left": 1,
    "center": 2,
    "right": 3,
    "justify": 6,
    "distributed": 7,
}

# Vertical alignment: Univer VerticalAlign enum
_ALIGN_V_MAP = {
    "top": 1,
    "middle": 2,
    "center": 2,
    "bottom": 3,
    "justify": 4,
    "distributed": 5,
}


def _openpyxl_cell_to_univer(cell: Any) -> dict[str, Any] | None:
    """将单个 openpyxl Cell 转换为 Univer ICellData 对象。"""
    v = cell.value
    if v is None:
        return None

    cell_data: dict[str, Any] = {}

    # ── Value & type ──────────────────────────────────────────────────────────
    if isinstance(v, bool):
        cell_data["v"] = int(v)
        cell_data["t"] = _UNIVER_TYPE_BOOLEAN
    elif isinstance(v, (int, float)):
        cell_data["v"] = v
        cell_data["t"] = _UNIVER_TYPE_NUMBER
    else:
        cell_data["v"] = str(v)
        cell_data["t"] = _UNIVER_TYPE_STRING

    # ── Style ─────────────────────────────────────────────────────────────────
    style: dict[str, Any] = {}
    try:
        font = cell.font
        if font:
            if font.bold:
                style["bl"] = 1
            if font.italic:
                style["it"] = 1
            if font.size:
                style["fs"] = int(font.size)
            if font.color and font.color.type == "rgb" and font.color.rgb not in (
                "00000000", "FF000000"
            ):
                # Univer expects { rgb: "#RRGGBB" }
                style["cl"] = {"rgb": "#" + font.color.rgb[2:]}
        fill = cell.fill
        if fill and fill.fill_type not in (None, "none") and fill.fgColor:
            if fill.fgColor.type == "rgb" and fill.fgColor.rgb not in (
                "00000000",
                "FFFFFFFF",
            ):
                style["bg"] = {"rgb": "#" + fill.fgColor.rgb[2:]}
        ali = cell.alignment
        if ali:
            if ali.horizontal and ali.horizontal in _ALIGN_H_MAP:
                style["ht"] = _ALIGN_H_MAP[ali.horizontal]
            if ali.vertical and ali.vertical in _ALIGN_V_MAP:
                style["vt"] = _ALIGN_V_MAP[ali.vertical]
    except Exception:
        pass  # 样式提取失败不影响数据

    if style:
        cell_data["s"] = style

    return cell_data


def parse_xlsx(file_path: str, original_name: str | None = None) -> dict[str, Any]:
    """
    使用 openpyxl 将 XLSX 转换为 Univer Sheets IWorkbookData 快照格式。

    Args:
        file_path: 临时文件路径（可能是 UUID 命名）
        original_name: 用户上传的原始文件名（用于设置 workbook name）

    Returns:
        {
          "id": str,
          "name": str,
          "sheetOrder": [str, ...],
          "sheets": {
            "<sheetId>": { ... }
          },
          "_warnings": ["..."]   # 非空时应由前端显示提示
        }
    """
    try:
        import openpyxl
    except ImportError:
        raise RuntimeError("openpyxl 未安装，请执行: pip install openpyxl")

    # ── 公式检测：先以 data_only=False 快速扫描，判断是否含有公式 ──────────
    _warnings: list[str] = []
    try:
        _wb_check = openpyxl.load_workbook(file_path, data_only=False, read_only=True)
        _formula_count = 0
        for _ws in _wb_check.worksheets:
            for _row in _ws.iter_rows():
                for _cell in _row:
                    if isinstance(_cell.value, str) and _cell.value.startswith("="):
                        _formula_count += 1
                        if _formula_count >= 1:
                            break  # 找到任意一个公式即可，不必继续
                if _formula_count:
                    break
            if _formula_count:
                break
        _wb_check.close()
        if _formula_count:
            _warnings.append(
                "此表格包含公式（如 =SUM(...)）。Koto 目前以「静态值」模式读取 Excel，"
                "公式已转换为计算结果，保存导出后公式将永久丢失。如需保留公式，请下载原始文件。"
            )
    except Exception:
        pass  # 检测失败不影响主流程

    wb = openpyxl.load_workbook(file_path, data_only=True)

    workbook_id = str(uuid.uuid4())
    if original_name:
        workbook_name = os.path.splitext(os.path.basename(original_name))[0]
    else:
        workbook_name = os.path.splitext(os.path.basename(file_path))[0]
    sheet_order: list[str] = []
    sheets: dict[str, Any] = {}

    # ── Shared styles registry ────────────────────────────────────────────────
    # Univer v0.5.x expects cellData["s"] to be a *string* style-ID that keys
    # into the top-level "styles" map.  Inline IStyleData objects (the old
    # approach) are silently ignored by Univer's createUnit(), which is why
    # all cells appeared blank even though the data was correctly parsed.
    _style_hash_to_id: dict[str, str] = {}
    _styles_registry: dict[str, Any] = {}

    def _get_style_id(style_obj: dict[str, Any]) -> str:
        """Return a stable string key for *style_obj*, registering it if new."""
        import json as _json
        h = _json.dumps(style_obj, sort_keys=True, ensure_ascii=False)
        if h not in _style_hash_to_id:
            sid = str(len(_style_hash_to_id))
            _style_hash_to_id[h] = sid
            _styles_registry[sid] = style_obj
        return _style_hash_to_id[h]

    for idx, ws in enumerate(wb.worksheets):
        sheet_id = f"sheet{idx + 1}"
        sheet_order.append(sheet_id)

        # ── Cell data: nested dict {row: {col: ICellData}} ────────────────────
        cell_data: dict[int, dict[int, Any]] = {}
        for row in ws.iter_rows():
            for cell in row:
                cd = _openpyxl_cell_to_univer(cell)
                if cd is not None:
                    # Convert inline style object → style ID string
                    if "s" in cd and isinstance(cd["s"], dict):
                        cd["s"] = _get_style_id(cd["s"])
                    r = cell.row - 1
                    c = cell.column - 1
                    if r not in cell_data:
                        cell_data[r] = {}
                    cell_data[r][c] = cd

        # ── Merge data ────────────────────────────────────────────────────────
        merge_data: list[dict[str, int]] = []
        for merge_range in ws.merged_cells.ranges:
            merge_data.append({
                "startRow": merge_range.min_row - 1,
                "startColumn": merge_range.min_col - 1,
                "endRow": merge_range.max_row - 1,
                "endColumn": merge_range.max_col - 1,
            })

        sheets[sheet_id] = {
            "id": sheet_id,
            "name": ws.title,
            "rowCount": max(ws.max_row or 30, 30),
            "columnCount": max(ws.max_column or 10, 10),
            "cellData": cell_data,
            "mergeData": merge_data,
        }

    wb.close()

    return {
        "id": workbook_id,
        "name": workbook_name,
        "appVersion": "0.5.0",   # required by IWorkbookData; Univer fails silently without it
        "locale": "zh-CN",       # required by IWorkbookData; used for cell formatting
        "sheetOrder": sheet_order,
        "sheets": sheets,
        "styles": _styles_registry,  # style-id → IStyleData (populated during cell scan)
        "resources": [],  # Univer plugin resources (e.g. conditional formatting)
        "_warnings": _warnings,  # 前端应在非空时展示用户提示
    }


# ─────────────────────────────────────────────────────────────────────────────
# PPTX → 结构化文本 JSON (卡片编辑模型)
# ─────────────────────────────────────────────────────────────────────────────


def parse_pptx(file_path: str) -> list[dict[str, Any]]:
    """
    使用 python-pptx 提取每个 Slide 的文本框内容。
    保留 shape_id 以便后端导出时可回写原文件。

    Returns:
        [{"slide_id": int, "slide_index": int,
          "texts": [{"shape_id": int, "shape_name": str, "text": str, "is_title": bool}]}]
    """
    try:
        from pptx import Presentation
        from pptx.enum.shapes import PP_PLACEHOLDER
    except ImportError:
        raise RuntimeError("python-pptx 未安装，请执行: pip install python-pptx")

    prs = Presentation(file_path)
    slides_data: list[dict[str, Any]] = []

    for slide_idx, slide in enumerate(prs.slides):
        texts: list[dict[str, Any]] = []

        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue

            text_content = "\n".join(
                para.text for para in shape.text_frame.paragraphs
            ).strip()

            if not text_content:
                continue

            is_title = False
            try:
                ph = shape.placeholder_format
                if ph is not None:
                    is_title = ph.type in (
                        PP_PLACEHOLDER.TITLE,
                        PP_PLACEHOLDER.CENTER_TITLE,
                    )
            except Exception:
                pass

            texts.append(
                {
                    "shape_id": shape.shape_id,
                    "shape_name": shape.name,
                    "text": text_content,
                    "is_title": is_title,
                }
            )

        slides_data.append(
            {
                "slide_id": slide_idx + 1,
                "slide_index": slide_idx,
                "texts": texts,
            }
        )

    return slides_data


# ─────────────────────────────────────────────────────────────────────────────
# PPTX → 几何画布 JSON (含图片/表格/备注)
# ─────────────────────────────────────────────────────────────────────────────


def parse_pptx_geometry(file_path: str) -> dict[str, Any]:
    """
    使用 python-pptx 提取每个 Slide 的完整几何数据，供前端画布编辑器渲染。
    包含文本框 (含字体样式)、图片 (base64 data URI)、表格 (单元格文本)、备注。
    支持 GROUP 形状递归、从 layout/master 继承背景色。

    Returns:
        {
          "slide_width_emu": int,
          "slide_height_emu": int,
          "slides": [
            {
              "slide_index": int, "slide_id": int,
              "background": "#xxxxxx", "notes": str,
              "shapes": [
                {
                  "id": int, "name": str,
                  "_type": "TEXT" | "PICTURE" | "TABLE",
                  "left": int, "top": int, "width": int, "height": int,
                  "z_order": int, "fill": str | null,
                  # TEXT:    "has_text": true, "paragraphs": [{"align": str, "runs": [...]}]
                  # PICTURE: "image_b64": "data:image/...;base64,..."
                  # TABLE:   "table_rows": int, "table_cols": int,
                  #          "cells": [{"row": int, "col": int, "text": str}]
                }
              ]
            }
          ]
        }
    """
    try:
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
    except ImportError:
        raise RuntimeError("python-pptx 未安装，请执行: pip install python-pptx")

    prs = Presentation(file_path)
    slide_w: int = prs.slide_width or 9144000
    slide_h: int = prs.slide_height or 6858000
    slides_data: list[dict[str, Any]] = []

    # ── Inner helpers ────────────────────────────────────────────────────

    def _extract_bg(slide: Any) -> str:
        """Walk slide → layout → master for the first extractable solid fill."""
        for src in (slide, getattr(slide, "slide_layout", None), getattr(slide, "slide_master", None)):
            if src is None:
                continue
            try:
                f = src.background.fill
                # fill.type is an enum; compare by .name (e.g. 'SOLID') or numeric value 1
                if f.type is not None and getattr(f.type, 'name', '') == 'SOLID':
                    return "#" + str(f.fore_color.rgb).lower()
            except Exception:
                pass
        return "#FFFFFF"

    def _parse_tf(tf: Any) -> list[dict[str, Any]]:
        """Convert a python-pptx TextFrame into our [{align, runs:[...]}] format.

        Handles three common cases that cause text to disappear:
        1. Paragraph-level default run properties (defRPr) for font size/color
           — most real PPTs store the font size here, not on individual runs.
        2. Empty para.runs when text lives in <a:fld> field elements
           — use para.text as a fallback single run.
        3. Hard line-breaks (<a:br>) within a paragraph
           — emitted as a run with text='\n'.
        """
        # XML namespace used by DrawingML
        _NS = "http://schemas.openxmlformats.org/drawingml/2006/main"

        def _pt_from_emu_hundredths(val: Any) -> float | None:
            """python-pptx stores font size as 100ths of a point (e.g. 2400 = 24pt)."""
            try:
                v = int(val)
                return round(v / 100.0, 1) if v > 0 else None
            except Exception:
                return None

        def _read_rpr(rpr_el: Any) -> dict[str, Any]:
            """Extract font attributes from an <a:rPr> or <a:defRPr> XML element."""
            out: dict[str, Any] = {}
            if rpr_el is None:
                return out
            try:
                sz = rpr_el.get("sz")
                if sz:
                    pt = _pt_from_emu_hundredths(sz)
                    if pt:
                        out["size"] = pt
            except Exception:
                pass
            try:
                b = rpr_el.get("b")
                if b and b.lower() not in ("0", "false"):
                    out["bold"] = True
            except Exception:
                pass
            try:
                i = rpr_el.get("i")
                if i and i.lower() not in ("0", "false"):
                    out["italic"] = True
            except Exception:
                pass
            try:
                u = rpr_el.get("u")
                if u and u != "none":
                    out["underline"] = True
            except Exception:
                pass
            # Font name from <a:latin typeface="..."> child
            try:
                latin = rpr_el.find(f"{{{_NS}}}latin")
                if latin is not None:
                    tf_val = latin.get("typeface", "")
                    if tf_val and not tf_val.startswith("+"):
                        out["fontName"] = tf_val
            except Exception:
                pass
            # Solid colour from <a:solidFill><a:srgbClr val="rrggbb">
            try:
                solid = rpr_el.find(f"{{{_NS}}}solidFill")
                if solid is not None:
                    srgb = solid.find(f"{{{_NS}}}srgbClr")
                    if srgb is not None:
                        val = srgb.get("val", "")
                        if len(val) == 6:
                            out["color"] = "#" + val.lower()
            except Exception:
                pass
            return out

        paras: list[dict[str, Any]] = []
        for para in tf.paragraphs:
            align_name = "LEFT"
            try:
                if para.alignment:
                    align_name = para.alignment.name
            except Exception:
                pass

            # ── Read paragraph-level default run properties (defRPr) ──────
            # These serve as the fallback when a run has no explicit rPr attrs.
            para_defaults: dict[str, Any] = {}
            try:
                pPr = para._p.find(f"{{{_NS}}}pPr")
                if pPr is not None:
                    defRPr = pPr.find(f"{{{_NS}}}defRPr")
                    para_defaults = _read_rpr(defRPr)
            except Exception:
                pass

            p_obj: dict[str, Any] = {"align": align_name, "runs": []}

            # ── Iterate raw XML to capture <a:r> AND <a:br> (hard line-break) ──
            # python-pptx's para.runs only yields <a:r> elements and silently
            # skips <a:fld> field elements (e.g. slide numbers, date fields).
            # We walk _p directly so nothing is lost.
            try:
                for child in para._p:
                    tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

                    if tag == "br":
                        # Hard line-break: emit a newline run so rendering looks correct
                        p_obj["runs"].append({"text": "\n"})
                        continue

                    if tag not in ("r", "fld"):
                        continue

                    # Text node: <a:t> child
                    t_el = child.find(f"{{{_NS}}}t")
                    text_val = (t_el.text or "") if t_el is not None else ""

                    # Run-level properties (<a:rPr>)
                    rPr = child.find(f"{{{_NS}}}rPr")
                    run_attrs = _read_rpr(rPr)

                    # Merge: run attrs override paragraph defaults
                    r: dict[str, Any] = {"text": text_val}
                    for key in ("size", "bold", "italic", "underline", "fontName", "color"):
                        if key in run_attrs:
                            r[key] = run_attrs[key]
                        elif key in para_defaults:
                            r[key] = para_defaults[key]

                    p_obj["runs"].append(r)

            except Exception:
                # Fallback: use python-pptx's high-level .runs API
                for run in para.runs:
                    r_fb: dict[str, Any] = {"text": run.text}
                    try:
                        if run.font.size:
                            r_fb["size"] = round(run.font.size.pt, 1)
                    except Exception:
                        pass
                    try:
                        if run.font.bold:
                            r_fb["bold"] = True
                    except Exception:
                        pass
                    try:
                        if run.font.italic:
                            r_fb["italic"] = True
                    except Exception:
                        pass
                    try:
                        if run.font.underline:
                            r_fb["underline"] = True
                    except Exception:
                        pass
                    try:
                        if run.font.name:
                            r_fb["fontName"] = run.font.name
                    except Exception:
                        pass
                    try:
                        if run.font.color and run.font.color.type is not None:
                            r_fb["color"] = "#" + str(run.font.color.rgb).lower()
                    except Exception:
                        pass
                    p_obj["runs"].append(r_fb)

            # ── Fallback: if we still have no content, use para.text directly ──
            # This catches edge cases where XML walk also found nothing.
            if not any(r.get("text") for r in p_obj["runs"]):
                raw = ""
                try:
                    raw = para.text
                except Exception:
                    pass
                if raw.strip():
                    fallback_run: dict[str, Any] = {"text": raw}
                    fallback_run.update(para_defaults)
                    p_obj["runs"] = [fallback_run]

            paras.append(p_obj)
        return paras

    def _collect_shapes(
        shapes_iter: Any,
        out: list[dict[str, Any]],
        z_base: int = 0,
        off_left: int = 0,
        off_top: int = 0,
    ) -> None:
        """
        Recursively parse shapes into `out`.
        GROUP shapes are unwrapped and children are appended with their
        slide-absolute coordinates (group position added as offset).
        """
        for z_idx, shape in enumerate(shapes_iter):
            # ── Resolve effective geometry ───────────────────────────────────
            # python-pptx returns None for left/top/width/height when a
            # placeholder shape inherits its position from the slide layout.
            # (TITLE and BODY placeholders are almost always in this state.)
            # Falling back to 0 makes every text shape invisible because their
            # div has zero width/height — TABLE and PICTURE shapes are
            # always explicitly sized, which is why only they were visible.
            # Fix: pull the real geometry from the matching layout placeholder.
            eff_left = shape.left
            eff_top  = shape.top
            eff_w    = shape.width
            eff_h    = shape.height

            if None in (eff_left, eff_top, eff_w, eff_h):
                try:
                    ph_fmt = shape.placeholder_format
                    if ph_fmt is not None:
                        slide_layout = getattr(
                            getattr(shape, "part", None), "slide_layout", None
                        )
                        if slide_layout is not None:
                            for lph in slide_layout.placeholders:
                                try:
                                    if lph.placeholder_format.idx == ph_fmt.idx:
                                        if eff_left is None:
                                            eff_left = lph.left
                                        if eff_top is None:
                                            eff_top = lph.top
                                        if eff_w is None:
                                            eff_w = lph.width
                                        if eff_h is None:
                                            eff_h = lph.height
                                        break
                                except Exception:
                                    pass
                        # Walk slide master if layout didn't resolve everything
                        if None in (eff_left, eff_top, eff_w, eff_h):
                            slide_master = getattr(slide_layout, "slide_master", None) if slide_layout else None
                            if slide_master is not None:
                                for mph in slide_master.placeholders:
                                    try:
                                        if mph.placeholder_format.idx == ph_fmt.idx:
                                            if eff_left is None:
                                                eff_left = mph.left
                                            if eff_top is None:
                                                eff_top = mph.top
                                            if eff_w is None:
                                                eff_w = mph.width
                                            if eff_h is None:
                                                eff_h = mph.height
                                            break
                                    except Exception:
                                        pass
                        # If still None after layout+master, use standard widescreen EMU defaults
                        if None in (eff_left, eff_top, eff_w, eff_h):
                            _ph_idx = getattr(ph_fmt, "idx", -1)
                            _prs_shape = getattr(getattr(shape, "part", None), "presentation", None)
                            _sw = int(getattr(_prs_shape, "slide_width",  None) or 9144000)
                            _sh = int(getattr(_prs_shape, "slide_height", None) or 6858000)
                            if _ph_idx == 0:   # Title
                                if eff_left is None: eff_left = 457200
                                if eff_top  is None: eff_top  = 274638
                                if eff_w    is None: eff_w    = 8229600
                                if eff_h    is None: eff_h    = 1143000
                            elif _ph_idx == 1:  # Body / Content
                                if eff_left is None: eff_left = 457200
                                if eff_top  is None: eff_top  = 1600200
                                if eff_w    is None: eff_w    = 8229600
                                if eff_h    is None: eff_h    = 4525963
                            else:
                                if eff_left is None: eff_left = 0
                                if eff_top  is None: eff_top  = 0
                                if eff_w    is None: eff_w    = _sw
                                if eff_h    is None: eff_h    = _sh
                except Exception:
                    pass

            abs_left = (eff_left or 0) + off_left
            abs_top  = (eff_top  or 0) + off_top

            # ── Group: recurse with absolute-coordinate offset ──────────
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                try:
                    _collect_shapes(
                        shape.shapes,
                        out,
                        z_base=z_base + z_idx * 100,
                        off_left=abs_left,
                        off_top=abs_top,
                    )
                except Exception:
                    pass
                continue

            s: dict[str, Any] = {
                "id": shape.shape_id,
                "name": shape.name,
                "left": abs_left,
                "top": abs_top,
                "width":  eff_w or 0,
                "height": eff_h or 0,
                "z_order": z_base + z_idx,
                "fill": None,
            }

            # Shape fill colour — use .name attribute since str(fill.type) = 'SOLID (1)'
            try:
                fill = shape.fill
                if fill.type is not None and getattr(fill.type, 'name', '') == 'SOLID':
                    s["fill"] = "#" + str(fill.fore_color.rgb).lower()
            except Exception:
                pass

            # ── Picture ───────────────────────────────────────────────
            try:
                if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    img_blob = shape.image.blob
                    img_mime = shape.image.content_type or "image/png"
                    b64 = base64.b64encode(img_blob).decode("ascii")
                    s["_type"] = "PICTURE"
                    s["image_b64"] = f"data:{img_mime};base64,{b64}"
                    out.append(s)
                    continue
            except Exception:
                pass

            # ── Table ─────────────────────────────────────────────────
            try:
                if shape.has_table:
                    tbl = shape.table
                    cells: list[dict[str, Any]] = []
                    for r_idx, row in enumerate(tbl.rows):
                        for c_idx, cell in enumerate(row.cells):
                            cell_text = ""
                            try:
                                cell_text = (
                                    cell.text_frame.text if cell.text_frame else ""
                                )
                            except Exception:
                                pass
                            cells.append({"row": r_idx, "col": c_idx, "text": cell_text})
                    s["_type"] = "TABLE"
                    s["table_rows"] = len(tbl.rows)
                    s["table_cols"] = len(tbl.columns)
                    s["cells"] = cells
                    out.append(s)
                    continue
            except Exception:
                pass

            # ── Text frame ────────────────────────────────────────────
            try:
                if getattr(shape, "has_text_frame", False) and shape.text_frame:
                    s["_type"] = "TEXT"
                    s["has_text"] = True
                    is_title = False
                    try:
                        from pptx.enum.shapes import PP_PLACEHOLDER
                        ph = shape.placeholder_format
                        if ph is not None:
                            is_title = ph.type in (
                                PP_PLACEHOLDER.TITLE,
                                PP_PLACEHOLDER.CENTER_TITLE,
                            )
                    except Exception:
                        pass
                    s["is_title"] = is_title
                    s["paragraphs"] = _parse_tf(shape.text_frame)
                    out.append(s)
            except Exception:
                pass

            # Connectors / freeforms / other unsupported — silently skip

    # ── Main loop ────────────────────────────────────────────────────────

    for slide_idx, slide in enumerate(prs.slides):
        bg_hex = _extract_bg(slide)

        notes_text = ""
        try:
            if slide.has_notes_slide:
                notes_text = slide.notes_slide.notes_text_frame.text.strip()
        except Exception:
            pass

        shapes_data: list[dict[str, Any]] = []
        _collect_shapes(slide.shapes, shapes_data)

        slides_data.append(
            {
                "slide_index": slide_idx,
                "slide_id": slide_idx + 1,
                "background": bg_hex,
                "notes": notes_text,
                "shapes": shapes_data,
            }
        )

    return {
        "slide_width_emu": int(slide_w),
        "slide_height_emu": int(slide_h),
        "slides": slides_data,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PDF → 文本提取 + 原始 URL
# ─────────────────────────────────────────────────────────────────────────────


def parse_pdf(file_path: str, file_id: str) -> dict[str, Any]:
    """
    提取 PDF 全量文本，供 AI RAG 使用。
    同时返回原始文件的 raw URL，供前端 PDF.js 渲染。

    文字提取回退链：pdfplumber → pypdf → PyPDF2。
    若三个库均不可用，仍返回含 raw_url 的结果（PDF.js 视觉渲染不依赖文字提取）。

    Returns:
        {"text": str, "page_count": int, "raw_url": str,
         "pages": [{"page": int, "text": str}]}
    """
    raw_url = f"/api/v1/workspace/raw/{file_id}"
    pages_text: list[dict[str, Any]] = []
    full_text_parts: list[str] = []
    page_count = 0

    # ── 1. pdfplumber（首选：支持表格提取） ─────────────────────────────────
    try:
        import pdfplumber  # type: ignore

        with pdfplumber.open(file_path) as pdf:
            page_count = len(pdf.pages)
            for i, page in enumerate(pdf.pages):
                try:
                    page_text = page.extract_text() or ""
                except Exception as e:
                    logger.warning(f"[PdfParser/pdfplumber] 第 {i+1} 页文本提取失败: {e}")
                    page_text = ""
                pages_text.append({"page": i + 1, "text": page_text})
                if page_text:
                    full_text_parts.append(page_text)

        return {
            "text": "\n\n".join(full_text_parts),
            "page_count": page_count,
            "raw_url": raw_url,
            "pages": pages_text,
        }
    except ImportError:
        logger.info("[PdfParser] pdfplumber 未安装，尝试 pypdf/PyPDF2")
    except Exception as e:
        logger.warning(f"[PdfParser] pdfplumber 解析失败: {e}，尝试下一库")

    # ── 2. pypdf / PyPDF2 回退 ───────────────────────────────────────────────
    for pkg_name, mod_name in [("pypdf", "pypdf"), ("PyPDF2", "PyPDF2")]:
        try:
            mod = __import__(mod_name)
            PdfReader = getattr(mod, "PdfReader")
            with open(file_path, "rb") as fh:
                reader = PdfReader(fh)
                page_count = len(reader.pages)
                for i, pg in enumerate(reader.pages):
                    try:
                        page_text = pg.extract_text() or ""
                    except Exception as e:
                        logger.warning(f"[PdfParser/{pkg_name}] 第 {i+1} 页文本提取失败: {e}")
                        page_text = ""
                    pages_text.append({"page": i + 1, "text": page_text})
                    if page_text:
                        full_text_parts.append(page_text)

            return {
                "text": "\n\n".join(full_text_parts),
                "page_count": page_count,
                "raw_url": raw_url,
                "pages": pages_text,
            }
        except ImportError:
            logger.info(f"[PdfParser] {pkg_name} 未安装，尝试下一库")
            continue
        except Exception as e:
            logger.warning(f"[PdfParser] {pkg_name} 解析失败: {e}，尝试下一库")
            pages_text = []
            full_text_parts = []
            continue

    # ── 3. 所有文字提取库均不可用——仍返回 raw_url 供 PDF.js 渲染 ────────────
    logger.warning(
        "[PdfParser] pdfplumber / pypdf / PyPDF2 均不可用，文字提取跳过。"
        " 请执行: pip install pdfplumber"
    )
    return {
        "text": "",
        "page_count": 0,
        "raw_url": raw_url,
        "pages": [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# DOCX 导出: 修改后 HTML → .docx
# ─────────────────────────────────────────────────────────────────────────────


def _css_color_to_hex(value: str) -> str | None:
    """Convert a CSS color string like '#aabbcc' or 'rgb(r,g,b)' to a 6-char hex string."""
    if not value:
        return None
    value = value.strip()
    if value.startswith("#"):
        v = value.lstrip("#")
        if len(v) == 3:
            v = "".join(c * 2 for c in v)
        return v.upper() if len(v) == 6 else None
    if value.startswith("rgb"):
        nums = re.findall(r"\d+", value)
        if len(nums) >= 3:
            return "{:02X}{:02X}{:02X}".format(int(nums[0]), int(nums[1]), int(nums[2]))
    return None


def _parse_css_inline(style_str: str) -> dict[str, str]:
    """Parse a CSS inline style string into a {property: value} dict."""
    result: dict[str, str] = {}
    for part in style_str.split(";"):
        part = part.strip()
        if ":" not in part:
            continue
        prop, _, val = part.partition(":")
        result[prop.strip().lower()] = val.strip()
    return result


def _apply_run_inline(run: Any, css: dict[str, str]) -> None:
    """Apply inline CSS to a python-docx Run (bold, italic, color, font-size)."""
    from docx.shared import Pt, RGBColor

    if css.get("font-weight") in ("bold", "700", "800", "900"):
        run.bold = True
    if css.get("font-style") == "italic":
        run.italic = True
    if css.get("text-decoration") == "underline":
        run.underline = True
    color_hex = _css_color_to_hex(css.get("color", ""))
    if color_hex:
        r, g, b = int(color_hex[0:2], 16), int(color_hex[2:4], 16), int(color_hex[4:6], 16)
        run.font.color.rgb = RGBColor(r, g, b)
    fs = css.get("font-size", "")
    if fs.endswith("pt"):
        try:
            run.font.size = Pt(float(fs[:-2]))
        except ValueError:
            pass
    elif fs.endswith("px"):
        try:
            run.font.size = Pt(float(fs[:-2]) * 0.75)
        except ValueError:
            pass


def _add_paragraph_from_tag(doc: Any, tag: Any) -> None:
    """Convert a single <p>/<h1>-<h6>/<li> BS4 tag into a python-docx paragraph."""
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    tag_name = tag.name.lower()
    if tag_name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = int(tag_name[1])
        para = doc.add_heading("", level=level)
    else:
        para = doc.add_paragraph()

    # Text alignment from parent style
    style_str = tag.get("style", "")
    if style_str:
        pcss = _parse_css_inline(style_str)
        align = pcss.get("text-align", "")
        if align == "center":
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif align == "right":
            para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        elif align == "justify":
            para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    # Walk inline children (text nodes + <strong>, <em>, <span>, <a>, <u>)
    for child in tag.children:
        if hasattr(child, "name") and child.name is None:
            # NavigableString
            text = str(child)
            if text:
                para.add_run(text)
        elif hasattr(child, "name"):
            name = child.name.lower() if child.name else ""
            text = child.get_text()
            if not text:
                continue
            run = para.add_run(text)
            child_css: dict[str, str] = _parse_css_inline(child.get("style", ""))
            if name in ("strong", "b"):
                run.bold = True
            if name in ("em", "i"):
                run.italic = True
            if name == "u":
                run.underline = True
            if name == "s":
                run.font.strike = True
            _apply_run_inline(run, child_css)


def _set_cell_shading(cell: Any, fill_hex: str) -> None:
    """Set the background shading of a python-docx table cell via direct XML."""
    from lxml import etree

    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    # Remove any existing shd element
    for shd in tcPr.findall(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}shd"
    ):
        tcPr.remove(shd)
    WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    shd = etree.SubElement(tcPr, f"{{{WNS}}}shd")
    shd.set(f"{{{WNS}}}val", "clear")
    shd.set(f"{{{WNS}}}color", "auto")
    shd.set(f"{{{WNS}}}fill", fill_hex.upper())


def _set_cell_borders(cell: Any, border_hex: str | None) -> None:
    """Apply a simple all-sides border to a cell using the given colour hex."""
    from lxml import etree

    if not border_hex:
        return
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    tcBorders = tcPr.find(f"{{{WNS}}}tcBorders")
    if tcBorders is None:
        tcBorders = etree.SubElement(tcPr, f"{{{WNS}}}tcBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = tcBorders.find(f"{{{WNS}}}{side}")
        if el is None:
            el = etree.SubElement(tcBorders, f"{{{WNS}}}{side}")
        el.set(f"{{{WNS}}}val", "single")
        el.set(f"{{{WNS}}}sz", "4")
        el.set(f"{{{WNS}}}color", border_hex.upper())


def _export_docx_python(html_content: str) -> bytes:
    """
    Build a .docx from WangEditor HTML using python-docx directly.

    Supports:
    - Headings (h1–h6), paragraphs, list items
    - Tables with colspan/rowspan (merged cells), cell background colours,
      column widths, th header rows, text alignment, vertical alignment
    - Inline bold/italic/underline/strike/color/font-size on runs
    """
    try:
        from bs4 import BeautifulSoup
        from docx import Document
        from docx.shared import Inches, Pt, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.enum.table import WD_ALIGN_VERTICAL
        from docx.oxml.ns import qn
    except ImportError as exc:
        raise RuntimeError(f"python-docx 或 beautifulsoup4 未安装: {exc}") from exc

    doc = Document()

    # Remove default empty paragraph that python-docx adds on creation
    for para in list(doc.paragraphs):
        p = para._element
        p.getparent().remove(p)

    soup = BeautifulSoup(html_content, "html.parser")
    body = soup.find("body") or soup

    for top in body.children:
        if not hasattr(top, "name") or top.name is None:
            # bare text node
            text = str(top).strip()
            if text:
                doc.add_paragraph(text)
            continue

        tag_name = top.name.lower()

        # ── Block-level text elements ──────────────────────────────────────
        if tag_name in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li"):
            _add_paragraph_from_tag(doc, top)
            continue

        if tag_name in ("ul", "ol"):
            for li in top.find_all("li", recursive=False):
                _add_paragraph_from_tag(doc, li)
            continue

        # ── Tables ─────────────────────────────────────────────────────────
        if tag_name == "table":
            rows_tags = top.find_all("tr")
            if not rows_tags:
                continue

            # Determine table dimensions
            col_count = 0
            for r in rows_tags:
                c = 0
                for cell in r.find_all(["td", "th"], recursive=False):
                    c += int(cell.get("colspan", 1))
                col_count = max(col_count, c)
            if col_count == 0:
                continue

            tbl = doc.add_table(rows=len(rows_tags), cols=col_count)
            tbl.style = "Table Grid"

            # Track which (row, col) positions are already consumed by a
            # rowspan merge so we skip writing to them again.
            occupied: dict[tuple[int, int], bool] = {}

            for ri, row_tag in enumerate(rows_tags):
                cell_tags = row_tag.find_all(["td", "th"], recursive=False)
                ci = 0  # logical col cursor
                for cell_tag in cell_tags:
                    # Advance past cells already filled by a previous rowspan
                    while occupied.get((ri, ci)):
                        ci += 1

                    colspan = int(cell_tag.get("colspan", 1))
                    rowspan = int(cell_tag.get("rowspan", 1))

                    # Guard against out-of-range
                    if ci >= col_count:
                        break

                    # Mark all cells this span covers as occupied
                    for dr in range(rowspan):
                        for dc in range(colspan):
                            if dr == 0 and dc == 0:
                                continue
                            occupied[(ri + dr, ci + dc)] = True

                    tbl_cell = tbl.cell(ri, ci)

                    # ── Merge ────────────────────────────────────────────
                    end_r = min(ri + rowspan - 1, len(rows_tags) - 1)
                    end_c = min(ci + colspan - 1, col_count - 1)
                    if end_r > ri or end_c > ci:
                        tbl_cell.merge(tbl.cell(end_r, end_c))

                    # ── Cell text ────────────────────────────────────────
                    # Clear the default empty paragraph python-docx adds
                    for p_el in list(tbl_cell.paragraphs):
                        p_el._element.getparent().remove(p_el._element)

                    # Write inline content into the cell
                    cell_para = tbl_cell.add_paragraph()
                    cell_css = _parse_css_inline(cell_tag.get("style", ""))

                    # Text alignment
                    align = cell_css.get("text-align", "")
                    if align == "center":
                        cell_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    elif align == "right":
                        cell_para.alignment = WD_ALIGN_PARAGRAPH.RIGHT

                    # Vertical alignment
                    v_align = cell_css.get("vertical-align", "").lower()
                    if v_align == "middle":
                        tbl_cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                    elif v_align == "bottom":
                        tbl_cell.vertical_alignment = WD_ALIGN_VERTICAL.BOTTOM

                    # Bold if <th>
                    is_header = cell_tag.name.lower() == "th"

                    for child in cell_tag.children:
                        if not hasattr(child, "name") or child.name is None:
                            text = str(child).strip()
                            if text:
                                run = cell_para.add_run(text)
                                if is_header:
                                    run.bold = True
                        else:
                            child_name = child.name.lower() if child.name else ""
                            text = child.get_text()
                            if not text:
                                continue
                            run = cell_para.add_run(text)
                            if is_header:
                                run.bold = True
                            child_css = _parse_css_inline(child.get("style", ""))
                            if child_name in ("strong", "b"):
                                run.bold = True
                            if child_name in ("em", "i"):
                                run.italic = True
                            if child_name == "u":
                                run.underline = True
                            _apply_run_inline(run, child_css)

                    # ── Cell background colour ───────────────────────────
                    bg = cell_css.get("background-color", "") or cell_css.get("background", "")
                    bg_hex = _css_color_to_hex(bg)
                    if not bg_hex and is_header:
                        bg_hex = "EEF1F8"  # default header shading
                    if bg_hex:
                        _set_cell_shading(tbl_cell, bg_hex)

                    # ── Border colour override ───────────────────────────
                    border_raw = cell_css.get("border-color", "")
                    border_hex = _css_color_to_hex(border_raw)
                    if border_hex:
                        _set_cell_borders(tbl_cell, border_hex)

                    ci += colspan

            # ── Column widths from <col> or first row <td style="width:..."> ──
            col_tags = top.find_all("col")
            if col_tags:
                for idx, col_tag in enumerate(col_tags[:col_count]):
                    w_css = _parse_css_inline(col_tag.get("style", ""))
                    width_str = w_css.get("width", col_tag.get("width", ""))
                    if width_str:
                        try:
                            if width_str.endswith("px"):
                                emu = int(float(width_str[:-2]) * 9144)  # 1px ≈ 9144 EMU
                                for r in range(len(rows_tags)):
                                    tbl.cell(r, idx).width = emu
                            elif width_str.endswith("%"):
                                pass  # relative widths handled by Word auto-layout
                        except (ValueError, IndexError):
                            pass

            continue  # done with this table

        # ── Any other block: just extract its text ─────────────────────────
        text = top.get_text(separator=" ").strip()
        if text:
            doc.add_paragraph(text)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


def export_docx(html_content: str) -> bytes:
    """
    将 WangEditor 产出的 HTML 转换为 .docx 字节流。

    主路径：_export_docx_python — 基于 python-docx 直接构建，完整支持：
      - 合并单元格 (colspan/rowspan)
      - 单元格背景色、边框色
      - 列宽、对齐方式
      - 行内格式（加粗、斜体、颜色、字号）

    备用路径：html2docx（当 python-docx/bs4 导入失败时）

    Returns:
        bytes — .docx 文件内容
    """
    logger.info(
        "[export_docx] html_content length=%d preview=%.200s",
        len(html_content or ""),
        (html_content or "")[:200],
    )

    # ── Primary: rich python-docx builder ──────────────────────────────────
    try:
        return _export_docx_python(html_content)
    except Exception as exc:
        logger.warning("[export_docx] python-docx builder failed (%s), falling back to html2docx", exc)

    # ── Fallback: html2docx (handles edge cases the builder misses) ─────────
    try:
        from html2docx import html2docx

        wrapped_html = (
            '<html><head><meta charset="utf-8">'
            '<style>body{font-family:"Microsoft YaHei","PingFang SC","SimHei",Arial,sans-serif;'
            "font-size:11pt;line-height:1.6;}"
            "h1{font-size:20pt}h2{font-size:16pt}h3{font-size:14pt}"
            "</style></head><body>" + html_content + "</body></html>"
        )
        buf = html2docx(wrapped_html, title="Koto 导出文档")
        buf.seek(0)
        data = buf.read()
        if data:
            return data
    except ImportError:
        pass

    raise RuntimeError("export_docx: 所有路径均失败，请确认 python-docx 和 beautifulsoup4 已安装")


# ─────────────────────────────────────────────────────────────────────────────
# XLSX 导出: Luckysheet JSON → .xlsx
# ─────────────────────────────────────────────────────────────────────────────


def export_xlsx(
    sheets_json: Any, images: list[dict] | None = None
) -> bytes:
    """
    将编辑器序列化数据重建为 .xlsx 字节流。

    支持两种输入格式:
    - Univer IWorkbookData (dict): {sheetOrder:[...], sheets:{id:{name, cellData:{row:{col:{v,...}}}}}}
    - Luckysheet legacy (list):  [{name, celldata:[{r,c,v:{v:...}}]}]

    副加 images (前端 overlay) 嵌入到第一个 sheet。

    Returns:
        bytes — .xlsx 文件内容
    """
    try:
        import openpyxl
    except ImportError:
        raise RuntimeError("openpyxl 未安装")

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # 删除默认空 sheet

    # ── Detect format ────────────────────────────────────────────────────────
    is_univer = isinstance(sheets_json, dict) and "sheetOrder" in sheets_json

    if is_univer:
        # Univer IWorkbookData format
        sheet_order = sheets_json.get("sheetOrder", [])
        sheets_map = sheets_json.get("sheets", {})
        for sheet_id in sheet_order:
            sheet_data = sheets_map.get(sheet_id, {})
            ws = wb.create_sheet(title=sheet_data.get("name", "Sheet"))
            cell_data = sheet_data.get("cellData", {})
            for row_key, row_cells in cell_data.items():
                r = int(row_key) + 1  # Univer 0-indexed → openpyxl 1-indexed
                for col_key, cell in row_cells.items():
                    c = int(col_key) + 1
                    if cell and "v" in cell:
                        ws.cell(row=r, column=c, value=cell["v"])
    else:
        # Luckysheet legacy format (list of sheets)
        if not isinstance(sheets_json, list):
            sheets_json = []
        for sheet_data in sheets_json:
            ws = wb.create_sheet(title=sheet_data.get("name", "Sheet"))
            for cell_entry in sheet_data.get("celldata", []):
                r = cell_entry.get("r", 0) + 1  # Luckysheet 0-indexed → openpyxl 1-indexed
                c = cell_entry.get("c", 0) + 1
                v = cell_entry.get("v", {})
                if v:
                    ws.cell(row=r, column=c, value=v.get("v"))

    # Embed overlay images into the first sheet (if any)
    if images and wb.worksheets:
        import base64
        import io as _io

        try:
            from openpyxl.drawing.image import Image as XlImage
        except ImportError:
            XlImage = None
        if XlImage:
            ws_first = wb.worksheets[0]
            for img_data in images:
                src = img_data.get("src", "")
                if not src or not src.startswith("data:image"):
                    continue
                try:
                    # data:image/png;base64,<data>
                    b64 = src.split(",", 1)[1]
                    raw = base64.b64decode(b64)
                    ximg = XlImage(_io.BytesIO(raw))
                    ws_first.add_image(ximg, "A1")
                except Exception:
                    pass  # skip unreadable images

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


# ─────────────────────────────────────────────────────────────────────────────
# PPTX 导出: 仅替换文字 (保留主题/动画)
# ─────────────────────────────────────────────────────────────────────────────


def export_pptx(original_path: str, slides_json: Any) -> bytes:
    """
    在原始 PPTX 文件上就地替换文字/表格内容，不重建 PPT 结构。
    保留原 PPT 的主题背景、图片、动画等。

    Args:
        original_path: 暂存的原始 .pptx 文件路径
        slides_json: 画布编辑器序列化数据（两种格式）:
          - 新格式 (几何画布): {"slides": [{"slide_index": int, "shapes": [
              {"_type": "TEXT", "id": int, "text": str} |
              {"_type": "TABLE", "id": int, "cells": [{"row", "col", "text"}]}
            ]}]}
          - 旧格式 (文本卡片): [{"slide_index": int, "texts": [{"shape_id": int, "text": str}]}]

    Returns:
        bytes — 修改后的 .pptx 文件内容
    """
    try:
        from pptx import Presentation
    except ImportError:
        raise RuntimeError("python-pptx 未安装")

    prs = Presentation(original_path)

    # 构建 shape lookup: slide_index → shape_id → shape (all shapes, not just text)
    slides_map: dict[int, dict[int, Any]] = {}
    for slide_idx, slide in enumerate(prs.slides):
        shape_map: dict[int, Any] = {shape.shape_id: shape for shape in slide.shapes}
        slides_map[slide_idx] = shape_map

    def _replace_text_frame(tf: Any, new_text: str) -> None:
        """Replace all text in a text frame preserving the first run's style."""
        if not tf.paragraphs:
            return
        first_para = tf.paragraphs[0]
        if first_para.runs:
            first_para.runs[0].text = new_text
            for run in first_para.runs[1:]:
                run.text = ""
        else:
            # No existing runs — add one rather than using para.text= (which destroys XML)
            run = first_para.add_run()
            run.text = new_text
        for para in tf.paragraphs[1:]:
            for run in para.runs:
                run.text = ""

    # Detect format: new geometry canvas dict vs legacy text-card list
    if isinstance(slides_json, dict) and "slides" in slides_json:
        # ── New geometry canvas format ──
        for slide_data in slides_json["slides"]:
            slide_idx = slide_data.get("slide_index", 0)
            shape_map = slides_map.get(slide_idx, {})
            for shape_entry in slide_data.get("shapes", []):
                shape_id = shape_entry.get("id") or shape_entry.get("shape_id")
                shape = shape_map.get(shape_id)
                if shape is None:
                    continue
                stype = shape_entry.get("_type", "TEXT")
                if stype == "TEXT":
                    if shape.has_text_frame:
                        _replace_text_frame(
                            shape.text_frame, shape_entry.get("text", "")
                        )
                elif stype == "TABLE":
                    if shape.has_table:
                        tbl = shape.table
                        for cell_data in shape_entry.get("cells", []):
                            r, c = cell_data.get("row", 0), cell_data.get("col", 0)
                            try:
                                cell = tbl.cell(r, c)
                                if cell.text_frame:
                                    _replace_text_frame(
                                        cell.text_frame, cell_data.get("text", "")
                                    )
                            except Exception:
                                pass
    else:
        # ── Legacy text-card format ──
        for slide_data in slides_json or []:
            slide_idx = slide_data.get("slide_index", 0)
            shape_map = slides_map.get(slide_idx, {})
            for text_entry in slide_data.get("texts", []):
                shape_id = text_entry.get("shape_id")
                shape = shape_map.get(shape_id)
                if shape is None or not shape.has_text_frame:
                    continue
                _replace_text_frame(shape.text_frame, text_entry.get("text", ""))

    buf = io.BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf.read()
