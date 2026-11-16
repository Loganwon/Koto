# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Auto-generated split from doc_gen_service.py"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Tuple

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


class _PdfGenerator:
    """基于 reportlab 生成专业品质的 PDF 文档，支持中文字体自动检测。"""

    def _register_fonts(self) -> Tuple[str, str]:
        """
        注册系统中文字体并返回 (正文字体名, 粗体字体名)。
        若找不到中文字体则回退到 Helvetica。
        """
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        zh_path = find_chinese_font()
        if zh_path:
            try:
                # .ttc 文件需指定子字体索引
                if zh_path.lower().endswith(".ttc"):
                    from reportlab.pdfbase.ttfonts import TTFont as _TTF

                    pdfmetrics.registerFont(_TTF("KotoCNBody", zh_path, subfontIndex=0))
                    pdfmetrics.registerFont(_TTF("KotoCNBold", zh_path, subfontIndex=0))
                else:
                    pdfmetrics.registerFont(TTFont("KotoCNBody", zh_path))
                    pdfmetrics.registerFont(TTFont("KotoCNBold", zh_path))
                return "KotoCNBody", "KotoCNBold"
            except Exception as fe:
                logger.warning(f"[DocGen] 中文字体注册失败 ({zh_path}): {fe}")
        logger.warning(
            "[DocGen] 未找到中文字体，PDF 正文可能显示为方框（推荐安装微软雅黑）"
        )
        return "Helvetica", "Helvetica-Bold"

    def generate(self, req: DocGenRequest, output_path: Path) -> None:
        try:
            from reportlab.lib import colors
            from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import cm
            from reportlab.platypus import (
                HRFlowable,
                ListFlowable,
                ListItem,
                PageBreak,
                Paragraph,
                Preformatted,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )
        except ImportError as e:
            raise ImportError(
                f"reportlab 未安装: {e}\n" "请运行: pip install reportlab>=4.0.0"
            )

        preset = get_preset(req.style_preset)
        body_font, bold_font = self._register_fonts()

        pr, pg, pb = preset["primary_rgb"]
        sr, sg, sb = preset["secondary_rgb"]
        ar, ag, ab = preset["accent_rgb"]
        hbr, hbg, hbb = preset["header_bg_rgb"]
        hfr, hfg, hfb = preset["header_fg_rgb"]
        stripe_r, stripe_g, stripe_b = preset["stripe_bg_rgb"]

        primary_color = colors.Color(pr / 255, pg / 255, pb / 255)
        secondary_color = colors.Color(sr / 255, sg / 255, sb / 255)
        accent_color = colors.Color(ar / 255, ag / 255, ab / 255)
        header_bg_color = colors.Color(hbr / 255, hbg / 255, hbb / 255)
        header_fg_color = colors.Color(hfr / 255, hfg / 255, hfb / 255)
        stripe_color = colors.Color(stripe_r / 255, stripe_g / 255, stripe_b / 255)

        styles = getSampleStyleSheet()
        base_font_size = preset["body_font_size"]

        # 自定义样式
        style_title = ParagraphStyle(
            "KotoTitle",
            fontName=bold_font,
            fontSize=preset["title_font_size"],
            textColor=primary_color,
            spaceAfter=12,
            alignment=TA_CENTER,
        )
        style_meta = ParagraphStyle(
            "KotoMeta",
            fontName=body_font,
            fontSize=10,
            textColor=secondary_color,
            spaceAfter=20,
            alignment=TA_CENTER,
        )
        style_h1 = ParagraphStyle(
            "KotoH1",
            fontName=bold_font,
            fontSize=preset["h1_font_size"],
            textColor=primary_color,
            spaceBefore=14,
            spaceAfter=6,
            borderPad=(0, 0, 3, 0),
        )
        style_h2 = ParagraphStyle(
            "KotoH2",
            fontName=bold_font,
            fontSize=preset["h2_font_size"],
            textColor=secondary_color,
            spaceBefore=10,
            spaceAfter=4,
        )
        style_h3 = ParagraphStyle(
            "KotoH3",
            fontName=bold_font,
            fontSize=preset["h3_font_size"],
            textColor=accent_color,
            spaceBefore=6,
            spaceAfter=4,
        )
        style_body = ParagraphStyle(
            "KotoBody",
            fontName=body_font,
            fontSize=base_font_size,
            leading=base_font_size * preset["line_spacing"],
            spaceAfter=6,
            alignment=TA_JUSTIFY,
        )
        style_quote = ParagraphStyle(
            "KotoQuote",
            fontName=body_font,
            fontSize=base_font_size,
            textColor=accent_color,
            leftIndent=30,
            rightIndent=30,
            spaceAfter=8,
            fontStyle="italic" if body_font == "Helvetica" else "normal",
        )
        style_code = ParagraphStyle(
            "KotoCode",
            fontName="Courier",
            fontSize=9,
            leftIndent=20,
            backColor=colors.Color(0.95, 0.95, 0.95),
            spaceAfter=8,
        )
        style_caption = ParagraphStyle(
            "KotoCaption",
            fontName=body_font,
            fontSize=9,
            textColor=secondary_color,
            alignment=TA_CENTER,
            spaceAfter=8,
        )

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            leftMargin=3.0 * cm,
            rightMargin=2.5 * cm,
            topMargin=2.5 * cm,
            bottomMargin=2.5 * cm,
            title=req.title,
            author=req.author,
            subject=req.subject,
        )

        story = []

        # ── 标题区 ────────────────────────────────────────────────────────
        story.append(Paragraph(req.title, style_title))
        meta_parts = [req.author, datetime.now().strftime("%Y年%m月%d日")]
        if req.subject:
            meta_parts.insert(0, req.subject)
        story.append(Paragraph("  |  ".join(meta_parts), style_meta))
        story.append(HRFlowable(width="100%", thickness=1.5, color=primary_color))
        story.append(Spacer(1, 12))

        # ── 正文 ──────────────────────────────────────────────────────────
        for s in req.sections:
            ct = (
                s.content_type.lower()
                if isinstance(s.content_type, str)
                else s.content_type.value
            )

            if ct == ContentType.HEADING:
                style_map = {1: style_h1, 2: style_h2, 3: style_h3}
                h_style = style_map.get(s.level, style_h1)
                # Add underline for H1
                if s.level == 1:
                    story.append(Paragraph(str(s.content), h_style))
                    story.append(
                        HRFlowable(
                            width="100%",
                            thickness=0.5,
                            color=primary_color,
                            spaceAfter=4,
                        )
                    )
                else:
                    story.append(Paragraph(str(s.content), h_style))

            elif ct == ContentType.TEXT:
                story.append(Paragraph(str(s.content), style_body))

            elif ct == ContentType.TABLE:
                rows_data = s.content
                if not isinstance(rows_data, list) or len(rows_data) == 0:
                    continue
                table_data = []
                for row in rows_data:
                    table_data.append([str(c) for c in row])

                col_count = max(len(row) for row in table_data)
                available_width = doc.width
                col_width = available_width / col_count

                tbl = Table(table_data, colWidths=[col_width] * col_count, repeatRows=1)
                tbl_style = TableStyle(
                    [
                        # 表头
                        ("BACKGROUND", (0, 0), (-1, 0), header_bg_color),
                        ("TEXTCOLOR", (0, 0), (-1, 0), header_fg_color),
                        ("FONTNAME", (0, 0), (-1, 0), bold_font),
                        ("FONTSIZE", (0, 0), (-1, 0), 10),
                        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        # 边框
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.Color(0.7, 0.7, 0.7)),
                        ("BOX", (0, 0), (-1, -1), 1.0, primary_color),
                        # 正文
                        ("FONTNAME", (0, 1), (-1, -1), body_font),
                        ("FONTSIZE", (0, 1), (-1, -1), 9),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [colors.white, stripe_color],
                        ),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ]
                )
                tbl.setStyle(tbl_style)
                story.append(tbl)
                if s.caption:
                    story.append(Paragraph(s.caption, style_caption))

            elif ct == ContentType.BULLET_LIST:
                items = s.content if isinstance(s.content, list) else [str(s.content)]
                story.append(
                    ListFlowable(
                        [
                            ListItem(
                                Paragraph(str(item), style_body),
                                bulletColor=primary_color,
                            )
                            for item in items
                        ],
                        bulletType="bullet",
                    )
                )

            elif ct == ContentType.NUMBERED_LIST:
                items = s.content if isinstance(s.content, list) else [str(s.content)]
                story.append(
                    ListFlowable(
                        [ListItem(Paragraph(str(item), style_body)) for item in items],
                        bulletType="1",
                    )
                )

            elif ct == ContentType.CODE:
                story.append(Preformatted(str(s.content), style_code))

            elif ct == ContentType.QUOTE:
                story.append(Paragraph(f'"{s.content}"', style_quote))

            elif ct == ContentType.IMAGE:
                try:
                    from reportlab.platypus import Image as RLImage

                    img_path = str(s.content)
                    if os.path.exists(img_path):
                        img = RLImage(img_path, width=14 * cm)
                        story.append(img)
                    if s.caption:
                        story.append(Paragraph(s.caption, style_caption))
                except Exception as img_err:
                    story.append(Paragraph(f"[图片加载失败: {img_err}]", style_body))

            elif ct == ContentType.PAGE_BREAK:
                story.append(PageBreak())

            elif ct == ContentType.HORIZONTAL_RULE:
                story.append(
                    HRFlowable(width="100%", thickness=0.5, color=accent_color)
                )
                story.append(Spacer(1, 6))

        doc.build(story)
        logger.info(f"[DocGen] PDF 生成完成: {output_path}")


# ══════════════════════════════════════════════════════════════════════════════
# Excel 生成器
# ══════════════════════════════════════════════════════════════════════════════
