# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

import json
import os
import threading

_user_settings_cache = {}
_user_settings_lock = threading.Lock()


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_user_settings_path() -> str:
    return os.environ.get(
        "KOTO_USER_SETTINGS_PATH",
        os.path.join(_project_root(), "config", "user_settings.json"),
    )


def _load_user_settings() -> dict:
    with _user_settings_lock:
        if "data" in _user_settings_cache:
            return _user_settings_cache["data"]
        settings_path = get_user_settings_path()
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        _user_settings_cache["data"] = data
        return data


def get_workspace_root() -> str:
    settings = _load_user_settings()
    workspace_dir = settings.get("storage", {}).get("workspace_dir")
    if workspace_dir:
        return workspace_dir
    return os.path.join(_project_root(), "workspace")


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
    with _user_settings_lock:
        _user_settings_cache.clear()
