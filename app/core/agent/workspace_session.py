# ══════════════════════════════════════════════════════════════
# workspace_session.py — Per-Session Memory for WorkspaceTaskAgent
#
# Maintains lightweight context across task invocations within
# the same session.  Enables cross-task reference resolution
# ("刚才那个文件" / "上次生成的报告") without full conversation
# history storage.
#
# Thread-safe LRU cache; auto-evicts idle sessions after TTL.
# ══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

_MAX_SESSIONS = 128
_MAX_TASK_HISTORY = 8
_MAX_FILE_HISTORY = 20
_SESSION_TTL_SECONDS = 3600 * 4  # 4 hours idle → evict


# ── Data models ────────────────────────────────────────────────────────────


@dataclass
class TaskRecord:
    """Summary of one completed workspace task."""

    task: str
    summary: str
    files_operated: List[str]  # workspace-relative or absolute paths
    timestamp: float = field(default_factory=time.time)

    def to_context_str(self) -> str:
        parts = [f"- 任务: {self.task[:120]}"]
        if self.summary:
            parts.append(f"  结果: {self.summary[:200]}")
        if self.files_operated:
            files_str = "、".join(self.files_operated[:5])
            parts.append(f"  涉及文件: {files_str}")
        return "\n".join(parts)


@dataclass
class WorkspaceSession:
    """In-memory state for one browser/user session."""

    session_id: str
    task_history: List[TaskRecord] = field(default_factory=list)
    recent_files: List[str] = field(default_factory=list)
    last_used: float = field(default_factory=time.time)

    def add_task(
        self,
        task: str,
        summary: str,
        files_operated: List[str],
    ) -> None:
        record = TaskRecord(
            task=task,
            summary=summary,
            files_operated=[f for f in files_operated if f],
        )
        self.task_history.append(record)
        if len(self.task_history) > _MAX_TASK_HISTORY:
            self.task_history = self.task_history[-_MAX_TASK_HISTORY:]

        # Deduplicated recent-files list (newest first)
        for f in reversed(files_operated):
            if not f:
                continue
            if f in self.recent_files:
                self.recent_files.remove(f)
            self.recent_files.insert(0, f)
        if len(self.recent_files) > _MAX_FILE_HISTORY:
            self.recent_files = self.recent_files[:_MAX_FILE_HISTORY]

        self.last_used = time.time()

    def build_context_prompt(self) -> str:
        """Return a brief context block for injection into the system prompt."""
        if not self.task_history and not self.recent_files:
            return ""

        parts: List[str] = []

        if self.task_history:
            parts.append("## 本次会话已完成的任务")
            for record in self.task_history[-5:]:  # last 5 only
                parts.append(record.to_context_str())

        if self.recent_files:
            parts.append("\n## 最近操作过的文件")
            for f in self.recent_files[:10]:
                parts.append(f"- {f}")

        return "\n".join(parts)

    def is_expired(self) -> bool:
        return (time.time() - self.last_used) > _SESSION_TTL_SECONDS


# ── Singleton memory store ─────────────────────────────────────────────────


class WorkspaceSessionMemory:
    """
    Thread-safe LRU cache of WorkspaceSession objects.

    Usage:
        mem = WorkspaceSessionMemory.get_instance()
        ctx_text = mem.build_context_prompt(session_id)
        # ... run task ...
        mem.update_session(session_id, task, summary, files)
    """

    _instance: Optional["WorkspaceSessionMemory"] = None
    _instance_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._sessions: OrderedDict[str, WorkspaceSession] = OrderedDict()
        self._lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "WorkspaceSessionMemory":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _get_or_create(self, session_id: str) -> WorkspaceSession:
        """Return existing session or create a new one (LRU eviction if full)."""
        with self._lock:
            if session_id in self._sessions:
                self._sessions.move_to_end(session_id)
                session = self._sessions[session_id]
                session.last_used = time.time()
                return session

            # Evict oldest expired session first, then by LRU order
            to_evict = [sid for sid, s in self._sessions.items() if s.is_expired()]
            for sid in to_evict:
                del self._sessions[sid]
                logger.debug(
                    "[WorkspaceSessionMemory] evicted expired session: %s", sid
                )

            while len(self._sessions) >= _MAX_SESSIONS:
                evicted_id, _ = self._sessions.popitem(last=False)
                logger.debug("[WorkspaceSessionMemory] evicted (LRU): %s", evicted_id)

            session = WorkspaceSession(session_id=session_id)
            self._sessions[session_id] = session
            return session

    def get_session(self, session_id: str) -> WorkspaceSession:
        return self._get_or_create(session_id)

    def build_context_prompt(self, session_id: str) -> str:
        """Return session context text for system prompt injection."""
        if not session_id:
            return ""
        try:
            session = self._get_or_create(session_id)
            return session.build_context_prompt()
        except Exception as exc:
            logger.debug("[WorkspaceSessionMemory] build_context_prompt error: %s", exc)
            return ""

    def update_session(
        self,
        session_id: str,
        task: str,
        summary: str,
        files_operated: List[str],
    ) -> None:
        """Record the result of a completed task into session memory."""
        if not session_id:
            return
        try:
            session = self._get_or_create(session_id)
            session.add_task(
                task=task[:200],
                summary=summary[:300],
                files_operated=files_operated[:10],
            )
            logger.debug(
                "[WorkspaceSessionMemory] updated session %s: %d task(s) recorded",
                session_id,
                len(session.task_history),
            )
        except Exception as exc:
            logger.debug("[WorkspaceSessionMemory] update_session error: %s", exc)
