# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Single runtime owner for Koto's active workspace directory."""

from __future__ import annotations

import os
import threading
from pathlib import Path

_lock = threading.RLock()
_runtime_override: str | None = None


def _normalize_workspace_root(path: str | os.PathLike[str]) -> str:
    return str(Path(path).expanduser().resolve())


def _workspace_from_external_settings_file() -> str:
    """Honor the test/portable settings override without importing the web layer."""
    settings_path = str(os.getenv("KOTO_USER_SETTINGS_PATH") or "").strip()
    if not settings_path:
        return ""
    try:
        from app.core.config.settings_store import load_settings_document

        payload = load_settings_document(settings_path)
        return str((payload.get("storage") or {}).get("workspace_dir") or "").strip()
    except Exception:
        return ""


def get_workspace_root() -> str:
    """Return the live workspace root used by web, chat, agents, and file tools."""
    with _lock:
        if _runtime_override:
            return _runtime_override

    configured = str(os.getenv("KOTO_WORKSPACE_DIR") or "").strip()
    if not configured:
        configured = _workspace_from_external_settings_file()
    if not configured:
        from app.core.config.user_settings import SettingsManager

        configured = str(SettingsManager().workspace_dir or "").strip()
    if not configured:
        project_root = Path(__file__).resolve().parents[3]
        configured = str(project_root / "workspace")
    return _normalize_workspace_root(configured)


def set_workspace_root(path: str | os.PathLike[str]) -> str:
    """Update the process-wide workspace root and return its normalized value."""
    normalized = _normalize_workspace_root(path)
    with _lock:
        global _runtime_override
        _runtime_override = normalized
    return normalized


def clear_workspace_root_override() -> None:
    """Drop the process override so configuration becomes authoritative again."""
    with _lock:
        global _runtime_override
        _runtime_override = None


def reload_workspace_root() -> str:
    """Reload the configured root while preserving environment precedence."""
    clear_workspace_root_override()
    return get_workspace_root()
