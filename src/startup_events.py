"""Structured, privacy-safe startup event recording for Koto desktop."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
_EVENT_NAME = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_SENSITIVE_FIELD = re.compile(
    r"(?:authorization|cookie|password|secret|api_?key|launch_?token)", re.I
)


def _safe_value(name: str, value: Any) -> Any:
    if _SENSITIVE_FIELD.search(name):
        return "[redacted]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, Path):
        return str(value)[:500]
    return str(value)[:500]


class StartupEventRecorder:
    """Append one bounded JSON object per startup lifecycle event."""

    def __init__(
        self,
        path: Path | str,
        *,
        session_id: str | None = None,
        parent_session_id: str | None = None,
        started_at_monotonic: float | None = None,
    ) -> None:
        self.path = Path(path)
        self.session_id = session_id or uuid.uuid4().hex
        self.parent_session_id = parent_session_id or None
        self.started_at = (
            float(started_at_monotonic)
            if started_at_monotonic is not None
            else time.monotonic()
        )
        self._lock = threading.Lock()

    def record(
        self,
        event: str,
        *,
        occurred_at_monotonic: float | None = None,
        **details: Any,
    ) -> dict[str, Any]:
        if not _EVENT_NAME.fullmatch(event):
            raise ValueError(f"invalid startup event name: {event!r}")

        occurred_at = (
            float(occurred_at_monotonic)
            if occurred_at_monotonic is not None
            else time.monotonic()
        )
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "session_id": self.session_id,
            "event": event,
            "elapsed_ms": max(0, round((occurred_at - self.started_at) * 1000)),
            "pid": os.getpid(),
        }
        if self.parent_session_id:
            payload["parent_session_id"] = self.parent_session_id
        payload.update(
            {name: _safe_value(name, value) for name, value in details.items()}
        )

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            with self._lock, self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            # Observability must never become a startup dependency.
            pass
        return payload
