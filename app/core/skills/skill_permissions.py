# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║   Koto  ─  SkillPermissions（技能权限系统）                        ║
╚══════════════════════════════════════════════════════════════════╝

Skill 权限分级制度
──────────────────
技能默认只能注入 Prompt（无需额外权限）。若技能需要更多能力，
须在 skill JSON 中声明 `permissions` 字段，并经用户显式授权后才能启用。

权限等级说明
────────────
  ui_style       : 改变界面主题、颜色、背景特效（需用户在 skill JSON 里写 ui_config）
  ui_interactive : 在聊天界面添加快捷按钮、快捷回复、浮动小组件等交互控件
                   (通过 ui_extensions 字段声明)
  notifications  : 向浏览器发送桌面通知（Notification API 权限）
  clipboard_read : 读取剪贴板内容
  clipboard_write: 写入剪贴板内容
  storage        : 在 workspace/ 目录下读写文件
  autorun        : 允许 Skill 由触发器自动运行，无需用户手动激活

设计原则
────────
- 无权限声明 = 只能 prompt injection（最安全默认值）
- 用户通过 API 显式 grant 每个权限
- 授权记录持久化到 config/skill_permissions.json
- 每次启用含 permissions 字段的 Skill 时，SkillPermissionManager 对比
  已授权列表；未授权的权限会通过 API 返回 needs_permission 字段，
  前端弹出授权对话框

持久化
──────
  config/skill_permissions.json
  格式：
  {
    "granted": {
      "skill_id": ["ui_style", "ui_interactive"],
      ...
    }
  }

典型用法
────────
    from app.core.skills.skill_permissions import SkillPermissionManager, PERMISSION_META

    # 检查是否已授权
    granted = SkillPermissionManager.get_granted("divination")
    missing = SkillPermissionManager.get_missing("my_skill", ["ui_interactive", "notifications"])

    # 授予权限
    SkillPermissionManager.grant("my_skill", ["ui_interactive"])

    # 撤销权限
    SkillPermissionManager.revoke("my_skill", ["notifications"])
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════
# 权限元数据（用于 UI 展示授权说明）
# ══════════════════════════════════════════════════════════════════

PERMISSION_META: Dict[str, Dict] = {
    "ui_style": {
        "label": "🎨 界面主题",
        "desc": "允许技能改变聊天界面的颜色、背景特效和字体风格",
        "risk": "low",
    },
    "ui_interactive": {
        "label": "🕹️ 交互控件",
        "desc": "允许技能在聊天界面添加快捷按钮、快捷回复气泡和浮动小组件（如骰子、计时器、便签）",
        "risk": "low",
    },
    "notifications": {
        "label": "🔔 桌面通知",
        "desc": "允许技能通过浏览器向桌面发送通知提醒",
        "risk": "medium",
    },
    "clipboard_read": {
        "label": "📋 读取剪贴板",
        "desc": "允许技能读取你当前剪贴板中的内容",
        "risk": "medium",
    },
    "clipboard_write": {
        "label": "📋 写入剪贴板",
        "desc": "允许技能将内容写入你的剪贴板",
        "risk": "low",
    },
    "storage": {
        "label": "💾 本地文件读写",
        "desc": "允许技能在 workspace/ 目录下读取或写入文件",
        "risk": "high",
    },
    "autorun": {
        "label": "⚡ 自动运行",
        "desc": "允许技能由计划任务或事件触发器自动执行，无需手动激活",
        "risk": "medium",
    },
}

# 所有合法权限 ID
ALL_PERMISSIONS: Set[str] = set(PERMISSION_META.keys())


def _config_dir() -> Path:
    """返回 config/ 目录的绝对路径（兼容打包和开发模式）"""
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "config"
    return Path(__file__).resolve().parents[3] / "config"


_PERMISSIONS_FILE_NAME = "skill_permissions.json"
_write_lock = threading.Lock()


# ══════════════════════════════════════════════════════════════════
# SkillPermissionManager
# ══════════════════════════════════════════════════════════════════

class SkillPermissionManager:
    """
    技能权限管理器（进程级单例）。

    职责：
      - 读取 / 写入 config/skill_permissions.json
      - 提供 grant / revoke / is_granted / get_missing 等 API
      - 提供 enrich_skill_list() — 批量为技能列表注入 needs_permission 字段
    """

    _cache: Optional[Dict[str, List[str]]] = None  # skill_id → granted perm list

    # ── 内部 I/O ──────────────────────────────────────────────────────────────

    @classmethod
    def _path(cls) -> Path:
        return _config_dir() / _PERMISSIONS_FILE_NAME

    @classmethod
    def _load(cls) -> Dict[str, List[str]]:
        if cls._cache is not None:
            return cls._cache
        p = cls._path()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                cls._cache = data.get("granted", {})
                return cls._cache
            except Exception as e:
                logger.warning("[SkillPermissionManager] 加载失败: %s", e)
        cls._cache = {}
        return cls._cache

    @classmethod
    def _save(cls):
        p = cls._path()
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"granted": cls._cache or {}}, ensure_ascii=False, indent=2)
        with _write_lock:
            p.write_text(payload, encoding="utf-8")

    # ── 公开 API ──────────────────────────────────────────────────────────────

    @classmethod
    def get_granted(cls, skill_id: str) -> List[str]:
        """返回某 skill 已被用户授权的权限列表"""
        return list(cls._load().get(skill_id, []))

    @classmethod
    def is_granted(cls, skill_id: str, permission: str) -> bool:
        """检查某 skill 是否已获得特定权限"""
        return permission in cls._load().get(skill_id, [])

    @classmethod
    def get_missing(cls, skill_id: str, required: List[str]) -> List[str]:
        """返回 required 中尚未被授权的权限列表"""
        granted = set(cls._load().get(skill_id, []))
        return [p for p in required if p not in granted]

    @classmethod
    def grant(cls, skill_id: str, permissions: List[str]) -> List[str]:
        """
        授予 skill_id 指定权限。
        只接受合法权限 ID（过滤未知权限）。
        返回最终已授权的完整列表。
        """
        store = cls._load()
        valid = [p for p in permissions if p in ALL_PERMISSIONS]
        if not valid:
            return store.get(skill_id, [])

        current = set(store.get(skill_id, []))
        current.update(valid)
        store[skill_id] = sorted(current)
        cls._save()
        logger.info("[SkillPermissionManager] grant skill=%s perms=%s", skill_id, valid)
        return store[skill_id]

    @classmethod
    def revoke(cls, skill_id: str, permissions: Optional[List[str]] = None) -> List[str]:
        """
        撤销 skill_id 的指定权限。
        若 permissions=None，则撤销该 skill 的所有权限。
        返回剩余已授权列表。
        """
        store = cls._load()
        if skill_id not in store:
            return []
        if permissions is None:
            del store[skill_id]
            cls._save()
            return []
        current = set(store.get(skill_id, []))
        current -= set(permissions)
        if current:
            store[skill_id] = sorted(current)
        else:
            del store[skill_id]
        cls._save()
        return store.get(skill_id, [])

    @classmethod
    def get_permission_info(cls, permissions: List[str]) -> List[Dict]:
        """返回权限列表对应的元数据（用于前端展示授权说明）"""
        result = []
        for p in permissions:
            meta = PERMISSION_META.get(p)
            if meta:
                result.append({"id": p, **meta})
            else:
                result.append({"id": p, "label": p, "desc": "未知权限", "risk": "unknown"})
        return result

    @classmethod
    def enrich_skill_list(cls, skills: List[Dict]) -> List[Dict]:
        """
        批量为技能列表注入权限字段：
          - granted_permissions : 已授权的权限列表
          - needs_permission     : 技能声明但尚未授权的权限列表
          - permission_info      : needs_permission 对应的元数据（UI 展示用）
        """
        for s in skills:
            sid = s.get("id", "")
            required = s.get("permissions", [])
            granted = cls.get_granted(sid)
            missing = cls.get_missing(sid, required)
            s["granted_permissions"] = granted
            s["needs_permission"] = missing
            if missing:
                s["permission_info"] = cls.get_permission_info(missing)
        return skills

    @classmethod
    def invalidate_cache(cls):
        """清空内存缓存，强制下次从文件重新加载"""
        cls._cache = None
