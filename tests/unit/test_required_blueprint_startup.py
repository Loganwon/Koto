"""Startup guarantees for required and optional Flask blueprints."""

from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest
from flask import Flask

import web.app_blueprints as blueprint_registration


class _NullLogger:
    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


@pytest.fixture(autouse=True)
def _isolated_blueprint_registration(monkeypatch):
    """Keep the once-per-process registration guard out of these unit tests."""
    monkeypatch.setattr(blueprint_registration, "_blueprints_registered", False)
    monkeypatch.setattr(blueprint_registration, "_PRELOAD_MODULES", ["os"])
    yield


def _app(*, testing: bool) -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = testing
    return app


def _fail_module(monkeypatch, target: str) -> None:
    real_import = importlib.import_module

    def fail_target(name: str, package: str | None = None):
        if name == target:
            raise ImportError(f"simulated missing module: {target}")
        return real_import(name, package)

    monkeypatch.setattr(blueprint_registration.importlib, "import_module", fail_target)


@patch("web.routes.health._check_ollama", return_value={"status": "ok"})
@patch("web.routes.health._check_disk", return_value={"status": "ok", "free_mb": 5000})
def test_required_blueprint_import_failure_is_unhealthy_in_development(
    _disk, _ollama, monkeypatch
):
    app = _app(testing=True)
    monkeypatch.setattr(
        blueprint_registration,
        "_WEB_BLUEPRINT_CONFIGS",
        [("web.blueprints.editor_ai", "editor_ai_bp", None, "EditorAI")],
    )
    _fail_module(monkeypatch, "web.blueprints.editor_ai")

    blueprint_registration.register_blueprints_deferred(app, _NullLogger())

    response = app.test_client().get("/api/health")
    payload = response.get_json()
    assert response.status_code == 503
    assert payload["status"] == "unhealthy"
    assert payload["checks"]["blueprints"]["status"] == "error"
    assert payload["checks"]["blueprints"]["missing_required"] == [
        {
            "name": "EditorAI",
            "module": "web.blueprints.editor_ai",
            "reason": "simulated missing module: web.blueprints.editor_ai",
        }
    ]


def test_required_blueprint_import_failure_aborts_release_startup(monkeypatch):
    app = _app(testing=False)
    monkeypatch.setattr(
        blueprint_registration,
        "_WEB_BLUEPRINT_CONFIGS",
        [("web.blueprints.editor_ai", "editor_ai_bp", None, "EditorAI")],
    )
    _fail_module(monkeypatch, "web.blueprints.editor_ai")

    with pytest.raises(blueprint_registration.RequiredBlueprintRegistrationError):
        blueprint_registration.register_blueprints_deferred(app, _NullLogger())


@patch("web.routes.health._check_ollama", return_value={"status": "ok"})
@patch("web.routes.health._check_disk", return_value={"status": "ok", "free_mb": 5000})
def test_optional_blueprint_import_failure_is_listed_as_degraded(
    _disk, _ollama, monkeypatch
):
    app = _app(testing=True)
    monkeypatch.setattr(
        blueprint_registration,
        "_WEB_BLUEPRINT_CONFIGS",
        [("web.blueprints.voice", "voice_bp", None, "VoiceBP")],
    )
    _fail_module(monkeypatch, "web.blueprints.voice")

    blueprint_registration.register_blueprints_deferred(app, _NullLogger())

    response = app.test_client().get("/api/health")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["status"] == "degraded"
    assert payload["checks"]["blueprints"]["status"] == "warning"
    assert payload["checks"]["blueprints"]["missing_optional"] == [
        {
            "name": "VoiceBP",
            "module": "web.blueprints.voice",
            "reason": "simulated missing module: web.blueprints.voice",
        }
    ]
