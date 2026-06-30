# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.core.file_assistant import PptxPreflightError, PptxPreflightService


def test_pptx_preflight_skips_non_pptx(tmp_path: Path):
    target = tmp_path / "notes.txt"
    target.write_text("hello", encoding="utf-8")

    PptxPreflightService().check(target, ".txt")


def test_pptx_preflight_rejects_embedded_video(tmp_path: Path):
    target = tmp_path / "video.pptx"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("ppt/media/movie1.mp4", b"video")

    with pytest.raises(PptxPreflightError) as exc:
        PptxPreflightService().check(target, ".pptx")

    assert exc.value.status_code == 415
    assert "movie1.mp4" in str(exc.value)


def test_pptx_preflight_rejects_large_file(tmp_path: Path):
    target = tmp_path / "large.pptx"
    with target.open("wb") as fh:
        fh.seek(PptxPreflightService.MAX_BYTES + 1)
        fh.write(b"\0")

    with pytest.raises(PptxPreflightError) as exc:
        PptxPreflightService().check(target, ".pptx")

    assert exc.value.status_code == 413
    assert "文件过大" in str(exc.value)


def test_find_embedded_video_returns_none_for_invalid_zip(tmp_path: Path):
    target = tmp_path / "bad.pptx"
    target.write_bytes(b"not a zip")

    assert PptxPreflightService.find_embedded_video(target) is None
