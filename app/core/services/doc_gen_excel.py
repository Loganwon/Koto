# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Auto-generated split from doc_gen_service.py"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

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


class _ExcelGenerator:
    """基于 openpyxl 生成专业品质的 Excel 报表。"""

    def _apply_header_style(
        self, ws, row_idx: int, col_count: int, preset: Dict, bg_rgb, fg_rgb
    ) -> None:
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

        thick_border = Border(
            bottom=Side(style="medium"),
            top=Side(style="medium"),
        )
        bg_hex = f"{bg_rgb[0]:02X}{bg_rgb[1]:02X}{bg_rgb[2]:02X}"
        fg_hex = f"{fg_rgb[0]:02X}{fg_rgb[1]:02X}{fg_rgb[2]:02X}"

        for col in range(1, col_count + 1):
            cell = ws.cell(row=row_idx, column=col)
            cell.fill = PatternFill(
                start_color=bg_hex, end_color=bg_hex, fill_type="solid"
            )
            cell.font = Font(name="微软雅黑", bold=True, color=fg_hex, size=10)
            cell.alignment = Alignment(
                horizontal="center", vertical="center", wrap_text=True
            )
            cell.border = thick_border

    def generate(self, req: DocGenRequest, output_path: Path) -> None:
        try:
            import openpyxl
            from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
            from openpyxl.utils import get_column_letter
        except ImportError as e:
            raise ImportError(f"openpyxl 未安装: {e}")

        preset = get_preset(req.style_preset)
        wb = openpyxl.Workbook()
        pr, pg, pb = preset["primary_rgb"]
        sr, sg, sb = preset["secondary_rgb"]
        hbr, hbg, hbb = preset["header_bg_rgb"]
        hfr, hfg, hfb = preset["header_fg_rgb"]
        stripe_r, stripe_g, stripe_b = preset["stripe_bg_rgb"]

        primary_hex = f"{pr:02X}{pg:02X}{pb:02X}"
        stripe_hex = f"{stripe_r:02X}{stripe_g:02X}{stripe_b:02X}"

        # ── 确定 Sheet 数据 ───────────────────────────────────────────────
        sheets_to_gen: List[ExcelSheet] = req.excel_sheets if req.excel_sheets else []

        # 如果没有提供 excel_sheets，从 sections 提取表格数据建立默认 Sheet
        if not sheets_to_gen:
            default_rows: List[List[Any]] = []
            default_headers: List[str] = []
            for s in req.sections:
                ct = (
                    s.content_type.lower()
                    if isinstance(s.content_type, str)
                    else s.content_type.value
                )
                if (
                    ct == ContentType.TABLE
                    and isinstance(s.content, list)
                    and len(s.content) > 0
                ):
                    if not default_headers:
                        default_headers = [str(c) for c in s.content[0]]
                        default_rows = [list(row) for row in s.content[1:]]
            if default_headers:
                sheets_to_gen = [
                    ExcelSheet(
                        name="数据",
                        title=req.title,
                        column_headers=default_headers,
                        rows=default_rows,
                    )
                ]
            else:
                # 如果完全没有表格数据，生成一个说明 Sheet
                sheets_to_gen = [
                    ExcelSheet(
                        name="说明",
                        title=req.title,
                        column_headers=["内容"],
                        rows=[
                            [s.content]
                            for s in req.sections
                            if isinstance(s.content, str)
                        ],
                    )
                ]

        # 删除默认空 Sheet
        if "Sheet" in wb.sheetnames:
            del wb["Sheet"]

        for sheet_def in sheets_to_gen:
            ws = wb.create_sheet(title=sheet_def.name[:31])  # Excel 限 31 字符

            row_cursor = 1

            # Sheet 大标题
            if sheet_def.title:
                ws.cell(row=row_cursor, column=1, value=sheet_def.title)
                ws.cell(row=row_cursor, column=1).font = Font(
                    name="微软雅黑",
                    bold=True,
                    size=14,
                    color=primary_hex,
                )
                ws.merge_cells(
                    start_row=row_cursor,
                    start_column=1,
                    end_row=row_cursor,
                    end_column=max(len(sheet_def.column_headers), 1),
                )
                ws.cell(row=row_cursor, column=1).alignment = Alignment(
                    horizontal="center"
                )
                row_cursor += 1
                # 生成日期行
                ws.cell(
                    row=row_cursor,
                    column=1,
                    value=f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
                )
                ws.cell(row=row_cursor, column=1).font = Font(
                    name="微软雅黑", size=9, color="888888"
                )
                row_cursor += 1

            # 表头
            headers = sheet_def.column_headers
            if headers:
                for col_idx, header in enumerate(headers, start=1):
                    ws.cell(row=row_cursor, column=col_idx, value=header)
                self._apply_header_style(
                    ws,
                    row_cursor,
                    len(headers),
                    preset,
                    (hbr, hbg, hbb),
                    (hfr, hfg, hfb),
                )
                row_cursor += 1

            # 数据行
            thin_border = Border(
                left=Side(style="thin", color="DDDDDD"),
                right=Side(style="thin", color="DDDDDD"),
                top=Side(style="thin", color="DDDDDD"),
                bottom=Side(style="thin", color="DDDDDD"),
            )
            totals: Dict[int, Any] = {}  # col_idx → running sum
            for data_row in sheet_def.rows:
                for col_idx, cell_val in enumerate(data_row, start=1):
                    c = ws.cell(row=row_cursor, column=col_idx, value=cell_val)
                    c.font = Font(name="微软雅黑", size=10)
                    c.border = thin_border
                    c.alignment = Alignment(vertical="center", wrap_text=True)
                    # 斑马条纹
                    if row_cursor % 2 == 0:
                        c.fill = PatternFill(
                            start_color=stripe_hex,
                            end_color=stripe_hex,
                            fill_type="solid",
                        )
                    # 尝试累加数值列
                    if sheet_def.add_totals_row:
                        try:
                            totals[col_idx] = totals.get(col_idx, 0) + float(
                                str(cell_val)
                                .replace(",", "")
                                .replace("¥", "")
                                .replace("%", "")
                            )
                        except ValueError:
                            totals.setdefault(col_idx, "─")
                row_cursor += 1

            # 合计行
            if sheet_def.add_totals_row and totals:
                ws.cell(row=row_cursor, column=1, value="合 计")
                ws.cell(row=row_cursor, column=1).font = Font(
                    name="微软雅黑", bold=True, size=10
                )
                for col_idx, val in totals.items():
                    if col_idx == 1:
                        continue
                    c = ws.cell(
                        row=row_cursor,
                        column=col_idx,
                        value=val if isinstance(val, str) else round(val, 2),
                    )
                    c.font = Font(
                        name="微软雅黑", bold=True, size=10, color=primary_hex
                    )
                    c.fill = PatternFill(
                        start_color=stripe_hex, end_color=stripe_hex, fill_type="solid"
                    )
                row_cursor += 1

            # ── 列宽自适应 ────────────────────────────────────────────────
            for col_idx in range(1, (len(headers) or 1) + 1):
                col_letter = get_column_letter(col_idx)
                if sheet_def.column_widths and col_idx - 1 < len(
                    sheet_def.column_widths
                ):
                    ws.column_dimensions[col_letter].width = sheet_def.column_widths[
                        col_idx - 1
                    ]
                else:
                    max_len = 0
                    for row_cells in ws.iter_rows(min_col=col_idx, max_col=col_idx):
                        for c in row_cells:
                            if c.value:
                                # 中文字符计2个单位
                                val_str = str(c.value)
                                char_width = sum(
                                    2 if ord(ch) > 127 else 1 for ch in val_str
                                )
                                max_len = max(max_len, char_width)
                    ws.column_dimensions[col_letter].width = min(max_len + 4, 50)

            # 冻结表头
            if sheet_def.freeze_header and headers:
                freeze_row = (3 if sheet_def.title else 1) + 1
                ws.freeze_panes = f"A{freeze_row}"

            # 行高
            ws.row_dimensions[1].height = 30 if sheet_def.title else 20

        # ── 元数据 ────────────────────────────────────────────────────────
        wb.properties.title = req.title
        wb.properties.creator = req.author
        wb.properties.subject = req.subject
        wb.save(str(output_path))
        logger.info(f"[DocGen] Excel 生成完成: {output_path}")


# ══════════════════════════════════════════════════════════════════════════════
# PowerPoint 生成器
# ══════════════════════════════════════════════════════════════════════════════
