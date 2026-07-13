# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Koto Settings Manager
???????? - ??????????????
"""

import atexit
import json
import logging
import os
import sys
import tempfile
import threading

# ????????
# ?????config/ ?? Koto.exe??????config/ ? web/ ???

logger = logging.getLogger(__name__)

if getattr(sys, "frozen", False):
    PROJECT_ROOT = os.path.dirname(sys.executable)
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    # user_settings.py lives in app/core/config.  The prior one-level lookup
    # resolved to app/core, creating a second settings file that the launcher,
    # setup tools and packaged runtime never use.  Development must use the
    # same project-root config directory as every other entry point.
    PROJECT_ROOT = os.path.abspath(
        os.path.join(SCRIPT_DIR, os.pardir, os.pardir, os.pardir)
    )
SETTINGS_FILE = os.path.join(PROJECT_ROOT, "config", "user_settings.json")

# ????
DEFAULT_SETTINGS = {
    "storage": {
        "workspace_dir": os.path.join(PROJECT_ROOT, "workspace"),
        "documents_dir": os.path.join(PROJECT_ROOT, "workspace", "documents"),
        "images_dir": os.path.join(PROJECT_ROOT, "workspace", "images"),
        "chats_dir": os.path.join(PROJECT_ROOT, "chats"),
    },
    "appearance": {
        "theme": "light",  # dark, light, auto
        "language": "zh-CN",  # zh-CN, en-US
        "font_size": "medium",  # small, medium, large
        "ui_zoom": 1.0,  # UI ???? 0.7~1.5
    },
    "ai": {
        "default_model": "auto",
        "cloud_provider": "deepseek",
        "deepseek_model": "deepseek-chat",
        "auto_execute_scripts": True,
        "stream_response": True,
        "use_agent_loop": True,  # Unified agent loop is the default path
        "use_doc_agent": False,  # DocAgent remains opt-in for heavy multi-file workflows
        "show_thinking": False,  # ???????????
        "show_task_type": False,  # ????????
        "auto_save_files": True,  # ?????????????/??/????
        "enable_mini_game": True,  # ?????????
        "use_local_only": False,  # ????????
    },
    "proxy": {
        "enabled": True,
        "auto_detect": True,
        "manual_proxy": "",
    },
    "model_mode": "deepseek",
    "local_model": "",
    "user": {
        "name": "",
        "role": "admin",
    },
}


class SettingsManager:
    """?????"""

    _instance = None
    _settings = None
    _dirty = False
    _flush_timer: "threading.Timer | None" = None
    _lock = threading.Lock()
    _FLUSH_DELAY = 2.0  # seconds to wait before flushing dirty writes to disk

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_settings()
        return cls._instance

    def flush(self):
        """Write to disk now (kept for backwards compatibility)."""
        with self._lock:
            result = self._save_settings()
            if result:
                self._dirty = False
            return result

    def reload(self):
        """Force re-read settings from disk."""
        with self._lock:
            self._load_settings()
            self._dirty = False

    def _load_settings(self):
        """????"""
        import copy

        if os.path.exists(SETTINGS_FILE):
            try:
                # utf-8-sig handles both plain UTF-8 and UTF-8 with BOM (PowerShell default)
                with open(SETTINGS_FILE, "r", encoding="utf-8-sig") as f:
                    raw = json.load(f)
                # ????????????????
                self._settings = self._merge_settings(DEFAULT_SETTINGS, raw)
                # ?????????????????????? ai ????
                # ????????????????????????????
                if self._has_missing_defaults(raw):
                    self._save_settings()
            except Exception as e:
                logger.error(f"??????: {e}")
                self._settings = copy.deepcopy(DEFAULT_SETTINGS)
        else:
            self._settings = copy.deepcopy(DEFAULT_SETTINGS)
            self._save_settings()

        # ?????????????????
        self._normalize_storage()

    def _has_missing_defaults(self, raw: dict) -> bool:
        """?? raw ?????? DEFAULT_SETTINGS ?????????"""

        def _missing(default: dict, current: dict) -> bool:
            for k, v in default.items():
                if k not in current:
                    return True
                if isinstance(v, dict) and isinstance(current.get(k), dict):
                    if _missing(v, current[k]):
                        return True
            return False

        return _missing(DEFAULT_SETTINGS, raw)

    def _normalize_storage(self):
        """???????????????????????????"""
        storage = self._settings.get("storage", {})
        for key, default_value in DEFAULT_SETTINGS.get("storage", {}).items():
            if not storage.get(key) or (
                isinstance(storage.get(key), str) and not storage.get(key).strip()
            ):
                storage[key] = default_value
        self._settings["storage"] = storage

    def _merge_settings(self, default, current):
        """????????????????????????????"""
        import copy

        result = copy.deepcopy(default)
        for key, value in current.items():
            if (
                key in result
                and isinstance(value, dict)
                and isinstance(result[key], dict)
            ):
                result[key] = self._merge_settings(result[key], value)
            else:
                # ??????????????????????????
                if isinstance(value, dict) and key not in result:
                    result[key] = copy.deepcopy(value)
                else:
                    result[key] = value
        return result

    # SkillManager ???? "skills" ??SettingsManager ???????
    _EXTERNAL_KEYS = frozenset({"skills"})

    def _save_settings(self):
        """???? ? read-modify-write???????????????

        MUST be called while holding ``self._lock``.
        Uses atomic write (temp file + os.replace) to prevent corruption.
        """
        try:
            settings_dir = os.path.dirname(SETTINGS_FILE)
            os.makedirs(settings_dir, exist_ok=True)
            # ?????????????????????? SkillManager ? "skills"?
            on_disk = {}
            if os.path.exists(SETTINGS_FILE):
                try:
                    with open(SETTINGS_FILE, "r", encoding="utf-8-sig") as f:
                        on_disk = json.load(f)
                except Exception:
                    pass
            # ?? SettingsManager ????? key???????????? key
            for key, value in self._settings.items():
                if key not in self._EXTERNAL_KEYS:
                    on_disk[key] = value
            # ????????????? os.replace ?????
            fd, tmp_path = tempfile.mkstemp(
                dir=settings_dir, suffix=".tmp", prefix=".user_settings_"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(on_disk, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, SETTINGS_FILE)
            except BaseException:
                # ??????
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            return True
        except Exception as e:
            logger.error(f"??????: {e}")
            return False

    def get(self, category, key=None):
        """????"""
        if category in self._settings:
            if key is None:
                return self._settings[category]
            value = self._settings[category].get(key)
            # ??????????????????????????/????
            if (
                category == "storage"
                and key in DEFAULT_SETTINGS.get("storage", {})
                and isinstance(value, str)
                and not value.strip()
            ):
                return DEFAULT_SETTINGS["storage"].get(key)
            return value
        return None

    def set(self, category, key, value):
        """????? ? immediately flushes to disk."""
        with self._lock:
            if category not in self._settings:
                self._settings[category] = {}

            # ?????????????????????????????
            if (
                category == "storage"
                and key in DEFAULT_SETTINGS.get("storage", {})
                and isinstance(value, str)
                and not value.strip()
            ):
                value = DEFAULT_SETTINGS["storage"].get(key)

            self._settings[category][key] = value
            self._normalize_storage()
            self._dirty = True
            return self._save_settings()

    def update(self, category, values):
        """?????????? ? immediately flushes to disk."""
        with self._lock:
            if category not in self._settings:
                self._settings[category] = {}

            # ?? storage ???????????????
            if category == "storage":
                for k, v in values.items():
                    if (
                        k in DEFAULT_SETTINGS.get("storage", {})
                        and isinstance(v, str)
                        and not v.strip()
                    ):
                        values[k] = DEFAULT_SETTINGS["storage"].get(k)

            self._settings[category].update(values)
            self._normalize_storage()
            return self._save_settings()

    def get_all(self):
        """??????"""
        import copy

        return copy.deepcopy(self._settings)

    def reset(self, category=None):
        """????"""
        import copy

        with self._lock:
            if category:
                if category in DEFAULT_SETTINGS:
                    self._settings[category] = copy.deepcopy(DEFAULT_SETTINGS[category])
            else:
                self._settings = copy.deepcopy(DEFAULT_SETTINGS)
            return self._save_settings()

    def ensure_directories(self):
        """??????????"""
        storage = self._settings.get("storage", {})
        for key, path in storage.items():
            if path and not os.path.exists(path):
                try:
                    os.makedirs(path, exist_ok=True)
                except Exception as e:
                    logger.info(f"?????? {path}: {e}")

    # ????
    @property
    def workspace_dir(self):
        return self.get("storage", "workspace_dir")

    @property
    def documents_dir(self):
        return self.get("storage", "documents_dir")

    @property
    def images_dir(self):
        return self.get("storage", "images_dir")

    @property
    def chats_dir(self):
        return self.get("storage", "chats_dir")

    @property
    def theme(self):
        return self.get("appearance", "theme")


# ??????
settings = SettingsManager()
