"""Durable browser action handoff using the existing TaskLedger connection.

Dispatch is an uncertain side-effect boundary, not an exactly-once executor.
An expired mutation lease becomes unknown and is never dispatched again.
Only the original browser's delivery capability can attach its real receipt.
"""

from __future__ import annotations

import copy
import hashlib
import json
import posixpath
import secrets
import time
from contextlib import contextmanager

ACTION_DDL = """
CREATE TABLE IF NOT EXISTS koto_frontend_actions (
 action_id TEXT PRIMARY KEY,
 fingerprint TEXT NOT NULL,
 status TEXT NOT NULL,
 browser_id TEXT NOT NULL DEFAULT '',
 document_path TEXT NOT NULL DEFAULT '',
 file_id TEXT NOT NULL DEFAULT '',
 principal_id TEXT NOT NULL DEFAULT '',
 tenant_id TEXT NOT NULL DEFAULT '',
 mutation INTEGER NOT NULL DEFAULT 0,
 payload TEXT NOT NULL,
 result TEXT,
 error TEXT NOT NULL DEFAULT '',
 delivery_token TEXT NOT NULL DEFAULT '',
 lease_until REAL NOT NULL DEFAULT 0,
 created_ts REAL NOT NULL,
 updated_ts REAL NOT NULL,
 expires_at REAL NOT NULL DEFAULT 0,
 redacted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_frontend_actions_queue
 ON koto_frontend_actions(status,browser_id,created_ts);
CREATE INDEX IF NOT EXISTS idx_frontend_actions_document
 ON koto_frontend_actions(document_path,status,mutation);
"""
_FINAL = {"completed", "failed", "expired", "cancelled"}
_MAX_BYTES = 2 * 1024 * 1024


def _dump(value):
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if len(text.encode("utf-8")) > _MAX_BYTES:
        raise ValueError(
            "Browser action or receipt exceeds the 2 MiB persistence limit"
        )
    return text


def _path(value):
    text = str(value or "").strip().replace("\\", "/")
    return posixpath.normpath(text).casefold() if text else ""


class FrontendActionStore:
    """No separate connection, queue worker, or task execution owner."""

    def __init__(self, ledger):
        self.ledger = ledger
        self.conn = ledger._conn
        self.lock = ledger._lock
        with self.lock:
            self.conn.executescript(ACTION_DDL)
            self.conn.commit()

    @contextmanager
    def _transaction(self):
        with self.lock:
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                yield
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise

    def _item(self, row):
        if row is None:
            return None
        item = json.loads(row["payload"])
        item.update(
            id=row["action_id"],
            status=row["status"],
            execution_status=row["status"],
            updated_ts=row["updated_ts"],
            target_session_id=row["browser_id"],
        )
        # Never expose the capability in status/debug APIs; dispatch returns it
        # explicitly to the selected browser, which must persist it with receipt.
        if row["result"] is not None:
            item["result"] = json.loads(row["result"])
            item["ok"] = row["status"] == "completed"
        if row["error"]:
            item["error"] = row["error"]
        if row["redacted"]:
            item["receipt_expired"] = True
        if row["status"] in {"unknown", "dispatched"} and row["mutation"]:
            item["reconciliation_required"] = True
        return item

    def _cancelled(self, item):
        ids = [str(item.get(k) or "") for k in ("task_id", "run_id")]
        return any(self.ledger.is_cancel_requested(key) for key in ids if key)

    def _refresh(self):
        now = time.time()
        rows = self.conn.execute(
            "SELECT * FROM koto_frontend_actions WHERE status IN ('queued','dispatched')"
        ).fetchall()
        for row in rows:
            item = json.loads(row["payload"])
            cancelled = self._cancelled(item)
            if row["status"] == "queued":
                if cancelled or (row["expires_at"] and row["expires_at"] <= now):
                    status = "cancelled" if cancelled else "expired"
                    self.conn.execute(
                        "UPDATE koto_frontend_actions SET status=?,error=?,updated_ts=? WHERE action_id=?",
                        (
                            status,
                            (
                                "Cancelled before dispatch"
                                if cancelled
                                else "Expired before dispatch"
                            ),
                            now,
                            row["action_id"],
                        ),
                    )
            elif cancelled or row["lease_until"] <= now:
                status = (
                    "unknown"
                    if row["mutation"]
                    else ("cancelled" if cancelled else "queued")
                )
                self.conn.execute(
                    "UPDATE koto_frontend_actions SET status=?,error=?,updated_ts=? WHERE action_id=?",
                    (
                        status,
                        (
                            "Browser execution receipt is unknown"
                            if row["mutation"]
                            else ""
                        ),
                        now,
                        row["action_id"],
                    ),
                )

    def queue(self, item):
        item = copy.deepcopy(item)
        serialized = _dump(item)
        fingerprint = str(
            item.get("request_fingerprint")
            or hashlib.sha256(serialized.encode()).hexdigest()
        )
        now = time.time()
        with self._transaction():
            self._refresh()
            existing = self.conn.execute(
                "SELECT * FROM koto_frontend_actions WHERE action_id=?", (item["id"],)
            ).fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint:
                    return {
                        "success": False,
                        "status": "conflict",
                        "error": "operation_id was already used for a different action or trusted scope",
                    }
                return {
                    "success": True,
                    "action": self._item(existing),
                    "duplicate": True,
                }
            if (
                self.conn.execute(
                    "SELECT COUNT(*) FROM koto_frontend_actions WHERE status='queued'"
                ).fetchone()[0]
                >= 500
            ):
                return {
                    "success": False,
                    "status": "busy",
                    "error": "The durable browser action queue is full",
                }
            if item.get("mutation"):
                # Canonical source path is compared across browser incarnations
                # and file IDs; reopening a document cannot bypass unknown work.
                unresolved = self.conn.execute(
                    "SELECT * FROM koto_frontend_actions WHERE mutation=1 AND status IN ('dispatched','unknown') AND tenant_id=? AND principal_id=?",
                    (
                        str(item.get("tenant_id") or ""),
                        str(item.get("principal_id") or ""),
                    ),
                ).fetchall()
                for row in unresolved:
                    same_document = (
                        not _path(item.get("document_path"))
                        or not row["document_path"]
                        or _path(item.get("document_path")) == row["document_path"]
                        or (item.get("file_id") and item["file_id"] == row["file_id"])
                    )
                    if same_document:
                        return {
                            "success": False,
                            "status": "blocked",
                            "pending_action_id": row["action_id"],
                            "error": "Document mutation has no confirmed receipt; inspect its status before another write",
                        }
            status = "cancelled" if self._cancelled(item) else "queued"
            self.conn.execute(
                """INSERT INTO koto_frontend_actions
                (action_id,fingerprint,status,browser_id,document_path,file_id,principal_id,tenant_id,mutation,payload,created_ts,updated_ts,expires_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    item["id"],
                    fingerprint,
                    status,
                    str(item.get("target_session_id") or ""),
                    _path(item.get("document_path")),
                    str(item.get("file_id") or ""),
                    str(item.get("principal_id") or ""),
                    str(item.get("tenant_id") or ""),
                    int(bool(item.get("mutation"))),
                    serialized,
                    now,
                    now,
                    float(item.get("expires_at") or 0),
                ),
            )
            return {
                "success": True,
                "action": self._item(
                    self.conn.execute(
                        "SELECT * FROM koto_frontend_actions WHERE action_id=?",
                        (item["id"],),
                    ).fetchone()
                ),
            }

    def get(self, action_id):
        with self._transaction():
            self._refresh()
            return self._item(
                self.conn.execute(
                    "SELECT * FROM koto_frontend_actions WHERE action_id=?",
                    (str(action_id),),
                ).fetchone()
            )

    def list_recent(self, limit=20):
        with self._transaction():
            self._refresh()
            return [
                self._item(row)
                for row in self.conn.execute(
                    "SELECT * FROM koto_frontend_actions ORDER BY created_ts DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
            ]

    def dispatch(self, browser_id, *, lease_seconds=30):
        if not browser_id:
            return None
        with self._transaction():
            self._refresh()
            candidates = self.conn.execute(
                "SELECT * FROM koto_frontend_actions WHERE status='queued' AND (browser_id=? OR browser_id='') ORDER BY created_ts",
                (str(browser_id),),
            ).fetchall()
            row = None
            for candidate in candidates:
                if candidate["mutation"]:
                    pending = self.conn.execute(
                        """SELECT 1 FROM koto_frontend_actions WHERE mutation=1
                        AND status IN ('dispatched','unknown') AND tenant_id=? AND principal_id=?
                        AND (document_path='' OR ?='' OR document_path=? OR (file_id<>'' AND file_id=?)) LIMIT 1""",
                        (
                            candidate["tenant_id"],
                            candidate["principal_id"],
                            candidate["document_path"],
                            candidate["document_path"],
                            candidate["file_id"],
                        ),
                    ).fetchone()
                    if pending:
                        continue
                row = candidate
                break
            if not row:
                return None
            token = secrets.token_urlsafe(32)
            self.conn.execute(
                "UPDATE koto_frontend_actions SET status='dispatched',browser_id=?,delivery_token=?,lease_until=?,updated_ts=? WHERE action_id=?",
                (
                    browser_id,
                    token,
                    time.time() + max(1, float(lease_seconds)),
                    time.time(),
                    row["action_id"],
                ),
            )
            item = self._item(
                self.conn.execute(
                    "SELECT * FROM koto_frontend_actions WHERE action_id=?",
                    (row["action_id"],),
                ).fetchone()
            )
            item.update(delivery_token=token, browser_id=browser_id)
            return item

    def complete(
        self,
        action_id,
        *,
        browser_id,
        delivery_token,
        ok,
        result,
        error="",
        unknown=False,
        request_id="",
        session_id="",
    ):
        receipt = _dump(result or {})
        with self._transaction():
            self._refresh()
            row = self.conn.execute(
                "SELECT * FROM koto_frontend_actions WHERE action_id=?",
                (str(action_id),),
            ).fetchone()
            if row is None:
                return {
                    "success": False,
                    "error": "action not found",
                    "http_status": 404,
                    "action": None,
                }
            if (
                not browser_id
                or browser_id != row["browser_id"]
                or not delivery_token
                or not secrets.compare_digest(
                    str(delivery_token), row["delivery_token"]
                )
            ):
                return {
                    "success": False,
                    "error": "Browser or delivery capability does not match the dispatched action",
                    "http_status": 403,
                }
            item = json.loads(row["payload"])
            if item.get("request_id") and (
                str(request_id) != item["request_id"]
                or str(session_id) != str(item.get("session_id") or "")
            ):
                return {
                    "success": False,
                    "error": "Receipt request or conversation identity does not match the trusted action",
                    "http_status": 403,
                }
            if row["status"] in _FINAL:
                if row["status"] in {"completed", "failed"}:
                    return {
                        "success": True,
                        "duplicate": True,
                        "action": self._item(row),
                    }
                return {
                    "success": False,
                    "error": "Action was not dispatched or is no longer executable",
                    "http_status": 410,
                    "action": self._item(row),
                }
            if row["status"] not in {"dispatched", "unknown"}:
                return {
                    "success": False,
                    "error": "A queued action cannot have an execution receipt",
                    "http_status": 409,
                }
            # A failure after a real edit/save is still an unknown commit result,
            # not permission to try the same mutation under another ID.
            if (
                ok
                and item.get("request_id")
                and item.get("action")
                in {"ui_read_context", "ui_apply_edit", "ui_save"}
                and not unknown
            ):
                if (
                    _path((result or {}).get("document_path")) != row["document_path"]
                    or str((result or {}).get("file_id") or "") != row["file_id"]
                ):
                    return {
                        "success": False,
                        "error": "Receipt document identity does not match the trusted action",
                        "http_status": 409,
                    }
            uncertain = (
                unknown
                or (result or {}).get("execution_unknown") is True
                or (
                    not ok
                    and bool(row["mutation"])
                    and any(
                        (result or {}).get(k) is True for k in ("applied", "persisted")
                    )
                )
            )
            if ok and item.get("request_id") and item.get("action") == "ui_apply_edit":
                uncertain = uncertain or not (
                    (result or {}).get("applied") is True
                    and (result or {}).get("revision_after")
                    and (result or {}).get("revision_before")
                    == (item.get("options") or {}).get("expected_revision")
                )
            if ok and item.get("request_id") and item.get("action") == "ui_save":
                uncertain = uncertain or not (
                    (result or {}).get("persisted") is True
                    and (result or {}).get("raw_sha256")
                    and (result or {}).get("revision")
                    == (item.get("options") or {}).get("expected_revision")
                )
            state = "unknown" if uncertain else ("completed" if ok else "failed")
            self.conn.execute(
                "UPDATE koto_frontend_actions SET status=?,result=?,error=?,updated_ts=? WHERE action_id=?",
                (state, receipt, str(error or "")[:4000], time.time(), str(action_id)),
            )
            return {
                "success": True,
                "action": self._item(
                    self.conn.execute(
                        "SELECT * FROM koto_frontend_actions WHERE action_id=?",
                        (str(action_id),),
                    ).fetchone()
                ),
            }

    def expire(self, action_id):
        with self._transaction():
            self.conn.execute(
                "UPDATE koto_frontend_actions SET status='expired',error='Frontend did not acknowledge before timeout',updated_ts=? WHERE action_id=? AND status='queued'",
                (time.time(), str(action_id)),
            )

    def purge(self, keep_days=7):
        """Erase old document contents, retain dedup tombstones and unknown work."""
        cutoff = time.time() - max(1, int(keep_days)) * 86400
        with self._transaction():
            rows = self.conn.execute(
                "SELECT * FROM koto_frontend_actions WHERE status IN ('completed','failed','expired','cancelled') AND updated_ts<? AND redacted=0",
                (cutoff,),
            ).fetchall()
            for row in rows:
                old = json.loads(row["payload"])
                tombstone = {
                    key: old.get(key)
                    for key in (
                        "id",
                        "action",
                        "request_id",
                        "session_id",
                        "operation_id",
                        "operation_namespace",
                        "task_id",
                        "run_id",
                        "document_path",
                        "file_id",
                        "target_session_id",
                    )
                }
                self.conn.execute(
                    "UPDATE koto_frontend_actions SET payload=?,result=NULL,error='',redacted=1 WHERE action_id=?",
                    (_dump(tombstone), row["action_id"]),
                )
            unresolved = self.conn.execute(
                "SELECT * FROM koto_frontend_actions WHERE status='unknown' AND updated_ts<? AND redacted=0",
                (time.time() - 30 * 86400,),
            ).fetchall()
            for row in unresolved:
                old = json.loads(row["payload"])
                kept = {
                    key: old.get(key)
                    for key in (
                        "id",
                        "action",
                        "request_id",
                        "session_id",
                        "tenant_id",
                        "principal_id",
                        "operation_id",
                        "operation_namespace",
                        "task_id",
                        "run_id",
                        "document_path",
                        "file_id",
                        "target_session_id",
                    )
                }
                kept["options"] = {
                    key: (old.get("options") or {}).get(key)
                    for key in ("expected_revision", "expected_source_sha256")
                }
                self.conn.execute(
                    "UPDATE koto_frontend_actions SET payload=?,result=NULL,redacted=1 WHERE action_id=?",
                    (_dump(kept), row["action_id"]),
                )
            return len(rows)
