"""Cooperative cancellation primitives for expensive file-open requests."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


class FileOpenCancelledError(RuntimeError):
    """Raised at a parser checkpoint after the browser cancels an open request."""


@dataclass
class FileOpenCancellationToken:
    request_id: str
    created_at: float = field(default_factory=time.monotonic)
    _event: threading.Event = field(default_factory=threading.Event, repr=False)

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise FileOpenCancelledError("文件打开已取消")


class FileOpenCancellationRegistry:
    """Session-scoped token registry that also remembers early cancel requests."""

    def __init__(self, *, ttl_seconds: float = 300.0) -> None:
        self._ttl_seconds = ttl_seconds
        self._tokens: dict[tuple[str, str], FileOpenCancellationToken] = {}
        self._lock = threading.Lock()

    @staticmethod
    def validate_request_id(request_id: str) -> str:
        value = str(request_id or "").strip()
        if not _REQUEST_ID_RE.fullmatch(value):
            raise ValueError("open_request_id 格式不合法")
        return value

    def _prune_locked(self, now: float) -> None:
        expired = [
            key
            for key, token in self._tokens.items()
            if now - token.created_at > self._ttl_seconds
        ]
        for key in expired:
            self._tokens.pop(key, None)

    def begin(self, session_id: str, request_id: str) -> FileOpenCancellationToken:
        request_id = self.validate_request_id(request_id)
        key = (str(session_id or "default"), request_id)
        with self._lock:
            self._prune_locked(time.monotonic())
            token = self._tokens.get(key)
            if token is None:
                token = FileOpenCancellationToken(request_id)
                self._tokens[key] = token
            return token

    def cancel(self, session_id: str, request_id: str) -> FileOpenCancellationToken:
        # Creating a cancelled tombstone makes cancellation reliable even if the
        # cancel POST overtakes a request that is still copying/preflighting.
        token = self.begin(session_id, request_id)
        token.cancel()
        return token

    def finish(self, session_id: str, request_id: str) -> None:
        key = (str(session_id or "default"), str(request_id or ""))
        with self._lock:
            self._tokens.pop(key, None)


__all__ = [
    "FileOpenCancelledError",
    "FileOpenCancellationRegistry",
    "FileOpenCancellationToken",
]
