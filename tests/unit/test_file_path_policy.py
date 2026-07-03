# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.file.path_policy import FilePathPolicy, PathPolicyError
from app.core.file_assistant import WorkspaceFsError, WorkspaceFsService
from app.core.services.file_service import FileService


def test_file_path_policy_resolves_workspace_relative_path(tmp_path: Path) -> None:
    policy = FilePathPolicy()

    resolved = policy.resolve_under_root(tmp_path, "notes/today.txt")

    assert resolved == (tmp_path / "notes" / "today.txt").resolve()


def test_file_path_policy_rejects_workspace_escape(tmp_path: Path) -> None:
    with pytest.raises(PathPolicyError):
        FilePathPolicy().resolve_under_root(tmp_path, "../outside.txt")


def test_workspace_fs_service_preserves_escape_error_contract(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceFsError) as exc:
        WorkspaceFsService().create_folder(
            workspace_dir=tmp_path,
            parent_rel="../outside",
            name="x",
        )

    assert exc.value.status_code == 403
    assert str(exc.value) == "路径不合法"


def test_file_service_delegates_safety_to_shared_policy(tmp_path: Path) -> None:
    class DenyAllPolicy(FilePathPolicy):
        def is_outside_protected_dirs(self, raw_path: str | Path) -> bool:
            return False

    svc = FileService(
        workspace_dir=str(tmp_path),
        backup_enabled=False,
        path_policy=DenyAllPolicy(),
    )

    assert svc.is_safe_path(str(tmp_path / "file.txt")) is False
    result = svc.write_file(str(tmp_path / "file.txt"), "content")
    assert result == {"success": False, "error": "拒绝写入系统保护目录"}
