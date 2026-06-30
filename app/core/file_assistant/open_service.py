# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

PathGuard = Callable[[Path], bool]
RepairFile = Callable[[Path], bool]
CopyToTmp = Callable[..., None]
SaveUpload = Callable[[Path], None]
PreCopyCheck = Callable[[Path, str], None]


class OpenFilePermissionError(PermissionError):
    """Raised when an open-file target fails path-safety checks."""


class OpenFileInConfigError(OpenFilePermissionError):
    """Raised when a request attempts to open Koto's config directory."""


class OpenFileNotFoundError(FileNotFoundError):
    """Raised when an open-file target does not exist."""


class OpenFileUnsupportedTypeError(ValueError):
    """Raised when an open-file target has an unsupported extension."""


class OpenFileCopyError(RuntimeError):
    """Raised when the source file cannot be copied into the editor tmp dir."""


class OpenFileEmptyError(ValueError):
    """Raised when an uploaded file is empty."""


@dataclass(frozen=True)
class PreparedOpenFile:
    raw_path: str
    target_path: Path
    tmp_path: Path
    file_id: str
    extension: str


@dataclass(frozen=True)
class PreparedUploadedFile:
    original_name: str
    tmp_path: Path
    file_id: str
    extension: str


class OpenFileByPathService:
    """Prepare an existing file for editor parsing."""

    def prepare(
        self,
        *,
        raw_path: str,
        workspace_dir: str | Path,
        app_config_dir: str | Path,
        tmp_dir: str | Path,
        file_id: str,
        allowed_extensions: Iterable[str],
        fs_guard: PathGuard,
        repair_zero_byte_file: RepairFile,
        copy_to_tmp: CopyToTmp,
        pre_copy_check: PreCopyCheck | None = None,
        copy_error_prefix: str = "文件复制失败",
        allow_external_absolute: bool = False,
    ) -> PreparedOpenFile:
        target = self.resolve_target(
            raw_path=raw_path,
            workspace_dir=workspace_dir,
            app_config_dir=app_config_dir,
            fs_guard=fs_guard,
            allow_external_absolute=allow_external_absolute,
        )

        if not target.is_file():
            raise OpenFileNotFoundError("文件不存在")

        ext = target.suffix.lower()
        if ext not in {str(item).lower() for item in allowed_extensions}:
            raise OpenFileUnsupportedTypeError(f"不支持的格式: {ext}")

        repair_zero_byte_file(target)
        if pre_copy_check is not None:
            pre_copy_check(target, ext)

        tmp_path = Path(tmp_dir) / f"{file_id}{ext}"
        try:
            copy_to_tmp(target, tmp_path, ext=ext)
        except Exception as exc:
            raise OpenFileCopyError(f"{copy_error_prefix}: {exc}") from exc

        return PreparedOpenFile(
            raw_path=raw_path,
            target_path=target,
            tmp_path=tmp_path,
            file_id=file_id,
            extension=ext,
        )

    @staticmethod
    def resolve_target(
        *,
        raw_path: str,
        workspace_dir: str | Path,
        app_config_dir: str | Path,
        fs_guard: PathGuard,
        allow_external_absolute: bool = False,
    ) -> Path:
        candidate = Path(raw_path)
        root = Path(workspace_dir).resolve()
        config_root = Path(app_config_dir).resolve()

        if candidate.is_absolute():
            target = candidate.resolve()
            try:
                target.relative_to(config_root)
            except ValueError:
                pass
            else:
                raise OpenFileInConfigError("不允许访问应用配置目录")
            if not allow_external_absolute:
                try:
                    target.relative_to(root)
                except ValueError as exc:
                    raise OpenFilePermissionError("路径不合法") from exc
            if not fs_guard(target):
                raise OpenFilePermissionError("路径不合法")
            return target

        target = root.joinpath(raw_path).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise OpenFilePermissionError("路径不合法") from exc
        return target


class UploadedOpenFileService:
    """Prepare an uploaded file for editor parsing."""

    def prepare(
        self,
        *,
        original_name: str,
        tmp_dir: str | Path,
        file_id: str,
        allowed_extensions: Iterable[str],
        save_upload: SaveUpload,
    ) -> PreparedUploadedFile:
        name = original_name or "unknown"
        ext = Path(name).suffix.lower()
        if ext not in {str(item).lower() for item in allowed_extensions}:
            raise OpenFileUnsupportedTypeError(
                f"不支持的格式: {ext}，仅支持 {sorted(allowed_extensions)}"
            )

        tmp_path = Path(tmp_dir) / f"{file_id}{ext}"
        save_upload(tmp_path)
        if tmp_path.stat().st_size == 0:
            tmp_path.unlink(missing_ok=True)
            raise OpenFileEmptyError(
                f"{name} 文件内容为空，无法打开。请重新选择非空文件。"
            )

        return PreparedUploadedFile(
            original_name=name,
            tmp_path=tmp_path,
            file_id=file_id,
            extension=ext,
        )
