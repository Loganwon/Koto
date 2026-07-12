# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Shared state module for Koto web application.

This module centralizes shared globals that are used across multiple
blueprint modules. It avoids circular imports by providing a single
source of truth for application state.

Usage:
    from web.shared import get_app, settings_manager, session_manager, ...
"""

import logging
import os
import sys
import threading

_logger = logging.getLogger("koto.shared")

# ─── Project root detection ──────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    PROJECT_ROOT = os.path.dirname(sys.executable)
else:
    _SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)

# ─── Settings Manager (single source of truth) ───────────────────────────────
from app.core.config.user_settings import SettingsManager

settings_manager = SettingsManager()

# ─── User settings helpers (delegate to SettingsManager) ─────────────────────
_user_settings_cache: dict = {}  # legacy empty cache
_user_settings_lock = threading.Lock()  # kept for backward compatibility


def _load_user_settings() -> dict:
    """Return all user settings — checks module cache first, reads from env-configurable path."""
    import json as _json
    with _user_settings_lock:
        if "data" in _user_settings_cache:
            return _user_settings_cache["data"]
        settings_path = get_user_settings_path()
        try:
            with open(settings_path, "r", encoding="utf-8-sig") as _f:
                data = _json.load(_f)
        except Exception:
            data = {}
        _user_settings_cache["data"] = data
        return data


def get_user_settings_path() -> str:
    return os.environ.get(
        "KOTO_USER_SETTINGS_PATH",
        os.path.join(PROJECT_ROOT, "config", "user_settings.json"),
    )


def get_workspace_root() -> str:
    settings = _load_user_settings()
    workspace_dir = settings.get("storage", {}).get("workspace_dir")
    if workspace_dir:
        return workspace_dir
    return settings_manager.workspace_dir


def get_organize_root() -> str:
    settings = _load_user_settings()
    organize_root = settings.get("storage", {}).get("organize_root")
    if organize_root:
        return organize_root
    return os.path.join(get_workspace_root(), "_organize")


def get_default_wechat_files_dir() -> str:
    settings = _load_user_settings()
    return settings.get("storage", {}).get("wechat_files_dir", "")


def invalidate_settings_cache() -> None:
    """Clear cache and force SettingsManager to re-read from disk."""
    with _user_settings_lock:
        _user_settings_cache.clear()
    settings_manager.reload()


def clear_user_settings_cache():
    """Alias for invalidate_settings_cache."""
    invalidate_settings_cache()


# ─── Directory paths ─────────────────────────────────────────────────────────
CHAT_DIR = os.path.join(PROJECT_ROOT, "chats")
UPLOAD_DIR = os.path.join(PROJECT_ROOT, "web", "uploads")
WORKSPACE_DIR = get_workspace_root()

# ─── Ensure directories exist ────────────────────────────────────────────────
os.makedirs(CHAT_DIR, exist_ok=True)
os.makedirs(WORKSPACE_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ─── Flask app reference (set by app.py during init) ─────────────────────────
_flask_app = None


def set_app(app):
    """Store the Flask app reference for blueprints to use."""
    global _flask_app
    _flask_app = app


def get_app():
    """Get the Flask app reference."""
    return _flask_app


# --- Formatting utilities ---




def try_libreoffice(source_path: str, out_dir: str, target_fmt: str = "docx"):
    """Try LibreOffice --headless conversion, returns output path or None."""
    import shutil, subprocess
    candidates = (
        "soffice",
        "libreoffice",
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    )
    for soffice in candidates:
        if not (shutil.which(soffice) or os.path.exists(soffice)):
            continue
        try:
            subprocess.run(
                [soffice, "--headless", "--convert-to", target_fmt, "--outdir", out_dir, source_path],
                capture_output=True, timeout=60,
            )
            base = os.path.splitext(os.path.basename(source_path))[0]
            output = os.path.join(out_dir, f"{base}.{target_fmt}")
            if os.path.exists(output):
                return output
        except Exception:
            continue
    return None


def ollama_available() -> bool:
    import socket
    try:
        s = socket.create_connection(("127.0.0.1", 11434), timeout=1)
        s.close()
        return True
    except OSError:
        return False


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} PB"


def human_time(ts: float) -> str:
    import datetime
    try:
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "unknown"


# ─── Error response helper ───────────────────────────────────────────────────


def _error_response(message: str, status_code: int = 500, error_type: str = None):
    """Create a standardized JSON error response."""
    from flask import jsonify

    payload = {"error": message, "success": False}
    if error_type:
        payload["type"] = error_type
    return jsonify(payload), status_code