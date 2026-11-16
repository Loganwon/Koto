"""Durable action/observation history. Recovery never replays native commands."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid


def document_scope(host, path):
    if not path:
        return None  # Unsaved documents with equal names must never share history.
    from urllib.parse import unquote

    value = unquote(str(path)).replace("\\", "/").removeprefix("file:///")
    if os.name == "nt":
        value = value.casefold()
    return hashlib.sha256((host + ":" + value).encode("utf-8")).hexdigest()


def default_journal():
    folder = (
        Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
        / "Koto"
        / "Addin"
    )
    return EventJournal(folder / "activity.sqlite3")


class EventJournal:
    def __init__(self, path=":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.doc_locks = {}
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL, scope TEXT NOT NULL, task TEXT NOT NULL, turn TEXT NOT NULL, kind TEXT NOT NULL, action TEXT, at REAL NOT NULL, body TEXT NOT NULL)"
        )
        self.db.execute("CREATE INDEX IF NOT EXISTS scope_events ON events(scope,seq)")
        self.db.commit()

    def record(self, scope, task, turn, kind, body=None, action=None, event_id=None):
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO events(event_id,scope,task,turn,kind,action,at,body) VALUES(?,?,?,?,?,?,?,?)",
                (
                    event_id or uuid.uuid4().hex,
                    scope,
                    task,
                    turn,
                    kind,
                    action,
                    time.time(),
                    json.dumps(body or {}, ensure_ascii=False),
                ),
            )

    @contextmanager
    def document_lock(self, scope):
        with self.lock:
            lock = self.doc_locks.setdefault(scope, threading.RLock())
        with lock:
            yield

    def recovery(self, scope):
        with self.lock:
            rows = self.db.execute(
                "SELECT kind,action,body FROM events WHERE scope=? ORDER BY seq",
                (scope,),
            ).fetchall()
        history, pending, latest = [], {}, None
        for kind, action, body in rows:
            value = json.loads(body)
            if kind == "write_requested":
                pending[action] = value
            elif kind in ("write_verified", "write_rejected"):
                pending.pop(action, None)
            if kind == "write_verified":
                latest = value
            if kind == "turn_completed":
                history.extend(
                    [
                        {"role": "user", "content": value["user"]},
                        {"role": "assistant", "content": value["assistant"]},
                    ]
                )
        return {
            "history": history[-12:],
            "unverified": list(pending.values()),
            "last_verified": latest,
            "replay_allowed": False,
        }

    def close(self):
        with self.lock:
            self.db.close()

    def history_page(self, scope, before=None, query="", limit=20):
        """Read completed exchanges only; browsing never restores executable state."""
        if (
            (before is not None and (type(before) is not int or before < 1))
            or (type(limit) is not int or not 1 <= limit <= 50)
            or not isinstance(query, str)
            or len(query) > 200
        ):
            raise ValueError("invalid history page")
        where = "scope=? AND kind='turn_completed'"
        values = [scope]
        if query.strip():
            where += " AND instr(lower(body),lower(?))>0"
            values.append(query.strip())
        with self.lock:
            total = self.db.execute(
                "SELECT count(*) FROM events WHERE " + where, values
            ).fetchone()[0]
            if before is not None:
                where += " AND seq<?"
                values.append(before)
            rows = self.db.execute(
                "SELECT seq,task,turn,at,body FROM events WHERE "
                + where
                + " ORDER BY seq DESC LIMIT ?",
                values + [limit + 1],
            ).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        return {
            "scope": scope,
            "total": total,
            "next_before": rows[-1][0] if more else None,
            "items": [
                {"id": seq, "task": task, "turn": turn, "at": at, **json.loads(body)}
                for seq, task, turn, at, body in reversed(rows)
            ],
        }
