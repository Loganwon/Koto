#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Shared pytest fixtures for Koto test suite.
"""

from __future__ import annotations

# phase2_smoke_test.py is a standalone script (calls sys.exit at module level)
# and must not be collected by pytest.
collect_ignore = ["phase2_smoke_test.py"]

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _cleanup_test_artifacts() -> None:
    root = _root()
    for rel in (".hypothesis", ".pytest_tmp", ".pytest_cache_local"):
        target = root / rel
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)


@pytest.fixture(scope="session")
def _koto_tmp_db(tmp_path_factory):
    """Isolated temp DB dir for the whole session."""
    tmpdir = str(tmp_path_factory.mktemp("koto_db"))
    os.environ["KOTO_DB_DIR"] = tmpdir
    return tmpdir


@pytest.fixture(scope="session")
def app(_koto_tmp_db):
    root = _root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from flask import Flask

    from app.api.job_routes import job_bp
    from app.api.skill_routes import skill_bp

    application = Flask(__name__)
    application.register_blueprint(skill_bp)
    application.register_blueprint(job_bp)
    application.config["TESTING"] = True
    return application


@pytest.fixture(scope="session")
def client(app):
    return app.test_client()


@pytest.fixture(scope="session")
def binding_id(client):
    """Create a test intent binding and return its ID for dependent tests."""
    resp = client.post(
        "/api/skills/concise_mode/bindings/intent",
        json={"patterns": ["测试极简", "最短回答"], "auto_disable_after_turns": 1},
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    data = resp.get_json()
    return data["binding"]["binding_id"]


# ── Full-app fixture (all blueprints) ────────────────────────────────────────


@pytest.fixture(scope="session")
def full_app(_koto_tmp_db):
    """Flask app with ALL blueprints registered — used by integration tests."""
    root = _root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from flask import Flask

    from app.api.agent_routes import agent_bp
    from app.api.file_hub_routes import file_hub_bp
    from app.api.goal_routes import goal_bp
    from app.api.job_routes import job_bp
    from app.api.macro_routes import macro_bp
    from app.api.ops_routes import ops_bp
    from app.api.shadow_routes import shadow_bp
    from app.api.skill_marketplace_routes import marketplace_bp
    from app.api.skill_routes import skill_bp
    from app.api.task_routes import task_bp

    application = Flask(__name__)
    application.register_blueprint(skill_bp)
    application.register_blueprint(job_bp)
    application.register_blueprint(ops_bp)
    application.register_blueprint(marketplace_bp)
    application.register_blueprint(macro_bp)
    application.register_blueprint(shadow_bp)
    # Blueprints without built-in url_prefix need it provided here
    application.register_blueprint(task_bp, url_prefix="/api/tasks")
    application.register_blueprint(goal_bp, url_prefix="/api/goals")
    application.register_blueprint(file_hub_bp, url_prefix="/api/files")
    application.register_blueprint(agent_bp, url_prefix="/api/agent")
    application.config["TESTING"] = True
    return application


@pytest.fixture(scope="session")
def full_client(full_app):
    """Test client for the full-app fixture."""
    return full_app.test_client()


@pytest.fixture
def mock_llm_provider():
    """A minimal in-process LLMProvider stub that never calls a real LLM."""
    from app.core.llm.base import LLMProvider

    class _StubProvider(LLMProvider):
        def generate_content(self, prompt, model, **kwargs):
            return {"content": "stub response", "model": model}

        def get_token_count(self, prompt, model):
            return 1

    return _StubProvider()


@pytest.fixture
def tmp_workspace(tmp_path):
    """A temporary directory pre-configured as KOTO_WORKSPACE."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    os.environ["KOTO_WORKSPACE"] = str(ws)
    yield ws
    os.environ.pop("KOTO_WORKSPACE", None)


def pytest_sessionfinish(session, exitstatus):
    if os.getenv("KOTO_KEEP_TEST_ARTIFACTS", "0") == "1":
        return
    _cleanup_test_artifacts()


def pytest_unconfigure(config):
    if os.getenv("KOTO_KEEP_TEST_ARTIFACTS", "0") == "1":
        return
    _cleanup_test_artifacts()


@pytest.fixture(autouse=True)
def _mock_vosk_teardown(monkeypatch):
    """Prevents vosk segfaults in pytest by mocking out vosk Model if not strictly needed."""
    try:
        import vosk

        def dummy_del(self):
            pass

        if hasattr(vosk.Model, "__del__"):
            monkeypatch.setattr(vosk.Model, "__del__", dummy_del, raising=False)
        if hasattr(vosk.Recognizer, "__del__"):
            monkeypatch.setattr(vosk.Recognizer, "__del__", dummy_del, raising=False)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _isolate_app_context_and_singletons():
    """Reset AppContext singletons before/after each test to prevent cross-test pollution."""
    try:
        from app.core.app_context import ctx

        ctx.reset()
    except Exception:
        pass

    yield

    try:
        from app.core.app_context import ctx

        ctx.reset()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _isolate_shadow_watcher(monkeypatch, tmp_path):
    """Isolate ShadowWatcher singleton and file path in each test."""
    try:
        from app.core.learning.shadow_tracer import ShadowWatcher

        ShadowWatcher._instance = None
        monkeypatch.setattr(
            ShadowWatcher, "_OBS_FILE", str(tmp_path / "shadow_obs.json")
        )
    except Exception:
        pass
