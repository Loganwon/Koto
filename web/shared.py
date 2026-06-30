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

_logger = logging.getLogger("koto.shared")

# ─── Project root detection ──────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    PROJECT_ROOT = os.path.dirname(sys.executable)
else:
    _SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)

# ─── Directory paths ─────────────────────────────────────────────────────────
CHAT_DIR = os.path.join(PROJECT_ROOT, "chats")
UPLOAD_DIR = os.path.join(PROJECT_ROOT, "web", "uploads")

# ─── User settings cache ─────────────────────────────────────────────────────
from web.config import (
    _load_user_settings,
    _user_settings_cache,
    _user_settings_lock,
    get_default_wechat_files_dir,
    get_organize_root,
    get_user_settings_path,
    get_workspace_root,
    invalidate_settings_cache,
)


def clear_user_settings_cache():
    """Invalidate user settings cache (e.g. after settings update)."""
    invalidate_settings_cache()


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


# ─── Settings Manager ────────────────────────────────────────────────────────
try:
    from settings import SettingsManager
except ImportError:
    from web.settings import SettingsManager

settings_manager = SettingsManager()

# ─── Error response helper ───────────────────────────────────────────────────


def _error_response(message: str, status_code: int = 500, error_type: str = None):
    """Create a standardized JSON error response."""
    from flask import jsonify

    payload = {"error": message, "success": False}
    if error_type:
        payload["type"] = error_type
    return jsonify(payload), status_code
