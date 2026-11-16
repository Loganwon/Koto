# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Auto-generated split from doc_gen_service.py"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.services.doc_gen_shared import (
    build_output_path,
    ensure_output_dir,
    find_chinese_font,
    get_preset,
    hex_to_rgb,
)
from app.core.services.doc_gen_types import (
    ContentType,
    DocGenRequest,
    DocSection,
    ExcelSheet,
)

logger = logging.getLogger(__name__)


class _WordGenerator:
    """基于 python-docx 生成专业品质的 Word 文档。"""

    def generate(self, req: DocGenRequest, output_path: Path) -> None:
        try:
            from docx import Document
            from docx.enum.table import WD_TABLE_ALIGNMENT
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            from docx.oxml.ns import qn
            from docx.shared import Cm, Inches, Pt, RGBColor
        except ImportError as e:
            raise ImportError(f"python-docx 未安装: {e}")

        preset = get_preset(req.style_preset)
        doc = Document()

        # ── 页面设置 ──────────────────────────────────────────────────────
        for section in doc.sections:
            section.page_height = Cm(29.7)
            section.page_width = Cm(21.0)
            section.top_margin = Cm(2.5)
            section.bottom_margin = Cm(2.5)
            section.left_margin = Cm(3.0)
            section.right_margin = Cm(2.5)

        # ── 标题页 ────────────────────────────────────────────────────────
        title_para = doc.add_paragraph()
        title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        title_run = title_para.add_run(req.title)
        title_run.bold = True
        title_run.font.size = Pt(preset["title_font_size"])
        pr, pg, pb = preset["primary_rgb"]
        title_run.font.color.rgb = RGBColor(pr, pg, pb)
        title_run.font.name = "微软雅黑"
        title_run._r.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")

        # 副标题行（作者 + 日期）
        meta_para = doc.add_paragraph()
        meta_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        meta_text = f"{req.author}  |  {datetime.now().strftime('%Y年%m月%d日')}"
        if req.subject:
            meta_text = f"{req.subject}\n{meta_text}"
        meta_run = meta_para.add_run(meta_text)
        meta_run.font.size = Pt(11)
        sr, sg, sb = preset["secondary_rgb"]
        meta_run.font.color.rgb = RGBColor(sr, sg, sb)
        meta_run.font.name = "微软雅黑"
        meta_run._r.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")

        doc.add_paragraph("")  # 空行

        # ── 正文内容 ──────────────────────────────────────────────────────
        for s in req.sections:
            ct = (
                s.content_type.lower()
                if isinstance(s.content_type, str)
                else s.content_type.value
            )

            if ct == ContentType.HEADING:
                head_level = max(1, min(s.level, 3))
                h = doc.add_heading(str(s.content), level=head_level)
                h.alignment = WD_ALIGN_PARAGRAPH.LEFT
                # 应用样式色彩
                for run in h.runs:
                    run.font.color.rgb = RGBColor(pr, pg, pb)
                    run.font.name = "微软雅黑"
                    try:
                        run._r.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
                    except Exception:
                        import logging

                        logging.getLogger(__name__).warning(
                            "Silenced exception caught", exc_info=True
                        )

            elif ct == ContentType.TEXT:
                p = doc.add_paragraph(str(s.content))
                p.paragraph_format.space_after = Pt(6)
                for run in p.runs:
                    run.font.size = Pt(preset["body_font_size"])
                    run.font.name = "微软雅黑"
                    try:
                        run._r.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
                    except Exception:
                        import logging

                        logging.getLogger(__name__).warning(
                            "Silenced exception caught", exc_info=True
                        )

            elif ct == ContentType.TABLE:
                rows_data = s.content
                if not isinstance(rows_data, list) or len(rows_data) == 0:
                    continue
                table = doc.add_table(rows=len(rows_data), cols=len(rows_data[0]))
                table.style = "Table Grid"
                hbr, hbg, hbb = preset["header_bg_rgb"]
                sbr, sbg, sbb = preset["stripe_bg_rgb"]
                from docx.oxml import OxmlElement

                for row_idx, row_data in enumerate(rows_data):
                    row = table.rows[row_idx]
                    for col_idx, cell_val in enumerate(row_data):
                        cell = row.cells[col_idx]
                        cell.text = str(cell_val)
                        run = (
                            cell.paragraphs[0].runs[0]
                            if cell.paragraphs[0].runs
                            else cell.paragraphs[0].add_run(str(cell_val))
                        )
                        run.font.size = Pt(10)
                        run.font.name = "微软雅黑"
                        try:
                            run._r.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
                        except Exception:
                            import logging

                            logging.getLogger(__name__).warning(
                                "Silenced exception caught", exc_info=True
                            )
                        if row_idx == 0:
                            run.bold = True
                            # 表头背景色
                            tc = cell._tc
                            tcPr = tc.get_or_add_tcPr()
                            shd = OxmlElement("w:shd")
                            shd.set(qn("w:fill"), f"{hbr:02X}{hbg:02X}{hbb:02X}")
                            shd.set(qn("w:val"), "clear")
                            tcPr.append(shd)
                            hfr, hfg, hfb = preset["header_fg_rgb"]
                            run.font.color.rgb = RGBColor(hfr, hfg, hfb)
                        elif row_idx % 2 == 0:
                            # 斑马条纹
                            tc = cell._tc
                            tcPr = tc.get_or_add_tcPr()
                            shd = OxmlElement("w:shd")
                            shd.set(qn("w:fill"), f"{sbr:02X}{sbg:02X}{sbb:02X}")
                            shd.set(qn("w:val"), "clear")
                            tcPr.append(shd)
                if s.caption:
                    cap = doc.add_paragraph(s.caption)
                    cap.style = "Caption"
                    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER

            elif ct in (ContentType.BULLET_LIST, ContentType.NUMBERED_LIST):
                items = s.content if isinstance(s.content, list) else [str(s.content)]
                style = (
                    "List Bullet" if ct == ContentType.BULLET_LIST else "List Number"
                )
                for item in items:
                    p = doc.add_paragraph(str(item), style=style)
                    for run in p.runs:
                        run.font.size = Pt(preset["body_font_size"])
                        run.font.name = "微软雅黑"
                        try:
                            run._r.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
                        except Exception:
                            import logging

                            logging.getLogger(__name__).warning(
                                "Silenced exception caught", exc_info=True
                            )

            elif ct == ContentType.CODE:
                p = doc.add_paragraph()
                run = p.add_run(str(s.content))
                run.font.name = "Courier New"
                run.font.size = Pt(9)
                p.paragraph_format.left_indent = Inches(0.5)
                p.paragraph_format.space_before = Pt(6)
                p.paragraph_format.space_after = Pt(6)

            elif ct == ContentType.QUOTE:
                p = doc.add_paragraph(str(s.content))
                p.paragraph_format.left_indent = Inches(0.5)
                p.paragraph_format.right_indent = Inches(0.5)
                for run in p.runs:
                    ar, ag, ab = preset["accent_rgb"]
                    run.font.color.rgb = RGBColor(ar, ag, ab)
                    run.font.italic = True
                    run.font.size = Pt(preset["body_font_size"])

            elif ct == ContentType.IMAGE:
                try:
                    img_path = str(s.content)
                    if os.path.exists(img_path):
                        doc.add_picture(img_path, width=Inches(5.5))
                        last_para = doc.paragraphs[-1]
                        last_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    if s.caption:
                        cap = doc.add_paragraph(s.caption)
                        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
                except Exception as img_err:
                    doc.add_paragraph(f"[图片加载失败: {img_err}]")

            elif ct == ContentType.PAGE_BREAK:
                doc.add_page_break()

            elif ct == ContentType.HORIZONTAL_RULE:
                doc.add_paragraph("─" * 40)

        # ── 文档属性 ──────────────────────────────────────────────────────
        core_props = doc.core_properties
        core_props.title = req.title
        core_props.author = req.author
        core_props.subject = req.subject
        core_props.keywords = req.keywords
        core_props.created = datetime.now()

        doc.save(str(output_path))
        logger.info(f"[DocGen] Word 生成完成: {output_path}")


# ══════════════════════════════════════════════════════════════════════════════
# PDF 生成器（基于 reportlab）
# ══════════════════════════════════════════════════════════════════════════════
