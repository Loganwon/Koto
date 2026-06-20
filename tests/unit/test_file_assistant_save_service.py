# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.file_assistant import AutoSavePermissionError, AutoSavePersistenceService


def test_persist_implicit_save_writes_tmp_only(tmp_path: Path):
    workspace = tmp_path / "workspace"
    tmp_dir = tmp_path / "tmp"
    workspace.mkdir()
    tmp_dir.mkdir()

    result = AutoSavePersistenceService().persist(
        tmp_dir=tmp_dir,
        file_id="abc123",
        raw_bytes=b"draft",
        suffix=".txt",
        explicit=False,
        ws_source_path="notes.txt",
        workspace_dir=workspace,
        allowed_extensions={".txt"},
        fs_guard=lambda path: True,
    )

    assert result.src_written is False
    assert result.tmp_path == tmp_dir / "abc123.txt"
    assert result.tmp_path.read_bytes() == b"draft"
    assert not (workspace / "notes.txt").exists()


def test_persist_explicit_workspace_save_writes_source_and_snapshot(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    tmp_dir = tmp_path / "tmp"
    workspace.mkdir()
    tmp_dir.mkdir()

    monkeypatch.setattr(AutoSavePersistenceService, "_sync_registry", staticmethod(lambda path: None))

    result = AutoSavePersistenceService().persist(
        tmp_dir=tmp_dir,
        file_id="abc123",
        raw_bytes=b"final",
        suffix=".txt",
        explicit=True,
        ws_source_path="folder/notes.txt",
        workspace_dir=workspace,
        allowed_extensions={".txt"},
        fs_guard=lambda path: True,
    )

    source = workspace / "folder" / "notes.txt"
    assert result.src_written is True
    assert result.src_path == source
    assert source.read_bytes() == b"final"
    snapshots = list((workspace / "folder" / ".koto_versions" / "notes").glob("*.txt"))
    assert snapshots
    assert snapshots[-1].read_bytes() == b"final"


def test_persist_blocks_relative_path_traversal(tmp_path: Path):
    workspace = tmp_path / "workspace"
    tmp_dir = tmp_path / "tmp"
    workspace.mkdir()
    tmp_dir.mkdir()

    with pytest.raises(AutoSavePermissionError):
        AutoSavePersistenceService().persist(
            tmp_dir=tmp_dir,
            file_id="abc123",
            raw_bytes=b"bad",
            suffix=".txt",
            explicit=True,
            ws_source_path="../escape.txt",
            workspace_dir=workspace,
            allowed_extensions={".txt"},
            fs_guard=lambda path: True,
        )

    assert (tmp_dir / "abc123.txt").read_bytes() == b"bad"
    assert not (tmp_path / "escape.txt").exists()


def test_persist_external_missing_parent_skips_source_write(tmp_path: Path):
    workspace = tmp_path / "workspace"
    tmp_dir = tmp_path / "tmp"
    workspace.mkdir()
    tmp_dir.mkdir()
    external = tmp_path / "missing" / "external.txt"

    result = AutoSavePersistenceService().persist(
        tmp_dir=tmp_dir,
        file_id="abc123",
        raw_bytes=b"external",
        suffix=".txt",
        explicit=True,
        ws_source_path=str(external),
        workspace_dir=workspace,
        allowed_extensions={".txt"},
        fs_guard=lambda path: True,
    )

    assert result.src_written is False
    assert (tmp_dir / "abc123.txt").read_bytes() == b"external"
    assert not external.exists()
