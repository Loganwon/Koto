# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class TempFileInvalidIdError(ValueError):
    """Raised when a temporary file id is not safe to use."""


class TempFileNotFoundError(FileNotFoundError):
    """Raised when a temporary raw file cannot be found."""


class WorkspaceFilePermissionError(PermissionError):
    """Raised when a workspace file path escapes the workspace root."""


class WorkspaceFileNotFoundError(FileNotFoundError):
    """Raised when a workspace file cannot be found."""


class WorkspaceFileUnsupportedTypeError(ValueError):
    """Raised when a workspace file is not supported for serving."""


@dataclass(frozen=True)
class RawTempFile:
    path: Path
    mime_type: str
    headers: dict[str, str]


@dataclass(frozen=True)
class ServedWorkspaceFile:
    path: Path
    mime_type: str
    download_name: str


class WorkspaceTempStore:
    """Resolve session tmp files used by the workspace file assistant."""

    MIME_BY_SUFFIX = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }

    NO_CACHE_HEADERS = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
    }

    def raw_file(self, *, tmp_dir: str | Path, file_id: str) -> RawTempFile:
        if not file_id.isalnum():
            raise TempFileInvalidIdError("无效的 file_id")

        matches = list(Path(tmp_dir).glob(f"{file_id}.*"))
        if not matches:
            raise TempFileNotFoundError("文件不存在或已过期")

        target = matches[0].resolve()
        return RawTempFile(
            path=target,
            mime_type=self.mime_type_for_suffix(target.suffix),
            headers=dict(self.NO_CACHE_HEADERS),
        )

    @classmethod
    def mime_type_for_suffix(cls, suffix: str) -> str:
        return cls.MIME_BY_SUFFIX.get(str(suffix).lower(), "application/octet-stream")


class WorkspaceFileDownloadService:
    """Resolve workspace-relative files for direct browser serving."""

    def serve_file(
        self,
        *,
        workspace_dir: str | Path,
        filepath: str,
        allowed_extensions: set[str] | frozenset[str],
    ) -> ServedWorkspaceFile:
        root = Path(workspace_dir).resolve()
        target = root.joinpath(filepath).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise WorkspaceFilePermissionError("路径不合法") from exc

        if not target.is_file():
            raise WorkspaceFileNotFoundError("文件不存在")

        if target.suffix.lower() not in {
            str(ext).lower() for ext in allowed_extensions
        }:
            raise WorkspaceFileUnsupportedTypeError("不支持的文件类型")

        return ServedWorkspaceFile(
            path=target,
            mime_type=WorkspaceTempStore.mime_type_for_suffix(target.suffix),
            download_name=target.name,
        )


__all__ = [
    "RawTempFile",
    "ServedWorkspaceFile",
    "TempFileInvalidIdError",
    "TempFileNotFoundError",
    "WorkspaceTempStore",
    "WorkspaceFileDownloadService",
    "WorkspaceFileNotFoundError",
    "WorkspaceFilePermissionError",
    "WorkspaceFileUnsupportedTypeError",
]
