# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_settings_frontend_posts_backend_category_contract() -> None:
    settings = _read("web/src/app/settings.ts")
    update_body = settings[settings.index("export async function updateSetting") :]

    assert "JSON.stringify({ category, key, value })" in update_body
    assert "JSON.stringify({ section, key, value })" not in update_body
    assert "data.success === false" in update_body
    assert "rememberSetting(category, key, value);" in update_body
    assert "console.warn('Failed to update setting', category, key, e);" in update_body
    assert "throw e;" not in update_body


def test_settings_open_does_not_override_server_zoom_with_stale_local_storage() -> None:
    settings = _read("web/src/app/settings.ts")
    open_body = settings[settings.index("export function openSettings") : settings.index("export function closeSettings")]
    apply_body = settings[settings.index("export function applySettingsToUI") : settings.index("function setActivityActive")]
    theme = _read("web/src/app/theme.ts")

    assert "localStorage.getItem('koto.uiZoom')" not in open_body
    assert "setUIZoom(String(savedZoom), true)" in apply_body
    assert "localStorage.setItem('koto.uiZoom', normalizedZoom);" in theme
    assert "Math.max(0.7, Math.min(1.5" in theme
