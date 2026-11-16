"""Startup guarantees for required and optional Flask blueprints."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask

import web.app_blueprints as blueprint_registration

_ROOT = Path(__file__).resolve().parents[2]
_CORE_OWNER_TAGS = {
    "web/app_http.py": "HTTPWiring",
    "web/blueprints/auth.py": "Auth",
    "web/blueprints/chat.py": "Chat",
    "web/blueprints/editor_ai.py": "EditorAI",
    "app/api/file_hub_routes.py": "FileHubAPI",
    "web/routes/health.py": "HealthAPI",
    "web/blueprints/memory_api.py": "Memory",
    "web/blueprints/misc_api.py": "MiscAPI",
    "web/blueprints/pages.py": "Pages",
    "app/api/plugin_protocol_routes.py": "PluginProtocol",
    "web/ppt_api_routes.py": "PPTDownload",
    "app/api/response_routes.py": "ResponseAPI",
    "web/blueprints/sessions.py": "Sessions",
    "web/blueprints/settings.py": "Settings",
    "app/api/task_routes.py": "TaskAPI",
    "web/blueprints/template_api.py": "Template",
    "web/blueprints/voice.py": "VoiceBP",
    "web/blueprints/workspace.py": "Workspace",
    "web/blueprints/workspace_assistant.py": "WorkspaceAssistant",
}


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
    """Each Flask app owns its own P7 registration ledger."""
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


def test_required_blueprints_match_core_route_ownership():
    ownership = json.loads(
        (_ROOT / "config" / "route_ownership.json").read_text(encoding="utf-8")
    )
    core_owners = {
        entry["owner"]
        for entry in ownership["families"].values()
        if entry["tier"] == "core"
    }

    assert core_owners == set(_CORE_OWNER_TAGS)
    assert blueprint_registration._REQUIRED_BLUEPRINTS == frozenset(
        _CORE_OWNER_TAGS.values()
    )


def test_optional_route_features_follow_release_manifest(monkeypatch):
    app = _app(testing=False)
    monkeypatch.delenv("KOTO_OPTIONAL_FEATURES", raising=False)
    monkeypatch.setattr(blueprint_registration.sys, "frozen", True, raising=False)

    enabled = blueprint_registration._enabled_optional_features(app)
    optional = {
        spec.tag: spec.feature
        for spec in blueprint_registration._BLUEPRINT_SPECS
        if spec.feature is not None
    }

    assert enabled == set()
    assert optional == {
        "FileOrganize": "legacy-file-api",
        "GoalAPI": "goals",
        "JobAPI": "jobs",
        "RAG": "knowledge-base",
    }
    assert all(
        not blueprint_registration._spec_enabled(spec, enabled)
        for spec in blueprint_registration._BLUEPRINT_SPECS
        if spec.feature is not None
    )


def test_manifest_validation_rejects_duplicate_tags(monkeypatch):
    duplicate = blueprint_registration.BlueprintSpec(
        "example.routes", "example_bp", "Duplicate"
    )
    monkeypatch.setattr(
        blueprint_registration, "_BLUEPRINT_SPECS", (duplicate, duplicate)
    )

    with pytest.raises(RuntimeError, match="duplicate tags"):
        blueprint_registration._validate_blueprint_manifest()


def test_http_wiring_failure_aborts_release_startup(monkeypatch):
    app = _app(testing=False)

    def fail_http_wiring(*args, **kwargs):
        raise RuntimeError("simulated HTTP wiring failure")

    monkeypatch.setattr("web.app_http.configure_http_wiring", fail_http_wiring)

    with pytest.raises(
        blueprint_registration.RequiredBlueprintRegistrationError,
        match="HTTPWiring",
    ):
        blueprint_registration._register_health_and_http(app, _NullLogger())


def test_http_wiring_failure_is_unhealthy_in_development(monkeypatch):
    app = _app(testing=True)

    def fail_http_wiring(*args, **kwargs):
        raise RuntimeError("simulated HTTP wiring failure")

    monkeypatch.setattr("web.app_http.configure_http_wiring", fail_http_wiring)
    blueprint_registration._register_health_and_http(app, _NullLogger())

    state = app.extensions[blueprint_registration._BLUEPRINT_HEALTH_EXTENSION]
    assert state["missing_required"] == [
        {
            "name": "HTTPWiring",
            "module": "web.app_http",
            "reason": "simulated HTTP wiring failure",
        }
    ]


@patch("web.routes.health._check_ollama", return_value={"status": "ok"})
@patch("web.routes.health._check_disk", return_value={"status": "ok", "free_mb": 5000})
def test_required_blueprint_import_failure_is_unhealthy_in_development(
    _disk, _ollama, monkeypatch
):
    app = _app(testing=True)
    monkeypatch.setattr(
        blueprint_registration,
        "_BLUEPRINT_SPECS",
        (
            blueprint_registration.BlueprintSpec(
                "web.blueprints.editor_ai", "editor_ai_bp", "EditorAI"
            ),
        ),
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
        "_BLUEPRINT_SPECS",
        (
            blueprint_registration.BlueprintSpec(
                "web.blueprints.editor_ai", "editor_ai_bp", "EditorAI"
            ),
        ),
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
        "_BLUEPRINT_SPECS",
        (
            blueprint_registration.BlueprintSpec(
                "web.blueprints.rag_api",
                "rag_bp",
                "RAG",
                feature="knowledge-base",
            ),
        ),
    )
    _fail_module(monkeypatch, "web.blueprints.rag_api")

    blueprint_registration.register_blueprints_deferred(app, _NullLogger())

    response = app.test_client().get("/api/health")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["status"] == "degraded"
    assert payload["checks"]["blueprints"]["status"] == "warning"
    assert payload["checks"]["blueprints"]["missing_optional"] == [
        {
            "name": "RAG",
            "module": "web.blueprints.rag_api",
            "reason": "simulated missing module: web.blueprints.rag_api",
        }
    ]
