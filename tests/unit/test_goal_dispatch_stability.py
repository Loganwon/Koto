from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.core.goal.goal_manager import GoalManager
from app.core.jobs import job_runner as job_runner_module


def _goal():
    return SimpleNamespace(
        goal_id="goal-12345678",
        priority="high",
        session_id="session-1",
        title="稳定执行",
    )


def test_goal_dispatch_creates_only_the_job_runner_task(monkeypatch):
    manager = object.__new__(GoalManager)
    manager._update = MagicMock()
    runner = MagicMock()
    monkeypatch.setattr(job_runner_module, "get_job_runner", lambda: runner)

    manager._submit_goal_job(_goal())

    runner.submit.assert_called_once()
    spec = runner.submit.call_args.args[0]
    assert spec.job_type == "goal_check"
    assert spec.payload == {"goal_id": "goal-12345678"}
    assert "linked_task_id" not in spec.metadata
    manager._update.assert_not_called()


def test_goal_dispatch_failure_retries_without_spawning_direct_execution(
    monkeypatch,
):
    manager = object.__new__(GoalManager)
    manager._update = MagicMock()

    def unavailable():
        raise RuntimeError("runner offline")

    thread_factory = MagicMock()
    monkeypatch.setattr(job_runner_module, "get_job_runner", unavailable)
    monkeypatch.setattr("app.core.goal.goal_manager.threading.Thread", thread_factory)

    manager._submit_goal_job(_goal())

    manager._update.assert_called_once()
    assert manager._update.call_args.args == ("goal-12345678",)
    assert "next_check_at" in manager._update.call_args.kwargs
    thread_factory.assert_not_called()
