"""Unit tests for the /api/health and /api/ping endpoints."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure project root is importable
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from flask import Flask

from web.routes.health import _safe_probe_error, health_bp


@pytest.fixture()
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(health_bp)
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# /api/ping
# ---------------------------------------------------------------------------


class TestPing:
    def test_ping_returns_200(self, client):
        resp = client.get("/api/ping")
        assert resp.status_code == 200

    def test_ping_body(self, client):
        data = client.get("/api/ping").get_json()
        assert data["status"] == "ok"
        assert isinstance(data["providers"], list)
        assert isinstance(data["cloud_providers"], list)
        assert isinstance(data["ollama"], bool)
        assert data["has_any_provider"] is bool(data["providers"])

    @patch("app.core.llm.provider_factory.list_available_providers", return_value=[])
    def test_ping_never_opens_an_ollama_socket(self, list_providers, client):
        response = client.get("/api/ping")

        assert response.status_code == 200
        list_providers.assert_called_once_with(probe_local=False)


class TestModelLatencyProbe:
    def test_ollama_model_blob_failure_has_actionable_error(self):
        from requests import Response

        response = Response()
        response.status_code = 500
        response._content = b'{"error":"unable to load model: broken blob"}'

        assert _safe_probe_error(response) == "model_load_failed"

    @patch(
        "app.core.llm.ollama_runtime_compat.inspect_ollama_model_compatibility",
        return_value={
            "compatible": False,
            "current_version": "0.15.4",
            "required_version": "0.17.1",
        },
    )
    @patch(
        "app.core.llm.local_model_runtime.get_configured_local_model_tag",
        return_value="qwen3.5:9b",
    )
    def test_local_probe_reports_outdated_runtime_before_generation(
        self, _model: object, _compatibility: object
    ):
        from web.routes.health import _probe_local_model

        with patch("web.routes.health.requests.post") as generate:
            result = _probe_local_model()

        assert result["error"] == "runtime_outdated"
        assert result["current_version"] == "0.15.4"
        assert result["required_version"] == "0.17.1"
        generate.assert_not_called()

    @patch(
        "web.routes.health._probe_deepseek",
        return_value={
            "reachable": True,
            "latency_ms": 123,
            "model_id": "deepseek-chat",
        },
    )
    @patch(
        "web.routes.health._probe_local_model",
        return_value={
            "reachable": False,
            "latency_ms": None,
            "error": "service_unavailable",
            "model_id": "qwen3.5:9b",
        },
    )
    @patch(
        "app.core.llm.model_selection.get_configured_cloud_provider",
        return_value="deepseek",
    )
    @patch(
        "app.core.llm.model_selection.get_configured_cloud_model",
        return_value="deepseek-chat",
    )
    @patch(
        "app.core.llm.local_model_runtime.get_configured_local_model_tag",
        return_value="qwen3.5:9b",
    )
    @patch(
        "app.core.llm.local_model_runtime.get_configured_model_mode",
        return_value="cloud",
    )
    def test_reports_real_probe_results_and_active_cloud_state(
        self,
        _mode,
        _local_model,
        _cloud_model,
        _provider,
        _local_probe,
        _cloud_probe,
        client,
    ):
        response = client.get("/api/ping/models")

        assert response.status_code == 200
        data = response.get_json()
        assert data["active"] == {
            "mode": "cloud",
            "provider": "deepseek",
            "model_id": "deepseek-chat",
            "reachable": True,
        }
        assert data["deepseek"]["latency_ms"] == 123
        assert data["local"]["error"] == "service_unavailable"

    @patch(
        "web.routes.health._probe_deepseek",
        return_value={
            "reachable": False,
            "latency_ms": None,
            "error": "key_invalid",
            "model_id": "deepseek-chat",
        },
    )
    @patch(
        "web.routes.health._probe_local_model",
        return_value={"reachable": True, "latency_ms": 456, "model_id": "qwen3.5:9b"},
    )
    @patch(
        "app.core.llm.model_selection.get_configured_cloud_provider",
        return_value="deepseek",
    )
    @patch(
        "app.core.llm.model_selection.get_configured_cloud_model",
        return_value="deepseek-chat",
    )
    @patch(
        "app.core.llm.local_model_runtime.get_configured_local_model_tag",
        return_value="qwen3.5:9b",
    )
    @patch(
        "app.core.llm.local_model_runtime.get_configured_model_mode",
        return_value="local",
    )
    def test_active_local_state_stays_healthy_when_cloud_key_is_invalid(
        self,
        _mode,
        _local_model,
        _cloud_model,
        _provider,
        _local_probe,
        _cloud_probe,
        client,
    ):
        data = client.get("/api/ping/models").get_json()

        assert data["active"]["mode"] == "local"
        assert data["active"]["reachable"] is True
        assert data["deepseek"]["error"] == "key_invalid"


# ---------------------------------------------------------------------------
# /api/health — happy path
# ---------------------------------------------------------------------------


class TestHealthHappyPath:
    @patch("web.routes.health._check_ollama", return_value={"status": "ok"})
    @patch(
        "web.routes.health._check_disk",
        return_value={"status": "ok", "free_mb": 5000.0},
    )
    def test_returns_200(self, _disk, _ollama, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    @patch("web.routes.health._check_ollama", return_value={"status": "ok"})
    @patch(
        "web.routes.health._check_disk",
        return_value={"status": "ok", "free_mb": 5000.0},
    )
    def test_has_expected_fields(self, _disk, _ollama, client):
        data = client.get("/api/health").get_json()
        assert data["status"] == "healthy"
        assert "uptime_seconds" in data
        assert "version" in data
        assert "checks" in data
        assert "timestamp" in data
        assert "ollama" in data["checks"]
        assert "disk" in data["checks"]

    @patch("web.routes.health._check_ollama", return_value={"status": "ok"})
    @patch(
        "web.routes.health._check_disk",
        return_value={"status": "ok", "free_mb": 5000.0},
    )
    def test_version_read(self, _disk, _ollama, client):
        data = client.get("/api/health").get_json()
        # VERSION file exists in the repo; should not be "unknown"
        assert data["version"] != ""
        assert isinstance(data["version"], str)

    @patch("web.routes.health._check_ollama", return_value={"status": "ok"})
    @patch(
        "web.routes.health._check_disk",
        return_value={"status": "ok", "free_mb": 5000.0},
    )
    def test_launch_token_is_returned_only_to_owning_launcher(
        self, _disk, _ollama, client
    ):
        with patch.dict(os.environ, {"KOTO_LAUNCH_TOKEN": "attempt-token"}):
            ordinary = client.get("/api/health").get_json()
            wrong = client.get(
                "/api/health",
                headers={"X-Koto-Launch-Token": "stale-token"},
            ).get_json()
            matching = client.get(
                "/api/health",
                headers={"X-Koto-Launch-Token": "attempt-token"},
            ).get_json()

        assert "launch_token" not in ordinary
        assert "launch_token" not in wrong
        assert matching["launch_token"] == "attempt-token"


class TestStartupHealth:
    def test_is_fast_and_skips_optional_dependency_checks(self, client):
        with patch(
            "web.routes.health._check_ollama",
            side_effect=AssertionError("startup probe must not contact Ollama"),
        ), patch(
            "web.routes.health._check_disk",
            side_effect=AssertionError("startup probe must not inspect disk"),
        ):
            response = client.get("/api/startup-health")

        assert response.status_code == 200
        assert response.get_json() == {"status": "healthy"}

    def test_returns_launch_proof_only_to_owning_launcher(self, client):
        with patch.dict(os.environ, {"KOTO_LAUNCH_TOKEN": "attempt-token"}):
            matching = client.get(
                "/api/startup-health",
                headers={"X-Koto-Launch-Token": "attempt-token"},
            ).get_json()
            wrong = client.get(
                "/api/startup-health",
                headers={"X-Koto-Launch-Token": "stale-token"},
            ).get_json()

        assert matching["launch_token"] == "attempt-token"
        assert "launch_token" not in wrong


class TestCapabilities:
    @patch("app.core.llm.runtime_capabilities.refresh_model_capabilities")
    def test_default_request_is_configuration_only(self, refresh, client):
        refresh.return_value = {"mode": "cloud", "capabilities": {}}

        response = client.get("/api/capabilities")

        assert response.status_code == 200
        refresh.assert_called_once_with(probe_local=False)

    @patch("app.core.llm.runtime_capabilities.refresh_model_capabilities")
    def test_explicit_refresh_may_probe_local_runtime(self, refresh, client):
        refresh.return_value = {"mode": "local", "capabilities": {}}

        response = client.get("/api/capabilities?refresh=1")

        assert response.status_code == 200
        refresh.assert_called_once_with(probe_local=True)


# ---------------------------------------------------------------------------
# Degraded — ollama unreachable
# ---------------------------------------------------------------------------


class TestHealthDegraded:
    @patch(
        "web.routes.health._check_ollama",
        return_value={"status": "error", "detail": "connection refused"},
    )
    @patch(
        "web.routes.health._check_disk",
        return_value={"status": "ok", "free_mb": 5000.0},
    )
    def test_degraded_when_ollama_down(self, _disk, _ollama, client):
        data = client.get("/api/health").get_json()
        assert data["status"] == "degraded"
        assert data["checks"]["ollama"]["status"] == "error"

    @patch(
        "web.routes.health._check_ollama",
        return_value={"status": "error", "detail": "connection refused"},
    )
    @patch(
        "web.routes.health._check_disk",
        return_value={"status": "ok", "free_mb": 5000.0},
    )
    def test_degraded_still_returns_200(self, _disk, _ollama, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    @patch(
        "web.routes.health._check_model_runtime_configuration",
        return_value={
            "status": "warning",
            "capability_status": "misconfigured",
            "detail": "api_key_missing",
        },
    )
    @patch("web.routes.health._check_ollama", return_value={"status": "ok"})
    @patch(
        "web.routes.health._check_disk",
        return_value={"status": "ok", "free_mb": 5000.0},
    )
    def test_missing_active_model_degrades_but_does_not_fail_startup(
        self, _disk, _ollama, _model_runtime, client
    ):
        response = client.get("/api/health")

        assert response.status_code == 200
        assert response.get_json()["status"] == "degraded"


# ---------------------------------------------------------------------------
# Unhealthy — disk check fails
# ---------------------------------------------------------------------------


class TestHealthUnhealthy:
    @patch("web.routes.health._check_ollama", return_value={"status": "ok"})
    @patch(
        "web.routes.health._check_disk",
        return_value={"status": "error", "detail": "low disk"},
    )
    def test_unhealthy_when_disk_fails(self, _disk, _ollama, client):
        resp = client.get("/api/health")
        data = resp.get_json()
        assert data["status"] == "unhealthy"
        assert resp.status_code == 503
