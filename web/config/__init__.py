# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Configuration helpers (re-export shim).

Delegates to `web.shared` which is the single source of truth for
settings helpers, paths, and the shared cache/lock.  This module exists
for backward compatibility only; new code should import from `web.shared`
directly.
"""

from web.shared import (  # noqa: F401
    _load_user_settings,
    _user_settings_cache,
    _user_settings_lock,
    clear_user_settings_cache,
    get_default_wechat_files_dir,
    get_organize_root,
    get_user_settings_path,
    get_workspace_root,
    invalidate_settings_cache,
)

__all__ = [
    "_load_user_settings",
    "_user_settings_cache",
    "_user_settings_lock",
    "clear_user_settings_cache",
    "get_default_wechat_files_dir",
    "get_organize_root",
    "get_user_settings_path",
    "get_workspace_root",
    "invalidate_settings_cache",
]
