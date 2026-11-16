# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""MCP Session Manager — extends the basic session store with lifecycle management."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from app.core.mcp.session_store import (
    _LOCK,
    _SESSIONS,
    mark_initialized,
    register_session,
    unregister_session,
)
from app.core.mcp.types import SessionInfo, TransportKind

logger = logging.getLogger(__name__)

# Session TTL in seconds
DEFAULT_SESSION_TTL = 300  # 5 minutes


class MCPSessionManager:
    """Manages MCP session lifecycle: creation, tracking, expiration, cleanup."""

    def __init__(self, ttl_seconds: float = DEFAULT_SESSION_TTL):
        self._ttl = ttl_seconds
        self._heartbeats: Dict[str, float] = {}

    # ── CRUD ────────────────────────────────────────────────────────────────

    def create_session(
        self,
        session_id: Optional[str] = None,
        transport_kind: TransportKind = "websocket",
    ) -> str:
        """Create and register a new session."""
        import uuid

        session_id = session_id or str(uuid.uuid4())
        register_session(session_id)
        with _LOCK:
            session = _SESSIONS.get(session_id, {})
            session["transport_kind"] = transport_kind
        self._heartbeats[session_id] = time.time()
        logger.debug("[MCPSessionManager] created session: %s", session_id)
        return session_id

    def initialize_session(
        self,
        session_id: str,
        client_info: Optional[Dict[str, Any]] = None,
        server_info: Optional[Dict[str, Any]] = None,
        protocol_version: str = "2024-11-05",
    ) -> None:
        """Mark a session as initialized with protocol metadata."""
        mark_initialized(session_id, client_info)
        with _LOCK:
            session = _SESSIONS.get(session_id, {})
            session["protocol_version"] = protocol_version
            if server_info:
                session["server_info"] = server_info
        self.heartbeat(session_id)
        logger.debug("[MCPSessionManager] initialized session: %s", session_id)

    def close_session(self, session_id: str) -> None:
        """Close and clean up a session."""
        unregister_session(session_id)
        self._heartbeats.pop(session_id, None)
        logger.debug("[MCPSessionManager] closed session: %s", session_id)

    def heartbeat(self, session_id: str) -> None:
        """Update the last-seen timestamp for a session."""
        self._heartbeats[session_id] = time.time()
        with _LOCK:
            session = _SESSIONS.get(session_id)
            if session is not None:
                session["last_seen_at"] = time.time()

    # ── Query ───────────────────────────────────────────────────────────────

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session data by ID."""
        with _LOCK:
            session = _SESSIONS.get(session_id)
            if session is None:
                return None
            return dict(session)

    def get_session_info(self, session_id: str) -> Optional[SessionInfo]:
        """Get typed session info."""
        raw = self.get_session(session_id)
        if raw is None:
            return None
        return SessionInfo(
            session_id=raw.get("session_id", session_id),
            connected_at=raw.get("connected_at", 0),
            last_seen_at=raw.get("last_seen_at", 0),
            initialized=raw.get("initialized", False),
            client_info=raw.get("client_info", {}),
            server_info=raw.get("server_info"),
            protocol_version=raw.get("protocol_version", ""),
            transport_kind=raw.get("transport_kind", "websocket"),
        )

    def list_sessions(self) -> List[SessionInfo]:
        """List all active sessions."""
        with _LOCK:
            return [
                SessionInfo(
                    session_id=s.get("session_id", ""),
                    connected_at=s.get("connected_at", 0),
                    last_seen_at=s.get("last_seen_at", 0),
                    initialized=s.get("initialized", False),
                    client_info=s.get("client_info", {}),
                    server_info=s.get("server_info"),
                    protocol_version=s.get("protocol_version", ""),
                    transport_kind=s.get("transport_kind", "websocket"),
                )
                for s in _SESSIONS.values()
            ]

    def session_count(self) -> int:
        """Number of active sessions."""
        with _LOCK:
            return len(_SESSIONS)

    def is_session_active(self, session_id: str) -> bool:
        """Check if a session is active (not expired)."""
        return session_id in _SESSIONS

    # ── Expiration ──────────────────────────────────────────────────────────

    def expire_stale_sessions(self, max_idle: Optional[float] = None) -> int:
        """Remove sessions that have been idle beyond the TTL. Returns count."""
        ttl = max_idle if max_idle is not None else self._ttl
        now = time.time()
        stale = [sid for sid, last in self._heartbeats.items() if now - last > ttl]
        for sid in stale:
            self.close_session(sid)
        if stale:
            logger.info("[MCPSessionManager] expired %d stale sessions", len(stale))
        return len(stale)

    # ── Diagnostics ─────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Return comprehensive session status."""
        sessions = self.list_sessions()
        initialized = [s for s in sessions if s.get("initialized")]
        return {
            "total_sessions": len(sessions),
            "initialized_sessions": len(initialized),
            "session_ids": [s.get("session_id") for s in sessions],
            "ttl_seconds": self._ttl,
        }


# ── Module-level singleton ──────────────────────────────────────────────────

_session_manager: Optional[MCPSessionManager] = None
_manager_lock = threading.Lock()


def get_session_manager() -> MCPSessionManager:
    """Get or create the global MCP session manager."""
    global _session_manager
    with _manager_lock:
        if _session_manager is None:
            _session_manager = MCPSessionManager()
        return _session_manager


def reset_session_manager() -> None:
    """Reset the session manager (for testing)."""
    global _session_manager
    with _manager_lock:
        _session_manager = None
        with _LOCK:
            _SESSIONS.clear()


__all__ = [
    "MCPSessionManager",
    "DEFAULT_SESSION_TTL",
    "get_session_manager",
    "reset_session_manager",
]
