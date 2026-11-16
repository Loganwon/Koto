# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Shared helpers for document generation (split from doc_gen_service.py)."""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# ── Style presets ───────────────────────────────────────────────────────────

_STYLE_PRESETS: Dict[str, Dict[str, Any]] = {
    "professional": {
        "title_font_size": 28,
        "h1_font_size": 16,
        "h2_font_size": 14,
        "h3_font_size": 12,
        "body_font_size": 11,
        "primary_rgb": (31, 78, 121),
        "secondary_rgb": (68, 114, 196),
        "accent_rgb": (237, 125, 49),
        "header_bg_rgb": (31, 78, 121),
        "header_fg_rgb": (255, 255, 255),
        "stripe_bg_rgb": (217, 225, 242),
        "line_spacing": 1.2,
    },
    "academic": {
        "title_font_size": 24,
        "h1_font_size": 14,
        "h2_font_size": 13,
        "h3_font_size": 12,
        "body_font_size": 11,
        "primary_rgb": (0, 0, 0),
        "secondary_rgb": (50, 50, 50),
        "accent_rgb": (0, 70, 130),
        "header_bg_rgb": (240, 240, 240),
        "header_fg_rgb": (0, 0, 0),
        "stripe_bg_rgb": (250, 250, 250),
        "line_spacing": 1.5,
    },
    "minimal": {
        "title_font_size": 26,
        "h1_font_size": 15,
        "h2_font_size": 13,
        "h3_font_size": 12,
        "body_font_size": 11,
        "primary_rgb": (60, 60, 60),
        "secondary_rgb": (100, 100, 100),
        "accent_rgb": (180, 180, 180),
        "header_bg_rgb": (230, 230, 230),
        "header_fg_rgb": (50, 50, 50),
        "stripe_bg_rgb": (248, 248, 248),
        "line_spacing": 1.3,
    },
    "colorful": {
        "title_font_size": 30,
        "h1_font_size": 18,
        "h2_font_size": 15,
        "h3_font_size": 13,
        "body_font_size": 11,
        "primary_rgb": (112, 48, 160),
        "secondary_rgb": (0, 176, 240),
        "accent_rgb": (255, 192, 0),
        "header_bg_rgb": (112, 48, 160),
        "header_fg_rgb": (255, 255, 255),
        "stripe_bg_rgb": (235, 220, 255),
        "line_spacing": 1.2,
    },
}

# ── Output directory ────────────────────────────────────────────────────────

_BASE_DIR = (
    Path(sys.executable).parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[3]
)
_DEFAULT_OUTPUT_DIR = _BASE_DIR / "workspace" / "doc_gen_outputs"


def get_preset(style_preset: str) -> Dict[str, Any]:
    return _STYLE_PRESETS.get(style_preset, _STYLE_PRESETS["professional"])


def ensure_output_dir(output_dir: str) -> Path:
    if output_dir:
        p = Path(output_dir)
    else:
        p = _DEFAULT_OUTPUT_DIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def build_output_path(output_dir: str, filename: str, extension: str) -> Path:
    out_dir = ensure_output_dir(output_dir)
    if filename:
        stem = Path(filename).stem
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = f"koto_{ts}_{uuid.uuid4().hex[:6]}"
    return out_dir / f"{stem}.{extension}"


def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 6:
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore
    return (31, 78, 121)


def find_chinese_font() -> Optional[str]:
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\simfang.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/Library/Fonts/Arial Unicode MS.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None
