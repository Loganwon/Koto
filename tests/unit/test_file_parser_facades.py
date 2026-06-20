# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations


def test_xlsx_parser_facade_owns_workbook_parse(tmp_path):
    from app.core.file.parsers.xlsx_parser import parse_xlsx

    import openpyxl

    path = tmp_path / "book.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.cell(row=1, column=1, value="hello")
    wb.save(path)
    wb.close()

    result = parse_xlsx(str(path), original_name="Original.xlsx")

    sheet_id = result["sheetOrder"][0]
    assert result["name"] == "Original"
    assert result["sheets"][sheet_id]["name"] == "Data"
    assert result["sheets"][sheet_id]["cellData"][0][0]["v"] == "hello"


def test_pdf_parser_facade_returns_graceful_fallback_for_unreadable_file():
    from app.core.file.parsers.pdf_parser import parse_pdf

    result = parse_pdf("missing.pdf", "abc123")

    assert result["raw_url"] == "/api/v1/workspace/raw/abc123"
    assert result["page_count"] == 0
    assert result["pages"] == []


def test_pptx_geometry_facade_delegates_to_geometry_parser(monkeypatch):
    from app.core.file.parsers import pptx_geometry_parser
    from app.core.file.parsers.pptx_parser import parse_pptx_geometry

    monkeypatch.setattr(
        pptx_geometry_parser,
        "parse_pptx_geometry",
        lambda file_path: {"geometry": file_path},
    )

    assert parse_pptx_geometry("deck.pptx") == {"geometry": "deck.pptx"}


def test_docx_export_compat_wrapper_delegates_to_exporter(monkeypatch):
    import app.core.file.exporters.docx_exporter as exporter_mod
    from app.core.file.file_parser import export_docx

    captured = {}

    def fake_export_docx(data, original_path=None):
        captured["docx"] = (data, original_path)
        return b"docx"

    monkeypatch.setattr(exporter_mod, "export_docx", fake_export_docx)

    assert export_docx({"html": "x"}, original_path="template.docx") == b"docx"
    assert captured["docx"] == ({"html": "x"}, "template.docx")


def test_docx_exporter_owns_export():
    from app.core.file.exporters.docx_exporter import export_docx

    raw = export_docx({"html": "<p>Hello</p>"})
    assert raw[:2] == b"PK"


def test_xlsx_exporter_owns_workbook_export():
    from app.core.file.exporters.xlsx_exporter import export_xlsx

    raw = export_xlsx({"sheetOrder": [], "sheets": {}})

    assert raw[:2] == b"PK"


def test_xlsx_exporter_normalizes_univer_snapshot_payload():
    from app.core.file.exporters.xlsx_exporter import normalize_workbook_export_payload

    snapshot = {"sheets": {"sheet1": {}}}
    images = [{"id": "img1"}]

    workbook_data, images_data = normalize_workbook_export_payload(
        {"snapshot": snapshot, "_images": images}
    )

    assert workbook_data is snapshot
    assert images_data is images


def test_xlsx_exporter_normalizes_bare_workbook_payload():
    from app.core.file.exporters.xlsx_exporter import normalize_workbook_export_payload

    workbook = {"sheets": {}}

    assert normalize_workbook_export_payload(workbook) == (workbook, [])


def test_system_paths_resolves_tesseract_from_env(monkeypatch, tmp_path):
    from app.core.shared.system_paths import resolve_tesseract_cmd

    exe = tmp_path / "tesseract.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("KOTO_TESSERACT_CMD", str(exe))

    assert resolve_tesseract_cmd() == str(exe)
