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
                "import threading; "
                "from web.app import app, socketio; "
                "assert app.name == 'web.app'; "
                "assert socketio is not None; "
                "assert any(rule.rule == '/api/health' for rule in app.url_map.iter_rules()); "
                "names = {thread.name for thread in threading.enumerate()}; "
                "assert not names.intersection({'ProxyWarmup', 'ModelManagerInit', 'ModelManagerRefresh'})"
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


def test_web_app_exposes_chat_services_through_the_registry(monkeypatch):
    monkeypatch.setenv("KOTO_SKIP_BACKGROUND_RUNTIME", "1")
    from web import app as app_module
    from web.runtime_context import service_registry

    assert service_registry.brain is app_module.brain
    assert service_registry.session_manager is app_module.session_manager
    assert service_registry.model_map is app_module.MODEL_MAP


def test_web_app_exposes_settings_state_through_the_registry(monkeypatch):
    monkeypatch.setenv("KOTO_SKIP_BACKGROUND_RUNTIME", "1")
    from web import app as app_module
    from web.runtime_context import service_registry

    runtime = service_registry.model_runtime
    assert service_registry.settings_manager is app_module.settings_manager
    assert runtime.model_map is app_module.MODEL_MAP
    assert runtime.model_info is app_module.MODEL_INFO


def test_settings_model_runtime_has_a_safe_startup_fallback():
    from web.runtime_context import ServiceRegistry

    model_map = {"CHAT": "configured-chat-model"}
    registry = ServiceRegistry()
    registry._module = SimpleNamespace(
        MODEL_MAP=model_map,
        MODEL_INFO={},
        get_model_display_name=lambda model_id: model_id,
        _init_model_manager=lambda: None,
    )

    runtime = registry.model_runtime
    assert runtime.fallback_model == "configured-chat-model"
    assert runtime.interactions_only_models == set()


def test_web_executable_entrypoint_has_no_parallel_service_startup_chain():
    root = Path(__file__).resolve().parents[2]
    entrypoint = (root / "web" / "app_entrypoint.py").read_text(encoding="utf-8")
    runtime = (root / "web" / "app_runtime.py").read_text(encoding="utf-8")

    assert "_start_compat_background_services" not in entrypoint
    assert "def _start_managed_services" in runtime
    assert "app.core.services.clipboard_manager" in runtime
    assert "app.core.services.task_scheduler" not in runtime
    assert "app.core.services.task_queue" not in runtime
    assert "app.core.services.auto_catalog_scheduler" in runtime
