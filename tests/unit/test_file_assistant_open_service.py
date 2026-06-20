# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.file_assistant import (
    OpenFileByPathService,
    OpenFileCopyError,
    OpenFileEmptyError,
    OpenFileInConfigError,
    OpenFileNotFoundError,
    OpenFilePermissionError,
    OpenFileUnsupportedTypeError,
    UploadedOpenFileService,
)


def test_prepare_workspace_relative_file_copies_to_tmp(tmp_path: Path):
    workspace = tmp_path / "workspace"
    tmp_dir = tmp_path / "tmp"
    config = tmp_path / "config"
    workspace.mkdir()
    tmp_dir.mkdir()
    config.mkdir()
    source = workspace / "docs" / "notes.txt"
    source.parent.mkdir()
    source.write_text("hello", encoding="utf-8")

    copied = {}

    def copy_to_tmp(src: Path, dst: Path, *, ext: str):
        copied["src"] = src
        copied["dst"] = dst
        copied["ext"] = ext
        dst.write_bytes(src.read_bytes())

    prepared = OpenFileByPathService().prepare(
        raw_path="docs/notes.txt",
        workspace_dir=workspace,
        app_config_dir=config,
        tmp_dir=tmp_dir,
        file_id="abc123",
        allowed_extensions={".txt"},
        fs_guard=lambda path: True,
        repair_zero_byte_file=lambda path: False,
        copy_to_tmp=copy_to_tmp,
    )

    assert prepared.target_path == source.resolve()
    assert prepared.tmp_path == tmp_dir / "abc123.txt"
    assert prepared.tmp_path.read_text(encoding="utf-8") == "hello"
    assert copied["ext"] == ".txt"


def test_prepare_blocks_relative_path_traversal(tmp_path: Path):
    workspace = tmp_path / "workspace"
    tmp_dir = tmp_path / "tmp"
    config = tmp_path / "config"
    workspace.mkdir()
    tmp_dir.mkdir()
    config.mkdir()

    with pytest.raises(OpenFilePermissionError):
        OpenFileByPathService().prepare(
            raw_path="../outside.txt",
            workspace_dir=workspace,
            app_config_dir=config,
            tmp_dir=tmp_dir,
            file_id="abc123",
            allowed_extensions={".txt"},
            fs_guard=lambda path: True,
            repair_zero_byte_file=lambda path: False,
            copy_to_tmp=lambda *args, **kwargs: None,
        )


def test_prepare_blocks_absolute_config_path(tmp_path: Path):
    workspace = tmp_path / "workspace"
    tmp_dir = tmp_path / "tmp"
    config = tmp_path / "config"
    workspace.mkdir()
    tmp_dir.mkdir()
    config.mkdir()
    target = config / "secret.txt"
    target.write_text("secret", encoding="utf-8")

    with pytest.raises(OpenFileInConfigError):
        OpenFileByPathService().prepare(
            raw_path=str(target),
            workspace_dir=workspace,
            app_config_dir=config,
            tmp_dir=tmp_dir,
            file_id="abc123",
            allowed_extensions={".txt"},
            fs_guard=lambda path: True,
            repair_zero_byte_file=lambda path: False,
            copy_to_tmp=lambda *args, **kwargs: None,
        )


def test_prepare_allows_absolute_workspace_path(tmp_path: Path):
    workspace = tmp_path / "workspace"
    tmp_dir = tmp_path / "tmp"
    config = tmp_path / "config"
    workspace.mkdir()
    tmp_dir.mkdir()
    config.mkdir()
    target = workspace / "notes.txt"
    target.write_text("hello", encoding="utf-8")

    prepared = OpenFileByPathService().prepare(
        raw_path=str(target),
        workspace_dir=workspace,
        app_config_dir=config,
        tmp_dir=tmp_dir,
        file_id="abc123",
        allowed_extensions={".txt"},
        fs_guard=lambda path: True,
        repair_zero_byte_file=lambda path: False,
        copy_to_tmp=lambda src, dst, *, ext: dst.write_bytes(src.read_bytes()),
    )

    assert prepared.target_path == target.resolve()


def test_prepare_blocks_external_absolute_path_by_default(tmp_path: Path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    tmp_dir = tmp_path / "tmp"
    config = tmp_path / "config"
    workspace.mkdir()
    outside.mkdir()
    tmp_dir.mkdir()
    config.mkdir()
    target = outside / "notes.txt"
    target.write_text("hello", encoding="utf-8")

    with pytest.raises(OpenFilePermissionError):
        OpenFileByPathService().prepare(
            raw_path=str(target),
            workspace_dir=workspace,
            app_config_dir=config,
            tmp_dir=tmp_dir,
            file_id="abc123",
            allowed_extensions={".txt"},
            fs_guard=lambda path: True,
            repair_zero_byte_file=lambda path: False,
            copy_to_tmp=lambda *args, **kwargs: None,
        )


def test_prepare_allows_external_absolute_path_when_explicit(tmp_path: Path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    tmp_dir = tmp_path / "tmp"
    config = tmp_path / "config"
    workspace.mkdir()
    outside.mkdir()
    tmp_dir.mkdir()
    config.mkdir()
    target = outside / "notes.txt"
    target.write_text("hello", encoding="utf-8")

    prepared = OpenFileByPathService().prepare(
        raw_path=str(target),
        workspace_dir=workspace,
        app_config_dir=config,
        tmp_dir=tmp_dir,
        file_id="abc123",
        allowed_extensions={".txt"},
        fs_guard=lambda path: True,
        repair_zero_byte_file=lambda path: False,
        copy_to_tmp=lambda src, dst, *, ext: dst.write_bytes(src.read_bytes()),
        allow_external_absolute=True,
    )

    assert prepared.target_path == target.resolve()


def test_prepare_rejects_missing_file(tmp_path: Path):
    workspace = tmp_path / "workspace"
    tmp_dir = tmp_path / "tmp"
    config = tmp_path / "config"
    workspace.mkdir()
    tmp_dir.mkdir()
    config.mkdir()

    with pytest.raises(OpenFileNotFoundError):
        OpenFileByPathService().prepare(
            raw_path="missing.txt",
            workspace_dir=workspace,
            app_config_dir=config,
            tmp_dir=tmp_dir,
            file_id="abc123",
            allowed_extensions={".txt"},
            fs_guard=lambda path: True,
            repair_zero_byte_file=lambda path: False,
            copy_to_tmp=lambda *args, **kwargs: None,
        )


def test_prepare_rejects_unsupported_extension(tmp_path: Path):
    workspace = tmp_path / "workspace"
    tmp_dir = tmp_path / "tmp"
    config = tmp_path / "config"
    workspace.mkdir()
    tmp_dir.mkdir()
    config.mkdir()
    target = workspace / "archive.xyz"
    target.write_text("data", encoding="utf-8")

    with pytest.raises(OpenFileUnsupportedTypeError):
        OpenFileByPathService().prepare(
            raw_path="archive.xyz",
            workspace_dir=workspace,
            app_config_dir=config,
            tmp_dir=tmp_dir,
            file_id="abc123",
            allowed_extensions={".txt"},
            fs_guard=lambda path: True,
            repair_zero_byte_file=lambda path: False,
            copy_to_tmp=lambda *args, **kwargs: None,
        )


def test_prepare_wraps_copy_failure(tmp_path: Path):
    workspace = tmp_path / "workspace"
    tmp_dir = tmp_path / "tmp"
    config = tmp_path / "config"
    workspace.mkdir()
    tmp_dir.mkdir()
    config.mkdir()
    target = workspace / "notes.txt"
    target.write_text("hello", encoding="utf-8")

    def fail_copy(*args, **kwargs):
        raise RuntimeError("boom")

    with pytest.raises(OpenFileCopyError, match="文件复制失败"):
        OpenFileByPathService().prepare(
            raw_path="notes.txt",
            workspace_dir=workspace,
            app_config_dir=config,
            tmp_dir=tmp_dir,
            file_id="abc123",
            allowed_extensions={".txt"},
            fs_guard=lambda path: True,
            repair_zero_byte_file=lambda path: False,
            copy_to_tmp=fail_copy,
        )


def test_prepare_uploaded_file_saves_to_tmp(tmp_path: Path):
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()

    prepared = UploadedOpenFileService().prepare(
        original_name="notes.txt",
        tmp_dir=tmp_dir,
        file_id="abc123",
        allowed_extensions={".txt"},
        save_upload=lambda target: target.write_bytes(b"hello"),
    )

    assert prepared.original_name == "notes.txt"
    assert prepared.extension == ".txt"
    assert prepared.tmp_path == tmp_dir / "abc123.txt"
    assert prepared.tmp_path.read_bytes() == b"hello"


def test_prepare_uploaded_file_rejects_unsupported_extension(tmp_path: Path):
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()

    with pytest.raises(OpenFileUnsupportedTypeError, match="不支持的格式"):
        UploadedOpenFileService().prepare(
            original_name="notes.xyz",
            tmp_dir=tmp_dir,
            file_id="abc123",
            allowed_extensions={".txt"},
            save_upload=lambda target: target.write_bytes(b"hello"),
        )


def test_prepare_uploaded_file_rejects_empty_file_and_removes_tmp(tmp_path: Path):
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()

    with pytest.raises(OpenFileEmptyError, match="文件内容为空"):
        UploadedOpenFileService().prepare(
            original_name="empty.txt",
            tmp_dir=tmp_dir,
            file_id="abc123",
            allowed_extensions={".txt"},
            save_upload=lambda target: target.write_bytes(b""),
        )

    assert not (tmp_dir / "abc123.txt").exists()
