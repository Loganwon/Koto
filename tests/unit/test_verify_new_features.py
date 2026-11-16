"""
Verification tests for all new features added across multiple sessions.

Categories:
  A. SkillAutoMatcher — _detect_conflicts / _CONFLICT_PAIRS
  B. SkillAutoMatcher — rating-aware scoring in match()
  C. SkillSuggester — Layer 4 rating scoring in _score_candidates
  D. TaskLedger — TaskPriority enum + set_priority + list ordering
"""

from __future__ import annotations

import os
import tempfile
import uuid
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# G. TaskLedger — TaskPriority enum + set_priority
# ─────────────────────────────────────────────────────────────────────────────
class TestTaskLedgerPriority:
    def _make_ledger(self):
        from app.core.tasks.task_ledger import TaskLedger

        tmp = tempfile.mktemp(suffix=".sqlite")
        ledger = TaskLedger(db_path=tmp)
        return ledger, tmp

    def _teardown(self, ledger, tmp):
        """Close the SQLite connection before deleting the temp file (Windows)."""
        try:
            ledger._conn.close()
        except Exception:
            pass
        try:
            os.unlink(tmp)
        except Exception:
            pass

    def test_task_priority_enum_values(self):
        from app.core.tasks.task_ledger import TaskPriority

        assert TaskPriority.LOW < TaskPriority.NORMAL
        assert TaskPriority.NORMAL < TaskPriority.HIGH
        assert TaskPriority.HIGH < TaskPriority.URGENT

    def test_create_task_with_priority(self):
        from app.core.tasks.task_ledger import TaskLedger, TaskPriority

        ledger, tmp = self._make_ledger()
        try:
            rec = ledger.create(
                "sess1", "test input", source="test", priority=TaskPriority.HIGH
            )
            tasks = ledger.list_tasks()
            task = next((t for t in tasks if t.task_id == rec.task_id), None)
            assert task is not None
            assert task.priority == int(TaskPriority.HIGH)
        finally:
            self._teardown(ledger, tmp)

    def test_set_priority_updates_value(self):
        from app.core.tasks.task_ledger import TaskLedger, TaskPriority

        ledger, tmp = self._make_ledger()
        try:
            rec = ledger.create("sess1", "prio input", source="test")
            ledger.set_priority(rec.task_id, TaskPriority.URGENT)
            tasks = ledger.list_tasks()
            task = next((t for t in tasks if t.task_id == rec.task_id), None)
            assert task.priority == int(TaskPriority.URGENT)
        finally:
            self._teardown(ledger, tmp)

    def test_list_tasks_order_by_priority(self):
        from app.core.tasks.task_ledger import TaskLedger, TaskPriority

        ledger, tmp = self._make_ledger()
        try:
            ledger.create("sess1", "low", source="test", priority=TaskPriority.LOW)
            ledger.create(
                "sess1", "urgent", source="test", priority=TaskPriority.URGENT
            )
            ledger.create(
                "sess1", "normal", source="test", priority=TaskPriority.NORMAL
            )
            tasks = ledger.list_tasks(order_by="priority")
            prios = [t.priority for t in tasks]
            # priority descending: URGENT(3) first, LOW(0) last
            assert prios == sorted(prios, reverse=True)
        finally:
            self._teardown(ledger, tmp)

    def test_list_tasks_filter_by_priority(self):
        from app.core.tasks.task_ledger import TaskLedger, TaskPriority

        ledger, tmp = self._make_ledger()
        try:
            ledger.create("sess1", "a", source="test", priority=TaskPriority.HIGH)
            ledger.create("sess1", "b", source="test", priority=TaskPriority.LOW)
            high_tasks = ledger.list_tasks(priority=int(TaskPriority.HIGH))
            assert all(t.priority == int(TaskPriority.HIGH) for t in high_tasks)
        finally:
            self._teardown(ledger, tmp)
