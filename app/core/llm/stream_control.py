"""Close an active provider response when a durable cancellation is requested.

The monitor never executes tools or declares a task stopped. The model iterator
must actually exit before its runtime can emit a cancellation terminal.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional


def watch_stream_cancellation(
    stream: Any,
    cancel_check: Optional[Callable[[], bool]],
) -> threading.Event:
    stopped = threading.Event()
    close = getattr(stream, "close", None)
    if not callable(cancel_check) or not callable(close):
        return stopped

    def watch():
        while not stopped.wait(0.1):
            try:
                cancelled = cancel_check()
            except Exception:
                continue
            if cancelled:
                try:
                    close()
                except Exception:
                    pass
                return

    threading.Thread(target=watch, daemon=True, name="koto-model-stream-cancel").start()
    return stopped
