#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
"""DOCX composite tools: insert paragraphs, Excel tables, and images."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.agent.toolkits.foundation.docx_style import (
    apply_docx_style as _apply_docx_style,
)
from app.core.agent.toolkits.foundation.docx_table_helpers import (
    _compact_financial_table_rows,
    _match_header_index,
    _normalize_table_columns,
    _style_compact_financial_docx_table,
    _table_sort_value,
)
from app.core.agent.toolkits.foundation.xlsx_sheet_selection import (
    select_workbook_sheet as _select_workbook_sheet,
)

from ._internal_backup import (
    _best_effort_backup,
    _ensure_existing_file_writable,
    _nonwritable_target_message,
    _nonwritable_target_next_step,
)
from ._internal_formats import _next_available_docx_copy_path
from ._internal_fs import _resolve_path, _result_path, _safe_resolve
from ._internal_normalize import _normalize_positive_float, _normalize_positive_int
from ._internal_results import _blocked_write_result, _file_task_diff, _success_result
from ._internal_tempfile import _save_docx_via_temp_file
from ._internal_warnings import _merge_warnings


def insert_excel_as_docx_table(
    source_path: str,
    target_path: str,
    sheet_name: str = "",
    table_title: str = "",
    max_rows: int = 200,
    sort_by: str = "",
    sort_order: str = "desc",
    columns: Any = "",
    financial_compact: bool = False,
) -> str:
    """Insert spreadsheet data into a DOCX file as a real Word table."""
    max_rows = _normalize_positive_int(max_rows, default=200, upper=5_000)
    sort_by_text = str(sort_by or "").strip()
    sort_descending = str(sort_order or "desc").strip().lower() not in {
        "asc",
        "ascending",
        "smallest",
        "lowest",
        "正序",
        "升序",
    }
    selected_columns = _normalize_table_columns(columns)
    source_resolved = _resolve_path(source_path)
    if not source_resolved:
        return json.dumps(
            {"error": f"File not found: {source_path}"}, ensure_ascii=False
        )

    target_resolved = _resolve_path(target_path)
    if not target_resolved:
        if os.path.isabs(target_path):
            target_resolved = os.path.normpath(target_path)
        else:
            target_resolved = _safe_resolve(target_path)
    if not target_resolved:
        return json.dumps({"error": f"Invalid path: {target_path}"}, ensure_ascii=False)

    try:
        from io import BytesIO

        import openpyxl
        from docx import Document

        workbook = openpyxl.load_workbook(
            source_resolved, read_only=True, data_only=True
        )
        target_sheet, requested_sheet, sheet_warning = _select_workbook_sheet(
            workbook, sheet_name
        )
        if not target_sheet:
            workbook.close()
            return json.dumps(
                {"error": sheet_warning},
                ensure_ascii=False,
            )

        worksheet = workbook[target_sheet]
        raw_rows: List[List[str]] = []
        read_row_limit = 5_000 if (sort_by_text or financial_compact) else max_rows + 1
        for row in worksheet.iter_rows(values_only=True):
            if len(raw_rows) >= read_row_limit + 1:
                break
            values = ["" if value is None else str(value) for value in row]
            if any(value.strip() for value in values):
                raw_rows.append(values)
        workbook.close()

        if not raw_rows:
            return json.dumps(
                {"error": f"Sheet '{target_sheet}' has no data"}, ensure_ascii=False
            )

        if financial_compact:
            compact_rows = _compact_financial_table_rows(raw_rows, max_rows)
            if compact_rows:
                raw_rows = compact_rows

        column_count = max(len(row) for row in raw_rows)
        normalized_rows = [row + [""] * (column_count - len(row)) for row in raw_rows]
        headers = normalized_rows[0]
        data_rows = normalized_rows[1:]
        sort_warning = ""
        selected_warning = ""

        if sort_by_text:
            sort_index = _match_header_index(headers, sort_by_text)
            if sort_index is None:
                sort_warning = f"未找到排序列“{sort_by_text}”，已保留原始行顺序。"
            else:
                data_rows = sorted(
                    data_rows,
                    key=lambda row_values: _table_sort_value(
                        row_values[sort_index] if sort_index < len(row_values) else ""
                    ),
                    reverse=sort_descending,
                )

        data_rows = data_rows[:max_rows]

        if selected_columns:
            selected_indexes: List[int] = []
            missing_columns: List[str] = []
            for column_name in selected_columns:
                matched_index = _match_header_index(headers, column_name)
                if matched_index is None:
                    missing_columns.append(column_name)
                    continue
                if matched_index not in selected_indexes:
                    selected_indexes.append(matched_index)
            if selected_indexes:
                headers = [headers[index] for index in selected_indexes]
                data_rows = [
                    [
                        row_values[index] if index < len(row_values) else ""
                        for index in selected_indexes
                    ]
                    for row_values in data_rows
                ]
                column_count = len(headers)
            if missing_columns:
                selected_warning = "未找到列：" + "、".join(missing_columns[:6])

        normalized_rows = [headers, *data_rows]

        os.makedirs(os.path.dirname(target_resolved), exist_ok=True)
        target_exists = os.path.exists(target_resolved)
        backup_warning = ""
        if target_exists:
            backup_warning = _best_effort_backup(target_resolved)
            try:
                with open(target_resolved, "rb") as existing_doc:
                    document = Document(BytesIO(existing_doc.read()))
            except Exception as open_err:
                return json.dumps(
                    {
                        "error": (
                            f"无法用 python-docx 打开 {os.path.basename(target_resolved)}"
                            f"（{open_err}）。"
                            "请改用 run_python_code + python-docx 手动追加表格，"
                            "或用 openpyxl 读取数据后用脚本写入 docx。"
                        )
                    },
                    ensure_ascii=False,
                )
        else:
            document = Document()

        if document.paragraphs and any(p.text.strip() for p in document.paragraphs):
            document.add_paragraph("")

        style_warning = ""
        if table_title:
            title_paragraph = document.add_paragraph(table_title)
            style_warning = _apply_docx_style(title_paragraph, "Heading 2")

        table = document.add_table(rows=len(normalized_rows), cols=column_count)
        style_warning = _merge_warnings(
            style_warning,
            _apply_docx_style(table, "Table Grid"),
        )

        for row_index, row_values in enumerate(normalized_rows):
            for column_index, value in enumerate(row_values):
                table.cell(row_index, column_index).text = value
        if financial_compact:
            _style_compact_financial_docx_table(table, document)

        preview_lines = []
        if headers:
            preview_lines.append(" | ".join(headers[:6]))
        for row_values in data_rows[:3]:
            preview_lines.append(" | ".join(row_values[:6]))

        try:
            _save_docx_via_temp_file(document, target_resolved)
        except PermissionError as exc:
            locked_message = str(exc).strip() or _nonwritable_target_message(
                target_resolved
            )
            try:
                fallback_resolved = _next_available_docx_copy_path(target_resolved)
                _save_docx_via_temp_file(document, fallback_resolved)
            except Exception:
                return _blocked_write_result(
                    _result_path(target_path, target_resolved),
                    summary=locked_message,
                    suggested_next_step=_nonwritable_target_next_step(target_resolved),
                    source_path=_result_path(source_path, source_resolved),
                    sheet=target_sheet,
                    requested_sheet=requested_sheet,
                )

            result_warning = "；".join(
                part
                for part in (
                    sheet_warning,
                    backup_warning,
                    f"原目标文件 {os.path.basename(target_resolved)} 当前不可写，结果已写入同目录副本 {os.path.basename(fallback_resolved)}。",
                )
                if part
            )
            return _blocked_write_result(
                _result_path(fallback_resolved, fallback_resolved),
                summary=(
                    f"原目标文件 {os.path.basename(target_resolved)} 当前不可写，尚未写回原文件；"
                    f"已将工作表“{target_sheet}”的 {len(data_rows)} 行数据写入恢复副本 {os.path.basename(fallback_resolved)}"
                ),
                suggested_next_step=_nonwritable_target_next_step(target_resolved),
                operation="insert_excel_as_docx_table",
                file_type="docx",
                change_type="create",
                preview="\n".join(preview_lines),
                focus=True,
                source_path=_result_path(source_path, source_resolved),
                sheet=target_sheet,
                requested_sheet=requested_sheet,
                warning=result_warning,
                rows_written=len(data_rows),
                columns_written=column_count,
                table_title=table_title,
                table_count=1,
                sort_by=sort_by_text,
                sort_order="desc" if sort_descending else "asc",
                selected_columns=selected_columns,
                financial_compact=bool(financial_compact),
                original_target_path=_result_path(target_path, target_resolved),
                blocked_target=True,
                blocked_reason=locked_message,
                fallback_copy=True,
            )

        result_warning = "；".join(
            part
            for part in (sheet_warning, sort_warning, selected_warning, style_warning)
            if part
        )
        if backup_warning:
            result_warning = "；".join(
                part for part in (result_warning, backup_warning) if part
            )

        return _success_result(
            _result_path(target_path, target_resolved),
            operation="insert_excel_as_docx_table",
            summary=f"已将工作表“{target_sheet}”的 {len(data_rows)} 行数据写入 Word 表格",
            file_type="docx",
            change_type="modify" if target_exists else "create",
            preview="\n".join(preview_lines),
            focus=True,
            source_path=_result_path(source_path, source_resolved),
            sheet=target_sheet,
            requested_sheet=requested_sheet,
            warning=result_warning,
            rows_written=len(data_rows),
            columns_written=column_count,
            table_title=table_title,
            table_count=1,
            sort_by=sort_by_text,
            sort_order="desc" if sort_descending else "asc",
            selected_columns=selected_columns,
            financial_compact=bool(financial_compact),
        )
    except ImportError as exc:
        return json.dumps({"error": f"Missing dependency: {exc}"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def insert_image_into_docx(
    path: str,
    image_path: str,
    title: str = "",
    caption: str = "",
    width_inches: Any = 6.5,
) -> str:
    """Append an image or chart into a DOCX file as a real inline picture."""
    resolved = _resolve_path(path)
    if not resolved:
        if os.path.isabs(path):
            resolved = os.path.normpath(path)
        else:
            resolved = _safe_resolve(path)
    if not resolved:
        return json.dumps({"error": f"Invalid path: {path}"}, ensure_ascii=False)

    image_resolved = _resolve_path(image_path)
    if not image_resolved:
        return json.dumps(
            {"error": f"File not found: {image_path}"}, ensure_ascii=False
        )

    title_text = str(title or "").strip()
    caption_text = str(caption or "").strip()
    image_width = _normalize_positive_float(width_inches, default=6.5, upper=10.0)

    try:
        from io import BytesIO

        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Inches

        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        target_exists = os.path.exists(resolved)
        backup_warning = ""
        write_warning = ""
        if target_exists:
            backup_warning = _best_effort_backup(resolved)
            write_warning = _ensure_existing_file_writable(resolved)
            try:
                with open(resolved, "rb") as existing_doc:
                    document = Document(BytesIO(existing_doc.read()))
            except Exception as open_err:
                return json.dumps(
                    {
                        "error": (
                            f"无法用 python-docx 打开 {os.path.basename(resolved)}"
                            f"（{open_err}）。"
                            "请改用 run_python_code + python-docx 手动插图，"
                            "或检查目标文件是否损坏。"
                        )
                    },
                    ensure_ascii=False,
                )
        else:
            document = Document()

        if document.paragraphs and any(
            paragraph.text.strip() for paragraph in document.paragraphs
        ):
            document.add_paragraph("")

        style_warning = ""
        if title_text:
            title_paragraph = document.add_paragraph(title_text)
            style_warning = _apply_docx_style(title_paragraph, "Heading 2")

        picture_paragraph = document.add_paragraph()
        picture_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        picture_run = picture_paragraph.add_run()
        picture_run.add_picture(image_resolved, width=Inches(image_width))

        if caption_text:
            caption_paragraph = document.add_paragraph(caption_text)
            caption_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            style_warning = _merge_warnings(
                style_warning,
                _apply_docx_style(caption_paragraph, "Caption"),
            )

        image_name = os.path.basename(image_resolved)
        preview_lines: List[str] = []
        if title_text:
            preview_lines.append(title_text)
        preview_lines.append(image_name)
        if caption_text:
            preview_lines.append(caption_text)

        try:
            _save_docx_via_temp_file(document, resolved)
        except PermissionError as exc:
            locked_message = str(exc).strip() or _nonwritable_target_message(resolved)
            try:
                fallback_resolved = _next_available_docx_copy_path(resolved)
                _save_docx_via_temp_file(document, fallback_resolved)
            except Exception:
                return _blocked_write_result(
                    _result_path(path, resolved),
                    summary=locked_message,
                    suggested_next_step=_nonwritable_target_next_step(resolved),
                    image_path=_result_path(image_path, image_resolved),
                    image_name=image_name,
                    images_inserted=1,
                    title=title_text,
                    caption=caption_text,
                )

            result_warning = "；".join(
                part
                for part in (
                    backup_warning,
                    write_warning,
                    style_warning,
                    f"原目标文件 {os.path.basename(resolved)} 当前不可写，结果已写入同目录副本 {os.path.basename(fallback_resolved)}。",
                )
                if part
            )
            return _blocked_write_result(
                _result_path(fallback_resolved, fallback_resolved),
                summary=(
                    f"原目标文件 {os.path.basename(resolved)} 当前不可写，尚未写回原文件；"
                    f"已将图片“{image_name}”插入恢复副本 {os.path.basename(fallback_resolved)}"
                ),
                suggested_next_step=_nonwritable_target_next_step(resolved),
                operation="insert_image_into_docx",
                file_type="docx",
                change_type="create",
                preview="\n".join(preview_lines),
                focus=True,
                image_path=_result_path(image_path, image_resolved),
                image_name=image_name,
                images_inserted=1,
                title=title_text,
                caption=caption_text,
                warning=result_warning,
                original_target_path=_result_path(path, resolved),
                blocked_target=True,
                blocked_reason=locked_message,
                fallback_copy=True,
            )

        return _success_result(
            _result_path(path, resolved),
            operation="insert_image_into_docx",
            summary=f"已将图片“{image_name}”插入 Word 文档",
            file_type="docx",
            change_type="modify" if target_exists else "create",
            preview="\n".join(preview_lines),
            focus=True,
            image_path=_result_path(image_path, image_resolved),
            image_name=image_name,
            images_inserted=1,
            title=title_text,
            caption=caption_text,
            warning=_merge_warnings(backup_warning, write_warning, style_warning),
        )
    except ImportError:
        return json.dumps({"error": "python-docx not installed"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def insert_docx_paragraph(
    path: str,
    text: str,
    after_heading: str = "",
    before_heading: str = "",
    style: str = "Normal",
) -> str:
    """Insert a single paragraph into an existing DOCX without rewriting the document."""
    resolved = _resolve_path(path)
    if not resolved:
        return json.dumps({"error": f"File not found: {path}"}, ensure_ascii=False)
    clean_text = str(text or "").strip()
    if not clean_text:
        return json.dumps({"error": "text is required"}, ensure_ascii=False)

    try:
        from docx import Document
        from docx.oxml import OxmlElement
        from docx.text.paragraph import Paragraph

        doc = Document(resolved)
        backup_warning = _best_effort_backup(resolved)
        write_warning = _ensure_existing_file_writable(resolved)
        after = str(after_heading or "").strip().casefold()
        before = str(before_heading or "").strip().casefold()
        insertion_index = len(doc.paragraphs)

        if before:
            for index, paragraph in enumerate(doc.paragraphs):
                if str(paragraph.text or "").strip().casefold() == before:
                    insertion_index = index
                    break
        elif after:
            for index, paragraph in enumerate(doc.paragraphs):
                if str(paragraph.text or "").strip().casefold() == after:
                    insertion_index = index + 1
                    break

        if insertion_index >= len(doc.paragraphs):
            paragraph = doc.add_paragraph(clean_text)
        else:
            anchor = doc.paragraphs[insertion_index]
            new_p = OxmlElement("w:p")
            anchor._p.addprevious(new_p)
            paragraph = Paragraph(new_p, anchor._parent)
            paragraph.add_run(clean_text)

        style_warning = _apply_docx_style(paragraph, style)

        _save_docx_via_temp_file(doc, resolved)
        return _success_result(
            _result_path(path, resolved),
            operation="insert_docx_paragraph",
            summary="已向 Word 文档插入 1 个段落",
            file_type="docx",
            change_type="modify",
            preview=clean_text,
            paragraphs_written=1,
            focus=True,
            inserted_text=clean_text,
            after_heading=after_heading,
            before_heading=before_heading,
            warning=_merge_warnings(backup_warning, write_warning, style_warning),
            diff=_file_task_diff(
                "docx_paragraphs",
                [
                    {
                        "paragraph_index": insertion_index + 1,
                        "before": "",
                        "after": clean_text,
                        "style": style or "",
                    }
                ],
            ),
        )
    except ImportError:
        return json.dumps({"error": "python-docx not installed"}, ensure_ascii=False)
    except PermissionError as exc:
        return _blocked_write_result(
            _result_path(path, resolved),
            summary=str(exc).strip() or _nonwritable_target_message(resolved),
            suggested_next_step=_nonwritable_target_next_step(resolved),
            operation="insert_docx_paragraph",
            file_type="docx",
            preview=clean_text,
        )
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
