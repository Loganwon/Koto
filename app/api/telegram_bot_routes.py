# -*- coding: utf-8 -*-
"""
Telegram Bot 管理 API
======================
提供查看 Bot 状态、更新配置、手动触发推送的接口。

路由:
  GET  /api/telegram/status      — Bot 运行状态
  POST /api/telegram/config      — 更新 Token / 白名单（写入运行时 env，重启后需重新设置）
  POST /api/telegram/test        — 向指定 chat_id 发送测试消息
  POST /api/telegram/restart     — 重新初始化 Bot（用新配置重连）
  GET  /api/telegram/contacts    — 联系人列表（分页）
  POST /api/telegram/contacts    — 手动新增联系人
  PATCH /api/telegram/contacts/<id> — 更新联系人
  DELETE /api/telegram/contacts/<id> — 删除联系人
  GET  /api/telegram/brief/preview — 预览今日晨间简报
  POST /api/telegram/brief/send    — 手动推送晨间简报
"""

from __future__ import annotations

import logging
import os

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

telegram_bp = Blueprint("telegram", __name__)


# ── Bot 状态 ─────────────────────────────────────────────────────────────────

@telegram_bp.get("/status")
def bot_status():
    try:
        from web.telegram_bot import get_telegram_bot

        bot = get_telegram_bot()
        if bot is None:
            return jsonify({"running": False, "reason": "未配置 TELEGRAM_BOT_TOKEN"})
        info = bot.get_bot_info()
        return jsonify({
            "running": bot.is_running,
            "bot_info": info,
            "allowed_chat_ids": os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", ""),
            "morning_brief_chat_id": os.environ.get("TELEGRAM_MORNING_BRIEF_CHAT_ID", ""),
            "morning_brief_time": os.environ.get("MORNING_BRIEF_TIME", "08:00"),
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── 配置更新 ─────────────────────────────────────────────────────────────────

@telegram_bp.post("/config")
def update_config():
    """
    更新 Telegram Bot 配置（持久化到 gemini_config.env）。
    Body JSON 字段（全部可选）:
      token, allowed_chat_ids, morning_brief_chat_id, morning_brief_time
    """
    try:
        data = request.get_json(force=True) or {}
        env_path = _find_env_file()

        updates: dict = {}
        if "token" in data:
            updates["TELEGRAM_BOT_TOKEN"] = str(data["token"]).strip()
        if "allowed_chat_ids" in data:
            updates["TELEGRAM_ALLOWED_CHAT_IDS"] = str(data["allowed_chat_ids"]).strip()
        if "morning_brief_chat_id" in data:
            updates["TELEGRAM_MORNING_BRIEF_CHAT_ID"] = str(data["morning_brief_chat_id"]).strip()
        if "morning_brief_time" in data:
            updates["MORNING_BRIEF_TIME"] = str(data["morning_brief_time"]).strip()
        if "morning_brief_enabled" in data:
            updates["MORNING_BRIEF_ENABLED"] = "true" if data["morning_brief_enabled"] else "false"

        if not updates:
            return jsonify({"error": "没有提供任何有效字段"}), 400

        _write_env_file(env_path, updates)

        # 同步更新当前进程的环境变量（无需重启即可生效）
        for k, v in updates.items():
            os.environ[k] = v

        return jsonify({"ok": True, "updated": list(updates.keys())})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── 测试消息 ─────────────────────────────────────────────────────────────────

@telegram_bp.post("/test")
def send_test():
    """
    向指定 chat_id 发送测试消息。
    Body: {"chat_id": 123456789, "text": "测试消息（可选）"}
    """
    try:
        from web.telegram_bot import get_telegram_bot

        data = request.get_json(force=True) or {}
        chat_id = data.get("chat_id")
        if not chat_id:
            return jsonify({"error": "缺少 chat_id"}), 400

        bot = get_telegram_bot()
        if not bot:
            return jsonify({"error": "Bot 未启动或未配置 Token"}), 503

        text = data.get("text", "👋 这是来自 Koto 的测试消息，连接正常！")
        ok = bot.send_text(int(chat_id), text)
        return jsonify({"ok": ok})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── 重启 Bot ─────────────────────────────────────────────────────────────────

@telegram_bp.post("/restart")
def restart_bot():
    """停止旧 Bot 实例，用最新环境变量重新创建并启动。"""
    try:
        import web.telegram_bot as _tb

        old_bot = _tb._bot_instance
        if old_bot:
            old_bot.stop()
        _tb._bot_instance = None  # 重置单例

        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            return jsonify({"ok": False, "reason": "未配置 TELEGRAM_BOT_TOKEN"}), 400

        new_bot = _tb.get_telegram_bot()
        if new_bot:
            new_bot.start()
            info = new_bot.get_bot_info()
            return jsonify({"ok": True, "bot_info": info})
        return jsonify({"ok": False, "reason": "Bot 创建失败"}), 500
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── 联系人 CRUD ───────────────────────────────────────────────────────────────

@telegram_bp.get("/contacts")
def list_contacts():
    try:
        from app.core.memory.contact_manager import get_contact_manager

        limit = min(int(request.args.get("limit", 20)), 100)
        sort_by = request.args.get("sort_by", "last_interaction")
        if sort_by not in {"last_interaction", "interaction_count", "name", "created_at"}:
            sort_by = "last_interaction"
        contacts = get_contact_manager().list_contacts(limit=limit, sort_by=sort_by)
        return jsonify({"contacts": contacts, "total": get_contact_manager().count()})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@telegram_bp.post("/contacts")
def create_contact():
    try:
        from app.core.memory.contact_manager import get_contact_manager

        data = request.get_json(force=True) or {}
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name 不能为空"}), 400
        cid = get_contact_manager().add_contact(
            name=name,
            relationship=data.get("relationship", "其他"),
            notes=data.get("notes", ""),
            follow_up_after_days=int(data.get("follow_up_after_days", 0)),
        )
        return jsonify({"ok": True, "id": cid}), 201
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@telegram_bp.patch("/contacts/<contact_id>")
def update_contact(contact_id: str):
    try:
        from app.core.memory.contact_manager import get_contact_manager

        data = request.get_json(force=True) or {}
        ok = get_contact_manager().update_contact(contact_id, **data)
        if not ok:
            return jsonify({"error": "联系人不存在"}), 404
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@telegram_bp.delete("/contacts/<contact_id>")
def delete_contact(contact_id: str):
    try:
        from app.core.memory.contact_manager import get_contact_manager

        ok = get_contact_manager().delete_contact(contact_id)
        if not ok:
            return jsonify({"error": "联系人不存在"}), 404
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── 晨间简报 ─────────────────────────────────────────────────────────────────

@telegram_bp.get("/brief/preview")
def preview_brief():
    try:
        from app.core.services.morning_brief import get_morning_brief_service

        text = get_morning_brief_service().generate_brief(as_text=False)
        return jsonify({"brief": text})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@telegram_bp.post("/brief/send")
def send_brief():
    """手动推送晨间简报到 Telegram 和 ProactiveAgent。"""
    try:
        from app.core.services.morning_brief import get_morning_brief_service

        svc = get_morning_brief_service()
        # 在当前线程同步执行（是 POST 请求触发，不需要异步）
        svc._deliver_brief()
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _find_env_file() -> str:
    """查找 gemini_config.env 文件路径。"""
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "config", "gemini_config.env"),
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "gemini_config.env"),
    ]
    for c in candidates:
        p = os.path.realpath(c)
        if os.path.exists(p):
            return p
    # 返回第一个候选路径（不存在时创建）
    return os.path.realpath(candidates[0])


def _write_env_file(env_path: str, updates: dict):
    """将键值对 upsert 到 .env 文件，保留其他行。"""
    lines: list = []
    existing_keys: set = set()
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    new_lines: list = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            existing_keys.add(key)
            new_lines.append(f"{key}={updates[key]}\n")
        else:
            new_lines.append(line)
    # 追加不存在的 key
    for k, v in updates.items():
        if k not in existing_keys:
            new_lines.append(f"{k}={v}\n")
    os.makedirs(os.path.dirname(env_path), exist_ok=True)
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
