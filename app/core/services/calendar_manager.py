#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
本地日程管理器
- 持久化到 workspace/calendar/events.json
- 支持新增/删除/查询
- 创建事件时自动触发本地提醒（使用 reminder_manager + win10toast）
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from app.core.config.atomic_json_store import load_json_document, save_json_document
from app.core.services.reminder_manager import get_reminder_manager

logger = logging.getLogger(__name__)


class CalendarManager:
    def __init__(self, events_file: Optional[str] = None):
        import sys

        if getattr(sys, "frozen", False):
            project_root = os.path.dirname(sys.executable)
        else:
            project_root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "..")
            )
        self.project_root = project_root
        configured_path = events_file or os.environ.get("KOTO_CALENDAR_EVENTS_PATH")
        self.events_file = configured_path or os.path.join(
            project_root, "data", "calendar", "events.json"
        )
        self.calendar_dir = os.path.dirname(self.events_file)
        os.makedirs(self.calendar_dir, exist_ok=True)
        self._legacy_events_file = os.path.join(
            project_root, "app", "core", "workspace", "calendar", "events.json"
        )

        self.events: List[Dict] = []
        self._load()

    def _load(self):
        load_path = self.events_file
        if (
            not os.path.exists(load_path)
            and not os.environ.get("KOTO_CALENDAR_EVENTS_PATH")
            and os.path.exists(self._legacy_events_file)
        ):
            load_path = self._legacy_events_file
        if os.path.exists(load_path):
            try:
                data = load_json_document(load_path, default=[])
                self.events = data if isinstance(data, list) else []
                logger.info(f"[日程] 已加载 {len(self.events)} 条事件")
            except Exception as e:
                logger.info(f"[日程] 加载失败: {e}")

    def _save(self):
        try:
            save_json_document(self.events_file, self.events)
        except Exception as e:
            logger.info(f"[日程] 保存失败: {e}")

    def list_events(self, limit: int = 100) -> List[Dict]:
        # 返回按开始时间排序的最近事件
        def _key(ev):
            try:
                return datetime.fromisoformat(ev.get("start"))
            except Exception:
                return datetime.max

        return sorted(self.events, key=_key)[:limit]

    def add_event(
        self,
        title: str,
        description: str,
        start: datetime,
        end: Optional[datetime] = None,
        remind_before_minutes: int = 0,
    ) -> str:
        event_id = f"event_{start.strftime('%Y%m%d_%H%M%S_%f')}"
        event = {
            "id": event_id,
            "title": title,
            "description": description,
            "start": start.isoformat(),
            "end": end.isoformat() if end else None,
            "created_at": datetime.now().isoformat(),
        }
        self.events.append(event)
        self._save()

        # 创建提醒：默认在开始时间提醒，可选提前 remind_before_minutes
        try:
            remind_at = start
            if remind_before_minutes > 0:
                remind_at = start - timedelta(minutes=remind_before_minutes)
            if remind_at > datetime.now():
                mgr = get_reminder_manager()
                mgr.add_reminder(
                    title=f"日程提醒: {title}",
                    message=description or "开始时间到",
                    remind_at=remind_at,
                    icon=os.path.join(self.project_root, "assets", "koto_icon.ico"),
                )
        except Exception as e:
            logger.warning(f"⚠️ 创建日程提醒失败: {e}")

        return event_id

    def delete_event(self, event_id: str) -> bool:
        before = len(self.events)
        self.events = [ev for ev in self.events if ev.get("id") != event_id]
        if len(self.events) != before:
            self._save()
            return True
        return False


_calendar_manager: Optional[CalendarManager] = None


def get_calendar_manager() -> CalendarManager:
    global _calendar_manager
    if _calendar_manager is None:
        _calendar_manager = CalendarManager()
    return _calendar_manager
