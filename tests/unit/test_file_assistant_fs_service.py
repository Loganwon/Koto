# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import sys
from pathlib import Path
import types

import pytest
from werkzeug.datastructures import FileStorage

from app.core.file_assistant import WorkspaceFsError, WorkspaceFsService


def _seed_text(path: Path) -> None:
    path.write_text("", encoding="utf-8")


class _RecordingFileService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []

    def create_directory(self, dir_path: str) -> dict[str, object]:
        self.calls.append(("create_directory", dir_path, None))
        Path(dir_path).mkdir(parents=True, exist_ok=True)
        return {"success": True, "path": dir_path}

    def rename_file(self, file_path: str, new_name: str) -> dict[str, object]:
        self.calls.append(("rename_file", file_path, new_name))
        path = Path(file_path)
        new_path = path.parent / new_name
        path.rename(new_path)
        return {"success": True, "new_path": str(new_path)}

    def copy_file(self, source: str, destination: str) -> dict[str, object]:
        self.calls.append(("copy_file", source, destination))
        Path(destination).write_bytes(Path(source).read_bytes())
        return {"success": True, "destination": destination}

    def copy_path(self, source: str, destination: str) -> dict[str, object]:
        self.calls.append(("copy_path", source, destination))
        source_path = Path(source)
        destination_path = Path(destination)
        if source_path.is_dir():
            destination_path.mkdir(parents=True, exist_ok=True)
            for child in source_path.iterdir():
                if child.is_file():
                    (destination_path / child.name).write_bytes(child.read_bytes())
        else:
            destination_path.write_bytes(source_path.read_bytes())
        return {"success": True, "destination": destination}

    def move_file(self, source: str, destination: str) -> dict[str, object]:
        self.calls.append(("move_file", source, destination))
        Path(source).replace(destination)
        return {"success": True, "destination": destination}

    def move_path(self, source: str, destination: str) -> dict[str, object]:
        self.calls.append(("move_path", source, destination))
        Path(source).replace(destination)
        return {"success": True, "destination": destination}

    def delete_file(self, file_path: str) -> dict[str, object]:
        self.calls.append(("delete_file", file_path, None))
        Path(file_path).unlink()
        return {"success": True, "deleted": file_path}

    def delete_path(self, path: str) -> dict[str, object]:
        self.calls.append(("delete_path", path, None))
        target = Path(path)
        if target.is_dir():
            for child in target.iterdir():
                if child.is_file():
                    child.unlink()
            target.rmdir()
        else:
            target.unlink()
        return {"success": True, "deleted": path}


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


def test_file_operations_delegate_to_file_service(tmp_path: Path) -> None:
    service = _RecordingFileService()
    fs = WorkspaceFsService(file_service=service)  # type: ignore[arg-type]

    folder = fs.create_folder(workspace_dir=tmp_path, parent_rel="", name="folder")
    assert folder.path == "folder"

    rel_file = tmp_path / "old.docx"
    rel_file.write_bytes(b"doc")
    renamed = fs.rename(
        workspace_dir=tmp_path,
        rel_path="old.docx",
        new_name="new.txt",
    )
    assert renamed.path == "new.docx"

    src = tmp_path / "source.txt"
    src.write_text("copy", encoding="utf-8")
    dst = tmp_path / "dst"
    dst.mkdir()
    copied = fs.copy_or_move_absolute_path(
        src_raw=str(src),
        dst_dir_raw=str(dst),
        move=False,
        path_guard=lambda _path: True,
    )
    assert (dst / copied.name).read_text(encoding="utf-8") == "copy"

    move_src = tmp_path / "move.txt"
    move_src.write_text("move", encoding="utf-8")
    moved = fs.copy_or_move_absolute_path(
        src_raw=str(move_src),
        dst_dir_raw=str(dst),
        move=True,
        path_guard=lambda _path: True,
    )
    assert not move_src.exists()
    assert (dst / moved.name).read_text(encoding="utf-8") == "move"

    doomed = tmp_path / "delete.txt"
    doomed.write_text("delete", encoding="utf-8")
    fs.delete_absolute_path(raw_path=str(doomed), path_guard=lambda _path: True)
    assert not doomed.exists()

    call_names = [call[0] for call in service.calls]
    assert call_names == [
        "create_directory",
        "rename_file",
        "copy_path",
        "move_path",
        "delete_path",
    ]
