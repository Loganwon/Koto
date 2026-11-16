"""Durable host-owned audit log for Addon lifecycle and contribution calls."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.core.config.runtime_storage import (
    legacy_config_path,
    prepare_runtime_database,
    runtime_database_path,
)


def _default_path() -> Path:
    configured = os.environ.get("KOTO_ADDON_AUDIT_DB_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return prepare_runtime_database(
        runtime_database_path("addon_audit.sqlite"),
        legacy_paths=(legacy_config_path("addon_audit.sqlite"),),
    )


class AddonAuditStore:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path).resolve() if path else _default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.path), check_same_thread=False, timeout=30.0
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS addon_audit_events (
                event_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                plugin_id TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_addon_audit_created "
            "ON addon_audit_events(created_at)"
        )
        self._conn.commit()

    def append(self, event: Mapping[str, Any]) -> str:
        payload = dict(event or {})
        event_id = str(payload.get("event_id") or uuid.uuid4())
        created_at = str(
            payload.get("created_at") or datetime.now(timezone.utc).isoformat()
        )
        event_type = str(payload.get("event") or "addon.unknown")[:160]
        plugin_id = str(payload.get("plugin_id") or "")[:160]
        correlation_id = str(payload.get("correlation_id") or "")[:200]
        payload.update({"event_id": event_id, "created_at": created_at})
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._conn.execute(
                """INSERT INTO addon_audit_events
                   (event_id, created_at, event_type, plugin_id,
                    correlation_id, payload)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    event_id,
                    created_at,
                    event_type,
                    plugin_id,
                    correlation_id,
                    encoded,
                ),
            )
            self._conn.commit()
        return event_id

    def list_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit or 100), 1000))
        with self._lock:
            rows = self._conn.execute(
                """SELECT payload FROM addon_audit_events
                   ORDER BY created_at DESC LIMIT ?""",
                (safe_limit,),
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]


_store: AddonAuditStore | None = None
_store_lock = threading.Lock()


def get_addon_audit_store() -> AddonAuditStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = AddonAuditStore()
        return _store


def set_addon_audit_store(store: AddonAuditStore | None) -> None:
    global _store
    with _store_lock:
        _store = store


__all__ = ["AddonAuditStore", "get_addon_audit_store", "set_addon_audit_store"]
