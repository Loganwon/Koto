# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Koto ContactManager — 关系记忆 / 社交 CRM
==========================================
追踪对话中提及的人物和关系，建立轻量的社交记忆层。

功能：
  - 从对话中自动识别人物提及（姓名 + 关系词识别）
  - 记录：最近互动日期、互动频次、话题摘要、关键备注
  - 跟进提醒：超过设定天数未提及 → 推入 ProactiveAgent
  - SQLite 持久化（和 GoalManager 共用同一个 DB 文件）
  - 支持手动增删查改

集成点：
  - MemoryReflector.reflect_async() 调用后触发 observe_turn()
  - ProactiveAgent.tick() 检查需要跟进的联系人

存储结构（SQLite table: contacts）:
  id TEXT PRIMARY KEY
  name TEXT NOT NULL
  aliases TEXT        -- JSON 数组，名字的别称
  relationship TEXT   -- 朋友/同事/家人/客户/其他
  notes TEXT          -- 用户添加的备注
  topics TEXT         -- JSON 数组，历次对话话题
  last_interaction TEXT  -- ISO8601 最近提及时间
  interaction_count INTEGER
  follow_up_after_days INTEGER  -- N 天无提及则跟进，0 表示不跟进
  created_at TEXT
  updated_at TEXT
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ── 数据库路径（与 GoalManager、TaskLedger 共用）──────────────────────────────
import os

_DEFAULT_DB_PATH = str(
    Path(
        os.environ.get(
            "KOTO_DB_DIR", Path(__file__).parent.parent.parent.parent / "config"
        )
    )
    / "koto_checkpoints.sqlite"
)

# ── 姓名识别模式 ──────────────────────────────────────────────────────────────
# 捕获人名：中文姓名 2-4 字，或前缀关系词后的名字
_RELATION_PREFIXES = (
    "我的?[朋友同事上司老板下属同学邻居客户老师导师合伙人合作伙伴爸爸妈妈爱人老婆老公丈夫妻子女朋友男朋友]",
    "我[认识找见了联系]|他|她|和|跟",
)
_CN_NAME_RE = re.compile(
    r"(?:(?:叫|是|找|联系|见了?|跟|和|给)\s*)?([赵钱孙李周吴郑王冯陈楮卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳酆鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄和穆萧尹][\u4e00-\u9fa5]{1,3})",
    re.UNICODE,
)
# 英文名（大写开头 2+ 个词或单词）
_EN_NAME_RE = re.compile(r"\b([A-Z][a-z]{1,15}(?:\s+[A-Z][a-z]{1,15})?)\b")

# 关系词推断
_RELATION_MAP = {
    "朋友": "朋友",
    "同学": "同学",
    "同事": "同事",
    "老板": "上级",
    "上司": "上级",
    "领导": "上级",
    "下属": "下属",
    "部下": "下属",
    "客户": "客户",
    "甲方": "客户",
    "老师": "老师",
    "导师": "导师",
    "爸爸": "家人",
    "妈妈": "家人",
    "父亲": "家人",
    "母亲": "家人",
    "老婆": "伴侣",
    "老公": "伴侣",
    "爱人": "伴侣",
    "妻子": "伴侣",
    "丈夫": "伴侣",
    "女朋友": "伴侣",
    "男朋友": "伴侣",
    "哥": "家人",
    "姐": "家人",
    "弟": "家人",
    "妹": "家人",
    "合伙人": "合作伙伴",
    "合作伙伴": "合作伙伴",
}

# ── 单例 ──────────────────────────────────────────────────────────────────────
_manager_instance: Optional["ContactManager"] = None
_manager_lock = threading.Lock()


def get_contact_manager() -> "ContactManager":
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = ContactManager()
    return _manager_instance


# ============================================================================
# ContactManager
# ============================================================================


class ContactManager:
    """轻量级社交 CRM —— 基于 SQLite 持久化。"""

    def __init__(self, db_path: str = _DEFAULT_DB_PATH):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    # ── 数据库初始化 ──────────────────────────────────────────────────────────

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS contacts (
                    id                   TEXT PRIMARY KEY,
                    name                 TEXT NOT NULL,
                    aliases              TEXT DEFAULT '[]',
                    relationship         TEXT DEFAULT '其他',
                    notes                TEXT DEFAULT '',
                    topics               TEXT DEFAULT '[]',
                    last_interaction     TEXT,
                    interaction_count    INTEGER DEFAULT 0,
                    follow_up_after_days INTEGER DEFAULT 0,
                    created_at           TEXT NOT NULL,
                    updated_at           TEXT NOT NULL
                )
            """)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # ── 核心分析 ──────────────────────────────────────────────────────────────

    def observe_turn(self, user_msg: str, ai_msg: str, topic: str = ""):
        """
        分析一轮对话，提取人物提及并更新联系人记录。
        由 MemoryReflector 或 app.py 的对话管道在每轮结束后异步调用。
        """
        names = self._extract_names(user_msg + " " + ai_msg)
        if not names:
            return
        relation = self._infer_relation(user_msg)
        now_iso = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            with self._connect() as conn:
                for name in names:
                    existing = self._find_by_name(conn, name)
                    if existing:
                        # 更新已有联系人
                        new_topics = json.loads(existing["topics"] or "[]")
                        if topic and topic not in new_topics:
                            new_topics.append(topic)
                            if len(new_topics) > 20:
                                new_topics = new_topics[-20:]
                        conn.execute(
                            """UPDATE contacts
                               SET last_interaction = ?,
                                   interaction_count = interaction_count + 1,
                                   topics = ?,
                                   updated_at = ?
                               WHERE id = ?""",
                            (
                                now_iso,
                                json.dumps(new_topics, ensure_ascii=False),
                                now_iso,
                                existing["id"],
                            ),
                        )
                    else:
                        # 新增联系人
                        topics_list = [topic] if topic else []
                        conn.execute(
                            """INSERT INTO contacts
                               (id, name, relationship, topics, last_interaction,
                                interaction_count, created_at, updated_at)
                               VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                            (
                                str(uuid.uuid4())[:8],
                                name,
                                relation,
                                json.dumps(topics_list, ensure_ascii=False),
                                now_iso,
                                now_iso,
                                now_iso,
                            ),
                        )
                conn.commit()
        logger.debug(f"[ContactManager] 观察到 {len(names)} 个人物: {names}")

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def add_contact(
        self,
        name: str,
        relationship: str = "其他",
        notes: str = "",
        follow_up_after_days: int = 0,
    ) -> str:
        """手动新增联系人，返回 contact_id。"""
        contact_id = str(uuid.uuid4())[:8]
        now_iso = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO contacts
                       (id, name, relationship, notes, follow_up_after_days,
                        interaction_count, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, 0, ?, ?)""",
                    (
                        contact_id,
                        name,
                        relationship,
                        notes,
                        follow_up_after_days,
                        now_iso,
                        now_iso,
                    ),
                )
                conn.commit()
        return contact_id

    def update_contact(self, contact_id: str, **kwargs) -> bool:
        """更新联系人字段。可更新: notes, relationship, follow_up_after_days。"""
        allowed = {"notes", "relationship", "follow_up_after_days", "aliases"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return False
        fields["updated_at"] = datetime.now().isoformat(timespec="seconds")
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [contact_id]
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    f"UPDATE contacts SET {set_clause} WHERE id = ?", values
                )
                conn.commit()
                return cursor.rowcount > 0

    def get_contact(self, contact_id: str) -> Optional[Dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM contacts WHERE id = ?", (contact_id,)
            ).fetchone()
            return dict(row) if row else None

    def find_contact(self, name: str) -> Optional[Dict]:
        with self._connect() as conn:
            row = self._find_by_name(conn, name)
            return dict(row) if row else None

    def list_contacts(
        self,
        limit: int = 20,
        sort_by: str = "last_interaction",
    ) -> List[Dict]:
        """列出联系人，按最近互动时间倒序。"""
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT * FROM contacts
                    ORDER BY {sort_by} DESC NULLS LAST
                    LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_contact(self, contact_id: str) -> bool:
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    "DELETE FROM contacts WHERE id = ?", (contact_id,)
                )
                conn.commit()
                return cursor.rowcount > 0

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]

    # ── 跟进检查 ──────────────────────────────────────────────────────────────

    def get_follow_up_pending(self) -> List[Dict]:
        """
        返回需要跟进的联系人列表：
        follow_up_after_days > 0 且距最近互动超过该天数。
        """
        now = datetime.now()
        results = []
        with self._connect() as conn:
            rows = conn.execute("""SELECT * FROM contacts
                   WHERE follow_up_after_days > 0
                     AND last_interaction IS NOT NULL""").fetchall()
            for row in rows:
                contact = dict(row)
                try:
                    last_dt = datetime.fromisoformat(contact["last_interaction"])
                    days_since = (now - last_dt).days
                    if days_since >= contact["follow_up_after_days"]:
                        contact["days_since"] = days_since
                        results.append(contact)
                except Exception:
                    import logging

                    logging.getLogger(__name__).warning(
                        "Silenced exception caught", exc_info=True
                    )
        return results

    def push_follow_up_reminders(self):
        """将需要跟进的联系人推入 ProactiveAgent 队列。"""
        pending = self.get_follow_up_pending()
        if not pending:
            return
        try:
            from app.core.agent.proactive_agent import ProactiveAgent

            pa = ProactiveAgent.get()
            for c in pending:
                days = c.get("days_since", c["follow_up_after_days"])
                content = (
                    f"你已经 {days} 天没和 **{c['name']}** 联系了，"
                    f"要不要发个消息问候一下？"
                )
                if c.get("notes"):
                    content += f"（备注：{c['notes'][:40]}）"
                pa._enqueue(
                    {
                        "id": f"followup_{c['id']}",
                        "type": "follow_up",
                        "content": content,
                        "priority": "medium",
                        "triggered_by": "contact_manager",
                        "created_at": datetime.now().isoformat(timespec="seconds"),
                        "expires_at": (datetime.now() + timedelta(hours=24)).isoformat(
                            timespec="seconds"
                        ),
                        "dismissed": False,
                    }
                )
            logger.info(f"[ContactManager] 推送了 {len(pending)} 条跟进提醒")
        except Exception as exc:
            logger.warning(f"[ContactManager] ProactiveAgent 推送失败: {exc}")

    # ── 私有工具 ──────────────────────────────────────────────────────────────

    def _find_by_name(
        self, conn: sqlite3.Connection, name: str
    ) -> Optional[sqlite3.Row]:
        """在 name 和 aliases 中查找匹配。"""
        row = conn.execute("SELECT * FROM contacts WHERE name = ?", (name,)).fetchone()
        if row:
            return row
        # 检查 aliases
        all_rows = conn.execute("SELECT * FROM contacts").fetchall()
        for r in all_rows:
            aliases = json.loads(r["aliases"] or "[]")
            if name in aliases:
                return r
        return None

    @staticmethod
    def _extract_names(text: str) -> List[str]:
        """从文本中提取人名（中文 + 英文）。"""
        names: List[str] = []
        # 中文姓名
        for m in _CN_NAME_RE.finditer(text):
            n = m.group(1).strip()
            if len(n) >= 2 and n not in _STOP_NAMES:
                names.append(n)
        # 英文名（仅在明显是人名上下文中）
        for m in _EN_NAME_RE.finditer(text):
            n = m.group(1).strip()
            if n not in _EN_STOP_WORDS and len(n) >= 3:
                names.append(n)
        return list(dict.fromkeys(names))  # 去重保序

    @staticmethod
    def _infer_relation(text: str) -> str:
        """从上下文文字推断关系类型。"""
        for keyword, relation in _RELATION_MAP.items():
            if keyword in text:
                return relation
        return "其他"


# ── 停用词（防止把常见词误判为人名）─────────────────────────────────────────────
_STOP_NAMES = {
    "用户",
    "系统",
    "助手",
    "机器",
    "工具",
    "模型",
    "数据",
    "文件",
    "内容",
    "信息",
    "结果",
    "问题",
    "任务",
    "项目",
    "代码",
    "文档",
    "报告",
    "分析",
    "方案",
    "计划",
    "测试",
}
_EN_STOP_WORDS = {
    "The",
    "This",
    "That",
    "With",
    "From",
    "Have",
    "Will",
    "Can",
    "Are",
    "Was",
    "Has",
    "For",
    "Your",
    "Our",
    "Please",
    "Thank",
    "Hello",
    "Sorry",
    "Sure",
    "Yes",
    "No",
    "True",
    "False",
    "None",
    "Error",
    "Warning",
    "Info",
}
