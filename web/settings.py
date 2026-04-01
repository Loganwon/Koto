# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Koto Settings Manager
用户设置管理模块 - 支持自定义存储路径和应用配置
"""

import atexit
import json
import logging
import os
import sys
import threading

# 默认设置文件位置
# 打包模式：config/ 紧邻 Koto.exe；开发模式：config/ 在 web/ 的父级

logger = logging.getLogger(__name__)

if getattr(sys, "frozen", False):
    PROJECT_ROOT = os.path.dirname(sys.executable)
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
SETTINGS_FILE = os.path.join(PROJECT_ROOT, "config", "user_settings.json")

# 默认设置
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
        "ui_zoom": 1.0,  # UI 缩放比例 0.7~1.5
    },
    "ai": {
        "default_model": "auto",
        "auto_execute_scripts": True,
        "voice_auto_send": False,  # 语音输入后自动发送
        "stream_response": True,
        "show_thinking": False,  # 显示思考过程（推理链）
        "show_task_type": False,  # 显示任务分类标签
        "auto_save_files": True,  # 自动保存回复中的文件（代码/文档/总结等）
        "enable_mini_game": True,  # 启用等待时的小游戏
        "voice_auto_mode": True,  # 语音自动模式
        "use_local_only": False,  # 本地模型独占模式
    },
    "proxy": {
        "enabled": True,
        "auto_detect": True,
        "manual_proxy": "",
    },
    "model_mode": "cloud",
    "local_model": "",
    "user": {
        "name": "",
        "role": "admin",
    },
}


class SettingsManager:
    """设置管理器"""

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
        result = self._save_settings()
        if result:
            self._dirty = False
        return result

    def _load_settings(self):
        """加载设置"""
        import copy
        if os.path.exists(SETTINGS_FILE):
            try:
                # utf-8-sig handles both plain UTF-8 and UTF-8 with BOM (PowerShell default)
                with open(SETTINGS_FILE, "r", encoding="utf-8-sig") as f:
                    raw = json.load(f)
                # 合并默认设置（处理新增的设置项）
                self._settings = self._merge_settings(DEFAULT_SETTINGS, raw)
                # 如果文件缺少新增的默认键（如版本升级后添加的 ai 子项），
                # 立即将完整合并结果写回磁盘，确保文件始终包含所有默认项。
                if self._has_missing_defaults(raw):
                    self._save_settings()
            except Exception as e:
                logger.info(f"加载设置失败: {e}")
                self._settings = copy.deepcopy(DEFAULT_SETTINGS)
        else:
            self._settings = copy.deepcopy(DEFAULT_SETTINGS)
            self._save_settings()

        # 规范化存储路径：空字符串回退默认值
        self._normalize_storage()

    def _has_missing_defaults(self, raw: dict) -> bool:
        """检查 raw 是否缺少当前 DEFAULT_SETTINGS 中的任意键（递归）"""
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
        """将空存储路径重置为默认值，避免路径丢失导致的查找失败。"""
        storage = self._settings.get("storage", {})
        for key, default_value in DEFAULT_SETTINGS.get("storage", {}).items():
            if not storage.get(key) or (isinstance(storage.get(key), str) and not storage.get(key).strip()):
                storage[key] = default_value
        self._settings["storage"] = storage

    def _merge_settings(self, default, current):
        """合并设置，保留用户设置，添加新的默认项，同时保留非默认键"""
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
                # 保留所有用户已保存的键值，包括不在默认设置中的新增项
                if isinstance(value, dict) and key not in result:
                    result[key] = copy.deepcopy(value)
                else:
                    result[key] = value
        return result

    # SkillManager 独立管理 "skills" 键，SettingsManager 写入时不得覆盖
    _EXTERNAL_KEYS = frozenset({"skills"})

    def _save_settings(self):
        """保存设置 — read-modify-write，避免覆盖其他子系统写入的数据"""
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            # 先读取磁盘最新数据，保留其他子系统的写入（如 SkillManager → "skills"）
            on_disk = {}
            if os.path.exists(SETTINGS_FILE):
                try:
                    with open(SETTINGS_FILE, "r", encoding="utf-8-sig") as f:
                        on_disk = json.load(f)
                except Exception:
                    pass
            # 写入 SettingsManager 管辖的所有 key，但跳过外部子系统独占的 key
            for key, value in self._settings.items():
                if key not in self._EXTERNAL_KEYS:
                    on_disk[key] = value
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(on_disk, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.info(f"保存设置失败: {e}")
            return False

    def get(self, category, key=None):
        """获取设置"""
        if category in self._settings:
            if key is None:
                return self._settings[category]
            value = self._settings[category].get(key)
            # 存储路径为空时自动回退默认值，避免路径缺失导致的寻路/查找失败
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
        """设置单个值 — immediately flushes to disk."""
        if category not in self._settings:
            self._settings[category] = {}

        # 如果用户将存储路径置空，则回退默认值，避免后续文件查找失败
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
        """更新一个分类的多个值 — immediately flushes to disk."""
        if category not in self._settings:
            self._settings[category] = {}

        # 处理 storage 目录值为空的情况，回退默认路径
        if category == "storage":
            for k, v in values.items():
                if k in DEFAULT_SETTINGS.get("storage", {}) and isinstance(v, str) and not v.strip():
                    values[k] = DEFAULT_SETTINGS["storage"].get(k)

        self._settings[category].update(values)
        self._normalize_storage()
        return self._save_settings()

    def get_all(self):
        """获取所有设置"""
        import copy
        return copy.deepcopy(self._settings)

    def reset(self, category=None):
        """重置设置"""
        import copy
        if category:
            if category in DEFAULT_SETTINGS:
                self._settings[category] = copy.deepcopy(DEFAULT_SETTINGS[category])
        else:
            self._settings = copy.deepcopy(DEFAULT_SETTINGS)
        return self._save_settings()

    def ensure_directories(self):
        """确保所有存储目录存在"""
        storage = self._settings.get("storage", {})
        for key, path in storage.items():
            if path and not os.path.exists(path):
                try:
                    os.makedirs(path, exist_ok=True)
                except Exception as e:
                    logger.info(f"创建目录失败 {path}: {e}")

    # 便捷方法
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


# 全局设置实例
settings = SettingsManager()
