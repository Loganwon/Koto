# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

from pathlib import Path

from app.core.file_assistant import WorkspaceTreeService


def _names(items: list[dict]) -> set[str]:
    return {item["name"] for item in items}


def test_workspace_tree_skips_hidden_and_runtime_dirs(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "memo.docx").write_bytes(b"doc")
    (tmp_path / "ppt_sessions").mkdir()
    (tmp_path / "ppt_sessions" / "old.pptx").write_bytes(b"ppt")
    (tmp_path / ".hidden").write_text("hidden", encoding="utf-8")
    (tmp_path / "tmp").mkdir()

    payload = WorkspaceTreeService().build_workspace_tree(
        root_path=tmp_path,
        allowed_extensions={".docx"},
    )

    assert payload["workspace_name"] == tmp_path.name
    assert payload["workspace_path"] == str(tmp_path.resolve())
    assert _names(payload["files"]) == {"docs"}
    docs = payload["files"][0]
    assert docs["children"][0]["name"] == "memo.docx"


def test_workspace_tree_file_entry_contains_category_support_size_and_mtime(tmp_path: Path):
    target = tmp_path / "sheet.xlsx"
    target.write_bytes(b"x" * 2048)

    payload = WorkspaceTreeService().build_workspace_tree(
        root_path=tmp_path,
        allowed_extensions={".xlsx"},
    )

    entry = payload["files"][0]
    assert entry["name"] == "sheet.xlsx"
    assert entry["type"] == "file"
    assert entry["ext"] == "xlsx"
    assert entry["path"] == "sheet.xlsx"
    assert entry["size"] == "2.0KB"
    assert isinstance(entry["mtime"], int)
    assert entry["supported"] is True
    assert entry["category"] == "xlsx"


def test_workspace_tree_marks_unsupported_files(tmp_path: Path):
    (tmp_path / "archive.zip").write_bytes(b"zip")

    payload = WorkspaceTreeService().build_workspace_tree(
        root_path=tmp_path,
        allowed_extensions={".txt"},
    )

    entry = payload["files"][0]
    assert entry["supported"] is False
    assert entry["category"] == "other"


def test_file_category_includes_bmp_image():
    assert WorkspaceTreeService.file_category(".bmp") == "image"
