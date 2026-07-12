"""Regression checks for the desktop server's Flask application contract."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


def test_web_app_exports_flask_application_for_desktop_launcher(monkeypatch):
    """``src.server`` must always be able to import ``web.app.app``."""
    monkeypatch.setenv("KOTO_AUTH_ENABLED", "false")
    monkeypatch.setenv("KOTO_DEPLOY_MODE", "local")
    monkeypatch.setenv("KOTO_SKIP_BACKGROUND_RUNTIME", "1")

    project_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from web.app import app, socketio; "
                "assert app.name == 'web.app'; "
                "assert socketio is not None; "
                "assert any(rule.rule == '/api/health' for rule in app.url_map.iter_rules())"
            ),
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_runtime_context_reads_replaced_brain_instance():
    """Request handlers must not retain a stale brain after a runtime swap."""
    from web.runtime_context import ServiceRegistry

    first = object()
    module = SimpleNamespace(brain=first)
    registry = ServiceRegistry()
    registry._module = module

    assert registry.brain is first
    replacement = object()
    module.brain = replacement
    assert registry.brain is replacement


def test_web_app_configures_chat_runtime_services(monkeypatch):
    monkeypatch.setenv("KOTO_SKIP_BACKGROUND_RUNTIME", "1")
    from web import app as app_module
    from web.chat_runtime_services import get_brain, get_model_map, get_session_manager

    assert get_brain() is app_module.brain
    assert get_session_manager() is app_module.session_manager
    assert get_model_map() is app_module.MODEL_MAP


def test_web_app_configures_settings_runtime_services(monkeypatch):
    monkeypatch.setenv("KOTO_SKIP_BACKGROUND_RUNTIME", "1")
    from web import app as app_module
    from web.settings_runtime_services import get_model_runtime, get_settings_manager

    runtime = get_model_runtime()
    assert get_settings_manager() is app_module.settings_manager
    assert runtime.model_map is app_module.MODEL_MAP
    assert runtime.model_info is app_module.MODEL_INFO


def test_web_executable_entrypoint_uses_canonical_compat_service_imports():
    source = (Path(__file__).resolve().parents[2] / "web" / "app_entrypoint.py").read_text(
        encoding="utf-8"
    )

    assert "def _start_compat_background_services" in source
    assert "_start_compat_background_services()" in source
    assert "from app.core.services.clipboard_manager import get_clipboard_manager" in source
    assert "from web.task_scheduler import get_task_scheduler" in source
    assert "from web.task_queue import task_queue" in source
    assert "from web.auto_catalog_scheduler import get_auto_catalog_scheduler" in source
    assert "from clipboard_manager import" not in source
    assert "from task_scheduler import" not in source
