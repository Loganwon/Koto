#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Shared pytest fixtures for Koto test suite.
"""

from __future__ import annotations

# These files are manual/live validation scripts rather than hermetic pytest
# modules.  Several of them read local credentials or call ``sys.exit`` while
# being imported, which used to abort a repository-wide pytest collection.
# They remain directly executable through the commands documented in each
# file, but are deliberately outside the automatic test suite boundary.
collect_ignore = [
    "phase2_smoke_test.py",
    "test_annotation.py",
    "test_e2e_agent.py",
    "test_editor_pipeline.py",
    "test_full_paper_processing.py",
    "test_intelligent_analyzer.py",
    "test_model_calls_live.py",
    "test_output_modes.py",
    "test_workflows_integration.py",
]

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
        from app.core.llm.deepseek_config import load_deepseek_config_env

        load_deepseek_config_env(override=False)
    except Exception:
        # Key loading should never break the test run.
        pass


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _assert_source_mode_imports_are_unshadowed(root: Path) -> None:
    """Stop source-mode tests before stale compiled modules mask current code."""
    from src.startup_diagnostics import _source_shadowing_extensions

    artifacts = _source_shadowing_extensions(root)
    if not artifacts:
        return
    preview = ", ".join(str(path.relative_to(root)) for path in artifacts[:3])
    remainder = len(artifacts) - 3
    suffix = f" (+{remainder} more)" if remainder > 0 else ""
    raise pytest.UsageError(
        f"Found {len(artifacts)} in-place .pyd file(s) shadowing source modules: "
        f"{preview}{suffix}. Run `.venv\\Scripts\\python.exe "
        "scripts\\clean_inplace_cython_artifacts.py --apply` before pytest."
    )


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

    _assert_source_mode_imports_are_unshadowed(_root())

    pytest_tmp = _root() / ".pytest_tmp"
    pytest_tmp.mkdir(exist_ok=True)
    run_tmp = pytest_tmp / f"run-{os.getpid()}"
    if run_tmp.exists():
        shutil.rmtree(run_tmp, ignore_errors=True)
    _CURRENT_PYTEST_TMP = run_tmp
    config.option.basetemp = str(run_tmp)

    # Every mutable runtime store must stay inside this pytest process's
    # isolated root.  Tests previously wrote task summaries, ledgers and Addon
    # audit data into the real project config directory.
    runtime_state = run_tmp / "runtime-state"
    runtime_state.mkdir(parents=True, exist_ok=True)
    _os_env = os.environ
    _os_env["KOTO_DB_DIR"] = str(runtime_state)
    _os_env["KOTO_ADDON_AUDIT_DB_PATH"] = str(runtime_state / "addon_audit.sqlite")
    _os_env["KOTO_ADDON_REGISTRY_PATH"] = str(runtime_state / "addons.json")
    _os_env["KOTO_FILE_TASK_SUMMARY_PATH"] = str(
        runtime_state / "file_task_summaries.json"
    )
    _os_env["KOTO_FILE_TASK_PLAN_PATH"] = str(runtime_state / "file_task_plans.json")
    _os_env["KOTO_FILE_TASK_FOLLOWUP_PATH"] = str(
        runtime_state / "file_task_followups.json"
    )
    _os_env["KOTO_KB_CONFIG_PATH"] = str(runtime_state / "kb_config.json")
    _os_env["KOTO_CALENDAR_EVENTS_PATH"] = str(
        runtime_state / "calendar" / "events.json"
    )
    _os_env["KOTO_REMINDERS_PATH"] = str(runtime_state / "reminders" / "reminders.json")
    _os_env["KOTO_SCHEDULED_TASKS_PATH"] = str(
        runtime_state / "tasks" / "scheduled_tasks.json"
    )
    _os_env["KOTO_RATING_DB_PATH"] = str(runtime_state / "ratings.db")
    _os_env["KOTO_SHADOW_OBSERVATIONS_PATH"] = str(
        runtime_state / "shadow_observations.json"
    )
    _os_env["KOTO_FILE_INDEX_PATH"] = str(runtime_state / "file_index.json")
    _os_env["KOTO_TOKEN_USAGE_PATH"] = str(runtime_state / "token_usage.json")
    _os_env["KOTO_PROACTIVE_QUEUE_PATH"] = str(runtime_state / "proactive_queue.json")
    _os_env["KOTO_TRIGGERS_PATH"] = str(runtime_state / "triggers.json")
    _os_env["KOTO_RUNTIME_DATA_DIR"] = str(runtime_state)
    _os_env["KOTO_RAG_INDEX_DIR"] = str(runtime_state / "rag_index")
    _os_env["KOTO_FILE_NETWORK_DB_PATH"] = str(
        runtime_state / "processed_file_network.db"
    )
    _os_env["KOTO_MEMORY_PATH"] = str(runtime_state / "memory.json")
    _os_env["KOTO_USERS_FILE"] = str(runtime_state / "users.json")
    _os_env["KOTO_ACTIVATION_CODES_FILE"] = str(runtime_state / "activation_codes.json")
    _os_env["KOTO_JWT_SECRET_FILE"] = str(runtime_state / "jwt_secret.txt")
    _os_env["KOTO_WORK_FILE_LIBRARY_DB_PATH"] = str(
        runtime_state / "work_file_library.db"
    )
    _os_env["KOTO_AUDIT_DB_PATH"] = str(runtime_state / "audit.db")

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

    application = Flask(__name__)
    application.register_blueprint(job_bp)
    application.config["TESTING"] = True
    return application


@pytest.fixture(scope="session")
def client(app):
    return app.test_client()


# ── Full-app fixture (all blueprints) ────────────────────────────────────────


@pytest.fixture(scope="session")
def full_app(_koto_tmp_db):
    """Flask app with ALL blueprints registered — used by integration tests."""
    root = _root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from flask import Flask

    from app.api.file_hub_routes import file_hub_bp
    from app.api.goal_routes import goal_bp
    from app.api.job_routes import job_bp
    from app.api.mcp_routes import mcp_bp
    from app.api.ops_routes import ops_bp
    from app.api.plugin_protocol_routes import plugin_protocol_bp
    from app.api.task_routes import task_bp

    application = Flask(__name__)
    application.register_blueprint(job_bp)
    application.register_blueprint(ops_bp)
    application.register_blueprint(plugin_protocol_bp)
    application.register_blueprint(mcp_bp)
    # Blueprints without built-in url_prefix need it provided here
    application.register_blueprint(task_bp, url_prefix="/api/tasks")
    application.register_blueprint(goal_bp, url_prefix="/api/goals")
    application.register_blueprint(file_hub_bp, url_prefix="/api/files")
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
def _isolate_process_singletons():
    """Reset stateful service owners around every test."""

    def _reset() -> None:
        resetters = (
            ("app.core.agent.checkpoint_manager", "reset_checkpointer"),
            ("app.core.agent.kernel_agent_service", "reset_kernel_agent_for_tests"),
            ("app.core.config.configuration_manager", "reset_config_manager_for_tests"),
            (
                "app.core.services.auto_catalog_scheduler",
                "reset_auto_catalog_scheduler_for_tests",
            ),
            ("app.core.services.file_rag_indexer", "reset_file_rag_indexers_for_tests"),
            ("app.core.services.knowledge_base", "reset_knowledge_base_for_tests"),
            ("app.core.services.memory_manager", "reset_memory_manager_for_tests"),
            ("app.core.services.rag_service", "reset_rag_service_cache_for_tests"),
            ("web.session_manager", "reset_session_runtime_for_tests"),
        )
        for module_name, function_name in resetters:
            try:
                module = __import__(module_name, fromlist=[function_name])
                getattr(module, function_name)()
            except Exception:
                pass

    _reset()

    yield
    _reset()


@pytest.fixture(autouse=True)
def _isolate_shadow_watcher(monkeypatch, tmp_path):
    """Isolate ShadowWatcher singleton and file path in each test."""
    try:
        from app.core.monitoring import shadow_watcher

        shadow_watcher.ShadowWatcher._instance = None
        monkeypatch.setattr(shadow_watcher, "_OBS_FILE", tmp_path / "shadow_obs.json")
    except Exception:
        pass


@pytest.fixture(scope="session", autouse=True)
def _protect_user_settings():
    """Protect the primary settings file and its recovery backup."""
    settings_path = _root() / "config" / "user_settings.json"
    protected_paths = (
        settings_path,
        settings_path.with_name(f"{settings_path.name}.bak"),
    )
    snapshots: dict[Path, bytes | None] = {}
    for path in protected_paths:
        try:
            snapshots[path] = path.read_bytes() if path.exists() else None
        except Exception:
            snapshots[path] = None
    yield
    for path, snapshot in snapshots.items():
        try:
            if snapshot is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(snapshot)
        except Exception:
            pass
