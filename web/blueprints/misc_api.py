# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Miscellaneous API blueprint.

Notes, reminders, calendar, clipboard and search routes.
"""

import logging
import os

from flask import Blueprint, Response, jsonify, request

_logger = logging.getLogger("koto.routes.misc_api")

misc_api_bp = Blueprint("misc_api", __name__)


# ---------------------------------------------------------------------------
# Lazy helpers – avoid circular imports with web.app
# ---------------------------------------------------------------------------


def _get_workspace_dir():
    from web.runtime_context import service_registry

    return service_registry.workspace_dir


# ========================= Notes API =========================


@misc_api_bp.route("/api/notes/add", methods=["POST"])
def add_note() -> Response:
    """添加笔记"""
    from note_manager import get_note_manager

    data = request.json
    title = data.get("title", "")
    content = data.get("content", "")
    category = data.get("category", "default")
    tags = data.get("tags", [])

    note_manager = get_note_manager()
    note = note_manager.add_note(content, tags=tags, category=category)
    note_id = note.get("id") if isinstance(note, dict) else note

    return jsonify({"success": True, "note_id": note_id})


@misc_api_bp.route("/api/notes/list", methods=["GET"])
def list_notes() -> Response:
    """列出最近笔记（补齐完整内容与标题，供前端列表直接渲染）"""
    from note_manager import get_note_manager

    limit = int(request.args.get("limit", 20))
    category = request.args.get("category")

    note_manager = get_note_manager()
    notes = note_manager.get_recent_notes(limit)

    hydrated = []
    for entry in notes:
        if not isinstance(entry, dict):
            continue
        note = note_manager.get_note(entry.get("id") or "")
        if not isinstance(note, dict):
            continue
        merged = dict(entry)
        merged.update(note)
        content = merged.get("content") or ""
        title = (merged.get("title") or "").strip()
        if not title:
            first_line = next((ln.strip() for ln in content.splitlines() if ln.strip()), "")
            title = first_line[:50] if first_line else "\u65e0\u6807\u9898\u7b14\u8bb0"
        merged["title"] = title
        merged["content"] = content
        if category and merged.get("category") != category:
            continue
        hydrated.append(merged)

    return jsonify({"notes": hydrated})


@misc_api_bp.route("/api/notes/search", methods=["GET"])
def search_notes() -> Response:
    """搜索笔记"""
    from note_manager import get_note_manager

    query = request.args.get("query", "")
    note_manager = get_note_manager()
    results = note_manager.search_notes(query)

    return jsonify({"results": results})


@misc_api_bp.route("/api/notes/<note_id>", methods=["DELETE"])
def delete_note(note_id: str) -> Response:
    """删除笔记"""
    from note_manager import get_note_manager

    note_manager = get_note_manager()
    success = note_manager.delete_note(note_id)

    return jsonify({"success": success})


@misc_api_bp.route("/api/notes/<note_id>", methods=["PUT"])
def update_note(note_id: str) -> Response:
    """更新现有笔记"""
    from note_manager import get_note_manager

    data = request.json or {}
    note_manager = get_note_manager()
    updated = note_manager.update_note(
        note_id,
        content=data.get("content", ""),
        tags=data.get("tags"),
        category=data.get("category"),
        title=data.get("title"),
    )
    if updated is None:
        return jsonify({"success": False, "error": "笔记不存在或更新失败"}), 404
    return jsonify({"success": True, "note": updated})


# ========================= Reminders API =========================


@misc_api_bp.route("/api/reminders/add", methods=["POST"])
def add_reminder() -> Response:
    """创建本地系统提醒
    请求体: {"title": str, "message": str, "time": ISO8601, "seconds": int}
    - 传 time (ISO 时间) 或 seconds (相对秒数) 任选其一
    """
    from datetime import datetime

    from app.core.services.reminder_manager import get_reminder_manager

    data = request.json or {}
    title = data.get("title") or "提醒"
    message = data.get("message") or ""
    icon = data.get("icon")
    remind_time = data.get("time")
    seconds = data.get("seconds")

    mgr = get_reminder_manager()
    if remind_time:
        try:
            dt = datetime.fromisoformat(remind_time)
        except Exception:
            return jsonify({"success": False, "error": "时间格式需为 ISO8601"}), 400
        rid = mgr.add_reminder(title, message, dt, icon)
    elif seconds is not None:
        try:
            sec = int(seconds)
        except Exception:
            return jsonify({"success": False, "error": "seconds 需为整数"}), 400
        rid = mgr.add_reminder_in(title, message, sec, icon)
    else:
        return jsonify({"success": False, "error": "需提供 time 或 seconds"}), 400

    return jsonify({"success": True, "reminder_id": rid})


@misc_api_bp.route("/api/reminders/list", methods=["GET"])
def list_reminders_api() -> Response:
    """列出所有提醒"""
    from app.core.services.reminder_manager import get_reminder_manager

    mgr = get_reminder_manager()
    return jsonify({"reminders": mgr.list_reminders()})


@misc_api_bp.route("/api/reminders/<reminder_id>", methods=["DELETE"])
def cancel_reminder(reminder_id: str) -> Response:
    """取消提醒"""
    from app.core.services.reminder_manager import get_reminder_manager

    mgr = get_reminder_manager()
    ok = mgr.cancel_reminder(reminder_id)
    return jsonify({"success": ok})


# ========================= Calendar API =========================


@misc_api_bp.route("/api/calendar/add", methods=["POST"])
def add_calendar_event() -> Response:
    """新增日程并自动创建本地提醒
    请求体: {"title": str, "description": str, "start": ISO8601, "end": ISO8601?, "remind_before_minutes": int?}
    """
    from datetime import datetime

    from app.core.services.calendar_manager import get_calendar_manager

    data = request.json or {}
    title = data.get("title") or "日程"
    description = data.get("description") or ""
    start = data.get("start")
    end = data.get("end")
    remind_before_minutes = int(data.get("remind_before_minutes") or 0)

    if not start:
        return jsonify({"success": False, "error": "start 不能为空 (ISO8601)"}), 400
    try:
        start_dt = datetime.fromisoformat(start)
    except Exception:
        return jsonify({"success": False, "error": "start 必须是 ISO8601 时间"}), 400
    end_dt = None
    if end:
        try:
            end_dt = datetime.fromisoformat(end)
        except Exception:
            return jsonify({"success": False, "error": "end 必须是 ISO8601 时间"}), 400

    mgr = get_calendar_manager()
    event_id = mgr.add_event(
        title, description, start_dt, end_dt, remind_before_minutes
    )
    return jsonify({"success": True, "event_id": event_id})


@misc_api_bp.route("/api/calendar/list", methods=["GET"])
def list_calendar_events() -> Response:
    from app.core.services.calendar_manager import get_calendar_manager

    limit = int(request.args.get("limit", 100))
    mgr = get_calendar_manager()
    return jsonify({"events": mgr.list_events(limit)})


@misc_api_bp.route("/api/calendar/<event_id>", methods=["DELETE"])
def delete_calendar_event(event_id: str) -> Response:
    from app.core.services.calendar_manager import get_calendar_manager

    mgr = get_calendar_manager()
    ok = mgr.delete_event(event_id)
    return jsonify({"success": ok})


# ========================= Clipboard API =========================


@misc_api_bp.route("/api/clipboard/history", methods=["GET"])
def get_clipboard_history() -> Response:
    """获取剪贴板历史"""
    from app.core.services.clipboard_manager import get_clipboard_manager

    limit = int(request.args.get("limit", 50))
    type_filter = request.args.get("type")
    clipboard_manager = get_clipboard_manager()
    history = clipboard_manager.get_history(limit)
    if type_filter:
        history = [item for item in history if item.get("type") == type_filter]

    return jsonify({"history": history})


@misc_api_bp.route("/api/clipboard/search", methods=["GET"])
def search_clipboard() -> Response:
    """搜索剪贴板历史"""
    from app.core.services.clipboard_manager import get_clipboard_manager

    query = request.args.get("query", "")
    type_filter = request.args.get("type")
    clipboard_manager = get_clipboard_manager()
    results = clipboard_manager.search(query)
    if type_filter:
        results = [item for item in results if item.get("type") == type_filter]

    return jsonify({"results": results})


@misc_api_bp.route("/api/clipboard/copy", methods=["POST"])
def copy_from_history() -> Response:
    """从历史中复制"""
    from app.core.services.clipboard_manager import get_clipboard_manager

    content = request.json.get("content")
    index = request.json.get("index")
    clipboard_manager = get_clipboard_manager()
    if index is not None:
        try:
            index = int(index)
        except Exception:
            return jsonify({"success": False, "error": "index 必须是整数"}), 400
        success = clipboard_manager.copy_from_history(index)
    else:
        success = clipboard_manager.copy_from_history(content or "")

    return jsonify({"success": success})


# ========================= Search API =========================


@misc_api_bp.route("/api/search/all", methods=["GET"])
def search_all() -> Response:
    """Global search across all indexed content.
    ---
    tags:
      - Search
    parameters:
      - in: query
        name: query
        type: string
        required: true
        description: Search query string
      - in: query
        name: max_results
        type: integer
        default: 50
        description: Maximum number of results to return
    responses:
      200:
        description: Search results
        schema:
          type: object
          properties:
            results:
              type: array
              items:
                type: object
            count:
              type: integer
              description: Total number of results
    """
    from app.core.services.search_engine import get_search_engine

    query = request.args.get("query", "")
    max_results = int(request.args.get("max_results", 50))

    search_engine = get_search_engine()
    results = search_engine.search_all(query, max_results)

    return jsonify(results)


@misc_api_bp.route("/api/search/files", methods=["GET"])
def search_files() -> Response:
    """搜索文件"""
    from app.core.services.search_engine import get_search_engine

    query = request.args.get("query", "")
    max_results = int(request.args.get("max_results", 20))

    search_engine = get_search_engine()
    results = search_engine.search_files(query, max_results)

    return jsonify({"results": results})


# ========================= Data Pipeline API =========================
