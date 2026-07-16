# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Koto Settings Manager
???????? - ??????????????
"""

import copy
import logging
import os
import sys
import threading
from collections.abc import Iterable, Mapping

from app.core.config.settings_store import (
    SettingsStoreError,
    atomic_update_settings,
    deep_merge,
    load_settings_document,
)

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
SETTINGS_FILE = os.environ.get(
    "KOTO_USER_SETTINGS_PATH",
    os.path.join(PROJECT_ROOT, "config", "user_settings.json"),
)

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
    _dirty_patch = None
    _dirty_replace_keys = frozenset()
    _flush_timer: "threading.Timer | None" = None
    _lock = threading.RLock()
    _instance_lock = threading.Lock()
    _file_signature = None
    _FLUSH_DELAY = 2.0  # seconds to wait before flushing dirty writes to disk

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._load_settings()
                    cls._instance = instance
        return cls._instance

    def flush(self):
        """Write only genuinely pending changes.

        Public mutators already persist atomically. Rewriting a clean in-memory
        snapshot during shutdown can clobber settings changed by another Koto
        helper or process after this instance loaded.
        """
        with self._lock:
            if not self._dirty:
                return True
            return self._save_settings()

    def reload(self):
        """Force re-read settings from disk."""
        with self._lock:
            self._load_settings()
            self._dirty = False

    def _load_settings(self):
        """????"""
        try:
            raw = load_settings_document(SETTINGS_FILE, defaults=DEFAULT_SETTINGS)
            self._settings = self._merge_settings(DEFAULT_SETTINGS, raw)
        except SettingsStoreError as exc:
            logger.error("Settings load lock failed: %s", exc)
            self._settings = copy.deepcopy(DEFAULT_SETTINGS)
        self._normalize_storage()
        self._file_signature = self._get_file_signature()
        self._dirty = False
        self._dirty_patch = {}
        self._dirty_replace_keys = frozenset()

    @staticmethod
    def _get_file_signature():
        try:
            stat = os.stat(SETTINGS_FILE)
            return (stat.st_mtime_ns, stat.st_size)
        except OSError:
            return None

    def _reload_if_changed_locked(self):
        """Refresh a clean singleton when another process updated the file."""
        current_signature = self._get_file_signature()
        if (
            not self._dirty
            and current_signature is not None
            and current_signature != self._file_signature
        ):
            self._load_settings()

    def _normalize_storage(self):
        """???????????????????????????"""
        storage = self._settings.get("storage", {})
        if not isinstance(storage, dict):
            storage = {}
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

    # SkillManager owns "skills"; fallback full writes must not replace it.
    _EXTERNAL_KEYS = frozenset({"skills"})

    def _mark_dirty(
        self,
        patch: Mapping[str, object],
        *,
        replace_top_level: Iterable[str] = (),
    ) -> None:
        self._dirty_patch = deep_merge(self._dirty_patch or {}, patch)
        self._dirty_replace_keys = frozenset(
            set(self._dirty_replace_keys) | set(replace_top_level)
        )
        self._dirty = True

    def patch(
        self,
        values: Mapping[str, object],
        *,
        replace_top_level: Iterable[str] = (),
    ) -> bool:
        """Persist a multi-section change as one cross-process transaction."""
        with self._lock:
            self._reload_if_changed_locked()
            self._settings = deep_merge(self._settings, values)
            for key in replace_top_level:
                if key in values:
                    self._settings[key] = copy.deepcopy(values[key])
            self._normalize_storage()
            self._mark_dirty(values, replace_top_level=replace_top_level)
            return self._save_settings()

    def _save_settings(self):
        """???? ? read-modify-write???????????????

        MUST be called while holding ``self._lock``.
        Uses atomic write (temp file + os.replace) to prevent corruption.
        """
        try:
            patch = self._dirty_patch or {
                key: value
                for key, value in self._settings.items()
                if key not in self._EXTERNAL_KEYS
            }
            persisted = atomic_update_settings(
                SETTINGS_FILE,
                patch,
                defaults=DEFAULT_SETTINGS,
                replace_top_level=self._dirty_replace_keys,
            )
            self._settings = self._merge_settings(DEFAULT_SETTINGS, persisted)
            self._normalize_storage()
            self._file_signature = self._get_file_signature()
            self._dirty = False
            self._dirty_patch = {}
            self._dirty_replace_keys = frozenset()
            return True
        except Exception as e:
            logger.error("Settings save failed: %s", e)
            return False

    def get(self, category, key=None):
        """????"""
        with self._lock:
            self._reload_if_changed_locked()
            if category in self._settings:
                if key is None:
                    return copy.deepcopy(self._settings[category])
                category_settings = self._settings[category]
                if not isinstance(category_settings, Mapping):
                    return None
                value = category_settings.get(key)
                # ??????????????????????????/????
                if (
                    category == "storage"
                    and key in DEFAULT_SETTINGS.get("storage", {})
                    and isinstance(value, str)
                    and not value.strip()
                ):
                    return DEFAULT_SETTINGS["storage"].get(key)
                return copy.deepcopy(value)
            return None

    def set(self, category, key, value):
        """????? ? immediately flushes to disk."""
        # ?????????????????????????????
        if (
            category == "storage"
            and key in DEFAULT_SETTINGS.get("storage", {})
            and isinstance(value, str)
            and not value.strip()
        ):
            value = DEFAULT_SETTINGS["storage"].get(key)
        return self.patch({category: {key: value}})

    def update(self, category, values):
        """?????????? ? immediately flushes to disk."""
        normalized_values = dict(values)
        # ?? storage ???????????????
        if category == "storage":
            for k, v in normalized_values.items():
                if (
                    k in DEFAULT_SETTINGS.get("storage", {})
                    and isinstance(v, str)
                    and not v.strip()
                ):
                    normalized_values[k] = DEFAULT_SETTINGS["storage"].get(k)
        return self.patch({category: normalized_values})

    def get_all(self):
        """??????"""
        with self._lock:
            self._reload_if_changed_locked()
            return copy.deepcopy(self._settings)

    def reset(self, category=None):
        """????"""
        with self._lock:
            self._reload_if_changed_locked()
            if category:
                if category in DEFAULT_SETTINGS:
                    return self.patch(
                        {category: copy.deepcopy(DEFAULT_SETTINGS[category])},
                        replace_top_level={category},
                    )
            else:
                return self.patch(
                    copy.deepcopy(DEFAULT_SETTINGS),
                    replace_top_level=DEFAULT_SETTINGS.keys(),
                )
            return True

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
