# -*- coding: utf-8 -*-
"""
Koto Telegram Bot Integration
==============================
让 Koto 在 Telegram 上随时响应，是最轻量的移动端接入方式。

功能:
  - 文字对话 → UnifiedAgent 处理（保留对话历史）
  - 语音消息 → OGG→WAV→STT → Agent
  - 文件/图片 → 下载后通过 Agent 分析
  - 命令: /start /help /goals /morning /status /memory /remind
  - 主动消息推送（ProactiveAgent 队列 → push_proactive_to_telegram）
  - 白名单安全模式（可选）

配置 (在 gemini_config.env 中添加):
  TELEGRAM_BOT_TOKEN=1234567890:ABCDEFGxxxxxx
  TELEGRAM_ALLOWED_CHAT_IDS=123456789,987654321   # 留空则全放行（私有部署慎用）
  TELEGRAM_MORNING_BRIEF_CHAT_ID=123456789        # 晨间简报推送目标 chat_id
  TELEGRAM_MAX_HISTORY_TURNS=20                   # 保留的历史记录轮数

依赖: requests（已在 requirements.txt 中）
"""

from __future__ import annotations

import io
import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────────
_TG_API_BASE = "https://api.telegram.org/bot{token}/{method}"
_POLL_TIMEOUT = 30          # long-poll 超时（秒）
_SESSION_PREFIX = "tg_"     # Telegram 会话 ID 前缀，与桌面端隔离
_MAX_MSG_LEN = 4000          # Telegram 单条消息最大长度（4096 减留量）
_MAX_HISTORY_TURNS = int(os.environ.get("TELEGRAM_MAX_HISTORY_TURNS", "20"))

# ── 单例 ──────────────────────────────────────────────────────────────────────
_bot_instance: Optional["TelegramBot"] = None
_bot_lock = threading.Lock()


def get_telegram_bot() -> Optional["TelegramBot"]:
    """返回单例 TelegramBot，无 token 时返回 None。"""
    global _bot_instance
    if _bot_instance is not None:
        return _bot_instance
    with _bot_lock:
        if _bot_instance is None:
            token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
            if not token:
                logger.info("[Telegram] 未配置 TELEGRAM_BOT_TOKEN，Bot 不启动")
                return None
            _bot_instance = TelegramBot(token)
    return _bot_instance


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _split_message(text: str, max_len: int = _MAX_MSG_LEN) -> List[str]:
    """将超长文本切割成多段，优先在换行处切割。"""
    if len(text) <= max_len:
        return [text]
    parts: List[str] = []
    while text:
        if len(text) <= max_len:
            parts.append(text)
            break
        cut = text.rfind("\n", 0, max_len)
        if cut <= 0:
            cut = max_len
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return parts


def _allowed_ids() -> Optional[List[int]]:
    """解析白名单 chat_id 列表；None 表示不限制。"""
    raw = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
    if not raw:
        return None
    try:
        return [int(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError:
        logger.warning("[Telegram] TELEGRAM_ALLOWED_CHAT_IDS 格式错误，已忽略白名单")
        return None


# ============================================================================
# TelegramBot
# ============================================================================


class TelegramBot:
    """
    基于长轮询的 Telegram Bot，不依赖 python-telegram-bot 等第三方库。
    所有网络调用均通过 requests 完成。
    """

    def __init__(self, token: str):
        self._token = token
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._offset: int = 0
        self._allowed: Optional[List[int]] = _allowed_ids()
        self._proactive_thread: Optional[threading.Thread] = None

    # ── 生命周期 ──────────────────────────────────────────────────────────────

    def start(self):
        """在后台线程中启动 Bot，幂等。"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, name="TelegramPollLoop", daemon=True
        )
        self._thread.start()
        # 独立线程：每分钟将 ProactiveAgent 队列中的消息推送给指定 chat_id
        self._proactive_thread = threading.Thread(
            target=self._proactive_loop, name="TelegramProactivePush", daemon=True
        )
        self._proactive_thread.start()
        logger.info("[Telegram] ✅ Bot 已启动（后台长轮询）")

    def stop(self):
        """停止 Bot。"""
        self._running = False
        logger.info("[Telegram] Bot 已停止")

    @property
    def is_running(self) -> bool:
        return self._running and (self._thread is not None and self._thread.is_alive())

    def get_bot_info(self) -> Optional[Dict]:
        """调用 getMe 获取 Bot 基础信息。"""
        try:
            resp = self._call("getMe")
            return resp.get("result") if resp.get("ok") else None
        except Exception:
            return None

    # ── 消息发送 ──────────────────────────────────────────────────────────────

    def send_text(self, chat_id: int, text: str, parse_mode: str = "Markdown") -> bool:
        """发送文本消息，自动处理超长分割。"""
        if not text:
            return False
        for part in _split_message(text):
            try:
                resp = self._call("sendMessage", {
                    "chat_id": chat_id,
                    "text": part,
                    "parse_mode": parse_mode,
                })
                if not resp.get("ok"):
                    # Markdown 解析失败时退回纯文本
                    if "can't parse" in str(resp).lower():
                        self._call("sendMessage", {"chat_id": chat_id, "text": part})
            except Exception as exc:
                logger.warning(f"[Telegram] send_text 失败: {exc}")
                return False
        return True

    def send_typing(self, chat_id: int):
        """发送"正在输入…"状态。"""
        try:
            self._call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        except Exception:
            pass

    # ── 主动推送 ──────────────────────────────────────────────────────────────

    def push_proactive_to_telegram(self, chat_id: Optional[int] = None):
        """
        从 ProactiveAgent 队列中取出消息，推送到指定 chat_id。
        chat_id 优先使用参数，其次读 TELEGRAM_MORNING_BRIEF_CHAT_ID。
        """
        target = chat_id or _get_morning_brief_chat_id()
        if not target:
            return
        try:
            from app.core.agent.proactive_agent import ProactiveAgent

            agent = ProactiveAgent.get()
            pending = agent.pending()
            for msg in pending:
                content = msg.get("content", "")
                if content:
                    icon = _type_icon(msg.get("type", ""))
                    self.send_text(target, f"{icon} {content}")
                    agent.dismiss(msg.get("id", ""))
        except Exception as exc:
            logger.debug(f"[Telegram] 主动消息推送跳过: {exc}")

    # ── 轮询循环 ──────────────────────────────────────────────────────────────

    def _poll_loop(self):
        logger.info("[Telegram] 开始长轮询…")
        while self._running:
            try:
                resp = self._call("getUpdates", {
                    "offset": self._offset,
                    "timeout": _POLL_TIMEOUT,
                    "allowed_updates": ["message"],
                })
                if not resp.get("ok"):
                    time.sleep(5)
                    continue
                for update in resp.get("result", []):
                    self._offset = update["update_id"] + 1
                    self._handle_update(update)
            except Exception as exc:
                logger.warning(f"[Telegram] 轮询异常: {exc}")
                time.sleep(10)

    def _proactive_loop(self):
        """每 60s 将主动消息推送到晨间简报目标 chat_id。"""
        while self._running:
            time.sleep(60)
            try:
                self.push_proactive_to_telegram()
            except Exception:
                pass

    # ── 消息路由 ──────────────────────────────────────────────────────────────

    def _handle_update(self, update: Dict):
        message = update.get("message")
        if not message:
            return

        chat_id: int = message["chat"]["id"]
        from_user = message.get("from", {})
        username = from_user.get("username") or from_user.get("first_name", "用户")

        # 白名单鉴权
        if self._allowed and chat_id not in self._allowed:
            self.send_text(chat_id, "⛔ 你没有使用权限，请联系管理员。")
            logger.warning(f"[Telegram] 拒绝未授权 chat_id={chat_id}")
            return

        # 命令处理
        text: str = message.get("text", "") or ""
        if text.startswith("/"):
            self._handle_command(chat_id, text, username)
            return

        # 语音消息
        if "voice" in message:
            self._handle_voice(chat_id, message["voice"])
            return

        # 文件/文档
        if "document" in message:
            caption = message.get("caption", "请分析这个文件。")
            self._handle_document(chat_id, message["document"], caption)
            return

        # 图片
        if "photo" in message:
            caption = message.get("caption", "请描述和分析这张图片。")
            self._handle_photo(chat_id, message["photo"], caption)
            return

        # 普通文字对话
        if text:
            self._handle_chat(chat_id, text, username)

    # ── 命令处理 ──────────────────────────────────────────────────────────────

    def _handle_command(self, chat_id: int, text: str, username: str):
        cmd = text.split()[0].lower().lstrip("/").split("@")[0]
        args = text.split(maxsplit=1)[1] if len(text.split()) > 1 else ""

        handlers = {
            "start": self._cmd_start,
            "help": self._cmd_help,
            "goals": self._cmd_goals,
            "morning": self._cmd_morning,
            "status": self._cmd_status,
            "memory": self._cmd_memory,
            "remind": self._cmd_remind,
            "contacts": self._cmd_contacts,
        }
        handler = handlers.get(cmd)
        if handler:
            try:
                handler(chat_id, args, username)
            except Exception as exc:
                logger.warning(f"[Telegram] 命令 /{cmd} 处理失败: {exc}")
                self.send_text(chat_id, f"❌ 命令执行出错: {exc}")
        else:
            # 未知命令当作普通对话
            self._handle_chat(chat_id, text, username)

    def _cmd_start(self, chat_id: int, _args: str, username: str):
        self.send_text(chat_id, (
            f"👋 你好，{username}！我是 Koto，你的个人 AI 助理。\n\n"
            "你可以直接发消息跟我聊，或者使用以下命令：\n"
            "/goals — 查看当前活跃目标\n"
            "/morning — 获取今日晨间简报\n"
            "/status — 查看系统状态\n"
            "/memory — 查看近期记忆摘要\n"
            "/remind <内容> — 设置一个提醒\n"
            "/contacts — 查看联系人列表\n"
            "/help — 查看帮助"
        ))

    def _cmd_help(self, chat_id: int, _args: str, _username: str):
        self.send_text(chat_id, (
            "🤖 *Koto 帮助*\n\n"
            "直接发送任意消息即可对话，我会调用工具帮你完成任务。\n\n"
            "*命令列表:*\n"
            "/goals — 活跃目标概览\n"
            "/morning — 今日晨间简报\n"
            "/status — 系统状态\n"
            "/memory — 近期记忆摘要\n"
            "/remind <内容> — 创建提醒（如：/remind 明天下午3点开会）\n"
            "/contacts — 联系人列表\n\n"
            "支持发送语音、图片、文档进行分析。"
        ))

    def _cmd_goals(self, chat_id: int, _args: str, _username: str):
        self.send_typing(chat_id)
        try:
            from app.core.goal.goal_manager import GoalStatus, get_goal_manager

            gm = get_goal_manager()
            goals = (
                gm.list_goals(status=GoalStatus.ACTIVE, limit=10)
                + gm.list_goals(status=GoalStatus.WAITING_USER, limit=10)
            )
            if not goals:
                self.send_text(chat_id, "✅ 当前没有活跃的目标。")
                return
            lines = ["📋 *活跃目标*\n"]
            for g in goals[:10]:
                status_icon = {"active": "🟢", "waiting_user": "🟡"}.get(str(g.status), "⚪")
                lines.append(f"{status_icon} *{g.title}*")
                if g.description:
                    lines.append(f"   {g.description[:60]}{'…' if len(g.description)>60 else ''}")
                if g.deadline:
                    lines.append(f"   ⏰ 截止: {g.deadline[:10]}")
                lines.append("")
            self.send_text(chat_id, "\n".join(lines))
        except Exception as exc:
            self.send_text(chat_id, f"❌ 获取目标失败: {exc}")

    def _cmd_morning(self, chat_id: int, _args: str, _username: str):
        self.send_typing(chat_id)
        try:
            from app.core.services.morning_brief import get_morning_brief_service

            brief_text = get_morning_brief_service().generate_brief(as_text=True)
            self.send_text(chat_id, brief_text)
        except Exception as exc:
            self.send_text(chat_id, f"❌ 晨间简报生成失败: {exc}")

    def _cmd_status(self, chat_id: int, _args: str, _username: str):
        self.send_typing(chat_id)
        try:
            import platform
            import psutil

            cpu = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            lines = [
                "🖥️ *系统状态*\n",
                f"CPU: `{cpu}%`",
                f"内存: `{mem.percent}%` ({mem.used // 1024 // 1024}MB / {mem.total // 1024 // 1024}MB)",
                f"磁盘: `{disk.percent}%` ({disk.used // 1024 // 1024 // 1024}GB / {disk.total // 1024 // 1024 // 1024}GB)",
                f"系统: `{platform.system()} {platform.version()[:30]}`",
            ]
            self.send_text(chat_id, "\n".join(lines))
        except ImportError:
            self.send_text(chat_id, "⚠️ psutil 未安装，无法获取系统状态。")
        except Exception as exc:
            self.send_text(chat_id, f"❌ 获取状态失败: {exc}")

    def _cmd_memory(self, chat_id: int, _args: str, _username: str):
        self.send_typing(chat_id)
        try:
            from pathlib import Path as _Path

            mem_path = _Path(__file__).parent.parent / "config" / "memory.json"
            if not mem_path.exists():
                self.send_text(chat_id, "📭 记忆库为空。")
                return
            with open(mem_path, "r", encoding="utf-8") as f:
                memories = json.load(f)
            if not memories:
                self.send_text(chat_id, "📭 记忆库为空。")
                return
            # 取最近 8 条
            recent = memories[-8:] if isinstance(memories, list) else list(memories.values())[-8:]
            lines = ["🧠 *近期记忆*\n"]
            for m in recent:
                if isinstance(m, dict):
                    content = m.get("content") or m.get("text") or str(m)
                    ts = m.get("created_at", "")[:10]
                    lines.append(f"• {content[:80]}{'…' if len(content)>80 else ''}")
                    if ts:
                        lines.append(f"  _({ts})_")
                else:
                    lines.append(f"• {str(m)[:80]}")
            self.send_text(chat_id, "\n".join(lines))
        except Exception as exc:
            self.send_text(chat_id, f"❌ 记忆获取失败: {exc}")

    def _cmd_remind(self, chat_id: int, args: str, _username: str):
        if not args:
            self.send_text(chat_id, "📌 用法: `/remind 明天下午3点开会`")
            return
        # 将提醒请求当作对话处理，Agent 会调用 reminder 工具
        self._handle_chat(chat_id, f"帮我设置一个提醒：{args}", "用户")

    def _cmd_contacts(self, chat_id: int, _args: str, _username: str):
        self.send_typing(chat_id)
        try:
            from app.core.memory.contact_manager import get_contact_manager

            cm = get_contact_manager()
            contacts = cm.list_contacts(limit=10)
            if not contacts:
                self.send_text(chat_id, "👥 联系人记录为空。")
                return
            lines = ["👥 *近期联系人*\n"]
            for c in contacts:
                lines.append(f"👤 *{c['name']}*")
                if c.get("last_interaction"):
                    lines.append(f"   最近互动: {c['last_interaction'][:10]}")
                if c.get("notes"):
                    lines.append(f"   备注: {c['notes'][:60]}")
                lines.append("")
            self.send_text(chat_id, "\n".join(lines))
        except Exception as exc:
            self.send_text(chat_id, f"❌ 获取联系人失败: {exc}")

    # ── 对话处理 ──────────────────────────────────────────────────────────────

    def _handle_chat(self, chat_id: int, text: str, username: str):
        """将用户消息转发给 UnifiedAgent，返回回复。"""
        self.send_typing(chat_id)
        session_id = f"{_SESSION_PREFIX}{chat_id}"
        try:
            from app.api.agent_routes import _load_history, _run_agent_collect, _save_history, get_agent

            history = _load_history(session_id, max_turns=_MAX_HISTORY_TURNS)
            agent = get_agent()
            result = _run_agent_collect(
                agent,
                message=text,
                history=history,
                session_id=session_id,
                task_type="CHAT",
            )
            answer = result.get("answer", "") if isinstance(result, dict) else str(result)
            if not answer:
                answer = "（抱歉，没有得到回复，请再试一次。）"
            _save_history(session_id, text, answer)
            self.send_text(chat_id, answer)
        except Exception as exc:
            logger.warning(f"[Telegram] Agent 调用失败 chat_id={chat_id}: {exc}")
            self.send_text(chat_id, f"❌ 出错了：{exc}")

    def _handle_voice(self, chat_id: int, voice: Dict):
        """下载语音，用 STT 转文字后当作普通对话处理。"""
        self.send_typing(chat_id)
        try:
            file_id = voice["file_id"]
            ogg_bytes = self._download_file(file_id)
            if not ogg_bytes:
                self.send_text(chat_id, "❌ 语音下载失败。")
                return
            # 转换为 WAV 并调用 STT
            text = self._stt_from_bytes(ogg_bytes, mime="audio/ogg")
            if not text:
                self.send_text(chat_id, "⚠️ 语音识别失败，请重新发送或改用文字。")
                return
            # 确认识别内容后转 Agent
            self.send_text(chat_id, f"🎤 识别到：_{text}_")
            self._handle_chat(chat_id, text, "用户")
        except Exception as exc:
            logger.warning(f"[Telegram] 语音处理失败: {exc}")
            self.send_text(chat_id, f"❌ 语音处理失败: {exc}")

    def _handle_document(self, chat_id: int, doc: Dict, caption: str):
        """下载文档到临时文件，通过 Agent 分析。"""
        self.send_typing(chat_id)
        try:
            file_id = doc["file_id"]
            filename = doc.get("file_name", "uploaded_file")
            file_bytes = self._download_file(file_id)
            if not file_bytes:
                self.send_text(chat_id, "❌ 文件下载失败。")
                return
            # 保存到 workspace/uploads/
            save_dir = Path(__file__).parent.parent / "workspace" / "tg_uploads"
            save_dir.mkdir(parents=True, exist_ok=True)
            save_path = save_dir / filename
            save_path.write_bytes(file_bytes)
            query = f"{caption}\n文件路径: {save_path}"
            self._handle_chat(chat_id, query, "用户")
        except Exception as exc:
            logger.warning(f"[Telegram] 文件处理失败: {exc}")
            self.send_text(chat_id, f"❌ 文件处理失败: {exc}")

    def _handle_photo(self, chat_id: int, photos: List[Dict], caption: str):
        """下载最高分辨率图片，通过 Agent 分析。"""
        self.send_typing(chat_id)
        try:
            # Telegram 返回多分辨率，取最后一张（最大）
            photo = photos[-1]
            file_id = photo["file_id"]
            file_bytes = self._download_file(file_id)
            if not file_bytes:
                self.send_text(chat_id, "❌ 图片下载失败。")
                return
            save_dir = Path(__file__).parent.parent / "workspace" / "tg_uploads"
            save_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = save_dir / f"photo_{ts}.jpg"
            save_path.write_bytes(file_bytes)
            query = f"{caption}\n图片路径: {save_path}"
            self._handle_chat(chat_id, query, "用户")
        except Exception as exc:
            logger.warning(f"[Telegram] 图片处理失败: {exc}")
            self.send_text(chat_id, f"❌ 图片处理失败: {exc}")

    # ── 工具方法 ──────────────────────────────────────────────────────────────

    def _call(self, method: str, data: Optional[Dict] = None, timeout: int = 35) -> Dict:
        """调用 Telegram Bot API，返回 JSON 响应。"""
        import requests  # 已在 requirements.txt

        url = _TG_API_BASE.format(token=self._token, method=method)
        resp = requests.post(url, json=data or {}, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def _download_file(self, file_id: str) -> Optional[bytes]:
        """通过 Telegram Bot API 下载文件，返回字节内容。"""
        import requests

        try:
            info = self._call("getFile", {"file_id": file_id})
            if not info.get("ok"):
                return None
            file_path = info["result"]["file_path"]
            url = f"https://api.telegram.org/file/bot{self._token}/{file_path}"
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            return resp.content
        except Exception as exc:
            logger.warning(f"[Telegram] 文件下载失败 file_id={file_id}: {exc}")
            return None

    def _stt_from_bytes(self, audio_bytes: bytes, mime: str = "audio/ogg") -> Optional[str]:
        """使用已有 STT 模块将音频字节转文字。"""
        try:
            import tempfile

            import ffmpeg  # type: ignore

            # OGG → WAV
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_ogg:
                tmp_ogg.write(audio_bytes)
                ogg_path = tmp_ogg.name
            wav_path = ogg_path.replace(".ogg", ".wav")
            (
                ffmpeg.input(ogg_path)
                .output(wav_path, ar=16000, ac=1)
                .overwrite_output()
                .run(quiet=True)
            )
            from web.voice_engine import transcribe_file

            return transcribe_file(wav_path)
        except ImportError:
            # ffmpeg-python 未安装，尝试 Google STT via LLM
            pass
        except Exception as exc:
            logger.debug(f"[Telegram] STT 转换失败（ffmpeg 路径）: {exc}")

        # 兜底：提示用户文字输入
        return None


# ── 辅助 ──────────────────────────────────────────────────────────────────────

def _get_morning_brief_chat_id() -> Optional[int]:
    raw = os.environ.get("TELEGRAM_MORNING_BRIEF_CHAT_ID", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return None


def _type_icon(msg_type: str) -> str:
    return {
        "greeting": "👋",
        "follow_up": "🔔",
        "suggestion": "💡",
        "reminder": "⏰",
        "insight": "🔍",
        "session_summary": "📝",
        "context_carry": "🔗",
        "correction_hint": "✏️",
    }.get(msg_type, "📌")
