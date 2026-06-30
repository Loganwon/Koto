# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.file_assistant import (
    TempFileInvalidIdError,
    TempFileNotFoundError,
    WorkspaceFileDownloadService,
    WorkspaceFileNotFoundError,
    WorkspaceFilePermissionError,
    WorkspaceFileUnsupportedTypeError,
    WorkspaceTempStore,
)


def test_raw_file_resolves_absolute_path_mime_and_no_cache_headers(tmp_path: Path):
    file_id = "abc123"
    target = tmp_path / f"{file_id}.pdf"
    target.write_bytes(b"%PDF")

    raw = WorkspaceTempStore().raw_file(tmp_dir=tmp_path, file_id=file_id)

    assert raw.path == target.resolve()
    assert raw.mime_type == "application/pdf"
    assert "no-store" in raw.headers["Cache-Control"]
    assert "no-cache" in raw.headers["Cache-Control"]
    assert raw.headers["Pragma"] == "no-cache"


def test_raw_file_rejects_non_alnum_id(tmp_path: Path):
    with pytest.raises(TempFileInvalidIdError):
        WorkspaceTempStore().raw_file(tmp_dir=tmp_path, file_id="bad..id")


def test_raw_file_raises_for_missing_id(tmp_path: Path):
    with pytest.raises(TempFileNotFoundError):
        WorkspaceTempStore().raw_file(tmp_dir=tmp_path, file_id="missing")


def test_mime_type_for_unknown_suffix_falls_back_to_octet_stream():
    assert WorkspaceTempStore.mime_type_for_suffix(".bin") == "application/octet-stream"


def test_mime_type_for_docx():
    assert "wordprocessingml" in WorkspaceTempStore.mime_type_for_suffix(".docx")


def test_workspace_file_download_resolves_workspace_file(tmp_path: Path):
    target = tmp_path / "sample.pdf"
    target.write_bytes(b"%PDF")

    served = WorkspaceFileDownloadService().serve_file(
        workspace_dir=tmp_path,
        filepath="sample.pdf",
        allowed_extensions={".pdf"},
    )

    assert served.path == target.resolve()
    assert served.mime_type == "application/pdf"
    assert served.download_name == "sample.pdf"


def test_workspace_file_download_resolves_subdir_file(tmp_path: Path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    target = uploads / "sub.pdf"
    target.write_bytes(b"%PDF")

    served = WorkspaceFileDownloadService().serve_file(
        workspace_dir=tmp_path,
        filepath="uploads/sub.pdf",
        allowed_extensions={".pdf"},
    )

    assert served.path == target.resolve()


def test_workspace_file_download_blocks_traversal(tmp_path: Path):
    outside = tmp_path.parent / "outside.pdf"
    outside.write_bytes(b"%PDF")

    with pytest.raises(WorkspaceFilePermissionError):
        WorkspaceFileDownloadService().serve_file(
            workspace_dir=tmp_path,
            filepath="../outside.pdf",
            allowed_extensions={".pdf"},
        )


def test_workspace_file_download_rejects_missing_file(tmp_path: Path):
    with pytest.raises(WorkspaceFileNotFoundError):
        WorkspaceFileDownloadService().serve_file(
            workspace_dir=tmp_path,
            filepath="ghost.pdf",
            allowed_extensions={".pdf"},
        )


def test_workspace_file_download_rejects_unsupported_extension(tmp_path: Path):
    target = tmp_path / "readme.xyz"
    target.write_text("hi", encoding="utf-8")

    with pytest.raises(WorkspaceFileUnsupportedTypeError):
        WorkspaceFileDownloadService().serve_file(
            workspace_dir=tmp_path,
            filepath="readme.xyz",
            allowed_extensions={".pdf"},
        )
