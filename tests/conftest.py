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
from unittest import mock

import pytest

_CURRENT_PYTEST_TMP: Path | None = None


try:
    import pytest_mock  # noqa: F401
except ImportError:

    class _PatchProxy:
        def __init__(self, patchers):
            self._patchers = patchers

        def __call__(self, target, *args, **kwargs):
            patcher = mock.patch(target, *args, **kwargs)
            started = patcher.start()
            self._patchers.append(patcher)
            return started

        def object(self, target, attribute, *args, **kwargs):
            patcher = mock.patch.object(target, attribute, *args, **kwargs)
            started = patcher.start()
            self._patchers.append(patcher)
            return started

    class _MiniMocker:
        Mock = mock.Mock
        MagicMock = mock.MagicMock
        mock_open = staticmethod(mock.mock_open)

        def __init__(self):
            self._patchers = []
            self.patch = _PatchProxy(self._patchers)

        def stopall(self):
            while self._patchers:
                self._patchers.pop().stop()

    @pytest.fixture
    def mocker():
        helper = _MiniMocker()
        try:
            yield helper
        finally:
            helper.stopall()


def _load_project_api_keys() -> None:
    """Load API keys from project config when env vars are not already set."""
    try:
        from app.core.llm.gemini_config import load_gemini_config_env

        load_gemini_config_env(override=False)
    except Exception:
        # Key loading should never break the test run.
        pass


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _cleanup_test_artifacts() -> None:
    root = _root()
    for rel in (".hypothesis", ".pytest_cache_local"):
        target = root / rel
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
    if _CURRENT_PYTEST_TMP is not None and _CURRENT_PYTEST_TMP.exists():
        shutil.rmtree(_CURRENT_PYTEST_TMP, ignore_errors=True)


def pytest_configure(config):
    """Use an isolated temp dir per pytest process and pre-load real packages.

    pytest.ini sets --basetemp=.pytest_tmp. Without isolation, concurrent test
    sessions can delete each other's tmp_path roots during startup.
    """
    global _CURRENT_PYTEST_TMP

    pytest_tmp = _root() / ".pytest_tmp"
    pytest_tmp.mkdir(exist_ok=True)
    run_tmp = pytest_tmp / f"run-{os.getpid()}"
    if run_tmp.exists():
        shutil.rmtree(run_tmp, ignore_errors=True)
    _CURRENT_PYTEST_TMP = run_tmp
    config.option.basetemp = str(run_tmp)

    # Pre-import packages so that module-level _stub() calls in test files
    # (which only stub when 'name not in sys.modules') won't replace the real
    # package with a MagicMock that breaks other tests.
    for _pkg in ("docx",):
        try:
            import importlib

            importlib.import_module(_pkg)
        except ImportError:
            pass

    # Use project/user-provided API keys in tests by default.
    _load_project_api_keys()

    import os as _os

    # Prevent HuggingFace model downloads in background threads (the fallback
    # embedding path when no Google key is set).  Without these flags the
    # thread tries to pull BAAI/bge-m3 (~570 MB) from the Hub, keeping its
    # socket open and blocking coverage.py's atexit handler for 15+ minutes.
    _os.environ.setdefault("HF_HUB_OFFLINE", "1")
    _os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    _os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
    # Suppress HuggingFace tokenizer parallelism warnings in CI
    _os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


@pytest.fixture(autouse=True)
def _reset_model_fallback_executor():
    """Clear ModelFallbackExecutor singleton state before each test.

    The executor is a global singleton that accumulates unavailable-model
    timestamps and circuit-breaker counters across tests.  Left uncleaned,
    tests that mock failing LLM calls poison later tests whose LLM calls are
    expected to succeed (e.g. TestDatetimeInjection).
    """

    # Ensure keys remain available even if other modules mutate env during collection.
    _load_project_api_keys()

    try:
        import app.core.llm.model_fallback as _mf  # noqa: PLC0415

        _mf.ModelFallbackExecutor._cascade_failures.clear()
        _mf.ModelFallbackExecutor._cascade_failure_times.clear()
        if _mf._executor is not None:
            _mf._executor._unavailable.clear()
    except Exception:  # pragma: no cover — module may not be importable yet
        pass


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
    from app.api.mcp_routes import mcp_bp
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
    application.register_blueprint(mcp_bp)
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
    if os.getenv("KOTO_KEEP_TEST_ARTIFACTS", "0") != "1":
        _cleanup_test_artifacts()
    # Hard-exit to prevent background threads (JobRunner, ThreadPoolExecutor
    # workers blocked on outbound HTTP) from keeping the process alive for
    # 15+ minutes after all tests finish, causing CI timeout cancellation.
    # Coverage.xml is written by pytest-cov before this hook runs.
    import os as _os

    if os.getenv("KOTO_PYTEST_HARD_EXIT", "1") == "1":
        _os._exit(int(exitstatus))


def pytest_unconfigure(config):
    if os.getenv("KOTO_KEEP_TEST_ARTIFACTS", "0") == "1":
        return
    _cleanup_test_artifacts()


@pytest.fixture(autouse=True)
def _isolate_app_context_and_singletons():
    """Reset AppContext singletons before/after each test to prevent cross-test pollution."""
    try:
        from app.core.app_context import ctx

        ctx.reset()
    except Exception:
        pass

    try:
        from app.core.agent.checkpoint_manager import reset_checkpointer

        reset_checkpointer()
    except Exception:
        pass

    yield

    try:
        from app.core.app_context import ctx

        ctx.reset()
    except Exception:
        pass

    try:
        from app.core.agent.checkpoint_manager import reset_checkpointer

        reset_checkpointer()
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


@pytest.fixture(scope="session", autouse=True)
def _protect_user_settings():
    """Back up config/user_settings.json before the test session and restore it
    afterwards.  Integration tests that call /api/settings/reset or
    /api/skillmarket/toggle must not permanently modify the developer's
    production settings file."""
    settings_path = _root() / "config" / "user_settings.json"
    backup: bytes | None = None
    if settings_path.exists():
        try:
            backup = settings_path.read_bytes()
        except Exception:
            pass
    yield
    if backup is not None:
        try:
            settings_path.write_bytes(backup)
        except Exception:
            pass
    elif settings_path.exists():
        # File was created during the session but didn't exist before — remove it
        # only if created by tests (i.e. it existed before = backup would be set).
        pass
