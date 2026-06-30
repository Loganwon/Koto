# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import zipfile
from pathlib import Path


class PptxPreflightError(ValueError):
    """Raised when a PPTX should be rejected before parsing."""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class PptxPreflightService:
    """Fast pre-parse checks for PPTX files opened by absolute path."""

    VIDEO_EXTENSIONS = frozenset(
        {
            ".mp4",
            ".mov",
            ".wmv",
            ".avi",
            ".m4v",
            ".mkv",
            ".flv",
            ".webm",
            ".asf",
            ".mpg",
            ".mpeg",
        }
    )
    MAX_BYTES = 50 * 1024 * 1024

    def check(self, file_path: str | Path, ext: str) -> None:
        if str(ext).lower() != ".pptx":
            return

        target = Path(file_path)
        found_video = self.find_embedded_video(target)
        if found_video:
            raise PptxPreflightError(
                (
                    f"该 PPTX 包含嵌入视频（{found_video}），Koto 当前不支持含视频的 PPTX 文件。\n"
                    f"请先在 PowerPoint 中选中视频 → 删除 → 另存为，然后重新打开。"
                ),
                status_code=415,
            )

        file_size = target.stat().st_size
        if file_size > self.MAX_BYTES:
            raise PptxPreflightError(
                f"PPTX 文件过大（{file_size / 1048576:.0f} MB），Koto 限制 50 MB。"
                f"建议压缩图片后重试。",
                status_code=413,
            )

    @classmethod
    def find_embedded_video(cls, file_path: str | Path) -> str | None:
        try:
            with zipfile.ZipFile(str(file_path)) as archive:
                for name in archive.namelist():
                    if Path(name).suffix.lower() in cls.VIDEO_EXTENSIONS:
                        return Path(name).name
        except Exception:
            return None
        return None


__all__ = ["PptxPreflightError", "PptxPreflightService"]
