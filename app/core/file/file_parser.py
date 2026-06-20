# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Koto 全格式文件解析模块 — Phase 1 BFF 管线核心
支持格式: DOCX / XLSX / PPTX / PDF
每个解析函数接收文件路径或字节流,输出标准化 JSON 供前端多态渲染器消费。
"""

from __future__ import annotations

import base64
import html
import io
import logging
import math
import mimetypes
import os
import re
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# DOCX → Semantic HTML
# ─────────────────────────────────────────────────────────────────────────────

# ── Shared image compression settings ────────────────────────────────────────
_MAX_IMG_DIMENSION = 1200  # px — max width or height
_MAX_IMG_BYTES = 300 * 1024   # 300 KB threshold for triggering compression
_MAX_BLOB_BYTES = 15 * 1024 * 1024  # 15 MB hard limit — blobs larger than this are skipped entirely
_MAX_PPTX_BYTES = 100 * 1024 * 1024  # 100 MB PPTX size cap (likely contains embedded video)
_DOCX_PREVIEW_TARGET_PAGES = 3
_DOCX_PREVIEW_UNITS_PER_PAGE = 34
_DOCX_PREVIEW_MAX_TABLE_ROWS = 18


def _compress_image_bytes(
    img_bytes: bytes, content_type: str = "image/png"
) -> tuple[bytes, str]:
    """
    Compress image bytes if they exceed _MAX_IMG_BYTES.

    Returns ``(possibly_compressed_bytes, mime_type)`` — unchanged if Pillow is
    not installed or the image is already small enough.
    """
    from app.core.file.image_utils import compress_image_bytes

    return compress_image_bytes(img_bytes, content_type)


def _extract_docx_comments(file_path: str) -> list[dict[str, Any]]:
    from app.core.file.parsers.docx_parser import _extract_docx_comments as _impl

    return _impl(file_path)


def _extract_docx_revisions(file_path: str) -> list[dict[str, Any]]:
    from app.core.file.parsers.docx_parser import _extract_docx_revisions as _impl

    return _impl(file_path)


def _extract_docx_footnotes(file_path: str) -> list[dict[str, Any]]:
    from app.core.file.parsers.docx_parser import _extract_docx_footnotes as _impl

    return _impl(file_path)


def count_docx_visible_chars(file_path: str) -> int:
    from app.core.file.parsers.docx_parser import count_docx_visible_chars as _impl

    return _impl(file_path)


def parse_docx(file_path: str, *, progressive_preview: bool = False) -> dict[str, Any]:
    from app.core.file.parsers.docx_parser import parse_docx as _impl

    return _impl(file_path, progressive_preview=progressive_preview)


def _openpyxl_cell_to_univer(cell: Any) -> dict[str, Any] | None:
    """将单个 openpyxl Cell 转换为 Univer ICellData 对象。"""
    from app.core.file.parsers.xlsx_parser import openpyxl_cell_to_univer

    return openpyxl_cell_to_univer(cell)


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
    from app.core.file.parsers.xlsx_parser import parse_xlsx as _parse_xlsx

    return _parse_xlsx(file_path, original_name=original_name)


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
    from app.core.file.parsers.pptx_parser import parse_pptx as _parse_pptx

    return _parse_pptx(file_path)


# ─────────────────────────────────────────────────────────────────────────────
# PPTX → 几何画布 JSON (含图片/表格/备注)
# ─────────────────────────────────────────────────────────────────────────────


def parse_pptx_geometry(file_path: Any) -> dict[str, Any]:
    """Compatibility wrapper for the PPTX geometry parser."""
    from app.core.file.parsers.pptx_geometry_parser import parse_pptx_geometry as _parse_pptx_geometry

    return _parse_pptx_geometry(file_path)
def parse_pdf(file_path: str, file_id: str) -> dict[str, Any]:
    """
    提取 PDF 全量文本，供 AI RAG 使用。
    同时返回原始文件的 raw URL，供前端 PDF.js 渲染。

    文字提取回退链：pdfplumber → pypdf → PyPDF2。
    若提取文本过少（扫描件），自动对空页运行 OCR（PyMuPDF + Tesseract）。
    若三个库均不可用，仍返回含 raw_url 的结果（PDF.js 视觉渲染不依赖文字提取）。

    Returns:
        {"text": str, "page_count": int, "raw_url": str,
         "pages": [{"page": int, "text": str}], "ocr_applied": bool,
         "outline": list, "metadata": dict}
    """
    from app.core.file.parsers.pdf_parser import parse_pdf as _parse_pdf

    return _parse_pdf(file_path, file_id)


# ─────────────────────────────────────────────────────────────────────────────
# DOCX 导出: 修改后 HTML → .docx
# ─────────────────────────────────────────────────────────────────────────────


def export_docx(docx_input: Any, original_path: str | None = None) -> bytes:
    """Compatibility wrapper for DOCX export."""
    from app.core.file.exporters.docx_exporter import export_docx as _export_docx

    return _export_docx(docx_input, original_path=original_path)




# ─────────────────────────────────────────────────────────────────────────────
# XLSX 导出: Univer JSON → .xlsx
# ─────────────────────────────────────────────────────────────────────────────


def export_xlsx(
    sheets_json: Any, images: list[dict] | None = None
) -> bytes:
    """
    将编辑器序列化数据重建为 .xlsx 字节流。

    支持输入格式:
    - Univer IWorkbookData (dict): {sheetOrder:[...], sheets:{id:{name, cellData:{row:{col:{v,...}}}}}}

    副加 images (前端 overlay) 嵌入到第一个 sheet。

    Returns:
        bytes — .xlsx 文件内容
    """
    from app.core.file.exporters.xlsx_exporter import export_xlsx as _export_xlsx

    return _export_xlsx(sheets_json, images)
