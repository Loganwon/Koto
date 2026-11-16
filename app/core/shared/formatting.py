"""Small presentation-neutral formatters shared by Core and Web adapters."""

from __future__ import annotations

from datetime import datetime


def human_size(size_bytes: int) -> str:
    """Format a byte count using binary units."""
    value = max(0, int(size_bytes))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024:
            return f"{value:.1f} {unit}" if unit != "B" else f"{value} B"
        value /= 1024
    return f"{value:.1f} PB"


def human_time(timestamp: float) -> str:
    """Format a local timestamp, returning a stable fallback when invalid."""
    try:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, TypeError, ValueError):
        return "unknown"
