# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import os
import shutil
from pathlib import Path

_TESSERACT_ENV_VARS = ("TESSERACT_CMD", "KOTO_TESSERACT_CMD")
_TESSERACT_WINDOWS_CANDIDATES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


def resolve_tesseract_cmd() -> str | None:
    for env_name in _TESSERACT_ENV_VARS:
        candidate = os.environ.get(env_name)
        if candidate and Path(candidate).is_file():
            return candidate

    for candidate in _TESSERACT_WINDOWS_CANDIDATES:
        if Path(candidate).is_file():
            return candidate

    return shutil.which("tesseract")
