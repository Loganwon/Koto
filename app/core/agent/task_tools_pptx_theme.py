# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import json
from typing import Any, Dict

_PPTX_THEME_PRESETS: Dict[str, Dict[str, Any]] = {
    "executive": {
        "name": "executive",
        "display_name": "商务简报",
        "font_family": "Microsoft YaHei",
        "background": "F7F3EA",
        "primary": "17324D",
        "body_text": "25313B",
        "inverse_text": "FFFFFF",
        "accent": "0F766E",
        "accent2": "D97706",
        "muted": "E6DED2",
    },
    "tech": {
        "name": "tech",
        "display_name": "科技深色",
        "font_family": "Microsoft YaHei",
        "background": "0F172A",
        "primary": "38BDF8",
        "body_text": "E5E7EB",
        "inverse_text": "F8FAFC",
        "accent": "14B8A6",
        "accent2": "F59E0B",
        "muted": "1E293B",
    },
    "minimal": {
        "name": "minimal",
        "display_name": "清爽简约",
        "font_family": "Microsoft YaHei",
        "background": "F8FAFC",
        "primary": "0F3B57",
        "body_text": "1F2937",
        "inverse_text": "FFFFFF",
        "accent": "14B8A6",
        "accent2": "C2410C",
        "muted": "E2E8F0",
    },
}


def _coerce_jsonish(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        if text[0] in "[{":
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _normalize_hex_color(value: Any, fallback: str) -> str:
    text = str(value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in text):
        return text.upper()
    return fallback.upper()


def _hex_to_rgb_color(value: Any, fallback: str):
    from pptx.dml.color import RGBColor

    color = _normalize_hex_color(value, fallback)
    return RGBColor(int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16))


def _color_luminance(hex_color: str) -> float:
    color = _normalize_hex_color(hex_color, "FFFFFF")
    red = int(color[0:2], 16)
    green = int(color[2:4], 16)
    blue = int(color[4:6], 16)
    return 0.299 * red + 0.587 * green + 0.114 * blue


def _select_pptx_theme(
    style_brief: Any = "",
    theme: Any = "",
    palette: Any = "",
    typography: Any = "",
) -> Dict[str, Any]:
    brief_text = f"{style_brief or ''} {theme or ''}".lower()
    light_theme_tokens = (
        "minimal",
        "简约",
        "清爽",
        "浅色",
        "浅色系",
        "明亮",
        "clean",
        "light",
        "white",
    )
    wants_light_theme = any(token in brief_text for token in light_theme_tokens)
    if wants_light_theme:
        preset_key = "minimal"
    elif any(
        token in brief_text
        for token in ("tech", "科技", "ai", "agent", "互联网", "dark", "深色")
    ):
        preset_key = "tech"
    else:
        preset_key = "executive"

    result = dict(_PPTX_THEME_PRESETS[preset_key])
    theme_value = _coerce_jsonish(theme)
    if isinstance(theme_value, dict):
        for key in (
            "name",
            "display_name",
            "font_family",
            "background",
            "primary",
            "body_text",
            "inverse_text",
            "accent",
            "accent2",
            "muted",
        ):
            if theme_value.get(key) not in (None, ""):
                result[key] = theme_value.get(key)

    typography_value = _coerce_jsonish(typography)
    if isinstance(typography_value, dict):
        font_family = (
            typography_value.get("font_family")
            or typography_value.get("font")
            or typography_value.get("body")
        )
        if font_family:
            result["font_family"] = str(font_family)
    elif typography_value:
        result["font_family"] = str(typography_value)

    palette_value = _coerce_jsonish(palette)
    if isinstance(palette_value, dict):
        aliases = {
            "background": ("background", "bg"),
            "primary": ("primary", "brand", "main"),
            "accent": ("accent", "secondary"),
            "accent2": ("accent2", "highlight"),
            "body_text": ("body_text", "text"),
        }
        for target_key, keys in aliases.items():
            for key in keys:
                if palette_value.get(key):
                    result[target_key] = palette_value.get(key)
                    break
    elif isinstance(palette_value, list):
        keys = ["primary", "accent", "accent2", "background", "body_text"]
        for key, value in zip(keys, palette_value):
            if value:
                result[key] = value

    for key in (
        "background",
        "primary",
        "body_text",
        "inverse_text",
        "accent",
        "accent2",
        "muted",
    ):
        result[key] = _normalize_hex_color(
            result.get(key), _PPTX_THEME_PRESETS[preset_key][key]
        )
    if wants_light_theme and _color_luminance(str(result["background"])) < 200:
        minimal = _PPTX_THEME_PRESETS["minimal"]
        for key in ("background", "body_text", "inverse_text", "muted"):
            result[key] = minimal[key]
        result["display_name"] = minimal["display_name"]
    if str(result.get("font_family") or "").strip().lower() in {
        "serif",
        "sans-serif",
        "sans serif",
        "monospace",
    }:
        result["font_family"] = _PPTX_THEME_PRESETS[preset_key]["font_family"]
    result["is_dark"] = _color_luminance(str(result["background"])) < 120
    return result


def _pptx_density_settings(density: Any) -> Dict[str, float]:
    value = str(density or "balanced").strip().lower()
    if value in {"compact", "dense", "紧凑", "高密度"}:
        return {
            "margin_x": 0.55,
            "title_top": 0.32,
            "title_size": 29,
            "body_size": 15,
            "body_top": 1.22,
        }
    if value in {"spacious", "loose", "舒展", "留白"}:
        return {
            "margin_x": 0.82,
            "title_top": 0.42,
            "title_size": 34,
            "body_size": 18,
            "body_top": 1.55,
        }
    return {
        "margin_x": 0.68,
        "title_top": 0.38,
        "title_size": 32,
        "body_size": 16,
        "body_top": 1.38,
    }
