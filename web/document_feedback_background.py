"""Small thread/queue bridge for document-feedback streaming stages."""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable


class BackgroundProgressBridge:
    """Run one blocking stage while its progress events stay streamable."""

    def __init__(self) -> None:
        self._queue: queue.Queue[Any] = queue.Queue()
        self._sentinel = object()
        self.result: Any = None
        self.error: Exception | None = None
        self._thread: threading.Thread | None = None

    def emit(self, event: dict[str, Any]) -> None:
        self._queue.put(event)

    def start(self, work: Callable[[], Any]) -> None:
        def runner() -> None:
            try:
                self.result = work()
            except Exception as exc:
                self.error = exc
            finally:
                self._queue.put(self._sentinel)

        self._thread = threading.Thread(target=runner, daemon=True)
        self._thread.start()

    def get(self, timeout: float) -> Any:
        return self._queue.get(timeout=timeout)

    def is_complete(self, value: Any) -> bool:
        return value is self._sentinel

    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def join(self, timeout: float) -> None:
        if self._thread:
            self._thread.join(timeout=timeout)
