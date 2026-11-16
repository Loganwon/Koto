# -*- coding: utf-8 -*-
"""
Unit tests for the exception-handling paths fixed in P0.

These tests verify that:
  - All previously-silent `except Exception: pass` blocks now LOG the error
    instead of swallowing it, and that the function still completes gracefully.

Files covered:
  - app/core/workflow/step_executor.py
  - app/core/jobs/job_runner.py
"""

from __future__ import annotations

import importlib
import json
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _inject_stub(module_path: str, stub_attrs: dict):
    """Insert a fake module into sys.modules so guarded `import` statements
    inside the functions-under-test resolve to our stub instead of raising
    ImportError.  Returns a context-manager-like object."""
    parts = module_path.rsplit(".", 1)
    pkg_path = parts[0] if len(parts) == 2 else None

    stub = types.ModuleType(module_path)
    for k, v in stub_attrs.items():
        setattr(stub, k, v)

    class _Ctx:
        def __enter__(self_inner):
            sys.modules[module_path] = stub
            if pkg_path and pkg_path not in sys.modules:
                sys.modules[pkg_path] = types.ModuleType(pkg_path)
            return stub

        def __exit__(self_inner, *_):
            sys.modules.pop(module_path, None)

    return _Ctx()


# ===========================================================================
# 2.  WorkflowRuntime
# ===========================================================================


class TestJobContextErrorHandling:
    """Tests for the JobContext.step() exception paths in job_runner.py."""

    @pytest.fixture(autouse=True)
    def _import_classes(self):
        from app.core.jobs.job_runner import JobContext

        self.JobContext = JobContext

    def _make_context(self, ledger=None, bus=None):
        ctx = self.JobContext.__new__(self.JobContext)
        ctx.task_id = "task-001"
        ctx.session_id = "sess-001"
        ctx.ledger = ledger or MagicMock()
        ctx.bus = bus or MagicMock()
        return ctx

    # ------------------------------------------------------------------
    # 4-A  ledger.add_step raises → logs WARNING, step() still continues
    # ------------------------------------------------------------------
    def test_step_ledger_failure_does_not_raise(self, caplog):
        import logging

        failing_ledger = MagicMock()
        failing_ledger.add_step.side_effect = RuntimeError("DB locked")
        ctx = self._make_context(ledger=failing_ledger)

        with caplog.at_level(logging.WARNING, logger="app.core.jobs.job_runner"):
            ctx.step("PLAN", "planning content", progress=10)

        assert "TaskLedger" in caplog.text or "ledger" in caplog.text.lower()

    # ------------------------------------------------------------------
    # 4-B  bus.publish_step raises → logs WARNING, step() still completes
    # ------------------------------------------------------------------
    def test_step_bus_failure_does_not_raise(self, caplog):
        import logging

        failing_bus = MagicMock()
        failing_bus.publish_step.side_effect = ConnectionError("SSE gone")
        ctx = self._make_context(bus=failing_bus)

        with caplog.at_level(logging.WARNING, logger="app.core.jobs.job_runner"):
            ctx.step("EXECUTE", "running tool", progress=50)

        assert "ProgressBus" in caplog.text or "publish" in caplog.text.lower()

    # ------------------------------------------------------------------
    # 4-C  Both ledger and bus fail → two warnings, no exception
    # ------------------------------------------------------------------
    def test_step_both_fail_still_returns(self, caplog):
        import logging

        fl = MagicMock()
        fl.add_step.side_effect = ValueError("bad step")
        fb = MagicMock()
        fb.publish_step.side_effect = ValueError("bad publish")
        ctx = self._make_context(ledger=fl, bus=fb)

        with caplog.at_level(logging.WARNING, logger="app.core.jobs.job_runner"):
            ctx.step("ANSWER", "final answer", progress=100)

        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) >= 2  # both failures should be logged

    # ------------------------------------------------------------------
    # 4-D  Normal happy path still works
    # ------------------------------------------------------------------
    def test_step_happy_path(self):
        ledger = MagicMock()
        bus = MagicMock()
        ctx = self._make_context(ledger=ledger, bus=bus)

        ctx.step("PLAN", "all good", progress=20, tool_name="my_tool")

        ledger.add_step.assert_called_once()
        bus.publish_step.assert_called_once()
