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


def test_settings_controls_have_one_persisted_runtime_path() -> None:
    panel = _read("web/templates/_settings_panel.html")
    settings = _read("web/src/app/settings.ts")
    theme = _read("web/src/app/theme.ts")
    chat_ui = _read("web/src/app/chat-ui.ts")

    assert "oninput=\"previewUIZoom(this.value / 100)\"" in panel
    assert "onchange=\"setUIZoom(this.value / 100)\"" in panel
    assert "onBooleanSettingChange(this, 'ai', 'enable_mini_game')" in panel
    assert "export async function onBooleanSettingChange" in settings
    assert "return false;" in settings[settings.index("export async function updateSetting") :]
    local_model_change = settings[settings.index("export async function onLocalModelChange") :]
    assert "body: JSON.stringify({ model_tag: nextModel })" in local_model_change
    assert "if (localOnly)" not in local_model_change.split("// ── Setup Wizard", 1)[0]
    assert "export function previewUIZoom" in theme
    assert "currentSettings?.appearance?.ui_zoom" in theme
    assert "_systemThemeQuery.addEventListener('change'" in theme
    assert "const enableMiniGame" not in chat_ui
    assert "(window as any).enableMiniGame === false" in chat_ui
