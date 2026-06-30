# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from werkzeug.datastructures import FileStorage

from app.core.file_assistant import WorkspaceFsError, WorkspaceFsService


def _seed_text(path: Path) -> None:
    path.write_text("", encoding="utf-8")


def test_create_file_seeds_workspace_relative_file(tmp_path: Path) -> None:
    result = WorkspaceFsService().create_file(
        workspace_dir=tmp_path,
        folder="",
        name="note.txt",
        allowed_extensions={".txt"},
        seed_file=_seed_text,
    )

    assert result.path == "note.txt"
    assert result.name == "note.txt"
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == ""


def test_create_file_rejects_traversal_folder(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceFsError) as exc:
        WorkspaceFsService().create_file(
            workspace_dir=tmp_path,
            folder="../../outside",
            name="note.txt",
            allowed_extensions={".txt"},
            seed_file=_seed_text,
        )

    assert exc.value.status_code == 403


@pytest.mark.parametrize(
    "rel_path",
    [
        r"..\..\secret.txt",
        r"C:\Windows\System32\drivers\etc\hosts",
    ],
)
def test_workspace_relative_paths_reject_windows_traversal_forms(
    tmp_path: Path, rel_path: str
) -> None:
    with pytest.raises(WorkspaceFsError) as exc:
        WorkspaceFsService().delete_file(
            workspace_dir=tmp_path,
            rel_path=rel_path,
            allowed_extensions={".txt"},
        )

    assert exc.value.status_code == 403


def test_rename_file_preserves_original_extension(tmp_path: Path) -> None:
    (tmp_path / "old.docx").write_bytes(b"doc")

    result = WorkspaceFsService().rename(
        workspace_dir=tmp_path,
        rel_path="old.docx",
        new_name="new.txt",
    )

    assert result.path == "new.docx"
    assert result.name == "new.docx"
    assert (tmp_path / "new.docx").is_file()


def test_rename_folder_keeps_requested_name(tmp_path: Path) -> None:
    (tmp_path / "old_folder").mkdir()

    result = WorkspaceFsService().rename(
        workspace_dir=tmp_path,
        rel_path="old_folder",
        new_name="new_folder",
    )

    assert result.path == "new_folder"
    assert result.name == "new_folder"
    assert (tmp_path / "new_folder").is_dir()


def test_delete_file_falls_back_when_send2trash_removed_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "vanish.txt"
    target.write_text("x", encoding="utf-8")

    def fake_send2trash(path: str) -> None:
        Path(path).unlink()
        raise OSError("already moved")

    monkeypatch.setitem(
        sys.modules,
        "send2trash",
        types.SimpleNamespace(send2trash=fake_send2trash),
    )

    WorkspaceFsService().delete_file(
        workspace_dir=tmp_path,
        rel_path="vanish.txt",
        allowed_extensions={".txt"},
    )

    assert not target.exists()


def test_copy_absolute_path_dedupes_existing_target(tmp_path: Path) -> None:
    src = tmp_path / "source.txt"
    dst = tmp_path / "dst"
    dst.mkdir()
    src.write_text("new", encoding="utf-8")
    (dst / "source.txt").write_text("old", encoding="utf-8")

    result = WorkspaceFsService().copy_or_move_absolute_path(
        src_raw=str(src),
        dst_dir_raw=str(dst),
        move=False,
        path_guard=lambda _path: True,
    )

    assert result.name == "source (1).txt"
    assert (dst / "source (1).txt").read_text(encoding="utf-8") == "new"
    assert src.exists()


def test_upload_to_absolute_folder_dedupes_filenames(tmp_path: Path) -> None:
    import io

    (tmp_path / "upload.txt").write_text("old", encoding="utf-8")
    upload = FileStorage(stream=io.BytesIO(b"new"), filename="upload.txt")

    saved = WorkspaceFsService().upload_to_absolute_folder(
        dest_dir_raw=str(tmp_path),
        uploaded_files=[upload],
        path_guard=lambda _path: True,
    )

    assert saved[0].name == "upload (1).txt"
    assert (tmp_path / "upload (1).txt").read_bytes() == b"new"
