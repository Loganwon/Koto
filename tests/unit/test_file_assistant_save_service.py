# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.core.file_assistant import (
    AutoSaveConflictError,
    AutoSavePermissionError,
    AutoSavePersistenceService,
)


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


def test_persist_explicit_workspace_save_writes_source_and_snapshot(
    tmp_path: Path, monkeypatch
):
    workspace = tmp_path / "workspace"
    tmp_dir = tmp_path / "tmp"
    workspace.mkdir()
    tmp_dir.mkdir()

    monkeypatch.setattr(
        AutoSavePersistenceService, "_sync_registry", staticmethod(lambda path: None)
    )

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


def test_explicit_save_returns_verified_digest_and_retains_original_version(
    tmp_path, monkeypatch
):
    workspace, cache = tmp_path / "workspace", tmp_path / "tmp"
    workspace.mkdir()
    cache.mkdir()
    source = workspace / "report.txt"
    source.write_bytes(b"original")
    monkeypatch.setattr(
        AutoSavePersistenceService, "_sync_registry", staticmethod(lambda path: None)
    )
    original_hash = hashlib.sha256(b"original").hexdigest()
    result = AutoSavePersistenceService().persist(
        tmp_dir=cache,
        file_id="abc123",
        raw_bytes=b"edited",
        suffix=".txt",
        explicit=True,
        ws_source_path="report.txt",
        workspace_dir=workspace,
        allowed_extensions={".txt"},
        fs_guard=lambda path: True,
        expected_source_sha256=original_hash,
    )
    assert result.verified is True
    assert result.source_sha256 == hashlib.sha256(b"edited").hexdigest()
    assert result.previous_source_sha256 == original_hash
    snapshots = list((workspace / ".koto_versions" / "report").glob("*.txt"))
    assert {item.read_bytes() for item in snapshots} == {b"original", b"edited"}


def test_source_conflict_preserves_external_change_and_editor_draft(tmp_path):
    workspace, cache = tmp_path / "workspace", tmp_path / "tmp"
    workspace.mkdir()
    cache.mkdir()
    source = workspace / "report.txt"
    source.write_bytes(b"changed elsewhere")
    with pytest.raises(AutoSaveConflictError) as caught:
        AutoSavePersistenceService().persist(
            tmp_dir=cache,
            file_id="abc123",
            raw_bytes=b"editor draft",
            suffix=".txt",
            explicit=True,
            ws_source_path="report.txt",
            workspace_dir=workspace,
            allowed_extensions={".txt"},
            fs_guard=lambda path: True,
            expected_source_sha256=hashlib.sha256(b"original").hexdigest(),
        )
    assert source.read_bytes() == b"changed elsewhere"
    assert (cache / "abc123.txt").read_bytes() == b"editor draft"
    assert (
        caught.value.current_sha256 == hashlib.sha256(b"changed elsewhere").hexdigest()
    )


def test_source_publication_failure_rolls_back_and_does_not_report_success(
    tmp_path, monkeypatch
):
    workspace, cache = tmp_path / "workspace", tmp_path / "tmp"
    workspace.mkdir()
    cache.mkdir()
    source = workspace / "report.txt"
    source.write_bytes(b"original")
    real_write = AutoSavePersistenceService._atomic_write

    def fail_source(target, data):
        if target == source:
            raise OSError("simulated disk write failure")
        real_write(target, data)

    monkeypatch.setattr(
        AutoSavePersistenceService, "_atomic_write", staticmethod(fail_source)
    )
    with pytest.raises(OSError, match="simulated"):
        AutoSavePersistenceService().persist(
            tmp_dir=cache,
            file_id="abc123",
            raw_bytes=b"draft",
            suffix=".txt",
            explicit=True,
            ws_source_path="report.txt",
            workspace_dir=workspace,
            allowed_extensions={".txt"},
            fs_guard=lambda path: True,
        )
    assert source.read_bytes() == b"original"
    assert (cache / "abc123.txt").read_bytes() == b"draft"
    assert not list(workspace.glob("*.koto-rollback*"))


def test_uploaded_copy_can_save_without_overwriting_its_version_before_check(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    cache = workspace / "tmp" / "session"
    cache.mkdir(parents=True)
    source = cache / "abc123.txt"
    source.write_bytes(b"original")
    monkeypatch.setattr(
        AutoSavePersistenceService, "_sync_registry", staticmethod(lambda path: None)
    )
    result = AutoSavePersistenceService().persist(
        tmp_dir=cache,
        file_id="abc123",
        raw_bytes=b"edited",
        suffix=".txt",
        explicit=True,
        ws_source_path="tmp/session/abc123.txt",
        workspace_dir=workspace,
        allowed_extensions={".txt"},
        fs_guard=lambda path: True,
        expected_source_sha256=hashlib.sha256(b"original").hexdigest(),
    )
    assert result.src_written and result.verified
    assert source.read_bytes() == b"edited"


def test_uploaded_copy_autosave_updates_hash_without_claiming_explicit_save(tmp_path):
    workspace = tmp_path / "workspace"
    cache = workspace / "tmp" / "session"
    cache.mkdir(parents=True)
    source = cache / "abc123.txt"
    source.write_bytes(b"original")
    result = AutoSavePersistenceService().persist(
        tmp_dir=cache,
        file_id="abc123",
        raw_bytes=b"draft",
        suffix=".txt",
        explicit=False,
        ws_source_path="tmp/session/abc123.txt",
        workspace_dir=workspace,
        allowed_extensions={".txt"},
        fs_guard=lambda path: True,
        expected_source_sha256=hashlib.sha256(b"original").hexdigest(),
    )
    assert result.src_written is False and result.verified is False
    assert result.source_sha256 == hashlib.sha256(b"draft").hexdigest()
    assert source.read_bytes() == b"draft"


def test_conflicting_uploaded_copy_preserves_source_and_separate_draft(tmp_path):
    workspace = tmp_path / "workspace"
    cache = workspace / "tmp" / "session"
    cache.mkdir(parents=True)
    source = cache / "abc123.txt"
    source.write_bytes(b"external change")
    with pytest.raises(AutoSaveConflictError):
        AutoSavePersistenceService().persist(
            tmp_dir=cache,
            file_id="abc123",
            raw_bytes=b"draft",
            suffix=".txt",
            explicit=True,
            ws_source_path="tmp/session/abc123.txt",
            workspace_dir=workspace,
            allowed_extensions={".txt"},
            fs_guard=lambda path: True,
            expected_source_sha256=hashlib.sha256(b"original").hexdigest(),
        )
    assert source.read_bytes() == b"external change"
    assert (cache / "abc123.koto-editor-draft.txt").read_bytes() == b"draft"
