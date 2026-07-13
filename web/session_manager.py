#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Chat session file storage helpers."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import datetime

logger = logging.getLogger(__name__)


_chat_dir_provider: Callable[[], str] | None = None
_default_session_manager: "SessionManager | None" = None


def configure_session_storage(chat_dir_provider: Callable[[], str]) -> None:
    """Bind session storage to the application-owned chat directory."""
    global _chat_dir_provider
    _chat_dir_provider = chat_dir_provider


def _chat_dir() -> str:
    if _chat_dir_provider is None:
        raise RuntimeError("Session storage is not configured")
    return str(_chat_dir_provider() or "")


# Per-session file lock to prevent concurrent read-modify-write cycles
_session_locks: dict[str, threading.Lock] = {}
_session_locks_lock = threading.Lock()


def _get_session_lock(filename: str) -> threading.Lock:
    """Get or create a per-file lock for thread-safe session I/O."""
    with _session_locks_lock:
        if filename not in _session_locks:
            _session_locks[filename] = threading.Lock()
        return _session_locks[filename]


class SessionManager:
    def __init__(self) -> None:
        self.sessions = {}

    def list_sessions(self) -> list[str]:
        """列出所有会话，按修改时间排序（最新在前）"""
        files = [f for f in os.listdir(_chat_dir()) if f.endswith(".json")]
        # 按修改时间排序，最新的在前
        files_with_time = []
        for f in files:
            path = os.path.join(_chat_dir(), f)
            mtime = os.path.getmtime(path)
            files_with_time.append((f, mtime))
        files_with_time.sort(key=lambda x: x[1], reverse=True)
        return [f[0] for f in files_with_time]

    def load(self, filename: str) -> list[dict]:
        """加载会话历史 - 返回用于模型上下文的截断版本"""
        path = os.path.join(_chat_dir(), filename)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    full_history = json.load(f)
                    # 仅截断用于模型上下文的部分，不影响持久化存储
                    return self._trim_history(full_history)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load session %s: %s", filename, e)
                return []
        return []

    def load_full(self, filename: str) -> list[dict]:
        """加载完整会话历史 - 用于追加保存，不做截断"""
        path = os.path.join(_chat_dir(), filename)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load full session %s: %s", filename, e)
                return []
        return []

    def _trim_history(self, history: list[dict], max_turns: int = 20) -> list[dict]:
        """保留最多 20 轮对话（约 12000+ tokens），确保上下文足够但不过长"""
        model_history = [
            turn
            for turn in history
            if not (
                isinstance(turn, dict)
                and (
                    turn.get("skip_model_context") is True
                    or str(turn.get("skip_model_context") or "").strip().lower() in {"1", "true", "yes"}
                    or turn.get("partial") is True
                    or str(turn.get("partial") or "").strip().lower() in {"1", "true", "yes"}
                )
            )
        ]
        if len(model_history) <= max_turns:
            return model_history
        # 只保留最后 N 轮对话
        trimmed = model_history[-max_turns:]
        logger.debug(
            f"[HISTORY] Trimmed to last {max_turns} turns (was {len(model_history)})"
        )
        return trimmed

    def create(self, name: str) -> str:
        safe = "".join([c if c.isalnum() else "_" for c in name])
        filename = f"{safe}.json"
        path = os.path.join(_chat_dir(), filename)
        # 若同名文件已存在，加时间戳后缀避免覆盖已有会话
        if os.path.exists(path):
            filename = f"{safe}_{int(time.time())}.json"
            path = os.path.join(_chat_dir(), filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f)
        return filename

    def save(self, filename: str, history: list[dict]) -> None:
        path = os.path.join(_chat_dir(), filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=os.path.dirname(path),
                delete=False,
                suffix=".tmp",
            ) as f:
                tmp_path = f.name
                json.dump(history, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def append_and_save(self, filename: str, user_msg: str, model_msg: str, **extra_fields: object) -> list[dict]:
        """追加消息并保存 - 基于磁盘完整历史，避免截断导致数据丢失"""
        lock = _get_session_lock(filename)
        with lock:
            full_history = self.load_full(filename)
            user_timestamp = extra_fields.pop("user_timestamp", datetime.now().isoformat())
            model_timestamp = extra_fields.pop(
                "model_timestamp", datetime.now().isoformat()
            )

            full_history.append(
                {"role": "user", "parts": [user_msg], "timestamp": user_timestamp}
            )
            model_entry = {"role": "model", "parts": [model_msg]}
            if "timestamp" not in extra_fields:
                model_entry["timestamp"] = model_timestamp
            model_entry.update(extra_fields)
            full_history.append(model_entry)
            self.save(filename, full_history)
            return full_history

    def append_user_early(self, filename: str, user_msg: str) -> int:
        """在请求到达时立即保存用户消息，防止断连导致丢失
        返回history长度，后续用update_last_model_response更新模型回复"""
        lock = _get_session_lock(filename)
        with lock:
            full_history = self.load_full(filename)
            now_iso = datetime.now().isoformat()
            full_history.append({"role": "user", "parts": [user_msg], "timestamp": now_iso})
            full_history.append(
                {"role": "model", "parts": ["⏳ 处理中..."], "timestamp": now_iso}
            )
            self.save(filename, full_history)
            return len(full_history)

    def update_last_model_response(self, filename: str, model_msg: str, **extra_fields: object) -> None:
        """更新最后一条模型回复（配合append_user_early使用）"""
        lock = _get_session_lock(filename)
        with lock:
            full_history = self.load_full(filename)
            if full_history and full_history[-1].get("role") == "model":
                model_entry = {"role": "model", "parts": [model_msg]}
                if "timestamp" not in extra_fields:
                    model_entry["timestamp"] = datetime.now().isoformat()
                model_entry.update(extra_fields)
                full_history[-1] = model_entry
                self.save(filename, full_history)
            else:
                # fallback: 直接追加
                model_entry = {"role": "model", "parts": [model_msg]}
                if "timestamp" not in extra_fields:
                    model_entry["timestamp"] = datetime.now().isoformat()
                model_entry.update(extra_fields)
                full_history.append(model_entry)
                self.save(filename, full_history)

    def add_message(
        self, filename, role, content, task="CHAT", model_name="Auto", **extra_fields
    ):
        """追加单条消息（兼容旧调用），默认附带时间戳"""
        lock = _get_session_lock(filename)
        with lock:
            full_history = self.load_full(filename)
            entry = {
                "role": role,
                "parts": [content],
                "task": task,
                "model_name": model_name,
                "timestamp": extra_fields.pop("timestamp", datetime.now().isoformat()),
            }
            entry.update(extra_fields)
            full_history.append(entry)
            self.save(filename, full_history)
            return entry

    def delete(self, filename: str) -> bool:
        path = os.path.join(_chat_dir(), filename)
        if os.path.exists(path):
            try:
                os.remove(path)
                return True
            except OSError as e:
                logger.warning("Failed to delete session %s: %s", filename, e)
                return False
        return False

    def rename(self, filename: str, new_name: str) -> dict[str, object]:
        """将会话文件重命名。new_name 为用户输入的显示名称（非文件名）。"""
        old_path = os.path.join(_chat_dir(), filename)
        if not os.path.exists(old_path):
            return {"success": False, "error": "会话不存在"}
        safe = "".join(
            [c if c.isalnum() or c in "_- " else "_" for c in new_name]
        ).strip()
        if not safe:
            return {"success": False, "error": "名称无效"}
        new_filename = f"{safe}.json"
        new_path = os.path.join(_chat_dir(), new_filename)
        if os.path.exists(new_path) and os.path.abspath(new_path) != os.path.abspath(
            old_path
        ):
            new_filename = f"{safe}_{int(time.time())}.json"
            new_path = os.path.join(_chat_dir(), new_filename)
        try:
            os.rename(old_path, new_path)
            return {"success": True, "new_filename": new_filename}
        except OSError as e:
            logger.warning(
                "Failed to rename session %s -> %s: %s", filename, new_filename, e
            )
            return {"success": False, "error": str(e)}


def get_session_manager() -> SessionManager:
    """Return the single application session manager."""
    global _default_session_manager
    if _default_session_manager is None:
        _default_session_manager = SessionManager()
    return _default_session_manager
