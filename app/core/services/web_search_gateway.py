# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Transport-neutral gateway for the application-provided web search backend."""

from __future__ import annotations

import threading
from typing import Any, Callable

SearchHandler = Callable[[str], dict[str, Any]]

_handler: SearchHandler | None = None
_lock = threading.RLock()


def configure_web_search_handler(handler: SearchHandler | None) -> None:
    """Bind the search implementation at the application composition root."""
    if handler is not None and not callable(handler):
        raise TypeError("web search handler must be callable")
    global _handler
    with _lock:
        _handler = handler


def get_web_search_handler() -> SearchHandler | None:
    """Return the current binding for lifecycle checks and test restoration."""
    with _lock:
        return _handler


def search_with_grounding(query: str) -> dict[str, Any]:
    """Call the configured search backend without importing a transport layer."""
    handler = get_web_search_handler()
    if handler is None:
        return {
            "success": False,
            "response": "Web search is currently unavailable; please try again later.",
            "sources": [],
        }
    return handler(query)


__all__ = [
    "configure_web_search_handler",
    "get_web_search_handler",
    "search_with_grounding",
]
