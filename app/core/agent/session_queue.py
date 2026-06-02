# ══════════════════════════════════════════════════════════════
# session_queue.py — Per-Session Request Serialization
#
# Inspired by OpenClaw's per-session queue serialization:
# Each session gets its own lock so concurrent requests within
# the same session are serialized (no race on history/context),
# but different sessions run in parallel.
#
# Also provides an optional global concurrency limiter to
# prevent overloading the LLM provider.
# ══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Maximum number of session locks to keep in LRU cache
_MAX_SESSIONS = 256


@dataclass
class _SessionState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_used: float = field(default_factory=time.time)
    queue_depth: int = 0


class SessionQueue:
    """
    Per-session serialization queue.

    Usage:
        sq = SessionQueue()
        with sq.acquire("session_123"):
            # this block is serialized per-session
            run_agent(...)
    """

    def __init__(
        self, max_sessions: int = _MAX_SESSIONS, global_concurrency: int = 0
    ) -> None:
        self._sessions: OrderedDict[str, _SessionState] = OrderedDict()
        self._meta_lock = threading.Lock()
        self._max_sessions = max_sessions
        # Optional global concurrency limiter (0 = unlimited)
        self._global_sem: Optional[threading.Semaphore] = (
            threading.Semaphore(global_concurrency) if global_concurrency > 0 else None
        )

    def _get_state(self, session_id: str) -> _SessionState:
        with self._meta_lock:
            if session_id in self._sessions:
                self._sessions.move_to_end(session_id)
                state = self._sessions[session_id]
                state.last_used = time.time()
                return state
            # Evict oldest if at capacity
            while len(self._sessions) >= self._max_sessions:
                evicted_id, evicted = self._sessions.popitem(last=False)
                if evicted.queue_depth > 0:
                    # Don't evict active sessions — put it back and evict next
                    self._sessions[evicted_id] = evicted
                    self._sessions.move_to_end(evicted_id)
                    break
                logger.debug("Evicted session lock: %s", evicted_id)
            state = _SessionState()
            self._sessions[session_id] = state
            return state

    def acquire(self, session_id: str) -> "_SessionLock":
        """Return a context manager that serializes within this session."""
        return _SessionLock(self, session_id)

    def queue_depth(self, session_id: str) -> int:
        with self._meta_lock:
            state = self._sessions.get(session_id)
            return state.queue_depth if state else 0


class _SessionLock:
    """Context manager for session lock + optional global semaphore."""

    def __init__(self, queue: SessionQueue, session_id: str) -> None:
        self._queue = queue
        self._session_id = session_id
        self._state: Optional[_SessionState] = None

    def __enter__(self) -> "_SessionLock":
        self._state = self._queue._get_state(self._session_id)
        self._state.queue_depth += 1
        # Acquire global semaphore first (if configured)
        if self._queue._global_sem is not None:
            self._queue._global_sem.acquire()
        # Then acquire per-session lock
        self._state.lock.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._state is not None:
            self._state.lock.release()
            self._state.queue_depth -= 1
        if self._queue._global_sem is not None:
            self._queue._global_sem.release()
        return None  # don't suppress exceptions
