from __future__ import annotations

from unittest.mock import patch

import requests
from flask import Flask

from web.routes.health import health_bp


def _health_app() -> Flask:
    app = Flask("p8-provider-degraded-startup")
    app.config["TESTING"] = True
    app.register_blueprint(health_bp)
    app.extensions["koto_blueprint_registration"] = {
        "missing_required": [],
        "missing_optional": [],
        "disabled_optional": [],
    }
    return app


def test_no_provider_keeps_startup_ready_and_reports_repairable_degradation() -> None:
    app = _health_app()
    with (
        patch(
            "app.core.llm.local_model_runtime.get_configured_model_mode",
            return_value="cloud",
        ),
        patch(
            "app.core.llm.local_model_runtime.get_configured_local_model_tag",
            return_value="",
        ),
        patch("app.core.llm.deepseek_config.get_deepseek_api_key", return_value=None),
        patch("app.core.llm.runtime_capabilities.requests.get") as network_probe,
        app.test_client() as client,
    ):
        startup = client.get("/api/startup-health")
        capabilities = client.get("/api/capabilities")
        detailed = client.get("/api/health")

    assert startup.status_code == 200
    assert startup.get_json() == {"status": "healthy"}
    assert capabilities.status_code == 200
    active = capabilities.get_json()["capabilities"]["active_model"]
    assert active["status"] == "misconfigured"
    assert active["repair_action"] == "open_model_settings"
    assert detailed.status_code == 200
    assert detailed.get_json()["status"] == "degraded"
    network_probe.assert_not_called()


def test_unreachable_selected_local_model_never_blocks_startup() -> None:
    app = _health_app()
    with (
        patch(
            "app.core.llm.local_model_runtime.get_configured_model_mode",
            return_value="local",
        ),
        patch(
            "app.core.llm.local_model_runtime.get_configured_local_model_tag",
            return_value="detached-drive:9b",
        ),
        patch("app.core.llm.deepseek_config.get_deepseek_api_key", return_value=None),
        patch(
            "app.core.llm.runtime_capabilities.requests.get",
            side_effect=requests.ConnectionError("offline"),
        ),
        app.test_client() as client,
    ):
        startup = client.get("/api/startup-health")
        refreshed = client.get("/api/capabilities?refresh=1")

    assert startup.status_code == 200
    assert startup.get_json()["status"] == "healthy"
    active = refreshed.get_json()["capabilities"]["active_model"]
    assert active["status"] == "unavailable"
    assert active["reason"] == "ollama_unreachable"
    assert active["repair_action"] == "start_or_install_ollama"
