"""Contracts for the installer first-run cloud/local choice."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def test_cloud_choice_persists_key_and_cloud_mode(tmp_path: Path) -> None:
    from src import local_model_installer as installer

    with patch.object(installer, "APP_DIR", tmp_path):
        installer.save_cloud_setup("sk-test-key-123456789", "https://proxy.example/v1")

    config_dir = tmp_path / "config"
    env_text = (config_dir / "deepseek_config.env").read_text(encoding="utf-8")
    settings = json.loads(
        (config_dir / "user_settings.json").read_text(encoding="utf-8")
    )
    completion = json.loads(
        (config_dir / "model_setup_done.json").read_text(encoding="utf-8")
    )
    assert "DEEPSEEK_API_KEY=sk-test-key-123456789" in env_text
    assert "DEEPSEEK_BASE_URL=https://proxy.example/v1" in env_text
    assert settings["model_mode"] == "cloud"
    assert settings["ai"]["cloud_provider"] == "deepseek"
    assert completion["mode"] == "cloud"


def test_cloud_choice_rejects_empty_or_short_key(tmp_path: Path) -> None:
    from src import local_model_installer as installer

    with patch.object(installer, "APP_DIR", tmp_path), pytest.raises(ValueError):
        installer.save_cloud_setup("short")


def test_local_choice_is_a_valid_first_run_completion(tmp_path: Path) -> None:
    from src import koto_setup

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "model_setup_done.json").write_text(
        json.dumps({"done": True, "mode": "local", "model": "qwen3:4b"}),
        encoding="utf-8",
    )
    with patch.object(koto_setup, "APP_ROOT", tmp_path):
        assert koto_setup._local_model_configured() is True


def test_missing_configuration_must_complete_unified_choice(tmp_path: Path) -> None:
    from src import koto_setup

    with patch.object(koto_setup, "APP_ROOT", tmp_path), patch.object(
        koto_setup, "_local_model_configured", return_value=False
    ), patch.object(
        koto_setup, "_api_key_configured", return_value=False
    ), patch.object(
        koto_setup, "_run_unified_setup", return_value=True
    ) as chooser:
        assert koto_setup._run_setup_if_needed() is True
    chooser.assert_called_once()


def test_cancelled_unified_choice_blocks_desktop_start(tmp_path: Path) -> None:
    from src import koto_setup

    with patch.object(koto_setup, "APP_ROOT", tmp_path), patch.object(
        koto_setup, "_local_model_configured", return_value=False
    ), patch.object(
        koto_setup, "_api_key_configured", return_value=False
    ), patch.object(
        koto_setup, "_run_unified_setup", return_value=False
    ), patch.object(
        koto_setup,
        "_show_api_setup_wizard",
        return_value={"key": None, "base": "", "cancelled": True},
    ):
        assert koto_setup._run_setup_if_needed() is False
