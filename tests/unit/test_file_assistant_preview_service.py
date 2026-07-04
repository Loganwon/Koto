# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.file_assistant import FileContextPreviewService
from app.core.file_assistant.open_service import (
    OpenFileInConfigError,
    OpenFilePermissionError,
)


def test_preview_service_builds_text_preview(tmp_path: Path):
    workspace = tmp_path / "workspace"
    config = tmp_path / "config"
    workspace.mkdir()
    config.mkdir()
    target = workspace / "notes.md"
    target.write_text("hello world", encoding="utf-8")

    preview = FileContextPreviewService().build(
        raw_path="notes.md",
        workspace_dir=workspace,
        app_config_dir=config,
        allowed_extensions={".md"},
        fs_guard=lambda path: True,
        preview_limit=1000,
        text_parser=lambda path, max_chars: "hello world",
    )

    assert preview.file_name == "notes.md"
    assert preview.file_type == "text"
    assert preview.content_preview == "hello world"
    assert preview.original_chars == len("helloworld")
    assert preview.preview_error == ""


def test_preview_service_keeps_attachment_available_on_parser_error_string(
    tmp_path: Path,
):
    workspace = tmp_path / "workspace"
    config = tmp_path / "config"
    workspace.mkdir()
    config.mkdir()
    target = workspace / "broken.pdf"
    target.write_bytes(b"%PDF")

    preview = FileContextPreviewService().build(
        raw_path="broken.pdf",
        workspace_dir=workspace,
        app_config_dir=config,
        allowed_extensions={".pdf"},
        fs_guard=lambda path: True,
        preview_limit=1000,
        text_parser=lambda path, max_chars: "Error parsing file: simulated failure",
    )

    assert preview.file_type == "pdf"
    assert preview.content_preview == ""
    assert "simulated failure" in preview.preview_error


def test_preview_service_uses_docx_char_counter(tmp_path: Path):
    workspace = tmp_path / "workspace"
    config = tmp_path / "config"
    workspace.mkdir()
    config.mkdir()
    target = workspace / "doc.docx"
    target.write_bytes(b"fake")

    preview = FileContextPreviewService().build(
        raw_path="doc.docx",
        workspace_dir=workspace,
        app_config_dir=config,
        allowed_extensions={".docx"},
        fs_guard=lambda path: True,
        preview_limit=1000,
        text_parser=lambda path, max_chars: "short preview",
        docx_char_counter=lambda path: 1234,
    )

    assert preview.file_type == "docx"
    assert preview.original_chars == 1234


def test_preview_service_samples_long_text(tmp_path: Path):
    workspace = tmp_path / "workspace"
    config = tmp_path / "config"
    workspace.mkdir()
    config.mkdir()
    target = workspace / "long.txt"
    target.write_text("x", encoding="utf-8")
    text = "a" * 2000 + "b" * 2000

    preview = FileContextPreviewService().build(
        raw_path="long.txt",
        workspace_dir=workspace,
        app_config_dir=config,
        allowed_extensions={".txt"},
        fs_guard=lambda path: True,
        preview_limit=1000,
        text_parser=lambda path, max_chars: text,
    )

    assert "...[中间内容已省略]..." in preview.content_preview
    assert len(preview.content_preview) <= 1100


def test_preview_service_blocks_relative_path_traversal(tmp_path: Path):
    workspace = tmp_path / "workspace"
    config = tmp_path / "config"
    workspace.mkdir()
    config.mkdir()

    with pytest.raises(OpenFilePermissionError):
        FileContextPreviewService().build(
            raw_path="../outside.txt",
            workspace_dir=workspace,
            app_config_dir=config,
            allowed_extensions={".txt"},
            fs_guard=lambda path: True,
            preview_limit=1000,
            text_parser=lambda path, max_chars: "",
        )


def test_preview_service_blocks_config_path(tmp_path: Path):
    workspace = tmp_path / "workspace"
    config = tmp_path / "config"
    workspace.mkdir()
    config.mkdir()
    target = config / "secret.txt"
    target.write_text("secret", encoding="utf-8")

    with pytest.raises(OpenFileInConfigError):
        FileContextPreviewService().build(
            raw_path=str(target),
            workspace_dir=workspace,
            app_config_dir=config,
            allowed_extensions={".txt"},
            fs_guard=lambda path: True,
            preview_limit=1000,
            text_parser=lambda path, max_chars: "",
        )
