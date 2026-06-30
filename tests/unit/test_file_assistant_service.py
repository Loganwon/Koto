# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.core.file_assistant import FileAssistantService, UnsupportedFileTypeError


def test_parse_editor_file_reads_text_payload(tmp_path: Path):
    target = tmp_path / "notes.md"
    target.write_text("# 标题\n正文", encoding="utf-8")

    parsed = FileAssistantService().parse_editor_file(
        target,
        file_id="abc123",
        display_name="notes.md",
    )

    assert parsed.file_type == "text"
    assert parsed.data["content"] == "# 标题\n正文"
    assert parsed.data["language"] == "md"
    assert parsed.data["extension"] == ".md"


def test_export_editor_file_writes_text_bytes():
    exported = FileAssistantService().export_editor_file(
        file_type="code",
        data={"content": "print('koto')"},
        file_name="script.py",
    )

    assert exported.raw_bytes == b"print('koto')"
    assert exported.mime == "text/plain; charset=utf-8"
    assert exported.file_name == "script.py"
    assert exported.suffix == ".py"


def test_export_editor_file_xlsx_uses_exporter_payload_normalization(monkeypatch):
    captured = {}

    def fake_export_xlsx(data, images_data=None):
        captured["data"] = data
        captured["images_data"] = images_data
        return b"xlsx-bytes"

    import app.core.file.exporters.xlsx_exporter as exporter_mod

    monkeypatch.setattr(exporter_mod, "export_xlsx", fake_export_xlsx)

    snapshot = {"sheets": {"sheet1": {}}}
    images = [{"id": "img1"}]
    exported = FileAssistantService().export_editor_file(
        file_type="xlsx",
        data={"snapshot": snapshot, "_images": images},
        file_name="book",
    )

    assert exported.raw_bytes == b"xlsx-bytes"
    assert exported.file_name == "book.xlsx"
    assert captured["data"] is snapshot
    assert captured["images_data"] is images


def test_parse_editor_file_rejects_unknown_extension(tmp_path: Path):
    target = tmp_path / "archive.xyz"
    target.write_text("data", encoding="utf-8")

    with pytest.raises(UnsupportedFileTypeError):
        FileAssistantService().parse_editor_file(target, file_id="abc123")


def test_export_editor_file_uses_tmp_docx_template(tmp_path: Path, monkeypatch):
    template = tmp_path / "abc123.docx"
    template.write_bytes(b"template")
    captured = {}

    def fake_export_docx(data, original_path=None):
        captured["data"] = data
        captured["original_path"] = original_path
        return b"docx-bytes"

    import app.core.file.exporters.docx_exporter as exporter_mod

    monkeypatch.setattr(exporter_mod, "export_docx", fake_export_docx)

    exported = FileAssistantService().export_editor_file(
        file_type="docx",
        file_id="abc123",
        data={"html": "<p>Hi</p>"},
        file_name="report",
        tmp_dir=tmp_path,
    )

    assert exported.raw_bytes == b"docx-bytes"
    assert exported.file_name == "report.docx"
    assert captured["data"] == {"html": "<p>Hi</p>"}
    assert captured["original_path"] == str(template)


def test_load_full_docx_uses_docx_parser_facade(tmp_path: Path, monkeypatch):
    target = tmp_path / "full.docx"
    target.write_bytes(b"docx")

    def fake_parse_docx(path: str):
        return {"html": "<p>Full</p>"}

    import app.core.file.parsers.docx_parser as docx_parser

    monkeypatch.setattr(docx_parser, "parse_docx", fake_parse_docx)

    data = FileAssistantService().load_full_docx(target, file_id="abc123")

    assert data == {
        "html": "<p>Full</p>",
        "raw_url": "/api/v1/workspace/raw/abc123",
    }


def test_parse_docx_for_workspace_open_retries_bad_tmp_copy(
    tmp_path: Path, monkeypatch
):
    tmp_docx = tmp_path / "tmp.docx"
    source_docx = tmp_path / "source.docx"
    tmp_docx.write_bytes(b"bad")
    source_docx.write_bytes(b"good")
    calls = {"parse": 0, "copy": 0}

    def fake_parse_docx(path: str):
        calls["parse"] += 1
        if calls["parse"] == 1:
            raise zipfile.BadZipFile("File is not a zip file")
        return {"html": "<p>Recovered</p>"}

    def fake_copy_to_tmp(src: Path, dst: Path, *, ext: str):
        calls["copy"] += 1
        assert src == source_docx
        assert dst == tmp_docx
        assert ext == ".docx"
        dst.write_bytes(src.read_bytes())

    import app.core.file.parsers.docx_parser as docx_parser

    monkeypatch.setattr(docx_parser, "parse_docx", fake_parse_docx)

    data = FileAssistantService().parse_docx_for_workspace_open(
        tmp_docx,
        file_id="abc123",
        source_path=source_docx,
        copy_to_tmp=fake_copy_to_tmp,
    )

    assert calls == {"parse": 2, "copy": 1}
    assert data["html"] == "<p>Recovered</p>"
    assert data["raw_url"] == "/api/v1/workspace/raw/abc123"


def test_should_retry_docx_tmp_parse_for_package_not_found(tmp_path: Path):
    tmp_docx = tmp_path / "missing.docx"
    exc = RuntimeError(f"Package not found at {tmp_docx}")

    assert FileAssistantService.should_retry_docx_tmp_parse(exc, tmp_docx) is True
