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

from web.routes.health import health_bp


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


class TestModelLatencyProbe:
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
