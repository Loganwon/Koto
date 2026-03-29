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

def parse_docx(file_path: str) -> dict[str, Any]:
    """
    使用 mammoth 将 DOCX 转换为语义 HTML。
    图片以 base64 data URI 内联，保证前端渲染自包含。

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

        return {"html": result.value, "messages": messages_out}
    except Exception as e:
        logger.error(f"[DocxParser] 解析失败: {e}")
        raise


# ─────────────────────────────────────────────────────────────────────────────
# XLSX → Luckysheet 兼容 JSON
# ─────────────────────────────────────────────────────────────────────────────

# Luckysheet 单元格数值类型映射
_CELL_TYPE_MAP = {
    "n": 1,   # numeric
    "s": 0,   # string (general)
    "b": "bool",
    "d": "date",
    "e": "error",
}

_ALIGN_H_MAP = {
    "general": 0,
    "left": 1,
    "center": 2,
    "right": 3,
    "fill": 4,
    "justify": 5,
    "centerContinuous": 6,
    "distributed": 7,
}

_ALIGN_V_MAP = {
    "top": 1,
    "center": 2,
    "bottom": 3,
    "justify": 4,
    "distributed": 5,
}


def _openpyxl_cell_to_luckysheet(cell: Any) -> dict[str, Any]:
    """将单个 openpyxl Cell 转换为 Luckysheet celldata 对象。"""
    v = cell.value
    ct: dict[str, Any] = {}

    if v is None:
        return {}

    # 基础值
    if isinstance(v, bool):
        ct = {"t": "b", "v": int(v), "m": str(v).upper()}
    elif isinstance(v, (int, float)):
        ct = {"t": "n", "v": v, "m": str(v)}
    else:
        ct = {"t": "s", "v": str(v), "m": str(v)}

    # 样式
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
            if font.color and font.color.type == "rgb" and font.color.rgb != "00000000":
                style["fc"] = "#" + font.color.rgb[2:]  # strip alpha
        fill = cell.fill
        if fill and fill.fill_type not in (None, "none") and fill.fgColor:
            if fill.fgColor.type == "rgb" and fill.fgColor.rgb not in ("00000000", "FFFFFFFF"):
                style["bg"] = "#" + fill.fgColor.rgb[2:]
        ali = cell.alignment
        if ali:
            if ali.horizontal and ali.horizontal in _ALIGN_H_MAP:
                style["ht"] = _ALIGN_H_MAP[ali.horizontal]
            if ali.vertical and ali.vertical in _ALIGN_V_MAP:
                style["vt"] = _ALIGN_V_MAP[ali.vertical]
    except Exception:
        pass  # 样式提取失败不影响数据

    if style:
        ct["s"] = style

    return ct


def parse_xlsx(file_path: str) -> list[dict[str, Any]]:
    """
    使用 openpyxl 将 XLSX 转换为 Luckysheet 初始化 JSON 数组。
    每个元素对应一个 Sheet。

    Returns:
        [{"name": str, "index": str, "order": int,
          "celldata": [{"r": int, "c": int, "v": {...}}],
          "mergeInfo": [...], "config": {"merge": {}}}]
    """
    try:
        import openpyxl
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise RuntimeError("openpyxl 未安装，请执行: pip install openpyxl")

    wb = openpyxl.load_workbook(file_path, data_only=True)
    sheets_data: list[dict[str, Any]] = []

    for idx, ws in enumerate(wb.worksheets):
        celldata: list[dict[str, Any]] = []

        for row in ws.iter_rows():
            for cell in row:
                ct = _openpyxl_cell_to_luckysheet(cell)
                if ct:
                    celldata.append({"r": cell.row - 1, "c": cell.column - 1, "v": ct})

        # 合并单元格
        merge_config: dict[str, Any] = {}
        for merge_range in ws.merged_cells.ranges:
            min_r = merge_range.min_row - 1
            min_c = merge_range.min_col - 1
            row_span = merge_range.max_row - merge_range.min_row
            col_span = merge_range.max_col - merge_range.min_col
            key = f"{min_r}_{min_c}"
            merge_config[key] = {
                "r": min_r,
                "c": min_c,
                "rs": row_span,
                "cs": col_span,
            }

        sheet_json: dict[str, Any] = {
            "name": ws.title,
            "index": str(idx),
            "order": idx,
            "status": 1 if idx == 0 else 0,
            "celldata": celldata,
            "row": ws.max_row or 30,
            "column": ws.max_column or 10,
            "config": {"merge": merge_config} if merge_config else {},
        }
        sheets_data.append(sheet_json)

    wb.close()
    return sheets_data


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

            texts.append({
                "shape_id": shape.shape_id,
                "shape_name": shape.name,
                "text": text_content,
                "is_title": is_title,
            })

        slides_data.append({
            "slide_id": slide_idx + 1,
            "slide_index": slide_idx,
            "texts": texts,
        })

    return slides_data


# ─────────────────────────────────────────────────────────────────────────────
# PPTX → 几何画布 JSON (含图片/表格/备注)
# ─────────────────────────────────────────────────────────────────────────────

def parse_pptx_geometry(file_path: str) -> dict[str, Any]:
    """
    使用 python-pptx 提取每个 Slide 的完整几何数据，供前端画布编辑器渲染。
    包含文本框 (含字体样式)、图片 (base64 data URI)、表格 (单元格文本)、备注。

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

    for slide_idx, slide in enumerate(prs.slides):
        # Background fill colour
        bg_hex = "#FFFFFF"
        try:
            bg_fill = slide.background.fill
            if bg_fill.type is not None and str(bg_fill.type) in ("SOLID", "1"):
                bg_hex = "#{:06x}".format(int(bg_fill.fore_color.rgb))
        except Exception:
            pass

        # Speaker notes
        notes_text = ""
        try:
            if slide.has_notes_slide:
                notes_text = slide.notes_slide.notes_text_frame.text.strip()
        except Exception:
            pass

        shapes_data: list[dict[str, Any]] = []

        for z_idx, shape in enumerate(slide.shapes):
            s: dict[str, Any] = {
                "id": shape.shape_id,
                "name": shape.name,
                "left": shape.left or 0,
                "top": shape.top or 0,
                "width": shape.width or 0,
                "height": shape.height or 0,
                "z_order": z_idx,
                "fill": None,
            }

            # Shape fill colour
            try:
                fill = shape.fill
                if fill.type is not None and str(fill.type) in ("SOLID", "1"):
                    s["fill"] = "#{:06x}".format(int(fill.fore_color.rgb))
            except Exception:
                pass

            # ── Picture ──
            try:
                if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    img_blob = shape.image.blob
                    img_mime = shape.image.content_type or "image/png"
                    b64 = base64.b64encode(img_blob).decode("ascii")
                    s["_type"] = "PICTURE"
                    s["image_b64"] = f"data:{img_mime};base64,{b64}"
                    shapes_data.append(s)
                    continue
            except Exception:
                pass

            # ── Table ──
            try:
                if shape.has_table:
                    tbl = shape.table
                    cells: list[dict[str, Any]] = []
                    for r_idx, row in enumerate(tbl.rows):
                        for c_idx, cell in enumerate(row.cells):
                            cell_text = ""
                            try:
                                cell_text = cell.text_frame.text if cell.text_frame else ""
                            except Exception:
                                pass
                            cells.append({"row": r_idx, "col": c_idx, "text": cell_text})
                    s["_type"] = "TABLE"
                    s["table_rows"] = len(tbl.rows)
                    s["table_cols"] = len(tbl.columns)
                    s["cells"] = cells
                    shapes_data.append(s)
                    continue
            except Exception:
                pass

            # ── Text frame ──
            if getattr(shape, "has_text_frame", False) and shape.text_frame:
                s["_type"] = "TEXT"
                s["has_text"] = True
                paras: list[dict[str, Any]] = []
                for para in shape.text_frame.paragraphs:
                    align_name = "LEFT"
                    try:
                        if para.alignment:
                            align_name = para.alignment.name
                    except Exception:
                        pass
                    p_obj: dict[str, Any] = {"align": align_name, "runs": []}
                    for run in para.runs:
                        r: dict[str, Any] = {"text": run.text}
                        try:
                            if run.font.size:
                                r["size"] = round(run.font.size.pt, 1)
                        except Exception:
                            pass
                        try:
                            if run.font.bold:
                                r["bold"] = True
                        except Exception:
                            pass
                        try:
                            if run.font.italic:
                                r["italic"] = True
                        except Exception:
                            pass
                        try:
                            if run.font.underline:
                                r["underline"] = True
                        except Exception:
                            pass
                        try:
                            if run.font.color and run.font.color.type is not None:
                                r["color"] = "#{:06x}".format(int(run.font.color.rgb))
                        except Exception:
                            pass
                        p_obj["runs"].append(r)
                    paras.append(p_obj)
                s["paragraphs"] = paras
            else:
                # Connectors, groups, or other unsupported shapes — skip
                continue

            shapes_data.append(s)

        slides_data.append({
            "slide_index": slide_idx,
            "slide_id": slide_idx + 1,
            "background": bg_hex,
            "notes": notes_text,
            "shapes": shapes_data,
        })

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
    使用 pdfplumber 提取 PDF 全量文本，供 AI RAG 使用。
    同时返回原始文件的 raw URL，供前端 PDF.js 渲染。

    Returns:
        {"text": str, "page_count": int, "raw_url": str,
         "pages": [{"page": int, "text": str}]}
    """
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pdfplumber 未安装，请执行: pip install pdfplumber")

    pages_text: list[dict[str, Any]] = []
    full_text_parts: list[str] = []

    with pdfplumber.open(file_path) as pdf:
        page_count = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            try:
                page_text = page.extract_text() or ""
            except Exception as e:
                logger.warning(f"[PdfParser] 第 {i+1} 页文本提取失败: {e}")
                page_text = ""
            pages_text.append({"page": i + 1, "text": page_text})
            if page_text:
                full_text_parts.append(page_text)

    return {
        "text": "\n\n".join(full_text_parts),
        "page_count": page_count,
        "raw_url": f"/api/v1/workspace/raw/{file_id}",
        "pages": pages_text,
    }


# ─────────────────────────────────────────────────────────────────────────────
# DOCX 导出: 修改后 HTML → .docx
# ─────────────────────────────────────────────────────────────────────────────

def export_docx(html_content: str) -> bytes:
    """
    将 WangEditor 产出的 HTML 转换为 .docx 字节流。
    优先使用 html2docx；若不可用则回退到 python-docx + BeautifulSoup 简单提取。

    Returns:
        bytes — .docx 文件内容
    """
    logger.info("[export_docx] html_content length=%d preview=%.200s", len(html_content or ""), (html_content or "")[:200])
    try:
        from html2docx import html2docx
        # Wrap with a default font style so html2docx preserves a consistent CJK-friendly font
        wrapped_html = (
            '<html><head><meta charset="utf-8">'
            '<style>body{font-family:"Microsoft YaHei","PingFang SC","SimHei",Arial,sans-serif;'
            'font-size:11pt;line-height:1.6;}'
            'h1{font-size:20pt}h2{font-size:16pt}h3{font-size:14pt}'
            '</style></head><body>'
            + html_content
            + '</body></html>'
        )
        buf = html2docx(wrapped_html, title="Koto 导出文档")
        buf.seek(0)  # html2docx returns BytesIO at EOF — must rewind before reading
        data = buf.read()
        if data:
            return data
        # Fall through to BeautifulSoup if html2docx produced empty output
    except ImportError:
        pass

    # 回退方案：python-docx 纯文本提取
    try:
        from docx import Document
        from bs4 import BeautifulSoup
    except ImportError:
        raise RuntimeError("html2docx 或 (python-docx + beautifulsoup4) 未安装")

    doc = Document()
    soup = BeautifulSoup(html_content, "html.parser")

    for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li"]):
        tag = element.name
        text = element.get_text(separator=" ").strip()
        if not text:
            continue
        if tag in ("h1", "h2", "h3"):
            doc.add_heading(text, level=int(tag[1]))
        else:
            doc.add_paragraph(text)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


# ─────────────────────────────────────────────────────────────────────────────
# XLSX 导出: Luckysheet JSON → .xlsx
# ─────────────────────────────────────────────────────────────────────────────

def export_xlsx(sheets_json: list[dict[str, Any]], images: list[dict] | None = None) -> bytes:
    """
    将 Luckysheet 序列化 JSON 重建为 .xlsx 字节流。
    按 celldata 数组写入每个工作表的单元格数据。
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
        import base64, io as _io
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

    # Detect format
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
                        _replace_text_frame(shape.text_frame, shape_entry.get("text", ""))
                elif stype == "TABLE":
                    if shape.has_table:
                        tbl = shape.table
                        for cell_data in shape_entry.get("cells", []):
                            r, c = cell_data.get("row", 0), cell_data.get("col", 0)
                            try:
                                cell = tbl.cell(r, c)
                                if cell.text_frame:
                                    _replace_text_frame(cell.text_frame, cell_data.get("text", ""))
                            except Exception:
                                pass
    else:
        # ── Legacy text-card format ──
        for slide_data in (slides_json or []):
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
