"""Contracts for optional, non-blocking model runtime capabilities."""

from __future__ import annotations

import sys
from unittest.mock import Mock, patch

import pytest
import requests

from app.core.llm.runtime_capabilities import (
    CapabilityState,
    CapabilityStatus,
    RuntimeCapabilityRegistry,
    inspect_local_model_capability,
    refresh_model_capabilities,
)


def test_registry_serializes_stable_public_status_values() -> None:
    registry = RuntimeCapabilityRegistry()
    registry.set(
        CapabilityState(
            name="local_model",
            status=CapabilityStatus.INCOMPATIBLE,
            reason="runtime_outdated",
        )
    )

    assert registry.snapshot()["local_model"]["status"] == "incompatible"


@pytest.mark.parametrize(
    ("scenario", "mode", "key", "model", "expected"),
    [
        ("blank", "cloud", None, "", "misconfigured"),
        ("cloud_invalid", "cloud", "invalid", "", "available"),
        ("cloud_offline", "cloud", "offline-key", "", "available"),
        ("local_unselected", "local", None, "", "misconfigured"),
        ("local_service_down", "local", None, "qwen2.5:7b", "checking"),
        ("local_model_missing", "local", None, "missing:latest", "checking"),
        ("local_runtime_incompatible", "local", None, "new-runtime:latest", "checking"),
        ("legacy_upgrade", "local", None, "legacy:7b", "checking"),
    ],
)
def test_configuration_refresh_never_probes_network(
    scenario: str, mode: str, key: str | None, model: str, expected: str
) -> None:
    with (
        patch(
            "app.core.llm.local_model_runtime.get_configured_model_mode",
            return_value=mode,
        ),
        patch(
            "app.core.llm.local_model_runtime.get_configured_local_model_tag",
            return_value=model,
        ),
        patch("app.core.llm.deepseek_config.get_deepseek_api_key", return_value=key),
        patch("app.core.llm.runtime_capabilities.requests.get") as network_get,
    ):
        result = refresh_model_capabilities(probe_local=False)

    assert result["capabilities"]["active_model"]["status"] == expected
    network_get.assert_not_called()


def test_local_service_down_is_unavailable_not_fatal() -> None:
    with (
        patch(
            "app.core.llm.local_model_runtime.get_configured_local_model_tag",
            return_value="qwen2.5:7b",
        ),
        patch(
            "app.core.llm.runtime_capabilities.requests.get",
            side_effect=requests.ConnectionError("offline"),
        ),
    ):
        state = inspect_local_model_capability()

    assert state.status is CapabilityStatus.UNAVAILABLE
    assert state.reason == "ollama_unreachable"


def test_selected_but_uninstalled_model_is_misconfigured() -> None:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"models": [{"name": "other:latest"}]}
    with (
        patch(
            "app.core.llm.local_model_runtime.get_configured_local_model_tag",
            return_value="missing:7b",
        ),
        patch("app.core.llm.runtime_capabilities.requests.get", return_value=response),
    ):
        state = inspect_local_model_capability()

    assert state.status is CapabilityStatus.MISCONFIGURED
    assert state.reason == "model_not_installed"


def test_runtime_model_version_mismatch_is_incompatible() -> None:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"models": [{"name": "qwen2.5:7b"}]}
    with (
        patch(
            "app.core.llm.local_model_runtime.get_configured_local_model_tag",
            return_value="qwen2.5:7b",
        ),
        patch("app.core.llm.runtime_capabilities.requests.get", return_value=response),
        patch(
            "app.core.llm.ollama_runtime_compat.inspect_ollama_model_compatibility",
            return_value={
                "compatible": False,
                "current_version": "0.1.0",
                "required_version": "0.5.0",
            },
        ),
    ):
        state = inspect_local_model_capability()

    assert state.status is CapabilityStatus.INCOMPATIBLE
    assert state.repair_action == "update_ollama_or_switch_model"


def test_show_probe_failure_never_promotes_selected_model_to_available() -> None:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"models": [{"name": "broken:latest"}]}
    with (
        patch(
            "app.core.llm.local_model_runtime.get_configured_local_model_tag",
            return_value="broken:latest",
        ),
        patch("app.core.llm.runtime_capabilities.requests.get", return_value=response),
        patch(
            "app.core.llm.ollama_runtime_compat.inspect_ollama_model_compatibility",
            return_value={
                "compatible": None,
                "reason": "model_load_failed",
                "current_version": "0.17.1",
                "required_version": "",
            },
        ),
    ):
        state = inspect_local_model_capability()

    assert state.status is CapabilityStatus.MISCONFIGURED
    assert state.reason == "model_load_failed"
    assert state.repair_action == "reinstall_or_switch_local_model"


def test_compatible_installed_model_is_available_without_generation() -> None:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"models": [{"model": "qwen2.5:7b"}]}
    with (
        patch(
            "app.core.llm.local_model_runtime.get_configured_local_model_tag",
            return_value="qwen2.5:7b",
        ),
        patch("app.core.llm.runtime_capabilities.requests.get", return_value=response),
        patch(
            "app.core.llm.ollama_runtime_compat.inspect_ollama_model_compatibility",
            return_value={
                "compatible": True,
                "current_version": "0.6.0",
                "required_version": "0.5.0",
            },
        ),
        patch("app.core.llm.runtime_capabilities.requests.post") as generation,
    ):
        state = inspect_local_model_capability()

    assert state.status is CapabilityStatus.AVAILABLE
    generation.assert_not_called()


def test_legacy_local_model_tag_remains_readable() -> None:
    from app.core.llm.local_model_runtime import get_configured_local_model_tag

    settings = Mock()
    settings.get_all.return_value = {
        "model_mode": "ollama",
        "local_model_tag": "legacy:7b",
    }
    with patch("app.core.config.user_settings.SettingsManager", return_value=settings):
        assert get_configured_local_model_tag() == "legacy:7b"


def test_deepseek_config_override_is_authoritative(tmp_path, monkeypatch) -> None:
    from app.core.llm.deepseek_config import _candidate_key_files

    isolated = tmp_path / "deepseek_config.env"
    monkeypatch.setenv("KOTO_DEEPSEEK_CONFIG_PATH", str(isolated))

    assert _candidate_key_files() == [isolated]


def test_frozen_deepseek_project_root_is_executable_directory(tmp_path) -> None:
    from app.core.llm.deepseek_config import project_root

    executable = tmp_path / "Koto.exe"
    with (
        patch.object(sys, "frozen", True, create=True),
        patch.object(sys, "executable", str(executable)),
    ):
        assert project_root() == tmp_path
