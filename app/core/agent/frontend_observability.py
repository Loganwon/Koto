# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Frontend observability buffer for MCP supervision tools."""

from __future__ import annotations

import copy
import hashlib
import json
import posixpath
import re
import threading
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass, fields, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, Iterable, List

from app.core.tasks.frontend_action_store import FrontendActionStore
from app.core.tasks.task_ledger import get_ledger

_MAX_EVENTS = 500
_MAX_FILE_LINES = 1000
_MAX_FIELD_CHARS = 4000
_MAX_ACTIONS = 200
_EVENTS: deque[Dict[str, Any]] = deque(maxlen=_MAX_EVENTS)
_ACTIONS: deque[Dict[str, Any]] = deque(maxlen=_MAX_ACTIONS)
# Compatibility projections for supervision; SQLite is the deduplication owner.
_DOCUMENT_OPERATION_LEDGER: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.RLock()
_ACTION_CONDITION = threading.Condition(_LOCK)
_DOCUMENT_ACTIONS = {"ui_read_context", "ui_apply_edit", "ui_save"}
_DOCUMENT_MUTATIONS = {"ui_apply_edit", "ui_save"}
_READ_ONLY_ACTIONS = {
    "snapshot",
    "read_dom",
    "task_result_evidence",
    "surface_inventory",
    "wait_for",
    "list_workspace_files",
    "current_file_state",
    "read_editor_content",
    "current_selection",
    "document_context",
    "ui_read_context",
}
_SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|pwd|token|secret|api[_-]?key|authorization|credential|cookie|session)",
    re.IGNORECASE,
)
_REDACTED = "[redacted]"


def _action_store() -> FrontendActionStore:
    ledger = get_ledger()
    with ledger._lock:
        store = getattr(ledger, "_frontend_action_store", None)
        if store is None:
            store = FrontendActionStore(ledger)
            ledger._frontend_action_store = store
        if time.time() >= getattr(store, "_next_retention_check", 0):
            store.purge()
            store._next_retention_check = time.time() + 86400
        return store


def _action_view(item):
    if item is None:
        return None
    item = copy.deepcopy(item)
    if item.get("status") == "dispatched":
        item["status"] = "delivered"  # compatibility transport spelling
    return item


def _remember_action(item, *, append=True):
    """The small supervision feed is a projection, never the dedup owner."""
    if not item:
        return
    view = _action_view(item)
    view.pop("delivery_token", None)
    with _LOCK:
        existing = next(
            (entry for entry in _ACTIONS if entry["id"] == item["id"]), None
        )
        if existing is None:
            if append:
                _ACTIONS.append(view)
        else:
            existing.clear()
            existing.update(view)
        if item.get("action") in _DOCUMENT_MUTATIONS:
            _DOCUMENT_OPERATION_LEDGER[item["id"]] = view
            if len(_DOCUMENT_OPERATION_LEDGER) > 2000:
                _DOCUMENT_OPERATION_LEDGER.pop(next(iter(_DOCUMENT_OPERATION_LEDGER)))
        _ACTION_CONDITION.notify_all()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _event_log_path() -> Path:
    return _project_root() / "logs" / "frontend_observability.jsonl"


def _is_sensitive_key(key: Any) -> bool:
    return bool(_SENSITIVE_KEY_RE.search(str(key or "")))


def _redacted_value(value: Any) -> Any:
    if value in ("", None, False):
        return value
    return _REDACTED


def _trim(value: Any, max_chars: int = _MAX_FIELD_CHARS) -> Any:
    if isinstance(value, str):
        return value[:max_chars]
    if isinstance(value, list):
        return [_trim(item, max_chars) for item in value[:50]]
    if isinstance(value, dict):
        trimmed: Dict[str, Any] = {}
        for key, item in list(value.items())[:80]:
            safe_key = str(key)[:120]
            trimmed[safe_key] = (
                _redacted_value(item)
                if _is_sensitive_key(key)
                else _trim(item, max_chars)
            )
        return trimmed
    return value


def _normalize_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    now = time.time()
    event_type = str(payload.get("type") or payload.get("event_type") or "event")
    level = str(payload.get("level") or "info").lower()
    return {
        "id": str(payload.get("id") or uuid.uuid4()),
        "server_ts": now,
        "client_ts": payload.get("client_ts") or payload.get("timestamp"),
        "type": event_type[:80],
        "level": level[:30],
        "message": _trim(payload.get("message") or "", 2000),
        "url": _trim(payload.get("url") or "", 1000),
        "route": _trim(payload.get("route") or "", 500),
        "session_id": _trim(payload.get("session_id") or "", 200),
        "source": _trim(payload.get("source") or "browser", 80),
        "details": _trim(payload.get("details") or {}),
    }


def _append_file(events: Iterable[Dict[str, Any]]) -> None:
    path = _event_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for event in events:
                fh.write(
                    json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
                )
    except Exception:
        return


def _load_recent_from_file(limit: int) -> List[Dict[str, Any]]:
    path = _event_log_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    events: List[Dict[str, Any]] = []
    for line in lines[-min(_MAX_FILE_LINES, max(limit * 4, limit)) :]:
        try:
            events.append(json.loads(line))
        except Exception:
            continue
    return events[-limit:]


def record_frontend_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    event = _normalize_event(payload or {})
    with _LOCK:
        _EVENTS.append(event)
    _append_file([event])
    return event


def record_frontend_events(payloads: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    events = [_normalize_event(payload or {}) for payload in payloads]
    if not events:
        return []
    with _LOCK:
        _EVENTS.extend(events)
    _append_file(events)
    return events


def recent_frontend_events(
    limit: int = 50,
    event_type: str = "",
    type: str = "",
    session_id: str = "",
    level: str = "",
    **_: Any,
) -> Dict[str, Any]:
    limit = max(1, min(int(limit or 50), 200))
    event_type = (event_type or type or "").strip().lower()
    session_id = (session_id or "").strip()
    level = (level or "").strip().lower()
    with _LOCK:
        events = list(_EVENTS)
    if len(events) < limit:
        merged = _load_recent_from_file(limit)
        known = {item.get("id") for item in events}
        events = [item for item in merged if item.get("id") not in known] + events
    if event_type:
        events = [
            item for item in events if str(item.get("type", "")).lower() == event_type
        ]
    if session_id:
        events = [
            item for item in events if str(item.get("session_id", "")) == session_id
        ]
    if level:
        events = [
            item for item in events if str(item.get("level", "")).lower() == level
        ]
    events = sorted(events, key=lambda item: item.get("server_ts") or 0, reverse=True)
    return {"success": True, "count": len(events), "events": events[:limit]}


def frontend_events(**kwargs: Any) -> Dict[str, Any]:
    return recent_frontend_events(**kwargs)


def frontend_snapshot(limit: int = 80, **_: Any) -> Dict[str, Any]:
    data = recent_frontend_events(limit=limit)
    events = data.get("events", [])
    by_type = Counter(str(item.get("type") or "event") for item in events)
    by_level = Counter(str(item.get("level") or "info") for item in events)
    latest_snapshot = next(
        (item for item in events if item.get("type") == "snapshot"), None
    )
    problem_types = {"console", "runtime_error", "unhandled_rejection", "network"}
    problems = [
        item
        for item in events
        if item.get("type") in problem_types
        or item.get("level") in {"error", "warn", "warning"}
    ][:20]
    return {
        "success": True,
        "event_count": len(events),
        "by_type": dict(by_type),
        "by_level": dict(by_level),
        "latest_snapshot": latest_snapshot,
        "recent_problems": problems,
    }


def clear_frontend_events(**_: Any) -> Dict[str, Any]:
    with _LOCK:
        count = len(_EVENTS)
        _EVENTS.clear()
        _ACTIONS.clear()
        _DOCUMENT_OPERATION_LEDGER.clear()
        _ACTION_CONDITION.notify_all()
    try:
        path = _event_log_path()
        if path.exists():
            path.write_text("", encoding="utf-8")
    except Exception:
        pass
    return {"success": True, "cleared": count}


def _latest_frontend_session_id() -> str:
    now = time.time()
    recent_actions = [
        (
            float(item.get("updated_ts") or item.get("server_ts") or 0),
            str(item.get("target_session_id") or "").strip(),
        )
        for item in list(_ACTIONS)
        if item.get("status") in {"delivered", "completed"}
        and str(item.get("target_session_id") or "").strip()
    ]
    if recent_actions:
        recent_actions.sort(reverse=True)
        action_ts, action_session_id = recent_actions[0]
        if now - action_ts <= 60:
            return action_session_id

    candidates: List[tuple[int, float, int, str]] = []
    for index, item in enumerate(list(_EVENTS)):
        session_id = str(item.get("session_id") or "").strip()
        if not session_id:
            continue
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        visibility = str(details.get("visibilityState") or "").lower()
        age = now - float(item.get("server_ts") or 0)
        if age > 300:
            continue
        priority = 2 if visibility == "visible" else 1
        if item.get("type") == "snapshot":
            priority += 1
        candidates.append(
            (priority, float(item.get("server_ts") or 0), index, session_id)
        )
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    return candidates[0][3]


def enqueue_frontend_action(
    action: str = "",
    session_id: str = "",
    selector: str = "",
    panel: str = "",
    path: str = "",
    text: str = "",
    value: str = "",
    key: str = "",
    target_session_id: str = "",
    options: Dict[str, Any] | None = None,
    wait_ms: int = 0,
    action_id: str = "",
    expires_after_ms: int = 0,
    trusted_scope=None,
    operation_id: str = "",
    **_: Any,
) -> Dict[str, Any]:
    from collections.abc import Mapping

    action_name = str(action or "").strip().lower()
    if not isinstance(options or {}, dict):
        return {"success": False, "error": "Frontend action options must be an object"}
    allowed = _READ_ONLY_ACTIONS | {
        "click",
        "fill",
        "type",
        "press",
        "open_panel",
        "search_workspace",
        "submit_prompt",
        "attach_task_file",
        "open_workspace_file",
        "select_text_range",
        "replace_text_selection",
        "set_editor_content",
        "replace_docx_anchor_text",
        "set_pptx_shape_text",
        "save_current_file",
        *_DOCUMENT_ACTIONS,
    }
    if action_name not in allowed:
        return {
            "success": False,
            "error": f"Unsupported frontend action: {action_name or '<empty>'}",
            "allowed": sorted(allowed),
        }
    scope = dict(trusted_scope) if isinstance(trusted_scope, Mapping) else {}
    target = str(
        scope.get("frontend_session_id") or target_session_id or session_id or ""
    )[:200]
    if not target:
        with _LOCK:
            target = _latest_frontend_session_id()[:200]
    now = time.time()
    item = {
        "id": str(action_id or uuid.uuid4()),
        "server_ts": now,
        "updated_ts": now,
        "status": "queued",
        "target_session_id": target,
        "action": action_name,
        "selector": str(selector or "")[:1000],
        "panel": str(panel or "")[:100],
        "path": str(scope.get("document_path") or path or "")[:4000],
        "text": str(text or ""),
        "value": str(value or ""),
        "key": str(key or "")[:100],
        # Document anchors, undo receipts and complete before/after text must
        # never be silently truncated by the telemetry redactor.
        "options": copy.deepcopy(options or {}),
        "mutation": action_name not in _READ_ONLY_ACTIONS,
        "request_id": str(scope.get("request_id") or ""),
        "session_id": str(scope.get("session_id") or ""),
        "tenant_id": str(scope.get("tenant_id") or ""),
        "principal_id": str(scope.get("principal_id") or ""),
        "task_id": str(scope.get("task_id") or ""),
        "run_id": str(scope.get("run_id") or ""),
        "document_path": str(
            scope.get("document_path")
            or path
            or (options or {}).get("document_path")
            or ""
        ),
        "file_id": str(scope.get("file_id") or (options or {}).get("file_id") or ""),
        "operation_id": str(operation_id or ""),
    }
    item["operation_namespace"] = hashlib.sha256(
        json.dumps(
            [
                item[k]
                for k in (
                    "request_id",
                    "session_id",
                    "target_session_id",
                    "document_path",
                    "file_id",
                    "operation_id",
                )
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    if expires_after_ms:
        item["expires_at"] = now + max(1, min(int(expires_after_ms), 30000)) / 1000
    immutable = {
        k: v
        for k, v in item.items()
        if k not in {"id", "status", "server_ts", "updated_ts", "expires_at"}
    }
    item["request_fingerprint"] = hashlib.sha256(
        json.dumps(immutable, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    try:
        queued = _action_store().queue(item)
    except (ValueError, TypeError) as exc:
        return {"success": False, "error": str(exc)}
    if not queued.get("success"):
        return queued
    _remember_action(queued["action"], append=not queued.get("duplicate"))
    queued["action"] = _action_view(queued["action"])
    if wait_ms:
        waited = wait_frontend_action(action_id=item["id"], timeout_ms=wait_ms)
        waited["queued_action"] = queued["action"]
        return waited
    return queued


def next_frontend_action(
    session_id: str = "", timeout_ms: int = 0, **_: Any
) -> Dict[str, Any]:
    browser_id = str(session_id or "").strip()
    deadline = time.monotonic() + max(0, min(int(timeout_ms or 0), 30000)) / 1000
    while True:
        item = _action_store().dispatch(browser_id)
        if item is not None:
            _remember_action(item)
            return {"success": True, "action": _action_view(item)}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {"success": True, "action": None}
        # Poll the durable owner across workers; notification is only a hint.
        with _ACTION_CONDITION:
            _ACTION_CONDITION.wait(timeout=min(remaining, 0.25))


def complete_frontend_action(
    action_id: str = "",
    id: str = "",
    ok: bool = True,
    result: Dict[str, Any] | None = None,
    error: str = "",
    browser_id: str = "",
    delivery_token: str = "",
    unknown: bool = False,
    **_: Any,
) -> Dict[str, Any]:
    if not isinstance(result or {}, dict):
        return {
            "success": False,
            "http_status": 400,
            "error": "A browser receipt must be an object",
        }
    try:
        completed = _action_store().complete(
            str(action_id or id or ""),
            browser_id=str(browser_id or ""),
            delivery_token=str(delivery_token or ""),
            ok=ok is True,
            result=result or {},
            error=error,
            unknown=unknown is True,
            request_id=str(_.get("request_id") or ""),
            session_id=str(_.get("session_id") or ""),
        )
    except (TypeError, ValueError) as exc:
        return {"success": False, "http_status": 400, "error": str(exc)}
    if completed.get("action"):
        _remember_action(completed["action"])
        completed["action"] = _action_view(completed["action"])
    return completed


def frontend_action_status(
    action_id: str = "", trusted_scope=None, **_: Any
) -> Dict[str, Any]:
    item = _action_store().get(str(action_id)) if action_id else None
    if action_id and item is None:
        return {"success": False, "error": "action not found", "action": None}
    if item is not None and trusted_scope is not None:
        from collections.abc import Mapping

        if not isinstance(trusted_scope, Mapping):
            return {
                "success": False,
                "error": "Trusted request scope is required",
                "action": None,
            }
        expected = {
            "request_id": trusted_scope.get("request_id"),
            "session_id": trusted_scope.get("session_id"),
            "target_session_id": trusted_scope.get("frontend_session_id"),
            "file_id": trusted_scope.get("file_id"),
            "tenant_id": trusted_scope.get("tenant_id"),
            "principal_id": trusted_scope.get("principal_id"),
        }
        if any(
            str(value or "") != str(item.get(key) or "")
            for key, value in expected.items()
        ) or _document_path(item.get("document_path")) != _document_path(
            trusted_scope.get("document_path")
        ):
            return {
                "success": False,
                "error": "Action belongs to a different trusted request or document scope",
                "action": None,
            }
    if item:
        _remember_action(item, append=False)
        return {"success": True, "action": _action_view(item)}
    return {
        "success": True,
        "actions": [_action_view(entry) for entry in _action_store().list_recent()],
    }


def wait_frontend_action(
    action_id: str = "", timeout_ms: int = 5000, **_: Any
) -> Dict[str, Any]:
    deadline = time.monotonic() + max(0, min(int(timeout_ms or 0), 30000)) / 1000
    while True:
        status = frontend_action_status(action_id=action_id)
        action = status.get("action")
        if not action or action.get("status") in {
            "completed",
            "failed",
            "expired",
            "cancelled",
            "unknown",
        }:
            return status
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if (
                action.get("status") == "queued"
                and action.get("action") in _DOCUMENT_ACTIONS
            ):
                _action_store().expire(action_id)
                status = frontend_action_status(action_id=action_id)
            return {**status, "timed_out": True, "completed": False}
        with _ACTION_CONDITION:
            _ACTION_CONDITION.wait(timeout=min(remaining, 0.25))


def frontend_surface_inventory(
    session_id: str = "",
    limit: int = 40,
    wait_ms: int = 0,
    **_: Any,
) -> Dict[str, Any]:
    if not wait_ms:
        events = recent_frontend_events(limit=200, session_id=session_id).get(
            "events", []
        )
        sessions: Dict[str, Dict[str, Any]] = {}
        for event in events:
            sid = str(event.get("session_id") or "")
            if not sid:
                continue
            details = (
                event.get("details") if isinstance(event.get("details"), dict) else {}
            )
            item = sessions.setdefault(sid, {"session_id": sid, "event_count": 0})
            item["event_count"] += 1
            item["last_event_type"] = event.get("type")
            item["last_seen"] = event.get("server_ts")
            if details:
                item["details"] = details
                if "visibilityState" in details:
                    item["visibilityState"] = details.get("visibilityState")
        ordered = sorted(
            sessions.values(),
            key=lambda item: float(item.get("last_seen") or 0),
            reverse=True,
        )
        return {
            "success": True,
            "session_count": len(ordered),
            "sessions": ordered[: max(1, min(int(limit or 40), 100))],
        }
    queued = enqueue_frontend_action(
        action="surface_inventory",
        target_session_id=session_id,
        options={"limit": max(1, min(int(limit or 40), 100))},
    )
    action = queued.get("action") or {}
    if wait_ms and action.get("id"):
        waited = wait_frontend_action(action_id=action["id"], timeout_ms=wait_ms)
        waited["queued_action"] = action
        return waited
    return {"success": True, "surface_inventory": queued}


def _document_path(value: Any) -> str:
    """Compare exact document identities; never use suffix/path guessing."""
    text = str(value or "").strip().replace("\\", "/")
    return posixpath.normpath(text).casefold() if text else ""


def bind_frontend_document_context(
    base_context, frontend_scope, *, session_id: str = ""
):
    """Bind a host context only to a recently observed browser/document pair.

    Request scope is transport metadata, not model arguments. Client supplied
    permissions are ignored; supported operations are fixed by the host.
    Missing/stale or mismatched metadata leaves the original context unchanged.
    """
    from app.core.agent.plugin_protocol.lifecycle import AddonInvocationContext

    if not isinstance(frontend_scope, dict):
        return base_context
    browser_id = str(frontend_scope.get("frontend_session_id") or "").strip()
    path = str(frontend_scope.get("document_path") or "").strip()
    file_id = str(frontend_scope.get("file_id") or "").strip()
    if not browser_id or not path or not file_id:
        return base_context
    now = time.time()
    with _LOCK:
        snapshot = next(
            (
                event
                for event in reversed(_EVENTS)
                if event.get("type") == "snapshot"
                and event.get("session_id") == browser_id
                and now - float(event.get("server_ts") or 0) <= 120
            ),
            None,
        )
    workspace = ((snapshot or {}).get("details") or {}).get("workspace") or {}
    observed_path = (
        workspace.get("activeTabPath") or workspace.get("wsSourcePath") or ""
    )
    observed_id = (
        workspace.get("fileId")
        or (workspace.get("activeTab") or {}).get("fileId")
        or ""
    )
    if _document_path(path) != _document_path(observed_path) or file_id != str(
        observed_id
    ):
        return base_context
    if base_context is not None and not isinstance(
        base_context, AddonInvocationContext
    ):
        return base_context
    base = base_context or AddonInvocationContext(
        request_id=str(uuid.uuid4()),
        session_id=session_id,
        tenant_id="local",
        principal_id="local-user",
        purpose_code="document_task",
    )
    kind = str(workspace.get("fileType") or "").lower()
    operations = (
        ("read", "edit", "save")
        if kind in {"docx", "text", "code", "txt", "md"}
        else ("read",)
    )
    scope = MappingProxyType(
        {
            "frontend_session_id": browser_id,
            "document_path": path,
            "file_id": file_id,
            "file_type": kind,
            "allowed_operations": operations,
        }
    )
    return _scoped_context_type()(
        **{
            field.name: getattr(base, field.name)
            for field in fields(AddonInvocationContext)
        },
        frontend_document_scope=scope,
    )


_SCOPED_CONTEXT_TYPE = None


def _scoped_context_type():
    global _SCOPED_CONTEXT_TYPE
    if _SCOPED_CONTEXT_TYPE is None:
        from app.core.agent.plugin_protocol.lifecycle import AddonInvocationContext

        @dataclass(frozen=True)
        class FrontendDocumentInvocationContext(AddonInvocationContext):
            frontend_document_scope: Any = None
            task_id: str = ""
            run_id: str = ""

        _SCOPED_CONTEXT_TYPE = FrontendDocumentInvocationContext
    return _SCOPED_CONTEXT_TYPE


def bind_frontend_run_context(context, *, task_id: str, run_id: str):
    """Attach the real Kernel run identity to an already host-bound scope."""
    if not isinstance(context, _scoped_context_type()):
        return context
    return replace(context, task_id=str(task_id or ""), run_id=str(run_id or ""))
