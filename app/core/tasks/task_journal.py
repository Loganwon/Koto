"""Durable run events and Kernel checkpoints owned by :class:`TaskLedger`.

This mixin uses the ledger's connection and lock.  It creates no registry,
worker, or independent storage lifecycle.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

JOURNAL_DDL = """
CREATE TABLE IF NOT EXISTS koto_run_identities (
    run_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_koto_run_identities_task ON koto_run_identities(task_id);
CREATE TABLE IF NOT EXISTS koto_run_events (
    task_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY(task_id, run_id, seq),
    UNIQUE(task_id, run_id, event_id)
);
CREATE INDEX IF NOT EXISTS idx_koto_run_events_task ON koto_run_events(task_id);
CREATE TABLE IF NOT EXISTS koto_kernel_checkpoints (
    task_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    state TEXT NOT NULL,
    phase TEXT NOT NULL,
    resumable INTEGER NOT NULL DEFAULT 1,
    owner_id TEXT,
    owner_pid INTEGER,
    owner_started REAL,
    lease_until REAL NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 1,
    updated_at REAL NOT NULL,
    PRIMARY KEY(task_id, run_id)
);
"""


def _process_identity() -> tuple[int, float]:
    try:
        import psutil

        return os.getpid(), psutil.Process().create_time()
    except (ImportError, OSError):
        return os.getpid(), 0.0


def _owner_is_alive(checkpoint: Dict[str, Any]) -> bool:
    """Read process identity; never send signals to a Windows process."""
    pid = int(checkpoint.get("owner_pid") or 0)
    if not pid:
        return True  # Unknown/old owner must respect its lease.
    try:
        import psutil

        process = psutil.Process(pid)
        started = float(checkpoint.get("owner_started") or 0)
        return not started or abs(process.create_time() - started) < 0.01
    except ImportError:
        return True
    except Exception as exc:
        # NoSuchProcess is conclusive. AccessDenied is not permission to steal.
        return type(exc).__name__ != "NoSuchProcess"


def _terminal_event(event: Dict[str, Any]) -> bool:
    kind = str(event.get("type") or "")
    payload = event.get("payload") or {}
    if kind in {"run.cancelled", "run.finished", "task_final"}:
        runtime = (
            payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
        )
        status = str(
            runtime.get("terminal_status")
            or payload.get("terminal_status")
            or payload.get("status")
            or ""
        ).lower()
        return not payload.get("awaiting_confirmation") and status not in {
            "waiting",
            "running",
            "awaiting_confirmation",
            "context_summary_fallback",
            "needs_review",
            "needs_attention",
        }
    return False


class TaskJournalMixin:
    """Transactional helpers sharing the TaskLedger SQLite owner."""

    def bind_run_identity(
        self, task_id: str, run_id: str, session_id: str = ""
    ) -> Dict[str, str]:
        """Bind a client run before registration/cancellation without a second owner."""
        task_id, run_id, session_id = (
            str(task_id or "").strip(),
            str(run_id or "").strip(),
            str(session_id or "").strip(),
        )
        if (
            not task_id
            or not run_id
            or any(
                len(value) > 160 or any(c in value for c in "\r\n\x00")
                for value in (task_id, run_id)
            )
        ):
            raise ValueError("task_id and run_id must be valid single-line identifiers")
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                existing = self._conn.execute(
                    "SELECT task_id,session_id FROM koto_run_identities WHERE run_id=?",
                    (run_id,),
                ).fetchone()
                if existing and (
                    existing["task_id"] != task_id
                    or (
                        session_id
                        and existing["session_id"]
                        and session_id != existing["session_id"]
                    )
                ):
                    raise ValueError(
                        "run_id is already bound to another task or session"
                    )
                for table in ("koto_run_events", "koto_kernel_checkpoints"):
                    owner = self._conn.execute(
                        f"SELECT task_id FROM {table} WHERE run_id=? LIMIT 1", (run_id,)
                    ).fetchone()
                    if owner and owner["task_id"] != task_id:
                        raise ValueError("run_id belongs to another existing task")
                self._conn.execute(
                    """INSERT INTO koto_run_identities(run_id,task_id,session_id,created_at) VALUES(?,?,?,?)
                    ON CONFLICT(run_id) DO UPDATE SET session_id=CASE WHEN koto_run_identities.session_id='' THEN excluded.session_id ELSE koto_run_identities.session_id END""",
                    (run_id, task_id, session_id, time.time()),
                )
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise
        return {
            "task_id": task_id,
            "run_id": run_id,
            "session_id": session_id or (existing["session_id"] if existing else ""),
        }

    def clear_cancel_for_retry(self, task_id: str) -> None:
        """Clear only the task control after an explicit new retry attempt.

        Old run controls and their immutable journal terminals remain intact.
        """
        with self._lock:
            self._conn.execute(
                "DELETE FROM koto_task_controls WHERE control_id=?", (str(task_id),)
            )
            self._conn.execute(
                "UPDATE koto_tasks SET cancel_requested=0,interrupt_requested=0 WHERE task_id=? AND status='pending'",
                (str(task_id),),
            )
            self._conn.commit()

    def append_run_event(
        self,
        task_id: str,
        run_id: str,
        event_type: str,
        payload: Dict[str, Any],
        *,
        event_id: Optional[str] = None,
        step_id: str = "",
        timestamp: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Assign sequence once, commit, then return the event to be published.

        A caller-provided event_id makes a retry of persistence idempotent.
        Sequence allocation is serialized across processes by BEGIN IMMEDIATE.
        """
        task_id = str(task_id or "").strip()
        run_id = str(run_id or task_id).strip()
        if not task_id or not run_id or not str(event_type or "").strip():
            raise ValueError("task_id, run_id and event_type are required")
        self.bind_run_identity(task_id, run_id)
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                if event_id:
                    previous = self._conn.execute(
                        "SELECT payload FROM koto_run_events WHERE task_id=? AND run_id=? AND event_id=?",
                        (task_id, run_id, str(event_id)),
                    ).fetchone()
                    if previous:
                        self._conn.commit()
                        return json.loads(previous["payload"])
                previous = self._conn.execute(
                    "SELECT seq,payload FROM koto_run_events WHERE task_id=? AND run_id=? ORDER BY seq DESC LIMIT 1",
                    (task_id, run_id),
                ).fetchone()
                if previous and _terminal_event(json.loads(previous["payload"])):
                    raise ValueError("run already has a durable terminal event")
                seq = int(previous["seq"] if previous else 0) + 1
                event = dict(extra or {})
                event.update(
                    {
                        "version": 1,
                        "task_id": task_id,
                        "run_id": run_id,
                        "seq": seq,
                        "event_id": str(event_id or f"{run_id}:{seq}"),
                        "type": str(event_type),
                        "step_id": str(step_id or ""),
                        "ts": float(
                            timestamp if timestamp is not None else time.time()
                        ),
                        "payload": dict(payload or {}),
                    }
                )
                encoded = json.dumps(event, ensure_ascii=False, default=str)
                self._conn.execute(
                    "INSERT INTO koto_run_events(task_id,run_id,seq,event_id,event_type,payload,created_at) VALUES(?,?,?,?,?,?,?)",
                    (
                        task_id,
                        run_id,
                        seq,
                        event["event_id"],
                        str(event_type),
                        encoded,
                        event["ts"],
                    ),
                )
                self._conn.commit()
                return json.loads(encoded)
            except BaseException:
                self._conn.rollback()
                raise

    def append_event(self, task_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
        """Persist an existing domain event without a second identity layer."""
        source = dict(event or {})
        return self.append_run_event(
            task_id,
            str(source.get("run_id") or task_id),
            str(source.get("type") or "progress"),
            source.get("payload") if isinstance(source.get("payload"), dict) else {},
            event_id=source.get("event_id"),
            step_id=str(source.get("step_id") or ""),
            timestamp=source.get("ts"),
            extra={k: v for k, v in source.items() if k not in {"seq", "event_id"}},
        )

    def list_run_events(
        self,
        task_id: str,
        run_id: Optional[str] = None,
        *,
        after_seq: int = 0,
        limit: int = 1000,
    ) -> list[Dict[str, Any]]:
        """Read one run's committed events after a cursor, including after restart."""
        with self._lock:
            if not run_id:
                latest = self._conn.execute(
                    "SELECT run_id FROM koto_run_events WHERE task_id=? ORDER BY rowid DESC LIMIT 1",
                    (str(task_id),),
                ).fetchone()
                if not latest:
                    return []
                run_id = latest["run_id"]
            rows = self._conn.execute(
                "SELECT payload FROM koto_run_events WHERE task_id=? AND run_id=? AND seq>? ORDER BY seq LIMIT ?",
                (
                    str(task_id),
                    str(run_id),
                    max(0, int(after_seq)),
                    max(1, min(int(limit), 10000)),
                ),
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def latest_run_event(
        self, task_id: str, run_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            query = "SELECT payload FROM koto_run_events WHERE task_id=?"
            values: list[Any] = [str(task_id)]
            if run_id:
                query += " AND run_id=?"
                values.append(str(run_id))
            row = self._conn.execute(
                query + " ORDER BY rowid DESC LIMIT 1", values
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def save_kernel_checkpoint(
        self,
        task_id: str,
        run_id: str,
        state: Dict[str, Any],
        *,
        resumable: bool = True,
        owner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Save full Kernel continuation state, never just a task-status flag."""
        task_id, run_id = str(task_id), str(run_id or task_id)
        snapshot = dict(state or {})
        snapshot.update({"task_id": task_id, "run_id": run_id})
        phase = str(snapshot.get("phase") or "model_complete")
        if any(
            item.get("read_only") is not True
            for item in snapshot.get("pending_tool_calls", [])
        ):
            resumable = False
        file_adapter = snapshot.get("runtime_adapter") == "file_task"
        if phase in {"cancelled", "failed", "domain_completed", "domain_failed"} or (
            phase == "completed" and not file_adapter
        ):
            resumable = False
        if snapshot.get("requires_authorization"):
            resumable = False
        if file_adapter and not (
            isinstance(snapshot.get("file_task_request"), dict)
            and isinstance(snapshot.get("adapter_receipts"), dict)
        ):
            resumable = False
        now = time.time()
        owner_pid, owner_started = _process_identity() if owner_id else (None, None)
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                existing = self._conn.execute(
                    "SELECT owner_id,lease_until FROM koto_kernel_checkpoints WHERE task_id=? AND run_id=?",
                    (task_id, run_id),
                ).fetchone()
                if (
                    owner_id
                    and existing
                    and existing["owner_id"] not in {None, "", owner_id}
                    and existing["lease_until"] > now
                ):
                    raise ValueError("checkpoint is owned by another active worker")
                self._conn.execute(
                    """INSERT INTO koto_kernel_checkpoints
                    (task_id,run_id,state,phase,resumable,owner_id,owner_pid,owner_started,lease_until,revision,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,1,?)
                    ON CONFLICT(task_id,run_id) DO UPDATE SET
                      state=excluded.state,phase=excluded.phase,resumable=excluded.resumable,
                      revision=koto_kernel_checkpoints.revision+1,updated_at=excluded.updated_at""",
                    (
                        task_id,
                        run_id,
                        json.dumps(snapshot, ensure_ascii=False, default=str),
                        phase,
                        int(resumable),
                        owner_id,
                        owner_pid,
                        owner_started,
                        now + 900.0 if owner_id else 0,
                        now,
                    ),
                )
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise
        return self.get_kernel_checkpoint(task_id, run_id) or {}

    def get_kernel_checkpoint(
        self, task_id: str, run_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            query = "SELECT * FROM koto_kernel_checkpoints WHERE task_id=?"
            values: list[Any] = [str(task_id)]
            if run_id:
                query += " AND run_id=?"
                values.append(str(run_id))
            row = self._conn.execute(
                query + " ORDER BY updated_at DESC LIMIT 1", values
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["state"] = json.loads(result["state"])
        result["resumable"] = bool(result["resumable"])
        return result

    def claim_kernel_checkpoint(
        self,
        task_id: str,
        owner_id: str,
        *,
        run_id: Optional[str] = None,
        lease_seconds: float = 60.0,
    ) -> Optional[Dict[str, Any]]:
        """Atomically admit only one worker to a safe, nonterminal continuation."""
        checkpoint = self.get_kernel_checkpoint(task_id, run_id)
        if not checkpoint or not checkpoint["resumable"]:
            return None
        now = time.time()
        owner_pid, owner_started = _process_identity()
        with self._lock:
            if checkpoint.get("owner_id") and not _owner_is_alive(checkpoint):
                self._conn.execute(
                    "UPDATE koto_kernel_checkpoints SET lease_until=0 WHERE task_id=? AND run_id=? AND owner_id=?",
                    (str(task_id), checkpoint["run_id"], checkpoint["owner_id"]),
                )
            cursor = self._conn.execute(
                """UPDATE koto_kernel_checkpoints SET owner_id=?,owner_pid=?,owner_started=?,lease_until=?
                WHERE task_id=? AND run_id=? AND resumable=1
                  AND (owner_id IS NULL OR owner_id='' OR lease_until<=? OR owner_id=?)
                  AND NOT EXISTS(SELECT 1 FROM koto_tasks WHERE task_id=? AND status IN ('completed','failed','cancelled'))
                  AND NOT EXISTS(SELECT 1 FROM koto_task_controls WHERE control_id IN (?,?) AND cancel_requested=1)""",
                (
                    str(owner_id),
                    owner_pid,
                    owner_started,
                    now + max(1.0, float(lease_seconds)),
                    str(task_id),
                    checkpoint["run_id"],
                    now,
                    str(owner_id),
                    str(task_id),
                    str(task_id),
                    checkpoint["run_id"],
                ),
            )
            self._conn.commit()
        return (
            self.get_kernel_checkpoint(task_id, checkpoint["run_id"])
            if cursor.rowcount
            else None
        )

    def renew_kernel_lease(
        self, task_id: str, run_id: str, owner_id: str, *, lease_seconds: float = 60.0
    ) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE koto_kernel_checkpoints SET lease_until=? WHERE task_id=? AND run_id=? AND owner_id=?",
                (
                    time.time() + max(1.0, float(lease_seconds)),
                    str(task_id),
                    str(run_id),
                    str(owner_id),
                ),
            )
            self._conn.commit()
        return bool(cursor.rowcount)

    def release_kernel_checkpoint(
        self, task_id: str, run_id: str, owner_id: str
    ) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE koto_kernel_checkpoints SET owner_id=NULL,lease_until=0 WHERE task_id=? AND run_id=? AND owner_id=?",
                (str(task_id), str(run_id), str(owner_id)),
            )
            self._conn.commit()
        return bool(cursor.rowcount)

    def list_kernel_checkpoints(
        self, *, expired_only: bool = False, limit: int = 100
    ) -> list[Dict[str, Any]]:
        """Find continuations for the existing JobRunner's recovery pass."""
        with self._lock:
            query = """SELECT c.task_id,c.run_id,t.metadata FROM koto_kernel_checkpoints c
            JOIN koto_tasks t ON t.task_id=c.task_id
            WHERE t.status NOT IN ('completed','failed','cancelled')"""
            values: list[Any] = []
            query += " ORDER BY c.updated_at LIMIT ?"
            values.append(max(1, min(1000, int(limit))))
            rows = self._conn.execute(query, values).fetchall()
        checkpoints = []
        for row in rows:
            metadata = json.loads(row["metadata"] or "{}")
            current_run = str(metadata.get("run_id") or "")
            if current_run and current_run != row["run_id"]:
                continue
            checkpoint = self.get_kernel_checkpoint(row["task_id"], row["run_id"])
            if checkpoint:
                checkpoints.append(checkpoint)
        if expired_only:
            now = time.time()
            checkpoints = [
                item
                for item in checkpoints
                if not item.get("owner_id")
                or item.get("lease_until", 0) <= now
                or not _owner_is_alive(item)
            ]
        return checkpoints
