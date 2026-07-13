# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Request deduplication middleware.

Prevents identical chat/file-task requests from being processed concurrently
when users rapidly double-click or resubmit.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Any

_logger = logging.getLogger("koto.dedup")


class RequestDeduplicator:
    """Thread-safe in-flight request tracker.

    Usage (Flask)::

        dedup = RequestDeduplicator(ttl_seconds=120)
        app.before_request(lambda: dedup.check_or_register())
        app.after_request(lambda resp: dedup.release())
    """

    def __init__(self, ttl_seconds: int = 120) -> None:
        self._lock = threading.Lock()
        self._in_flight: dict[str, float] = {}  # key → expiry timestamp
        self._ttl = ttl_seconds

    def _build_key(self) -> str | None:
        """Build a dedup key from session + message content."""
        from flask import request

        if request.method not in ("POST",):
            return None

        path = request.path
        # Only dedup chat and task-stream endpoints
        dedup_paths = (
            "/api/chat", "/api/chat/stream", "/api/chat/file",
            "/api/editor/ai/task-stream", "/api/mini/chat",
        )
        if not any(path.startswith(p) for p in dedup_paths):
            return None

        data = request.get_json(silent=True) or {}
        session = str(data.get("session", ""))
        message = str(data.get("message", "") or data.get("task", "") or "")
        if not session or not message:
            return None

        raw = f"{session}|{message}|{path}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _cleanup_expired(self) -> None:
        """Remove expired entries (called periodically)."""
        now = time.monotonic()
        expired = [k for k, exp in self._in_flight.items() if now >= exp]
        for k in expired:
            self._in_flight.pop(k, None)


    def release(self, key: str) -> None:
        with self._lock:
            self._in_flight.pop(key, None)

    # -- Flask hooks --

    def check_or_register(self) -> object | None:
        """before_request: atomically check for duplicate and register if new."""
        key = self._build_key()
        if key is None:
            return None

        from flask import g, jsonify

        with self._lock:
            self._cleanup_expired()
            if key in self._in_flight:
                _logger.info("[dedup] duplicate blocked: %s", key[:8])
                return jsonify({
                    "error": "DUPLICATE_REQUEST",
                    "message": "相同的请求正在处理中，请等待完成",
                    "status": 409,
                }), 409
            self._in_flight[key] = time.monotonic() + self._ttl

        g._dedup_key = key
        return None


        self.register(key)
        # Store key on request context for release in after_request
        from flask import g
        g._dedup_key = key
        return None

    def release_current(self, _response: Any = None) -> Any:
        """after_request: release the dedup key."""
        from flask import g
        key = getattr(g, "_dedup_key", None)
        if key:
            self.release(key)
        return _response


# Singleton for app-wide use
deduplicator = RequestDeduplicator(ttl_seconds=120)
