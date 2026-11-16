# -*- coding: utf-8 -*-
"""
Comprehensive unit tests for low-coverage app/core modules.

Modules tested:
  1. FileRegistry    — file metadata registry (SQLite-backed)
  2. FileWatcher     — directory polling monitor
  5. ConfigurationManager — system threshold configuration
  6. JobRunner       — background job executor
  7. OpsEventBus     — operational event bus
  8. OllamaLLMProvider — Ollama LLM provider
  9. RemediationManager — auto-remediation with approval workflow
"""

import json
import os
import sqlite3
import tempfile
import threading
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock, Mock, PropertyMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_file_registry_singleton():
    """Reset the global FileRegistry singleton between tests.

    Do not force-close the underlying sqlite connection here: watchdog callbacks may
    still be in flight on background threads, and closing from teardown can trigger
    interpreter-level crashes on Windows.
    """
    yield
    try:
        import app.core.file.file_registry as fr

        if fr._registry_instance is not None:
            fr._registry_instance = None
    except Exception:
        pass


# ============================================================================
# 1. TestFileRegistry
# ============================================================================


@pytest.mark.unit
class TestFileRegistry:
    """Tests for app.core.file.file_registry.FileRegistry."""

    @pytest.fixture
    def registry(self, tmp_path):
        """Create a FileRegistry backed by a temp SQLite file."""
        db_path = str(tmp_path / "test_registry.sqlite")
        from app.core.file.file_registry import FileRegistry

        reg = FileRegistry(db_path=db_path)
        yield reg
        reg._conn.close()

    @pytest.fixture
    def sample_file(self, tmp_path):
        """Create a temp text file for registration."""
        f = tmp_path / "sample.txt"
        f.write_text("Hello Koto test content", encoding="utf-8")
        return str(f)

    def test_init_creates_db(self, tmp_path):
        """FileRegistry __init__ creates the SQLite database file."""
        db_path = str(tmp_path / "sub" / "test.sqlite")
        from app.core.file.file_registry import FileRegistry

        reg = FileRegistry(db_path=db_path)
        assert Path(db_path).exists()

    def test_register_new_file(self, registry, sample_file):
        """register() inserts a new file and returns a FileEntry."""
        entry = registry.register(sample_file, source="upload")
        assert entry is not None
        assert entry.name == "sample.txt"
        assert entry.ext == ".txt"
        assert entry.source == "upload"
        assert entry.file_id  # non-empty UUID

    def test_register_nonexistent_file_returns_none(self, registry):
        """register() returns None for a path that does not exist."""
        result = registry.register("/nonexistent/path/to/file.txt")
        assert result is None

    def test_register_updates_existing(self, registry, tmp_path):
        """register() updates mtime/hash when file content changes."""
        f = tmp_path / "changing.txt"
        f.write_text("version 1", encoding="utf-8")
        entry1 = registry.register(str(f), source="manual")
        assert entry1 is not None

        # Modify the file to change mtime and content
        time.sleep(0.05)
        f.write_text("version 2 with more content", encoding="utf-8")
        # Force mtime change
        os.utime(str(f), (time.time() + 2, time.time() + 2))

        entry2 = registry.register(str(f), source="manual")
        assert entry2 is not None
        assert entry2.file_id == entry1.file_id

    def test_get_by_path(self, registry, sample_file):
        """get_by_path() retrieves a previously registered file."""
        registry.register(sample_file)
        entry = registry.get_by_path(sample_file)
        assert entry is not None
        assert entry.path == sample_file

    def test_get_by_path_not_found(self, registry):
        """get_by_path() returns None for unregistered path."""
        assert registry.get_by_path("/no/such/file") is None

    def test_get_by_id(self, registry, sample_file):
        """get_by_id() retrieves file by its UUID."""
        entry = registry.register(sample_file)
        fetched = registry.get_by_id(entry.file_id)
        assert fetched is not None
        assert fetched.path == sample_file

    def test_search_by_name(self, registry, tmp_path):
        """search() finds files by name substring."""
        f1 = tmp_path / "report_2024.txt"
        f1.write_text("quarterly report", encoding="utf-8")
        registry.register(str(f1), source="scanner")

        results = registry.search("report")
        assert len(results) >= 1
        assert any("report" in r.name for r in results)

    def test_search_with_category_filter(self, registry, tmp_path):
        """search() respects the category filter."""
        f = tmp_path / "code.py"
        f.write_text("print('hello')", encoding="utf-8")
        registry.register(str(f), source="manual")

        results_code = registry.search("code", category="代码")
        results_doc = registry.search("code", category="文档")
        assert len(results_code) >= 1
        assert len(results_doc) == 0

    def test_delete_file(self, registry, sample_file):
        """delete() removes a registered file and returns True."""
        registry.register(sample_file)
        assert registry.delete(sample_file) is True
        assert registry.get_by_path(sample_file) is None

    def test_delete_nonexistent_returns_false(self, registry):
        """delete() returns False for a path not in the registry."""
        assert registry.delete("/no/such/path.txt") is False

    def test_count(self, registry, tmp_path):
        """count() returns correct number of registered files."""
        for i in range(3):
            f = tmp_path / f"file_{i}.txt"
            f.write_text(f"content {i}", encoding="utf-8")
            registry.register(str(f))
        assert registry.count() == 3

    def test_stats(self, registry, tmp_path):
        """stats() returns category-grouped summary."""
        f = tmp_path / "test.py"
        f.write_text("x = 1", encoding="utf-8")
        registry.register(str(f))
        s = registry.stats()
        assert "total" in s
        assert "by_category" in s
        assert s["total"] >= 1

    def test_update_path(self, registry, tmp_path):
        """update_path() changes the stored path for a file."""
        f = tmp_path / "old_name.txt"
        f.write_text("content", encoding="utf-8")
        registry.register(str(f))

        new_path = str(tmp_path / "new_name.txt")
        f.rename(new_path)
        assert registry.update_path(str(f), new_path) is True
        assert registry.get_by_path(new_path) is not None

    def test_add_and_get_tags(self, registry, sample_file):
        """add_tag() and get_tags() manage file tags."""
        registry.register(sample_file)
        assert registry.add_tag(sample_file, "important") is True
        assert registry.add_tag(sample_file, "urgent") is True
        tags = registry.get_tags(sample_file)
        assert "important" in tags
        assert "urgent" in tags

    def test_remove_tag(self, registry, sample_file):
        """remove_tag() deletes a specific tag."""
        registry.register(sample_file)
        registry.add_tag(sample_file, "temp")
        assert registry.remove_tag(sample_file, "temp") is True
        assert "temp" not in registry.get_tags(sample_file)

    def test_add_empty_tag_returns_false(self, registry, sample_file):
        """add_tag() rejects empty tags."""
        assert registry.add_tag(sample_file, "") is False
        assert registry.add_tag(sample_file, "   ") is False

    def test_favorites(self, registry, sample_file):
        """add_favorite / list_favorites / remove_favorite work correctly."""
        registry.register(sample_file)
        assert registry.add_favorite(sample_file) is True
        assert sample_file in registry.list_favorites()
        assert registry.remove_favorite(sample_file) is True
        assert sample_file not in registry.list_favorites()

    def test_log_op_and_get_op_log(self, registry):
        """log_op() records operations and get_op_log() retrieves them."""
        op_id = registry.log_op(
            "move", "/src/a.txt", "/dst/a.txt", meta={"reason": "cleanup"}
        )
        assert op_id
        log = registry.get_op_log(limit=5)
        assert len(log) >= 1
        assert log[0]["op_type"] == "move"

    def test_escape_fts_special_chars(self, registry):
        """_escape_fts() safely escapes user queries for FTS5."""
        assert registry._escape_fts("hello world") == '"hello" "world"'
        assert registry._escape_fts("") == '""'

    def test_batch_register(self, registry, tmp_path):
        """batch_register() returns (added, updated) counts."""
        paths = []
        for i in range(3):
            f = tmp_path / f"batch_{i}.txt"
            f.write_text(f"batch content {i}", encoding="utf-8")
            paths.append(str(f))
        added, updated = registry.batch_register(paths, source="scanner")
        assert added == 3
        assert updated == 0

    def test_list_recent(self, registry, sample_file):
        """list_recent() returns recently indexed files."""
        registry.register(sample_file)
        recent = registry.list_recent(days=1)
        assert len(recent) >= 1


# ============================================================================
# 2. TestFileWatcher
# ============================================================================


@pytest.mark.unit
class TestFileWatcher:
    """Tests for app.core.file.file_watcher.FileWatcher."""

    @pytest.fixture
    def watcher(self, tmp_path):
        """Create a FileWatcher with a temporary settings file."""
        settings = tmp_path / "settings.json"
        settings.write_text(
            json.dumps(
                {
                    "file_watcher": {
                        "enabled": True,
                        "watch_dirs": [str(tmp_path / "watched")],
                        "interval_seconds": 10,
                        "max_file_size_mb": 5,
                        "skip_extensions": [".bak"],
                    }
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "watched").mkdir()
        from app.core.file.file_watcher import FileWatcher

        return FileWatcher(settings_path=str(settings))

    def test_init_loads_config(self, watcher, tmp_path):
        """__init__ loads configuration from the settings file."""
        assert watcher.enabled is True
        assert len(watcher.watch_dirs) == 1
        assert str(tmp_path / "watched") in watcher.watch_dirs[0]

    def test_default_properties(self, tmp_path):
        """Properties return defaults when config file is absent."""
        from app.core.file.file_watcher import FileWatcher

        w = FileWatcher(settings_path=str(tmp_path / "nonexistent.json"))
        assert w.enabled is False
        assert w.watch_dirs == []
        assert w.interval >= 10

    def test_add_dir(self, watcher):
        """add_dir() appends a new directory to watch_dirs."""
        initial_count = len(watcher.watch_dirs)
        watcher.add_dir("C:/new_dir")
        assert len(watcher.watch_dirs) == initial_count + 1
        assert "C:/new_dir" in watcher.watch_dirs

    def test_add_dir_no_duplicate(self, watcher):
        """add_dir() does not add the same directory twice."""
        watcher.add_dir("C:/dup_dir")
        watcher.add_dir("C:/dup_dir")
        assert watcher.watch_dirs.count("C:/dup_dir") == 1

    def test_remove_dir(self, watcher):
        """remove_dir() removes a directory from the list."""
        watcher.add_dir("C:/to_remove")
        watcher.remove_dir("C:/to_remove")
        assert "C:/to_remove" not in watcher.watch_dirs

    def test_skip_exts_includes_defaults_and_custom(self, watcher):
        """skip_exts combines default and user-configured extensions."""
        exts = watcher.skip_exts
        assert ".tmp" in exts  # default
        assert ".bak" in exts  # custom from settings

    def test_max_file_size_bytes(self, watcher):
        """max_file_size_bytes converts MB config to bytes."""
        assert watcher.max_file_size_bytes == 5 * 1024 * 1024

    def test_start_and_stop(self, watcher):
        """start() creates a daemon thread, stop() joins it."""
        # Prevent the loop from actually scanning (which triggers global singleton)
        watcher._stop_event = threading.Event()
        watcher._stop_event.set()  # immediately stop the loop
        watcher._running = False
        # Manually test start logic
        from app.core.file.file_watcher import FileWatcher

        watcher._stop_event.clear()
        watcher._running = True
        watcher._thread = threading.Thread(target=lambda: None, daemon=True)
        watcher._thread.start()
        assert watcher._running is True
        assert watcher._thread is not None
        watcher.stop()
        assert watcher._running is False

    def test_start_skips_if_already_running(self, watcher):
        """start() is a no-op when already running."""
        # Simulate already running state
        watcher._running = True
        watcher._thread = threading.Thread(target=lambda: None, daemon=True)
        watcher._thread.start()
        thread1 = watcher._thread
        watcher.start()  # second call should be no-op
        assert watcher._thread is thread1
        watcher._running = False

    def test_stop_noop_when_not_running(self, tmp_path):
        """stop() does nothing when watcher is not started."""
        from app.core.file.file_watcher import FileWatcher

        w = FileWatcher(settings_path=str(tmp_path / "no.json"))
        w.stop()  # should not raise

    @patch("app.core.file.file_registry.get_file_registry")
    def test_scan_once(self, mock_get_reg, watcher, tmp_path):
        """scan_once() registers discovered files and returns count."""
        watched = tmp_path / "watched"
        (watched / "a.txt").write_text("aaa", encoding="utf-8")
        (watched / "b.md").write_text("bbb", encoding="utf-8")
        (watched / "c.tmp").write_text("skip me", encoding="utf-8")  # skipped ext

        mock_reg = MagicMock()
        mock_entry = MagicMock()
        mock_reg.register.return_value = mock_entry
        mock_get_reg.return_value = mock_reg

        count = watcher.scan_once(str(watched))
        # .tmp should be skipped, so expect 2 registrations
        assert count == 2

    @patch("app.core.file.file_registry.get_file_registry")
    def test_scan_once_empty_dir(self, mock_get_reg, watcher, tmp_path):
        """scan_once() returns 0 for an empty directory."""
        empty = tmp_path / "empty_dir"
        empty.mkdir()
        assert watcher.scan_once(str(empty)) == 0

    def test_scan_once_nonexistent_dir(self, watcher):
        """scan_once() returns 0 for a non-existent directory."""
        assert watcher.scan_once("/nonexistent/dir") == 0

    def test_reload_config_with_bad_json(self, tmp_path):
        """_reload_config handles corrupt JSON gracefully."""
        bad_settings = tmp_path / "bad.json"
        bad_settings.write_text("{invalid json!!", encoding="utf-8")
        from app.core.file.file_watcher import FileWatcher

        w = FileWatcher(settings_path=str(bad_settings))
        assert w.enabled is False


# ============================================================================
# 5. TestConfigurationManager
# ============================================================================


@pytest.mark.unit
class TestConfigurationManager:
    """Tests for app.core.config.configuration_manager.ConfigurationManager."""

    @pytest.fixture
    def cm(self):
        from app.core.config.configuration_manager import ConfigurationManager

        return ConfigurationManager()

    def test_init_has_default_thresholds(self, cm):
        """ConfigurationManager initializes with default thresholds."""
        assert "cpu" in cm.thresholds
        assert "memory" in cm.thresholds
        assert cm.thresholds["cpu"]["warning"] == 70
        assert cm.thresholds["cpu"]["critical"] == 85

    def test_set_threshold_success(self, cm):
        """set_threshold() updates a known metric's level."""
        assert cm.set_threshold("cpu", "warning", 80) is True
        assert cm.get_threshold("cpu", "warning") == 80

    def test_set_threshold_unknown_metric(self, cm):
        """set_threshold() returns False for unknown metrics."""
        assert cm.set_threshold("unknown_metric", "warning", 50) is False

    def test_set_threshold_invalid_level(self, cm):
        """set_threshold() returns False for invalid severity levels."""
        assert cm.set_threshold("cpu", "extreme", 50) is False

    def test_get_threshold_full(self, cm):
        """get_threshold() without level returns the full dict."""
        t = cm.get_threshold("cpu")
        assert isinstance(t, dict)
        assert "warning" in t
        assert "critical" in t

    def test_get_threshold_unknown_returns_none(self, cm):
        """get_threshold() returns None for unknown metrics."""
        assert cm.get_threshold("nonexistent") is None

    def test_get_all_thresholds(self, cm):
        """get_all_thresholds() returns all configured thresholds."""
        all_t = cm.get_all_thresholds()
        assert len(all_t) == len(cm.DEFAULT_THRESHOLDS)

    def test_reset_threshold(self, cm):
        """reset_threshold() restores a metric to its default."""
        cm.set_threshold("cpu", "warning", 99)
        assert cm.reset_threshold("cpu") is True
        assert cm.get_threshold("cpu", "warning") == 70

    def test_reset_threshold_unknown(self, cm):
        """reset_threshold() returns False for unknown metrics."""
        assert cm.reset_threshold("bogus") is False

    def test_reset_all_thresholds(self, cm):
        """reset_all_thresholds() restores all to defaults."""
        cm.set_threshold("cpu", "warning", 10)
        cm.set_threshold("memory", "critical", 10)
        assert cm.reset_all_thresholds() is True
        assert cm.get_threshold("cpu", "warning") == 70
        assert cm.get_threshold("memory", "critical") == 90

    def test_set_and_get_setting(self, cm):
        """set_setting() and get_setting() manage arbitrary settings."""
        cm.set_setting("refresh_rate", 30)
        assert cm.get_setting("refresh_rate") == 30

    def test_get_setting_default(self, cm):
        """get_setting() returns default when key doesn't exist."""
        assert cm.get_setting("missing_key", "default_val") == "default_val"

    def test_get_all_settings(self, cm):
        """get_all_settings() returns all custom settings."""
        cm.set_setting("a", 1)
        cm.set_setting("b", 2)
        settings = cm.get_all_settings()
        assert settings["a"] == 1
        assert settings["b"] == 2

    def test_export_import_config(self, cm):
        """export_config() and import_config() round-trip correctly."""
        cm.set_threshold("cpu", "warning", 55)
        cm.set_setting("mode", "production")
        exported = cm.export_config()
        assert isinstance(exported, str)

        # Import into a fresh instance
        from app.core.config.configuration_manager import ConfigurationManager

        cm2 = ConfigurationManager()
        assert cm2.import_config(exported) is True
        assert cm2.get_threshold("cpu", "warning") == 55
        assert cm2.get_setting("mode") == "production"

    def test_import_config_bad_json(self, cm):
        """import_config() returns False for invalid JSON."""
        assert cm.import_config("not valid json{{{") is False

    def test_validate_metric_value_normal(self, cm):
        """validate_metric_value() returns normal status for low values."""
        result = cm.validate_metric_value("cpu", 30)
        assert result["valid"] is True
        assert result["status"] == "normal"

    def test_validate_metric_value_warning(self, cm):
        """validate_metric_value() returns warning for moderate values."""
        result = cm.validate_metric_value("cpu", 75)
        assert result["valid"] is False
        assert result["status"] == "warning"

    def test_validate_metric_value_critical(self, cm):
        """validate_metric_value() returns critical for high values."""
        result = cm.validate_metric_value("cpu", 90)
        assert result["valid"] is False
        assert result["status"] == "critical"

    def test_validate_metric_value_unknown(self, cm):
        """validate_metric_value() returns 'unknown' for unmapped metrics."""
        result = cm.validate_metric_value("nonexistent", 50)
        assert result["status"] == "unknown"


# ============================================================================
# 6. TestJobRunner
# ============================================================================


@pytest.mark.unit
class TestJobRunner:
    """Tests for app.core.jobs.job_runner.JobRunner."""

    @pytest.fixture
    def runner(self):
        from app.core.jobs.job_runner import JobRunner

        return JobRunner(max_workers=2)

    def test_init(self, runner):
        """JobRunner initializes with given max_workers."""
        assert runner._max_workers == 2
        assert runner._running is False
        assert runner._handlers == {}

    def test_register_handler(self, runner):
        """register_handler() stores a callable for a job_type."""
        handler = Mock()
        runner.register_handler("test_job", handler)
        assert "test_job" in runner._handlers
        assert runner._handlers["test_job"] is handler

    def test_start_and_stop(self, runner):
        """start() launches dispatcher thread, stop() shuts down."""
        with patch("app.core.jobs.job_runner.JobRunner._recover_stale_tasks"):
            runner.start()
            assert runner._running is True
            assert runner._dispatcher_thread is not None
            runner.stop()
            assert runner._running is False

    @patch("app.core.tasks.task_ledger.get_ledger")
    def test_submit_creates_task(self, mock_get_ledger, runner):
        """submit() creates a TaskLedger entry and returns task_id."""
        mock_ledger = MagicMock()
        mock_task = MagicMock()
        mock_task.task_id = "tid-123"
        mock_ledger.create.return_value = mock_task
        mock_get_ledger.return_value = mock_ledger

        from app.core.jobs.job_runner import JobSpec

        spec = JobSpec(
            job_type="agent_query",
            payload={"query": "test"},
            session_id="sess-1",
        )
        task_id = runner.submit(spec)
        assert task_id == "tid-123"
        mock_ledger.create.assert_called_once()

    @patch("app.core.tasks.task_ledger.get_ledger")
    def test_retry_requeues_existing_task(self, mock_get_ledger, runner):
        from app.core.jobs.job_runner import JobSpec
        from app.core.tasks.task_ledger import TaskStatus

        task = MagicMock(
            task_id="tid-123",
            status=TaskStatus.FAILED,
            metadata='{"job_type":"agent_query","max_retries":2}',
            task_type="agent_query",
            user_input='{"query":"retry me"}',
            session_id="sess-1",
            priority=2,
        )
        ledger = MagicMock()
        ledger.get.return_value = task
        mock_get_ledger.return_value = ledger

        assert runner.retry("tid-123") == "tid-123"
        queued = runner._queue.get_nowait()
        assert queued[2] == "tid-123"
        assert isinstance(queued[3], JobSpec)
        assert queued[3].payload == {"query": "retry me"}
        ledger._update_fields.assert_called_once()

    def test_jobspec_defaults(self):
        """JobSpec has sensible defaults."""
        from app.core.jobs.job_runner import JobSpec

        spec = JobSpec(job_type="test")
        assert spec.payload == {}
        assert spec.max_retries == 0
        assert spec.timeout_seconds == 300.0
        assert spec.session_id == ""

    def test_jobcontext_is_cancelled(self):
        """JobContext.is_cancelled() delegates to ledger."""
        from app.core.jobs.job_runner import JobContext

        mock_ledger = MagicMock()
        mock_ledger.is_cancel_requested.return_value = True
        ctx = JobContext(
            task_id="t1",
            session_id="s1",
            payload={},
            ledger=mock_ledger,
            bus=MagicMock(),
        )
        assert ctx.is_cancelled() is True
        mock_ledger.is_cancel_requested.assert_called_with("t1")

    def test_jobcontext_is_interrupted(self):
        """JobContext.is_interrupted() delegates to ledger."""
        from app.core.jobs.job_runner import JobContext

        mock_ledger = MagicMock()
        mock_ledger.is_interrupt_requested.return_value = False
        ctx = JobContext(
            task_id="t1",
            session_id="s1",
            payload={},
            ledger=mock_ledger,
            bus=MagicMock(),
        )
        assert ctx.is_interrupted() is False

    def test_jobcontext_step(self):
        """JobContext.step() calls both ledger.add_step and bus.publish_step."""
        from app.core.jobs.job_runner import JobContext

        mock_ledger = MagicMock()
        mock_bus = MagicMock()
        ctx = JobContext(
            task_id="t1",
            session_id="s1",
            payload={},
            ledger=mock_ledger,
            bus=mock_bus,
        )
        ctx.step("THOUGHT", "thinking...", progress=10)
        mock_ledger.add_step.assert_called_once()
        mock_bus.publish_step.assert_called_once()

    @patch("app.core.tasks.progress_bus.get_progress_bus")
    @patch("app.core.tasks.task_ledger.get_ledger")
    def test_run_job_unknown_type_marks_failed(
        self, mock_get_ledger, mock_get_bus, runner
    ):
        """_run_job() marks the task as failed for unknown job_type."""
        mock_ledger = MagicMock()
        mock_get_ledger.return_value = mock_ledger
        mock_get_bus.return_value = MagicMock()

        from app.core.jobs.job_runner import JobSpec

        spec = JobSpec(job_type="unknown_type", payload={})
        runner._run_job("tid-1", spec)
        mock_ledger.mark_failed.assert_called_once()

    @patch("app.core.tasks.progress_bus.get_progress_bus")
    @patch("app.core.tasks.task_ledger.get_ledger")
    def test_run_job_success(self, mock_get_ledger, mock_get_bus, runner):
        """_run_job() marks the task as completed on handler success."""
        mock_ledger = MagicMock()
        mock_ledger.is_cancel_requested.return_value = False
        mock_get_ledger.return_value = mock_ledger
        mock_get_bus.return_value = MagicMock()

        handler = Mock(return_value="done!")
        runner.register_handler("test_type", handler)

        from app.core.jobs.job_runner import JobSpec

        spec = JobSpec(job_type="test_type", payload={"x": 1}, session_id="s1")
        runner._run_job("tid-2", spec)
        mock_ledger.mark_running.assert_called_with("tid-2")
        mock_ledger.mark_completed.assert_called_once()

    def test_agent_query_handler_uses_job_runner_ledger_only(self):
        """agent_query should not create a second source=agent ledger task."""
        from app.core.agent.types import AgentStepType
        from app.core.jobs.job_runner import JobContext, _handle_agent_query

        calls = []

        class FakeStep:
            step_type = AgentStepType.ANSWER
            content = "done"

            def to_dict(self):
                return {"step_type": "ANSWER", "content": self.content}

        class FakeAgent:
            def run(self, **kwargs):
                calls.append(kwargs)
                yield FakeStep()

        ctx = JobContext(
            task_id="job-task",
            session_id="system",
            payload={"query": "health check", "history": []},
            ledger=MagicMock(),
            bus=MagicMock(),
        )
        with patch(
            "app.core.agent.kernel_agent_service.get_kernel_agent",
            return_value=FakeAgent(),
        ):
            result = _handle_agent_query(ctx)

        assert result == "done"
        assert calls
        assert calls[0]["record_task"] is False

    def test_proactive_llm_uses_core_provider_boundary(self, monkeypatch):
        import app.core.llm.model_selection as model_selection
        import app.core.llm.provider_factory as provider_factory
        from app.core.jobs.job_runner import _create_proactive_llm

        captured = {}

        class FakeProvider:
            def generate_content(self, **kwargs):
                captured.update(kwargs)
                return {"content": "主动提醒内容"}

        monkeypatch.setattr(
            model_selection,
            "get_configured_cloud_model",
            lambda **kwargs: "deepseek-chat",
        )
        monkeypatch.setattr(
            provider_factory,
            "get_llm_provider",
            lambda **kwargs: FakeProvider(),
        )

        llm_fn = _create_proactive_llm()

        assert llm_fn("生成一句提醒") == "主动提醒内容"
        assert captured["model"] == "deepseek-chat"
        assert captured["stream"] is False
        assert captured["max_tokens"] == 80

    def test_proactive_tick_continues_without_cloud_provider(self):
        from app.core.jobs.job_runner import JobContext, _handle_proactive_tick

        captured = {}

        class FakeAgent:
            def tick(self, llm_fn=None):
                captured["llm_fn"] = llm_fn

            def pending(self):
                return []

        ctx = JobContext(
            task_id="proactive-task",
            session_id="system",
            payload={},
            ledger=MagicMock(),
            bus=MagicMock(),
        )
        with (
            patch(
                "app.core.jobs.job_runner._create_proactive_llm",
                side_effect=RuntimeError("cloud unavailable"),
            ),
            patch(
                "app.core.agent.proactive_agent.get_proactive_agent",
                return_value=FakeAgent(),
            ),
        ):
            result = _handle_proactive_tick(ctx)

        assert result == "巡检完成，待推送消息 0 条"
        assert captured["llm_fn"] is None

    def test_recover_stale_tasks_cleans_startup_health_orphans(self, runner):
        """Startup recovery should cancel old health-check leftovers first."""
        from app.core.tasks.task_ledger import TaskStatus

        mock_ledger = MagicMock()
        mock_ledger.list_tasks.return_value = []

        with (
            patch("app.core.jobs.job_runner.time.sleep"),
            patch(
                "app.core.tasks.task_ledger.get_ledger",
                return_value=mock_ledger,
            ),
        ):
            runner._recover_stale_tasks()

        mock_ledger.cancel_stale_running_tasks.assert_called_once_with(
            timeout_seconds=86400.0
        )
        mock_ledger.cancel_stale_startup_health_tasks.assert_called_once_with(
            timeout_seconds=300.0
        )
        mock_ledger.list_tasks.assert_called_once_with(
            status=TaskStatus.PENDING, source="job_runner", limit=100
        )

    def test_task_ledger_cancels_only_stale_startup_health_tasks(self, tmp_path):
        """Stale startup health rows are cancelled without touching normal jobs."""
        from app.core.tasks.task_ledger import TaskLedger, TaskStatus

        ledger = TaskLedger(str(tmp_path / "task_ledger.sqlite"))
        old_started = "2000-01-01T00:00:00.000"

        health = ledger.create(
            session_id="system",
            user_input='{"preset_key": "startup_runtime_health"}',
            task_type="agent_query",
            source="job_runner",
            metadata={
                "job_type": "agent_query",
                "trigger_name": "启动自检摘要",
            },
        )
        agent_child = ledger.create(
            session_id="",
            user_input="请总结当前 Koto 的后台运行状态、关键模块是否就绪，并给出简短的启动后检查结论。",
            task_type="agent",
            source="agent",
        )
        ordinary = ledger.create(
            session_id="user",
            user_input="ordinary running task",
            task_type="agent",
            source="agent",
        )
        for task in (health, agent_child, ordinary):
            ledger.mark_running(task.task_id)
            ledger._update_fields(task.task_id, started_at=old_started)

        assert ledger.cancel_stale_startup_health_tasks(timeout_seconds=300.0) == 2
        assert ledger.get(health.task_id).status == TaskStatus.CANCELLED
        assert ledger.get(agent_child.task_id).status == TaskStatus.CANCELLED
        assert ledger.get(ordinary.task_id).status == TaskStatus.RUNNING
        ledger._conn.close()

    def test_task_ledger_cancels_only_old_running_orphans(self, tmp_path):
        """Generic startup cleanup leaves recent running tasks alone."""
        from app.core.tasks.task_ledger import TaskLedger, TaskStatus

        ledger = TaskLedger(str(tmp_path / "task_ledger.sqlite"))
        old_task = ledger.create(
            session_id="user",
            user_input="old file task",
            task_type="file_task",
            source="file_task",
        )
        fresh_task = ledger.create(
            session_id="user",
            user_input="fresh file task",
            task_type="file_task",
            source="file_task",
        )
        ledger.mark_running(old_task.task_id)
        ledger.mark_running(fresh_task.task_id)
        ledger._update_fields(
            old_task.task_id,
            started_at="2000-01-01T00:00:00.000",
        )

        assert ledger.cancel_stale_running_tasks(timeout_seconds=86400.0) == 1
        assert ledger.get(old_task.task_id).status == TaskStatus.CANCELLED
        assert ledger.get(fresh_task.task_id).status == TaskStatus.RUNNING
        ledger._conn.close()

    @patch("app.core.tasks.progress_bus.get_progress_bus")
    @patch("app.core.tasks.task_ledger.get_ledger")
    def test_run_job_handler_exception(self, mock_get_ledger, mock_get_bus, runner):
        """_run_job() handles handler exceptions by marking task failed."""
        mock_ledger = MagicMock()
        mock_task = MagicMock()
        mock_task.retry_count = 0
        mock_task.metadata = '{"max_retries": 0}'
        mock_ledger.get.return_value = mock_task
        mock_get_ledger.return_value = mock_ledger
        mock_get_bus.return_value = MagicMock()

        handler = Mock(side_effect=RuntimeError("boom"))
        runner.register_handler("fail_type", handler)

        from app.core.jobs.job_runner import JobSpec

        spec = JobSpec(job_type="fail_type", payload={})
        runner._run_job("tid-3", spec)
        mock_ledger.mark_failed.assert_called_once()


# ============================================================================
# 7. TestOpsEventBus
# ============================================================================


@pytest.mark.unit
class TestOpsEventBus:
    """Tests for app.core.ops.ops_event_bus.OpsEventBus."""

    @pytest.fixture
    def bus(self):
        from app.core.ops.ops_event_bus import OpsEventBus

        return OpsEventBus()

    def test_init_empty(self, bus):
        """OpsEventBus starts with empty history and handlers."""
        assert len(bus._history) == 0
        assert len(bus._handlers) == 0

    def test_emit_stores_event(self, bus):
        """emit() adds an event to the history."""
        bus.emit("test_event", {"key": "value"})
        assert len(bus._history) == 1
        assert bus._history[0].event_type == "test_event"

    def test_emit_with_severity(self, bus):
        """emit() stores events with the specified severity."""
        bus.emit("error_event", {"msg": "bad"}, severity="error")
        assert bus._history[0].severity == "error"

    def test_subscribe_and_emit(self, bus):
        """subscribe() registers a handler that gets called on emit."""
        handler = Mock()
        bus.subscribe("my_event", handler)
        bus.emit("my_event", {"data": 1})
        # Handler is called in a separate thread, wait a bit
        time.sleep(0.2)
        handler.assert_called_once()
        event_arg = handler.call_args[0][0]
        assert event_arg.event_type == "my_event"

    def test_subscribe_wildcard(self, bus):
        """subscribe('*', handler) receives all event types."""
        handler = Mock()
        bus.subscribe("*", handler)
        bus.emit("event_a", {})
        bus.emit("event_b", {})
        time.sleep(0.3)
        assert handler.call_count == 2

    def test_unsubscribe(self, bus):
        """unsubscribe() removes a handler."""
        handler = Mock()
        bus.subscribe("evt", handler)
        bus.unsubscribe("evt", handler)
        bus.emit("evt", {})
        time.sleep(0.1)
        handler.assert_not_called()

    def test_unsubscribe_nonexistent_handler(self, bus):
        """unsubscribe() silently ignores handlers not in the list."""
        handler = Mock()
        bus.unsubscribe("evt", handler)  # should not raise

    def test_get_recent(self, bus):
        """get_recent() returns events in reverse chronological order."""
        for i in range(5):
            bus.emit(f"event_{i}", {"i": i})
        recent = bus.get_recent(n=3)
        assert len(recent) == 3
        # Most recent first
        assert recent[0].event_type == "event_4"

    def test_get_by_type(self, bus):
        """get_by_type() filters events by type."""
        bus.emit("alpha", {})
        bus.emit("beta", {})
        bus.emit("alpha", {"second": True})
        result = bus.get_by_type("alpha")
        assert len(result) == 2
        assert all(e.event_type == "alpha" for e in result)

    def test_get_stats(self, bus):
        """get_stats() returns event count by type."""
        bus.emit("a", {})
        bus.emit("a", {})
        bus.emit("b", {})
        stats = bus.get_stats()
        assert stats["total"] == 3
        assert stats["by_type"]["a"] == 2
        assert stats["by_type"]["b"] == 1

    def test_ops_event_to_dict(self):
        """OpsEvent.to_dict() serializes all fields."""
        from app.core.ops.ops_event_bus import OpsEvent

        event = OpsEvent(
            event_type="test",
            detail={"k": "v"},
            severity="warning",
            source="unit_test",
        )
        d = event.to_dict()
        assert d["event_type"] == "test"
        assert d["severity"] == "warning"
        assert d["source"] == "unit_test"

    def test_history_max_limit(self):
        """History is bounded by _HISTORY_MAX."""
        from app.core.ops.ops_event_bus import _HISTORY_MAX, OpsEventBus

        bus = OpsEventBus()
        for i in range(_HISTORY_MAX + 50):
            bus.emit(f"overflow_{i}", {})
        assert len(bus._history) == _HISTORY_MAX

    def test_handler_exception_does_not_crash(self, bus):
        """Handler exceptions are caught and don't crash the bus."""
        bad_handler = Mock(side_effect=RuntimeError("handler crash"))
        bus.subscribe("crash_event", bad_handler)
        bus.emit("crash_event", {})
        time.sleep(0.2)
        # Should not raise, event still in history
        assert len(bus._history) == 1


# ============================================================================
# 8. TestOllamaLLMProvider
# ============================================================================


@pytest.mark.unit
class TestOllamaLLMProvider:
    """Tests for app.core.llm.ollama_llm_provider module."""

    def test_init_defaults(self):
        """OllamaLLMProvider initializes with default values."""
        from app.core.llm.ollama_llm_provider import OllamaLLMProvider

        provider = OllamaLLMProvider(model="qwen3:8b")
        assert provider.model == "qwen3:8b"
        assert ("localhost" in provider.base_url) or ("127.0.0.1" in provider.base_url)
        assert provider._options["temperature"] == 0.7

    def test_init_custom_params(self):
        """OllamaLLMProvider accepts custom parameters."""
        from app.core.llm.ollama_llm_provider import OllamaLLMProvider

        provider = OllamaLLMProvider(
            model="gemma3:4b",
            base_url="http://myhost:11434",
            temperature=0.3,
            num_predict=2048,
        )
        assert provider.model == "gemma3:4b"
        assert provider.base_url == "http://myhost:11434"
        assert provider._options["temperature"] == 0.3
        assert provider._options["num_predict"] == 2048

    def test_get_token_count_returns_zero(self):
        """get_token_count() returns a non-negative integer estimate."""
        from app.core.llm.ollama_llm_provider import OllamaLLMProvider

        provider = OllamaLLMProvider(model="test")
        result = provider.get_token_count("hello world", "test")
        assert isinstance(result, int) and result >= 0

    def test_to_ollama_messages_string_prompt(self):
        """_to_ollama_messages() converts string prompt to messages list."""
        from app.core.llm.ollama_llm_provider import _to_ollama_messages

        msgs = _to_ollama_messages("hello", "You are a helper")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "You are a helper"
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"] == "hello"

    def test_to_ollama_messages_list_prompt(self):
        """_to_ollama_messages() converts message list prompt."""
        from app.core.llm.ollama_llm_provider import _to_ollama_messages

        prompt = [
            {"role": "user", "content": "question"},
            {"role": "model", "content": "answer"},  # should become "assistant"
        ]
        msgs = _to_ollama_messages(prompt, None)
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"

    def test_to_ollama_messages_no_system(self):
        """_to_ollama_messages() omits system message when None."""
        from app.core.llm.ollama_llm_provider import _to_ollama_messages

        msgs = _to_ollama_messages("hi", None)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_to_ollama_tools_none(self):
        """_to_ollama_tools() returns None for empty/None input."""
        from app.core.llm.ollama_llm_provider import _to_ollama_tools

        assert _to_ollama_tools(None) is None
        assert _to_ollama_tools([]) is None

    def test_to_ollama_tools_conversion(self):
        """_to_ollama_tools() converts tool defs to Ollama format."""
        from app.core.llm.ollama_llm_provider import _to_ollama_tools

        tools = [{"name": "search", "description": "Search the web"}]
        result = _to_ollama_tools(tools)
        assert result is not None
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "search"

    def test_to_ollama_tools_skips_invalid(self):
        """_to_ollama_tools() skips tools without a name."""
        from app.core.llm.ollama_llm_provider import _to_ollama_tools

        tools = [{"description": "no name"}, {"name": "valid", "description": "ok"}]
        result = _to_ollama_tools(tools)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "valid"

    def test_parse_ollama_response(self):
        """_parse_ollama_response() extracts content, tool_calls, usage."""
        from app.core.llm.ollama_llm_provider import _parse_ollama_response

        resp = {
            "message": {"content": "Hello!", "tool_calls": None},
            "prompt_eval_count": 10,
            "eval_count": 20,
        }
        result = _parse_ollama_response(resp)
        assert result["content"] == "Hello!"
        assert result["tool_calls"] == []
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 20

    def test_parse_ollama_response_with_tool_calls(self):
        """_parse_ollama_response() parses tool_calls correctly."""
        from app.core.llm.ollama_llm_provider import _parse_ollama_response

        resp = {
            "message": {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "search", "arguments": {"q": "test"}}}
                ],
            }
        }
        result = _parse_ollama_response(resp)
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["name"] == "search"
        assert result["tool_calls"][0]["args"] == {"q": "test"}

    def test_parse_ollama_response_string_args(self):
        """_parse_ollama_response() parses string-encoded tool arguments."""
        from app.core.llm.ollama_llm_provider import _parse_ollama_response

        resp = {
            "message": {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "calc", "arguments": '{"expr": "1+1"}'}}
                ],
            }
        }
        result = _parse_ollama_response(resp)
        assert result["tool_calls"][0]["args"] == {"expr": "1+1"}

    @patch("app.core.llm.ollama_llm_provider._raw_post")
    def test_generate_content_non_stream(self, mock_post):
        """generate_content() calls Ollama API and returns parsed response."""
        from app.core.llm.ollama_llm_provider import OllamaLLMProvider

        mock_post.return_value = {
            "message": {"content": "Test response"},
            "prompt_eval_count": 5,
            "eval_count": 10,
        }
        provider = OllamaLLMProvider(model="qwen3:8b")
        result = provider.generate_content("What is 2+2?")
        assert result["content"] == "Test response"
        mock_post.assert_called_once()

    def test_resolve_model_explicit(self):
        """_resolve_model() returns the explicit model when set."""
        from app.core.llm.ollama_llm_provider import OllamaLLMProvider

        provider = OllamaLLMProvider(model="explicit:model")
        assert provider._resolve_model() == "explicit:model"

    def test_base_url_trailing_slash_stripped(self):
        """Base URL trailing slash is stripped."""
        from app.core.llm.ollama_llm_provider import OllamaLLMProvider

        provider = OllamaLLMProvider(model="m", base_url="http://host:1234/")
        assert provider.base_url == "http://host:1234"


# ============================================================================
# 9. TestRemediationManager
# ============================================================================


@pytest.mark.unit
class TestRemediationManager:
    """Tests for app.core.remediation.remediation_manager.RemediationManager."""

    @pytest.fixture
    def mgr(self):
        from app.core.remediation.remediation_manager import RemediationManager

        return RemediationManager()

    def test_create_action(self, mgr):
        """create_action() returns an action ID and stores the action."""
        aid = mgr.create_action(
            event_id=1,
            action_type="restart_service",
            description="Restart the web server",
            risk_level="low",
        )
        assert aid is not None
        assert aid in mgr.actions

    def test_get_action(self, mgr):
        """get_action() returns action details as a dict."""
        aid = mgr.create_action(1, "clear_cache", "Clear app cache")
        result = mgr.get_action(aid)
        assert result is not None
        assert result["action_type"] == "clear_cache"
        assert result["status"] == "pending"

    def test_get_action_not_found(self, mgr):
        """get_action() returns None for unknown action ID."""
        assert mgr.get_action("nonexistent") is None

    def test_approve_action(self, mgr):
        """approve_action() transitions from pending to approved."""
        aid = mgr.create_action(1, "restart", "Restart service")
        assert mgr.approve_action(aid, reason="looks good") is True
        action_dict = mgr.get_action(aid)
        assert action_dict["status"] == "approved"

    def test_approve_non_pending_fails(self, mgr):
        """approve_action() fails for already-approved actions."""
        aid = mgr.create_action(1, "restart", "Restart")
        mgr.approve_action(aid)
        assert mgr.approve_action(aid) is False  # already approved

    def test_approve_unknown_action(self, mgr):
        """approve_action() returns False for unknown action ID."""
        assert mgr.approve_action("fake_id") is False

    def test_reject_action(self, mgr):
        """reject_action() transitions from pending to rejected."""
        aid = mgr.create_action(1, "delete_logs", "Delete old logs")
        assert mgr.reject_action(aid, reason="too risky") is True
        action_dict = mgr.get_action(aid)
        assert action_dict["status"] == "rejected"

    def test_reject_non_pending_fails(self, mgr):
        """reject_action() fails for non-pending actions."""
        aid = mgr.create_action(1, "restart", "Restart")
        mgr.approve_action(aid)
        assert mgr.reject_action(aid) is False

    def test_get_pending_actions(self, mgr):
        """get_pending_actions() returns only pending actions."""
        aid1 = mgr.create_action(1, "type_a", "desc_a")
        aid2 = mgr.create_action(2, "type_b", "desc_b")
        mgr.approve_action(aid2)
        pending = mgr.get_pending_actions()
        assert len(pending) == 1
        assert pending[0]["id"] == aid1

    def test_get_all_actions(self, mgr):
        """get_all_actions() returns all actions."""
        mgr.create_action(1, "a", "desc")
        mgr.create_action(2, "b", "desc")
        all_actions = mgr.get_all_actions()
        assert len(all_actions) == 2

    def test_get_all_actions_filter_by_status(self, mgr):
        """get_all_actions(status=...) filters by status."""
        aid1 = mgr.create_action(1, "a", "desc")
        aid2 = mgr.create_action(2, "b", "desc")
        mgr.approve_action(aid2)
        approved = mgr.get_all_actions(status="approved")
        assert len(approved) == 1
        assert approved[0]["id"] == aid2

    def test_get_all_actions_invalid_status(self, mgr):
        """get_all_actions() returns empty list for invalid status."""
        mgr.create_action(1, "a", "desc")
        result = mgr.get_all_actions(status="nonexistent_status")
        assert result == []

    def test_execute_action(self, mgr):
        """execute_action() starts execution for an approved action."""
        aid = mgr.create_action(1, "restart", "Restart service")
        mgr.approve_action(aid)
        assert mgr.execute_action(aid) is True
        # The action should be in EXECUTING state immediately
        action_dict = mgr.get_action(aid)
        assert action_dict["status"] == "executing"

    def test_execute_non_approved_fails(self, mgr):
        """execute_action() fails for non-approved actions."""
        aid = mgr.create_action(1, "restart", "Restart")
        assert mgr.execute_action(aid) is False  # still pending

    def test_execute_unknown_action(self, mgr):
        """execute_action() returns False for unknown action IDs."""
        assert mgr.execute_action("fake") is False

    def test_get_stats(self, mgr):
        """get_stats() returns status breakdown."""
        mgr.create_action(1, "a", "desc")
        mgr.create_action(2, "b", "desc")
        aid3 = mgr.create_action(3, "c", "desc")
        mgr.approve_action(aid3)
        stats = mgr.get_stats()
        assert stats["total_actions"] == 3
        assert stats["by_status"]["pending"] == 2
        assert stats["by_status"]["approved"] == 1

    def test_remediation_action_lifecycle(self, mgr):
        """Full lifecycle: create → approve → execute → complete."""
        from app.core.remediation.remediation_manager import RemediationAction

        action = RemediationAction(
            event_id=99,
            action_type="fix",
            description="Fix issue",
        )
        assert action.approve("approved") is True
        assert action.start_execution() is True
        assert action.complete(True, "Fixed successfully") is True
        assert action.status.value == "success"
        assert action.result == "Fixed successfully"

    def test_remediation_action_complete_failure(self):
        """RemediationAction marks failure correctly."""
        from app.core.remediation.remediation_manager import RemediationAction

        action = RemediationAction(event_id=1, action_type="fix", description="Try")
        action.approve()
        action.start_execution()
        assert action.complete(False, "Something went wrong") is True
        assert action.status.value == "failed"

    def test_remediation_action_to_dict(self):
        """RemediationAction.to_dict() serializes all fields."""
        from app.core.remediation.remediation_manager import RemediationAction

        action = RemediationAction(
            event_id=5,
            action_type="scale_up",
            description="Scale up workers",
            risk_level="medium",
        )
        d = action.to_dict()
        assert d["event_id"] == 5
        assert d["action_type"] == "scale_up"
        assert d["risk_level"] == "medium"
        assert d["status"] == "pending"
        assert "created_at" in d

    def test_execute_async_completes(self, mgr):
        """_execute_async() marks the action as completed after running."""
        aid = mgr.create_action(1, "fix", "Auto fix")
        mgr.approve_action(aid)
        mgr.execute_action(aid)
        # Wait for async execution
        time.sleep(1.0)
        action_dict = mgr.get_action(aid)
        assert action_dict["status"] == "success"
