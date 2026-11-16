# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Koto Document Generation Service (Facade)
=========================================
Unified entry point for Word/PDF/Excel/PowerPoint generation.

Modules have been split into focused files:
  - doc_gen_types.py  : Data classes (ContentType, DocSection, ExcelSheet, DocGenRequest)
  - doc_gen_word.py   : _WordGenerator
  - doc_gen_pdf.py    : _PdfGenerator
  - doc_gen_excel.py  : _ExcelGenerator
  - doc_gen_pptx.py   : _PptxGenerator

This module remains as a backward-compatible facade.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.services.doc_gen_excel import _ExcelGenerator  # noqa: F401
from app.core.services.doc_gen_pdf import _PdfGenerator  # noqa: F401
from app.core.services.doc_gen_pptx import _PptxGenerator  # noqa: F401

# Re-export types
from app.core.services.doc_gen_types import (  # noqa: F401
    ContentType,
    DocGenRequest,
    DocSection,
    ExcelSheet,
)

# Re-export generators
from app.core.services.doc_gen_word import _WordGenerator  # noqa: F401

logger = logging.getLogger(__name__)

# ── 默认输出目录 ────────────────────────────────────────────────────────────
_DEFAULT_OUTPUT_DIR = os.environ.get(
    "KOTO_DOC_GEN_DIR",
    str(Path(__file__).parent.parent.parent.parent / "workspace" / "doc_gen_outputs"),
)


class DocGenService:
    """文档生成服务（薄门面）。

    委托给各格式的专用生成器。
    """

    def generate_word(self, req: DocGenRequest) -> str:
        return _generate(_WordGenerator(), req, "docx")

    def generate_pdf(self, req: DocGenRequest) -> str:
        return _generate(_PdfGenerator(), req, "pdf")

    def generate_excel(self, req: DocGenRequest) -> str:
        return _generate(_ExcelGenerator(), req, "xlsx")

    def generate_presentation(self, req: DocGenRequest) -> str:
        return _generate(_PptxGenerator(), req, "pptx")

    @staticmethod
    def build_request(data: Dict[str, Any]) -> DocGenRequest:
        """从字典构建 DocGenRequest。"""
        sections_data = data.get("sections", [])
        sections = []
        for s in sections_data:
            sections.append(
                DocSection(
                    content_type=ContentType(s.get("content_type", "text")),
                    content=s.get("content", ""),
                    level=s.get("level"),
                )
            )
        excel_sheets = None
        if data.get("excel_sheets"):
            excel_sheets = [
                ExcelSheet(
                    name=es.get("name", "Sheet1"),
                    title=es.get("title", ""),
                    headers=es.get("headers", []),
                    rows=es.get("rows", []),
                    column_widths=es.get("column_widths", {}),
                    freeze_header=bool(es.get("freeze_header", True)),
                    add_totals_row=bool(es.get("add_totals_row", False)),
                )
                for es in data["excel_sheets"]
            ]
        return DocGenRequest(
            title=data.get("title", "Untitled"),
            sections=sections,
            author=data.get("author", "Koto AI"),
            subject=data.get("subject", ""),
            keywords=data.get("keywords", ""),
            style_preset=data.get("style_preset", "professional"),
            pptx_layout=data.get("pptx_layout", "widescreen"),
            excel_sheets=excel_sheets,
            output_dir=data.get("output_dir"),
        )


def _generate(generator, req: DocGenRequest, ext: str) -> str:
    """通用生成流程。"""
    output_dir = req.output_dir or _DEFAULT_OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)
    import uuid

    filename = f"{req.title}_{uuid.uuid4().hex[:8]}.{ext}"
    output_path = Path(output_dir) / filename
    generator.generate(req, output_path)
    logger.info("[DocGen] 生成完成: %s", output_path)
    return str(output_path)
