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


class _PptxGenerator:
    """基于 python-pptx 生成专业品质的 PowerPoint 演示文稿。"""

    def generate(self, req: DocGenRequest, output_path: Path) -> None:
        try:
            from pptx import Presentation
            from pptx.dml.color import RGBColor
            from pptx.enum.text import PP_ALIGN
            from pptx.util import Emu, Inches, Pt
        except ImportError as e:
            raise ImportError(f"python-pptx 未安装: {e}")

        preset = get_preset(req.style_preset)
        prs = Presentation()

        # 幻灯片尺寸
        if req.pptx_layout == "widescreen":
            prs.slide_width = Inches(13.33)
            prs.slide_height = Inches(7.5)
        else:
            prs.slide_width = Inches(10)
            prs.slide_height = Inches(7.5)

        slide_layouts = prs.slide_layouts
        # 0 = Title Slide, 1 = Title & Content, 5 = Title Only, 6 = Blank
        BLANK_LAYOUT = 6
        TITLE_LAYOUT = 0
        CONTENT_LAYOUT = 1

        pr, pg, pb = preset["primary_rgb"]
        sr, sg, sb = preset["secondary_rgb"]
        ar, ag, ab = preset["accent_rgb"]
        hbr, hbg, hbb = preset["header_bg_rgb"]
        hfr, hfg, hfb = preset["header_fg_rgb"]

        def _rgb(t):
            from pptx.dml.color import RGBColor

            return RGBColor(t[0], t[1], t[2])

        def _set_font(
            run_or_para, font_name="微软雅黑", size_pt=None, bold=False, color=None
        ):
            try:
                tf = run_or_para.font
                tf.name = font_name
                if size_pt:
                    tf.size = Pt(size_pt)
                tf.bold = bold
                if color:
                    tf.color.rgb = _rgb(color)
            except Exception:
                import logging

                logging.getLogger(__name__).warning(
                    "Silenced exception caught", exc_info=True
                )

        # ── 封面幻灯片 ─────────────────────────────────────────────────────
        title_slide = prs.slides.add_slide(slide_layouts[TITLE_LAYOUT])
        title_ph = title_slide.shapes.title
        subtitle_ph = (
            title_slide.placeholders[1] if len(title_slide.placeholders) > 1 else None
        )

        title_ph.text = req.title
        for para in title_ph.text_frame.paragraphs:
            for run in para.runs:
                _set_font(
                    run,
                    size_pt=preset["title_font_size"],
                    bold=True,
                    color=(pr, pg, pb),
                )

        if subtitle_ph:
            sub_parts = [req.author, datetime.now().strftime("%Y年%m月%d日")]
            if req.subject:
                sub_parts.insert(0, req.subject)
            subtitle_ph.text = "  |  ".join(sub_parts)
            for para in subtitle_ph.text_frame.paragraphs:
                for run in para.runs:
                    _set_font(run, size_pt=14, color=(sr, sg, sb))

        # ── 正文幻灯片 ─────────────────────────────────────────────────────
        # 将 sections 分组：H1 创建新幻灯片，其余内容追加到当前幻灯片
        current_slide = None
        current_tf = None

        def _new_content_slide(heading_text: str):
            nonlocal current_slide, current_tf
            slide = prs.slides.add_slide(slide_layouts[CONTENT_LAYOUT])
            title_sp = slide.shapes.title
            if title_sp:
                title_sp.text = heading_text
                for para in title_sp.text_frame.paragraphs:
                    for run in para.runs:
                        _set_font(
                            run,
                            size_pt=preset["h1_font_size"],
                            bold=True,
                            color=(pr, pg, pb),
                        )
            # Content placeholder
            content_sp = None
            for ph in slide.placeholders:
                if ph.placeholder_format.idx == 1:
                    content_sp = ph
                    break
            if content_sp:
                current_tf = content_sp.text_frame
                current_tf.clear()
            else:
                current_tf = None
            current_slide = slide
            return slide

        def _add_text_to_tf(
            text: str, bold=False, size_pt=None, color=None, bullet=False
        ):
            if current_tf is None:
                return
            para = current_tf.add_paragraph()
            run = para.add_run()
            run.text = text
            _set_font(
                run, size_pt=size_pt or preset["body_font_size"], bold=bold, color=color
            )
            if bullet:
                para.level = 1

        for s in req.sections:
            ct = (
                s.content_type.lower()
                if isinstance(s.content_type, str)
                else s.content_type.value
            )

            if ct == ContentType.HEADING and s.level == 1:
                _new_content_slide(str(s.content))

            elif ct == ContentType.HEADING and s.level >= 2:
                _add_text_to_tf(
                    str(s.content),
                    bold=True,
                    size_pt=preset["h2_font_size"],
                    color=(sr, sg, sb),
                )

            elif ct == ContentType.TEXT:
                if current_slide is None:
                    _new_content_slide(req.title)
                _add_text_to_tf(str(s.content), size_pt=preset["body_font_size"])

            elif ct in (ContentType.BULLET_LIST, ContentType.NUMBERED_LIST):
                if current_slide is None:
                    _new_content_slide("内容")
                items = s.content if isinstance(s.content, list) else [str(s.content)]
                for item in items:
                    _add_text_to_tf(
                        f"• {item}" if ct == ContentType.BULLET_LIST else item,
                        size_pt=preset["body_font_size"],
                    )

            elif ct == ContentType.TABLE:
                # PPT 中的表格：新建一张独立幻灯片
                rows_data = s.content
                if not isinstance(rows_data, list) or len(rows_data) == 0:
                    continue
                table_slide = prs.slides.add_slide(slide_layouts[5])  # Title Only
                if table_slide.shapes.title and s.caption:
                    table_slide.shapes.title.text = s.caption or "数据表格"

                row_count = len(rows_data)
                col_count = max(len(r) for r in rows_data)
                left = Inches(0.5)
                top = Inches(1.5)
                width = prs.slide_width - Inches(1.0)
                height = min(
                    Inches(0.35 * row_count + 0.3), prs.slide_height - Inches(2.0)
                )

                tbl_shape = table_slide.shapes.add_table(
                    row_count, col_count, left, top, width, height
                )
                tbl = tbl_shape.table
                for row_idx, row_data in enumerate(rows_data):
                    for col_idx, cell_val in enumerate(row_data):
                        cell = tbl.cell(row_idx, col_idx)
                        cell.text = str(cell_val)
                        for para in cell.text_frame.paragraphs:
                            for run in para.runs:
                                is_header = row_idx == 0
                                _set_font(
                                    run,
                                    size_pt=9,
                                    bold=is_header,
                                    color=(hfr, hfg, hfb) if is_header else None,
                                )
                                if is_header:
                                    from pptx.dml.color import RGBColor as PPTXRGB

                                    cell.fill.solid()
                                    cell.fill.fore_color.rgb = PPTXRGB(hbr, hbg, hbb)

            elif ct == ContentType.PAGE_BREAK:
                current_slide = None  # 强制下一次内容到新幻灯片

        prs.save(str(output_path))
        logger.info(f"[DocGen] PPT 生成完成: {output_path}")


# ══════════════════════════════════════════════════════════════════════════════
# 对外 API（单例服务）
# ══════════════════════════════════════════════════════════════════════════════
