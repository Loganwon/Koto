# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""MCP WebSocket session store — shared between web layer and app layer."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict

_SESSIONS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.RLock()


def register_session(session_id: str) -> None:
    with _LOCK:
        _SESSIONS[session_id] = {
            "session_id": session_id,
            "connected_at": time.time(),
            "last_seen_at": time.time(),
            "initialized": False,
            "client_info": {},
        }


def unregister_session(session_id: str) -> None:
    with _LOCK:
        _SESSIONS.pop(session_id, None)


def mark_initialized(session_id: str, client_info: Dict[str, Any] | None = None) -> None:
    with _LOCK:
        session = _SESSIONS.setdefault(
            session_id,
            {
                "session_id": session_id,
                "connected_at": time.time(),
                "last_seen_at": time.time(),
            },
        )
        session["initialized"] = True
        session["client_info"] = client_info or {}
        session["last_seen_at"] = time.time()


def _is_external_session(session: Dict[str, Any]) -> bool:
    client = session.get("client_info") or {}
    name = str(client.get("name") or "").lower()
    return name not in {"koto-ui", "koto", "koto-frontend"}


def get_mcp_ws_status() -> Dict[str, Any]:
    with _LOCK:
        sessions = [dict(item) for item in _SESSIONS.values()]
    external = [item for item in sessions if _is_external_session(item)]
    for item in sessions:
        client = item.get("client_info") or {}
        item["client_name"] = client.get("name", "")
    for item in external:
        client = item.get("client_info") or {}
        item["client_name"] = client.get("name", "")
    return {
        "success": True,
        "active_session_count": len(sessions),
        "active_external_session_count": len(external),
        "sessions": sessions,
        "external_sessions": external,
    }
