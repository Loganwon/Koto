# Copyright (C) 2024-2026 Koto AI. All rights reserved.
"""Architecture guards for the single durable user-settings write path."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_production_settings_writers_use_shared_store() -> None:
    writers = (
        "src/koto_setup.py",
        "src/local_model_installer.py",
        "src/model_downloader.py",
        "web/blueprints/workspace_assistant.py",
        "app/core/skills/skill_manager.py",
    )
    forbidden = (
        "settings_path.write_text(",
        'open(settings_path, "w"',
        "open(settings_path, 'w'",
        "json.dump(settings,",
        "_json.dump(settings,",
    )

    for writer in writers:
        source = _source(writer)
        assert "atomic_update_settings" in source or "SettingsManager().set" in source
        for pattern in forbidden:
            assert pattern not in source, f"{writer} bypasses the shared settings store"


def test_settings_manager_does_not_expose_mutable_internal_sections() -> None:
    source = _source("app/core/config/user_settings.py")

    assert "return copy.deepcopy(self._settings[category])" in source
    assert "return copy.deepcopy(value)" in source
    assert "threading.RLock()" in source
    assert "atomic_update_settings(" in source


def test_standalone_installer_bundles_shared_settings_store() -> None:
    spec = _source("local_model_installer.spec")

    assert '"app.core.config.settings_store"' in spec
    assert '"web", "google", "flask"' in spec
    assert '"web", "app", "google", "flask"' not in spec
