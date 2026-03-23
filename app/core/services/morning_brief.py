# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Koto Morning Brief Service — 晨间简报
======================================
每日在指定时间（默认 08:00）生成一份综合简报，包含：
  1. 今日日程（CalendarManager）
  2. 活跃目标进展（GoalManager）
  3. 未完成提醒（ReminderManager）
  4. 近期记忆洞察（MemoryManager）
  5. ShadowWatcher：生产力摘要（活跃时段、高频话题）
  6. 格言 / 问候语（LLM 生成）

简报生成后：
  - 注入到 ProactiveAgent 队列（桌面端显示）
  - 如配置了 Telegram Bot，同步推送

调度方式：
  - JobRunner 中注册 "morning_brief" 定时任务（daily_at = "HH:MM"）
  - 也可通过 API /api/brief/generate 手动触发

配置:
  MORNING_BRIEF_TIME=08:00        (默认 08:00)
  MORNING_BRIEF_ENABLED=true      (默认开启)
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_BRIEF_TIME = os.environ.get("MORNING_BRIEF_TIME", "08:00").strip()
_BRIEF_ENABLED = os.environ.get("MORNING_BRIEF_ENABLED", "true").lower() != "false"

# ── 单例 ──────────────────────────────────────────────────────────────────────
_service_instance: Optional["MorningBriefService"] = None
_service_lock = threading.Lock()


def get_morning_brief_service() -> "MorningBriefService":
    global _service_instance
    if _service_instance is None:
        with _service_lock:
            if _service_instance is None:
                _service_instance = MorningBriefService()
    return _service_instance


# ============================================================================
# MorningBriefService
# ============================================================================


class MorningBriefService:
    """生成并分发每日晨间简报。"""

    def __init__(self):
        self._last_brief_date: Optional[str] = None  # YYYY-MM-DD
        self._scheduler_thread: Optional[threading.Thread] = None
        self._running = False

    # ── 调度 ──────────────────────────────────────────────────────────────────

    def start_scheduler(self):
        """启动日程调度器（每天检查是否到了简报时间）。"""
        if self._running or not _BRIEF_ENABLED:
            return
        self._running = True
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            name="MorningBriefScheduler",
            daemon=True,
        )
        self._scheduler_thread.start()
        logger.info(f"[MorningBrief] ✅ 调度器已启动，简报时间: {_BRIEF_TIME}")

    def stop_scheduler(self):
        self._running = False

    def _scheduler_loop(self):
        """每分钟检查一次是否到了简报时间。"""
        while self._running:
            try:
                now = datetime.now()
                today = now.strftime("%Y-%m-%d")
                current_time = now.strftime("%H:%M")
                if current_time == _BRIEF_TIME and self._last_brief_date != today:
                    self._last_brief_date = today
                    logger.info("[MorningBrief] 🌅 触发晨间简报生成…")
                    threading.Thread(
                        target=self._deliver_brief,
                        name="MorningBriefDeliver",
                        daemon=True,
                    ).start()
            except Exception as exc:
                logger.warning(f"[MorningBrief] 调度检查异常: {exc}")
            # 精确到分钟，每 30s 检查一次（避免整分恰好错过）
            import time

            time.sleep(30)

    # ── 生成 ──────────────────────────────────────────────────────────────────

    def generate_brief(self, as_text: bool = False) -> str:
        """
        生成完整晨间简报文本。

        Args:
            as_text: True 时返回纯文本（Telegram 用）；
                     False 时返回 Markdown（桌面端用）。
        Returns:
            简报字符串。
        """
        now = datetime.now()
        sections: List[str] = []

        # 标题
        greeting = _time_greeting(now)
        date_str = now.strftime("%Y年%m月%d日 %A")
        sections.append(f"# {greeting} · {date_str}\n")

        # 1. 今日日程
        calendar_section = self._section_calendar(now)
        if calendar_section:
            sections.append(calendar_section)

        # 2. 活跃目标
        goals_section = self._section_goals()
        if goals_section:
            sections.append(goals_section)

        # 3. 未完成提醒
        reminders_section = self._section_reminders(now)
        if reminders_section:
            sections.append(reminders_section)

        # 4. 记忆洞察
        memory_section = self._section_memory()
        if memory_section:
            sections.append(memory_section)

        # 5. 生产力摘要
        productivity_section = self._section_productivity(now)
        if productivity_section:
            sections.append(productivity_section)

        # 6. LLM 生成的一句话激励
        motivation = self._generate_motivation(now)
        if motivation:
            sections.append(f"\n---\n💬 *{motivation}*")

        brief = "\n".join(sections)
        if as_text:
            # 去掉 Markdown 符号给纯文本场景
            import re

            brief = re.sub(r"[#*`_]", "", brief)
        return brief

    def _deliver_brief(self):
        """生成后，推送到 ProactiveAgent 队列 + Telegram。"""
        try:
            brief_text = self.generate_brief(as_text=False)

            # 推送到 ProactiveAgent
            try:
                from app.core.agent.proactive_agent import ProactiveAgent

                ProactiveAgent.get()._enqueue(
                    {
                        "id": f"brief_{datetime.now().strftime('%Y%m%d')}",
                        "type": "session_summary",
                        "content": brief_text,
                        "priority": "high",
                        "triggered_by": "morning_brief",
                        "created_at": datetime.now().isoformat(timespec="seconds"),
                        "expires_at": (datetime.now() + timedelta(hours=12)).isoformat(
                            timespec="seconds"
                        ),
                        "dismissed": False,
                    }
                )
                logger.info("[MorningBrief] ✅ 简报已推入 ProactiveAgent 队列")
            except Exception as exc:
                logger.warning(f"[MorningBrief] ProactiveAgent 推送失败: {exc}")

            # 推送到 Telegram
            try:
                from web.telegram_bot import get_telegram_bot

                bot = get_telegram_bot()
                if bot and bot.is_running:
                    chat_id_str = os.environ.get(
                        "TELEGRAM_MORNING_BRIEF_CHAT_ID", ""
                    ).strip()
                    if chat_id_str:
                        tg_text = self.generate_brief(as_text=True)
                        bot.send_text(int(chat_id_str), tg_text)
                        logger.info("[MorningBrief] ✅ 简报已推送至 Telegram")
            except Exception as exc:
                logger.debug(f"[MorningBrief] Telegram 推送跳过: {exc}")

        except Exception as exc:
            logger.warning(f"[MorningBrief] 简报生成/分发失败: {exc}")

    # ── 各节内容构建 ──────────────────────────────────────────────────────────

    def _section_calendar(self, now: datetime) -> str:
        """今日日程。"""
        try:
            from web.calendar_manager import CalendarManager

            cm = CalendarManager()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timedelta(days=1)
            events = [
                e
                for e in cm.list_events(limit=50)
                if _in_range(e.get("start", ""), today_start, today_end)
            ]
            if not events:
                return ""
            lines = ["## 📅 今日日程\n"]
            for e in events:
                start_str = _fmt_time(e.get("start", ""))
                title = e.get("title", "（无标题）")
                lines.append(f"- **{start_str}** {title}")
                if e.get("description"):
                    lines.append(f"  {e['description'][:60]}")
            return "\n".join(lines) + "\n"
        except Exception as exc:
            logger.debug(f"[MorningBrief] 日程获取跳过: {exc}")
            return ""

    def _section_goals(self) -> str:
        """活跃目标。"""
        try:
            from app.core.goal.goal_manager import GoalStatus, get_goal_manager

            gm = get_goal_manager()
            goals = gm.list_goals(status=GoalStatus.ACTIVE, limit=10) + gm.list_goals(
                status=GoalStatus.WAITING_USER, limit=10
            )
            if not goals:
                return ""
            lines = ["## 🎯 活跃目标\n"]
            for g in goals[:5]:
                status_icon = {"active": "🟢", "waiting_user": "🟡"}.get(
                    str(g.status), "⚪"
                )
                lines.append(f"- {status_icon} **{g.title}**")
                if getattr(g, "deadline", None):
                    deadline = g.deadline[:10]
                    # 计算剩余天数
                    try:
                        days_left = (
                            datetime.fromisoformat(g.deadline) - datetime.now()
                        ).days
                        if days_left == 0:
                            lines.append(f"  ⚠️ 今天截止！")
                        elif days_left < 0:
                            lines.append(f"  ❌ 已逾期 {abs(days_left)} 天")
                        else:
                            lines.append(f"  ⏰ 还剩 {days_left} 天 ({deadline})")
                    except Exception:
                        lines.append(f"  ⏰ 截止: {deadline}")
            return "\n".join(lines) + "\n"
        except Exception as exc:
            logger.debug(f"[MorningBrief] 目标获取跳过: {exc}")
            return ""

    def _section_reminders(self, now: datetime) -> str:
        """今日及逾期的提醒。"""
        try:
            from web.reminder_manager import get_reminder_manager

            rm = get_reminder_manager()
            today_end = now.replace(hour=23, minute=59, second=59)
            pending = [
                r
                for r in rm.reminders.values()
                if r.get("status") == "scheduled"
                and _before_or_on(r.get("time", ""), today_end)
            ]
            if not pending:
                return ""
            lines = ["## ⏰ 今日提醒\n"]
            for r in sorted(pending, key=lambda x: x.get("time", ""))[:6]:
                time_str = _fmt_time(r.get("time", ""))
                lines.append(f"- **{time_str}** {r.get('title', '（无标题）')}")
            return "\n".join(lines) + "\n"
        except Exception as exc:
            logger.debug(f"[MorningBrief] 提醒获取跳过: {exc}")
            return ""

    def _section_memory(self) -> str:
        """昨日/近期记忆洞察。"""
        try:
            mem_path = (
                Path(__file__).parent.parent.parent.parent / "config" / "memory.json"
            )
            if not mem_path.exists():
                return ""
            with open(mem_path, "r", encoding="utf-8") as f:
                memories = json.load(f)
            if not memories:
                return ""
            # 取最近 24h 内的记忆
            cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
            recent = []
            items = memories if isinstance(memories, list) else list(memories.values())
            for m in items:
                if isinstance(m, dict) and m.get("created_at", "") >= cutoff:
                    recent.append(m)
            if not recent:
                return ""
            lines = ["## 🧠 昨日记忆摘要\n"]
            for m in recent[:4]:
                content = m.get("content") or m.get("text", "")
                if content:
                    lines.append(f"- {content[:80]}{'…' if len(content) > 80 else ''}")
            return "\n".join(lines) + "\n"
        except Exception as exc:
            logger.debug(f"[MorningBrief] 记忆获取跳过: {exc}")
            return ""

    def _section_productivity(self, now: datetime) -> str:
        """基于 ShadowWatcher 的生产力洞察。"""
        try:
            from app.core.monitoring.shadow_watcher import get_shadow_watcher

            watcher = get_shadow_watcher()
            obs = watcher.get_observations()
            if not obs:
                return ""

            lines: List[str] = []

            # 高频话题 Top 3
            topics: Dict[str, int] = obs.get("topics", {})
            if topics:
                top3 = sorted(topics.items(), key=lambda x: x[1], reverse=True)[:3]
                topic_strs = "、".join(f"**{k}**" for k, _ in top3)
                lines.append(f"- 近期最关注话题：{topic_strs}")

            # 最活跃时段
            active_hours: Dict[str, int] = obs.get("active_hours", {})
            if active_hours:
                peak_hour = max(active_hours, key=lambda h: active_hours[h])
                lines.append(f"- 你的高效时段通常是 **{peak_hour}:00** 前后")

            # 连续使用天数
            streak: int = obs.get("streak", 0)
            if streak > 1:
                lines.append(f"- 连续使用 **{streak} 天** 🔥，保持住！")

            if not lines:
                return ""
            return "## 📊 生产力参考\n\n" + "\n".join(lines) + "\n"
        except Exception as exc:
            logger.debug(f"[MorningBrief] ShadowWatcher 获取跳过: {exc}")
            return ""

    def _generate_motivation(self, now: datetime) -> str:
        """调用 LLM 生成一句今日激励语（限 30 字内）。"""
        try:
            from app.core.agent.factory import create_agent

            agent = create_agent()
            weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][
                now.weekday()
            ]
            prompt = (
                f"今天是{weekday}，请用一句话（不超过30字）给用户一个友善的激励或建议。"
                "风格简洁温暖，不要重复「加油」或「努力」之类的陈词。直接输出这句话，不加任何前缀。"
            )
            result = agent.llm_provider.generate_content(
                prompt, model=agent.model_id, max_tokens=60, temperature=0.9
            )
            text = (
                result.get("content", "") if isinstance(result, dict) else str(result)
            )
            return text.strip()[:60]
        except Exception as exc:
            logger.debug(f"[MorningBrief] LLM 激励生成跳过: {exc}")
            # 兜底：预设语录
            fallbacks = [
                "今天的每一步，都是明天的基础。",
                "专注当下，答案自然浮现。",
                "慢下来也是一种效率。",
                "清单完成一半的感觉，比什么都好。",
                "做好准备，让机会找到你。",
            ]
            return fallbacks[now.day % len(fallbacks)]


# ── 工具函数 ──────────────────────────────────────────────────────────────────


def _time_greeting(now: datetime) -> str:
    h = now.hour
    if h < 6:
        return "夜深了"
    elif h < 12:
        return "早上好"
    elif h < 14:
        return "午安"
    elif h < 18:
        return "下午好"
    elif h < 22:
        return "晚上好"
    else:
        return "夜深了"


def _in_range(iso_str: str, start: datetime, end: datetime) -> bool:
    if not iso_str:
        return False
    try:
        dt = datetime.fromisoformat(iso_str)
        return start <= dt < end
    except Exception:
        return False


def _before_or_on(iso_str: str, cutoff: datetime) -> bool:
    if not iso_str:
        return False
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt <= cutoff
    except Exception:
        return False


def _fmt_time(iso_str: str) -> str:
    if not iso_str:
        return "未知时间"
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%H:%M")
    except Exception:
        return iso_str[:16]
