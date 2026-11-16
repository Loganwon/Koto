from __future__ import annotations

from unittest.mock import Mock, patch

import requests

from app.core.llm.ollama_runtime_compat import (
    inspect_ollama_model_compatibility,
    version_is_at_least,
)


def _response(payload: dict) -> Mock:
    response = Mock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def test_version_comparison_handles_ollama_semver() -> None:
    assert version_is_at_least("0.17.1", "0.17.1") is True
    assert version_is_at_least("0.18.0-rc1", "0.17.1") is True
    assert version_is_at_least("0.15.4", "0.17.1") is False
    assert version_is_at_least("unknown", "0.17.1") is None


@patch("app.core.llm.ollama_runtime_compat.requests.post")
@patch("app.core.llm.ollama_runtime_compat.requests.get")
def test_inspection_reports_model_runtime_mismatch(get: Mock, post: Mock) -> None:
    get.return_value = _response({"version": "0.15.4"})
    post.return_value = _response({"requires": "0.17.1"})

    result = inspect_ollama_model_compatibility("qwen3.5:9b")

    assert result == {
        "model_id": "qwen3.5:9b",
        "current_version": "0.15.4",
        "required_version": "0.17.1",
        "compatible": False,
    }


@patch("app.core.llm.ollama_runtime_compat.requests.post")
@patch("app.core.llm.ollama_runtime_compat.requests.get")
def test_show_failure_reports_runtime_mismatch_instead_of_available(
    get: Mock, post: Mock
) -> None:
    get.return_value = _response({"version": "0.15.4"})
    failed = requests.Response()
    failed.status_code = 500
    failed._content = (
        b'{"error":"model requires Ollama 0.17.1; upgrade Ollama to continue"}'
    )
    post.return_value = failed

    result = inspect_ollama_model_compatibility("qwen3.5:9b")

    assert result["compatible"] is False
    assert result["reason"] == "runtime_outdated"
    assert result["current_version"] == "0.15.4"
    assert result["required_version"] == "0.17.1"


@patch("app.core.llm.ollama_runtime_compat.requests.post")
@patch("app.core.llm.ollama_runtime_compat.requests.get")
def test_show_failure_reports_corrupt_model_without_false_ready(
    get: Mock, post: Mock
) -> None:
    get.return_value = _response({"version": "0.17.1"})
    failed = requests.Response()
    failed.status_code = 500
    failed._content = b'{"error":"unable to load model: broken blob"}'
    post.return_value = failed

    result = inspect_ollama_model_compatibility("broken:latest")

    assert result["compatible"] is None
    assert result["reason"] == "model_load_failed"


def test_standalone_installers_block_incompatible_runtime() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    local_installer = (root / "src/local_model_installer.py").read_text(
        encoding="utf-8"
    )
    downloader = (root / "src/model_downloader.py").read_text(encoding="utf-8")
    shared_gate = (root / "src/model_install_compatibility.py").read_text(
        encoding="utf-8"
    )

    assert "reject_incompatible_model(" in local_installer
    assert "inspect_model_compatibility(tag)" in downloader
    assert "inspect_model_compatibility(tag)" in shared_gate
    assert "需要升级 Ollama" in downloader
    assert "需要升级 Ollama" in shared_gate
