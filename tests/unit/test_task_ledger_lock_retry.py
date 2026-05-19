from __future__ import annotations

import sqlite3


def test_task_ledger_create_retries_transient_db_lock(tmp_path):
    from app.core.tasks.task_ledger import TaskLedger

    ledger = TaskLedger(db_path=str(tmp_path / "task_ledger.sqlite"))
    real_conn = ledger._conn

    class _FlakyConn:
        def __init__(self, conn):
            self._conn = conn
            self.failures = 0
            self.rollbacks = 0

        def execute(self, sql, params=()):
            if "INSERT INTO koto_tasks" in sql and self.failures < 2:
                self.failures += 1
                raise sqlite3.OperationalError("database is locked")
            return self._conn.execute(sql, params)

        def commit(self):
            return self._conn.commit()

        def rollback(self):
            self.rollbacks += 1
            return self._conn.rollback()

        def __getattr__(self, name):
            return getattr(self._conn, name)

    flaky_conn = _FlakyConn(real_conn)
    ledger._conn = flaky_conn

    task = ledger.create(session_id="sess", user_input="hello", source="job_runner")

    assert task.task_id
    assert flaky_conn.failures == 2
    assert flaky_conn.rollbacks == 2
    loaded = ledger.get(task.task_id)
    assert loaded is not None
    assert loaded.user_input == "hello"