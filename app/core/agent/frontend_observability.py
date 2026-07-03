# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Frontend observability buffer for MCP supervision tools."""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from collections import Counter, deque
from pathlib import Path
from typing import Any, Dict, Iterable, List

_MAX_EVENTS = 500
_MAX_FILE_LINES = 1000
_MAX_FIELD_CHARS = 4000
_MAX_ACTIONS = 200
_EVENTS: deque[Dict[str, Any]] = deque(maxlen=_MAX_EVENTS)
_ACTIONS: deque[Dict[str, Any]] = deque(maxlen=_MAX_ACTIONS)
_LOCK = threading.RLock()
_ACTION_CONDITION = threading.Condition(_LOCK)
_SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|pwd|token|secret|api[_-]?key|authorization|credential|cookie|session)",
    re.IGNORECASE,
)
_REDACTED = "[redacted]"


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
                _redacted_value(item) if _is_sensitive_key(key) else _trim(item, max_chars)
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
                fh.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
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
    for line in lines[-min(_MAX_FILE_LINES, max(limit * 4, limit)):]:
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
        events = [item for item in events if str(item.get("type", "")).lower() == event_type]
    if session_id:
        events = [item for item in events if str(item.get("session_id", "")) == session_id]
    if level:
        events = [item for item in events if str(item.get("level", "")).lower() == level]
    events = sorted(events, key=lambda item: item.get("server_ts") or 0, reverse=True)
    return {"success": True, "count": len(events), "events": events[:limit]}


def frontend_events(**kwargs: Any) -> Dict[str, Any]:
    return recent_frontend_events(**kwargs)


def frontend_snapshot(limit: int = 80, **_: Any) -> Dict[str, Any]:
    data = recent_frontend_events(limit=limit)
    events = data.get("events", [])
    by_type = Counter(str(item.get("type") or "event") for item in events)
    by_level = Counter(str(item.get("level") or "info") for item in events)
    latest_snapshot = next((item for item in events if item.get("type") == "snapshot"), None)
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
        candidates.append((priority, float(item.get("server_ts") or 0), index, session_id))
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
    **_: Any,
) -> Dict[str, Any]:
    action_name = str(action or "").strip().lower()
    allowed = {
        "click",
        "fill",
        "type",
        "press",
        "snapshot",
        "read_dom",
        "surface_inventory",
        "wait_for",
        "open_panel",
        "search_workspace",
        "submit_prompt",
        "attach_task_file",
        "list_workspace_files",
        "open_workspace_file",
        "current_file_state",
        "read_editor_content",
        "current_selection",
        "document_context",
        "select_text_range",
        "replace_text_selection",
        "set_editor_content",
        "replace_docx_anchor_text",
        "set_pptx_shape_text",
        "save_current_file",
    }
    if action_name not in allowed:
        return {
            "success": False,
            "error": f"Unsupported frontend action: {action_name or '<empty>'}",
            "allowed": sorted(allowed),
        }
    resolved_target_session_id = str(target_session_id or "")[:200]
    if not resolved_target_session_id:
        resolved_target_session_id = str(session_id or "")[:200]
    if not resolved_target_session_id:
        with _LOCK:
            resolved_target_session_id = _latest_frontend_session_id()[:200]
    item = {
        "id": str(uuid.uuid4()),
        "server_ts": time.time(),
        "updated_ts": time.time(),
        "status": "queued",
        "target_session_id": resolved_target_session_id,
        "action": action_name,
        "selector": str(selector or "")[:1000],
        "panel": str(panel or "")[:100],
        "path": str(path or "")[:1000],
        "text": str(text or "")[:2000],
        "value": _trim(str(value or ""), 4000),
        "key": str(key or "")[:100],
        "options": _trim(options or {}),
    }
    with _LOCK:
        _ACTIONS.append(item)
        _ACTION_CONDITION.notify_all()
    if wait_ms:
        waited = wait_frontend_action(action_id=item["id"], timeout_ms=wait_ms)
        waited["queued_action"] = item
        return waited
    return {"success": True, "action": item}


def next_frontend_action(session_id: str = "", timeout_ms: int = 0, **_: Any) -> Dict[str, Any]:
    session_id = str(session_id or "").strip()
    deadline = time.time() + max(0, min(int(timeout_ms or 0), 30000)) / 1000
    with _ACTION_CONDITION:
        while True:
            now = time.time()
            for item in _ACTIONS:
                if item.get("status") != "queued":
                    continue
                target_session_id = str(item.get("target_session_id") or "").strip()
                if target_session_id and session_id and target_session_id != session_id:
                    continue
                if session_id and not target_session_id:
                    item["target_session_id"] = session_id[:200]
                item["status"] = "delivered"
                item["updated_ts"] = now
                return {"success": True, "action": dict(item)}
            remaining = deadline - time.time()
            if remaining <= 0:
                return {"success": True, "action": None}
            _ACTION_CONDITION.wait(timeout=min(remaining, 5.0))


def complete_frontend_action(
    action_id: str = "",
    id: str = "",
    ok: bool = True,
    result: Dict[str, Any] | None = None,
    error: str = "",
    **_: Any,
) -> Dict[str, Any]:
    action_id = str(action_id or id or "")
    with _LOCK:
        for item in _ACTIONS:
            if item.get("id") == action_id:
                item["status"] = "completed" if ok else "failed"
                item["ok"] = bool(ok)
                item["result"] = _trim(result or {})
                item["error"] = str(error or "")[:2000]
                item["updated_ts"] = time.time()
                _ACTION_CONDITION.notify_all()
                return {"success": True, "action": dict(item)}
    return {"success": False, "error": "action not found", "action": None}


def frontend_action_status(action_id: str = "", **_: Any) -> Dict[str, Any]:
    action_id = str(action_id or "")
    with _LOCK:
        actions = list(_ACTIONS)
    if action_id:
        for item in actions:
            if item.get("id") == action_id:
                return {"success": True, "action": item}
        return {"success": False, "error": "action not found", "action": None}
    return {"success": True, "actions": actions[-20:]}


def wait_frontend_action(action_id: str = "", timeout_ms: int = 5000, **_: Any) -> Dict[str, Any]:
    deadline = time.time() + max(0, min(int(timeout_ms or 0), 30000)) / 1000
    with _ACTION_CONDITION:
        while True:
            status = frontend_action_status(action_id=action_id)
            action = status.get("action")
            if action and action.get("status") in {"completed", "failed"}:
                return status
            remaining = deadline - time.time()
            if remaining <= 0:
                return status
            _ACTION_CONDITION.wait(timeout=min(remaining, 0.5))


def frontend_surface_inventory(
    session_id: str = "",
    limit: int = 40,
    wait_ms: int = 0,
    **_: Any,
) -> Dict[str, Any]:
    if not wait_ms:
        events = recent_frontend_events(limit=200, session_id=session_id).get("events", [])
        sessions: Dict[str, Dict[str, Any]] = {}
        for event in events:
            sid = str(event.get("session_id") or "")
            if not sid:
                continue
            details = event.get("details") if isinstance(event.get("details"), dict) else {}
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
