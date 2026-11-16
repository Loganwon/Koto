from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest


@pytest.mark.unit
def test_start_background_runtime_is_idempotent(monkeypatch):
    import web.app_runtime as mod

    thread = MagicMock()
    thread.start = MagicMock()
    thread_factory = MagicMock(return_value=thread)

    monkeypatch.setattr(mod, "_runtime_started", False)
    monkeypatch.setattr(mod, "_runtime_thread", None)
    monkeypatch.setattr(mod.threading, "Thread", thread_factory)

    logger = MagicMock()
    get_workspace_root = MagicMock(return_value=None)

    first = mod.start_background_runtime(logger, get_workspace_root)
    second = mod.start_background_runtime(logger, get_workspace_root)

    assert first is thread
    assert second is thread
    thread_factory.assert_called_once()
    thread.start.assert_called_once()


@pytest.mark.unit
def test_start_background_runtime_can_be_skipped_for_safe_import_probes(monkeypatch):
    import web.app_runtime as mod

    thread_factory = MagicMock()
    thread = MagicMock()
    thread_factory.return_value = thread
    monkeypatch.setattr(mod, "_runtime_started", False)
    monkeypatch.setattr(mod, "_runtime_thread", None)
    monkeypatch.setattr(mod.threading, "Thread", thread_factory)
    monkeypatch.setenv("KOTO_SKIP_BACKGROUND_RUNTIME", "1")

    result = mod.start_background_runtime(MagicMock(), MagicMock())

    assert result is thread
    thread.start.assert_not_called()


@pytest.mark.unit
def test_start_model_runtime_is_idempotent(monkeypatch):
    import web.app_runtime as mod

    thread = MagicMock()
    thread_factory = MagicMock(return_value=thread)
    monkeypatch.setattr(mod, "_model_runtime_started", False)
    monkeypatch.setattr(mod, "_model_runtime_threads", ())
    monkeypatch.setattr(mod.threading, "Thread", thread_factory)
    monkeypatch.delenv("KOTO_SKIP_BACKGROUND_RUNTIME", raising=False)

    logger = MagicMock()
    initialize = MagicMock()
    refresh = MagicMock()
    first = mod.start_model_runtime(logger, initialize, refresh)
    second = mod.start_model_runtime(logger, initialize, refresh)

    assert first == (thread,)
    assert second == first
    thread_factory.assert_called_once_with(
        target=mod._run_model_runtime,
        args=(logger, initialize, refresh),
        name="ModelManagerRuntime",
        daemon=True,
    )
    thread.start.assert_called_once_with()


@pytest.mark.unit
def test_model_runtime_initializes_before_refreshing():
    import web.app_runtime as mod

    calls = []
    mod._run_model_runtime(
        MagicMock(),
        lambda: calls.append("initialize"),
        lambda: calls.append("refresh"),
    )

    assert calls == ["initialize", "refresh"]


@pytest.mark.unit
def test_start_model_runtime_can_be_skipped_for_safe_import_probes(monkeypatch):
    import web.app_runtime as mod

    thread_factory = MagicMock()
    monkeypatch.setattr(mod, "_model_runtime_started", False)
    monkeypatch.setattr(mod, "_model_runtime_threads", ())
    monkeypatch.setattr(mod.threading, "Thread", thread_factory)
    monkeypatch.setenv("KOTO_SKIP_BACKGROUND_RUNTIME", "1")

    result = mod.start_model_runtime(MagicMock(), MagicMock(), MagicMock())

    assert result == ()
    thread_factory.assert_not_called()


@pytest.mark.unit
def test_proxy_warmup_is_idempotent_and_skippable(monkeypatch):
    import web.app_runtime as mod

    thread = MagicMock()
    thread_factory = MagicMock(return_value=thread)
    monkeypatch.setattr(mod, "_proxy_warmup_thread", None)
    monkeypatch.setattr(mod.threading, "Thread", thread_factory)
    monkeypatch.delenv("KOTO_SKIP_BACKGROUND_RUNTIME", raising=False)

    warmup = MagicMock()
    first = mod.start_proxy_warmup(MagicMock(), warmup)
    second = mod.start_proxy_warmup(MagicMock(), warmup)

    assert first is thread
    assert second is thread
    thread_factory.assert_called_once_with(
        target=warmup,
        name="ProxyWarmup",
        daemon=True,
    )
    thread.start.assert_called_once_with()

    monkeypatch.setattr(mod, "_proxy_warmup_thread", None)
    monkeypatch.setenv("KOTO_SKIP_BACKGROUND_RUNTIME", "1")
    assert mod.start_proxy_warmup(MagicMock(), warmup) is None
    assert thread_factory.call_count == 1


@pytest.mark.unit
def test_initialize_background_runtime_skips_disabled_workspace_watcher(
    monkeypatch, tmp_path
):
    import web.app_runtime as mod

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    fake_runner = object()
    fake_registry = types.SimpleNamespace(list_all=lambda: [])
    fake_file_registry = types.SimpleNamespace(count=lambda: 0)
    fake_file_watcher = types.SimpleNamespace(
        enabled=False,
        watch_dirs=[],
        add_dir=MagicMock(),
        scan_once=MagicMock(),
        start=MagicMock(),
    )
    fake_goal_manager = types.SimpleNamespace(count=lambda: 0)
    fake_morning_brief = types.SimpleNamespace(start_scheduler=MagicMock())
    fake_contact_manager = types.SimpleNamespace(count=lambda: 0)
    fake_work_file_library = types.SimpleNamespace(
        is_indexed=lambda: True,
        count=lambda: 0,
        scan_locations=MagicMock(),
    )

    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)

    job_runner_mod = types.ModuleType("app.core.jobs.job_runner")
    job_runner_mod.get_job_runner = lambda: fake_runner
    trigger_registry_mod = types.ModuleType("app.core.jobs.trigger_registry")
    trigger_registry_mod.get_trigger_registry = lambda: fake_registry
    ops_bus_mod = types.ModuleType("app.core.ops.ops_event_bus")
    ops_bus_mod.get_ops_bus = lambda: object()
    file_registry_mod = types.ModuleType("app.core.file.file_registry")
    file_registry_mod.get_file_registry = lambda: fake_file_registry
    file_watcher_mod = types.ModuleType("app.core.file.file_watcher")
    file_watcher_mod.get_file_watcher = lambda: fake_file_watcher
    goal_job_handler_mod = types.ModuleType("app.core.goal.goal_job_handler")
    goal_job_handler_mod.register_goal_handler = lambda runner: None
    goal_manager_mod = types.ModuleType("app.core.goal.goal_manager")
    goal_manager_mod.get_goal_manager = lambda: fake_goal_manager
    telegram_bot_mod = types.ModuleType("app.core.services.telegram_bot")
    telegram_bot_mod.get_telegram_bot = lambda: None
    morning_brief_mod = types.ModuleType("app.core.services.morning_brief")
    morning_brief_mod.get_morning_brief_service = lambda: fake_morning_brief
    contact_manager_mod = types.ModuleType("app.core.memory.contact_manager")
    contact_manager_mod.get_contact_manager = lambda: fake_contact_manager
    work_file_library_mod = types.ModuleType("web.files.work_file_library")
    work_file_library_mod.get_work_file_library = lambda: fake_work_file_library

    monkeypatch.setitem(sys.modules, "app.core.jobs.job_runner", job_runner_mod)
    monkeypatch.setitem(
        sys.modules, "app.core.jobs.trigger_registry", trigger_registry_mod
    )
    monkeypatch.setitem(sys.modules, "app.core.ops.ops_event_bus", ops_bus_mod)
    monkeypatch.setitem(sys.modules, "app.core.file.file_registry", file_registry_mod)
    monkeypatch.setitem(sys.modules, "app.core.file.file_watcher", file_watcher_mod)
    monkeypatch.setitem(
        sys.modules, "app.core.goal.goal_job_handler", goal_job_handler_mod
    )
    monkeypatch.setitem(sys.modules, "app.core.goal.goal_manager", goal_manager_mod)
    monkeypatch.setitem(sys.modules, "app.core.services.telegram_bot", telegram_bot_mod)
    monkeypatch.setitem(
        sys.modules, "app.core.services.morning_brief", morning_brief_mod
    )
    monkeypatch.setitem(
        sys.modules, "app.core.memory.contact_manager", contact_manager_mod
    )
    monkeypatch.setitem(
        sys.modules, "web.files.work_file_library", work_file_library_mod
    )

    logger = MagicMock()

    mod.initialize_background_runtime(logger, lambda: str(workspace_dir))

    fake_file_watcher.add_dir.assert_not_called()
    fake_file_watcher.start.assert_not_called()
    fake_work_file_library.scan_locations.assert_not_called()
