"""Privacy-preserving audit contracts for information access."""

from __future__ import annotations

import copy
from threading import RLock
from typing import Any, Mapping, Protocol


class InformationAuditSink(Protocol):
    def append(self, event: Mapping[str, Any]) -> None: ...


class InMemoryInformationAuditSink:
    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._lock = RLock()

    def append(self, event: Mapping[str, Any]) -> None:
        with self._lock:
            self._events.append(copy.deepcopy(dict(event)))

    def events(self) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._events)


__all__ = ["InMemoryInformationAuditSink", "InformationAuditSink"]
