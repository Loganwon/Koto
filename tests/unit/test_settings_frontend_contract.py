# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

from pathlib import Path

from tests.source_graph import read_frontend_partitions

ROOT = Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    if Path(rel_path).suffix in {".ts", ".js", ".css"}:
        return read_frontend_partitions(rel_path)
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
    open_body = settings[
        settings.index("export function openSettings") : settings.index(
            "export function closeSettings"
        )
    ]
    apply_body = settings[
        settings.index("export function applySettingsToUI") : settings.index(
            "function setActivityActive"
        )
    ]
    theme = _read("web/src/app/theme.ts")

    assert "localStorage.getItem('koto.uiZoom')" not in open_body
    assert "setUIZoom(String(savedZoom), true)" in apply_body
    assert "localStorage.setItem('koto.uiZoom', normalizedZoom);" in theme
    assert "normalizeUiZoom(rawZoom)" in theme


def test_settings_controls_have_one_persisted_runtime_path() -> None:
    panel = _read("web/templates/_settings_panel.html")
    settings = _read("web/src/app/settings.ts")
    event_controller = _read("web/src/app/template-event-controller.ts")
    theme = _read("web/src/app/theme.ts")
    chat_ui = _read("web/src/app/chat-ui.ts")

    assert 'data-koto-event-input="h_settings_preview_zoom"' in panel
    assert 'data-koto-event-change="h_settings_set_zoom"' in panel
    assert 'data-koto-event-change="h_settings_boolean"' in panel
    assert '"h_settings_boolean"' in event_controller
    assert '"h_settings_set_zoom"' in event_controller
    for inline_event in ("onclick=", "onchange=", "oninput=", "onkeydown="):
        assert inline_event not in panel
    # The unified workspace no longer exposes the legacy classic-chat game
    # toggle, which had no live consumer on the current surface.
    assert "onBooleanSettingChange(this, 'ai', 'enable_mini_game')" not in panel
    assert "export async function onBooleanSettingChange" in settings
    update_setting = settings[settings.index("export async function updateSetting") :]
    assert "settingsWriteQueue = settingsWriteQueue.then" in update_setting
    assert "resolveResult(false);" in update_setting
    local_model_change = settings[
        settings.index("export async function onLocalModelChange") :
    ]
    assert (
        "body: JSON.stringify({ mode: 'local', model_tag: nextModel })"
        in local_model_change
    )
    assert "if (localOnly)" not in local_model_change.split("// ── Setup Wizard", 1)[0]
    assert "export function previewUIZoom" in theme
    assert "setUIZoom(zoomStr, true, false);" in theme
    assert "currentSettings?.appearance?.ui_zoom" in theme
    assert "_systemThemeQuery.addEventListener('change'" in theme
    assert "const enableMiniGame" not in chat_ui
    assert "enableMiniGame" not in chat_ui
    assert "applyWorkspacePresentationSettings" in settings
    assert "data-koto-show-thinking" in _read("web/static/css/workspace.css")
    assert "root.setAttribute('data-theme', resolvedTheme);" in theme
