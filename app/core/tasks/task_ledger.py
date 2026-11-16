# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Koto Task Ledger
================
持久化任务台账，基于与 CheckpointManager 共用的 SQLite 数据库。

功能：
  - 每次 Agent 执行自动创建 TaskRecord
  - 记录任务全生命周期（步骤、工具调用、耗时、结果摘要）
  - 跨会话查询："列出今天的任务"、"任务 X 执行到哪了"
  - 支持外部注入取消请求（interrupt_task / cancel_task）
  - 与 ProgressBus 联动，状态变更自动广播

表结构（只读兼容，不侵入现有 checkpoints* 表）：
  koto_tasks        — 任务主表
  koto_task_steps   — 步骤明细表
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config.runtime_storage import (
    legacy_config_path,
    prepare_runtime_database,
    runtime_database_path,
)
from app.core.tasks.task_journal import JOURNAL_DDL, TaskJournalMixin

logger = logging.getLogger(__name__)

# ── 默认路径（与 CheckpointManager 同库文件）────────────────────────────────
_DEFAULT_DB_PATH = str(runtime_database_path("koto_checkpoints.sqlite"))


def _resolve_db_path(db_path: Optional[str] = None) -> str:
    if db_path:
        return db_path
    return str(
        prepare_runtime_database(
            _DEFAULT_DB_PATH,
            legacy_paths=(legacy_config_path("koto_checkpoints.sqlite"),),
        )
    )


# ── 单例 ─────────────────────────────────────────────────────────────────────
_ledger_instance: Optional["TaskLedger"] = None
_ledger_lock = threading.Lock()


# ============================================================================
# 枚举 & 数据类
# ============================================================================


class TaskStatus(str, Enum):
    PENDING = "pending"  # 已创建，未开始
    RUNNING = "running"  # 执行中
    WAITING = "waiting"  # 等待人工确认（Human-in-loop）
    COMPLETED = "completed"  # 成功完成
    FAILED = "failed"  # 执行失败
    CANCELLED = "cancelled"  # 被取消
    RETRYING = "retrying"  # 重试中


class TaskPriority(int, Enum):
    """任务优先级（数值越大越优先）。"""

    LOW = 0  # 低优先级（后台任务）
    NORMAL = 1  # 默认
    HIGH = 2  # 高优先级（用户主动触发）
    URGENT = 3  # 紧急（立即执行）


@dataclass
class TaskRecord:
    """任务台账条目（对应 koto_tasks 表的一行）"""

    task_id: str
    session_id: str
    user_input: str
    status: TaskStatus = TaskStatus.PENDING

    # 分类/来源
    task_type: Optional[str] = None  # "agent"/"ppt"/"code"/"scheduler"…
    source: str = "agent"  # 发起来源

    # 时间戳
    created_at: str = field(default_factory=lambda: _now_iso())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    # 执行情况
    step_count: int = 0
    tool_calls: int = 0  # 累计工具调用次数
    retry_count: int = 0
    error: Optional[str] = None
    result_summary: Optional[str] = None  # 最终答案的前 500 字

    # 优先级
    priority: int = 1  # TaskPriority 整数值（0=低/1=正常/2=高/3=紧急）

    # 控制标志
    interrupt_requested: bool = False  # 外部要求暂停（Human-in-loop）
    cancel_requested: bool = False  # 外部要求取消

    # 额外元数据（JSON 字符串存储）
    metadata: str = "{}"

    # ── 非持久化字段 ─────────────────────────────────────────────────────
    steps: List["StepRecord"] = field(default_factory=list, compare=False, repr=False)

    @property
    def elapsed_seconds(self) -> Optional[float]:
        if not self.started_at:
            return None
        end = self.completed_at or _now_iso()
        try:
            fmt = "%Y-%m-%dT%H:%M:%S.%f"
            s = datetime.strptime(self.started_at[:26], fmt)
            e = datetime.strptime(end[:26], fmt)
            return (e - s).total_seconds()
        except Exception:
            return None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["elapsed_seconds"] = self.elapsed_seconds
        d.pop("steps", None)
        return d


@dataclass
class StepRecord:
    """单步骤记录（对应 koto_task_steps 表的一行）"""

    step_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    task_id: str = ""
    step_index: int = 0
    step_type: str = ""  # THOUGHT / ACTION / OBSERVATION / ANSWER / ERROR
    content: str = ""
    tool_name: Optional[str] = None
    tool_args: Optional[str] = None  # JSON str
    observation: Optional[str] = None
    created_at: str = field(default_factory=lambda: _now_iso())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# 工具函数
# ============================================================================


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


# ============================================================================
# TaskLedger
# ============================================================================


class TaskLedger(TaskJournalMixin):
    """
    持久化任务台账。

    使用示例::

        ledger = get_ledger()

        # 创建一条新任务
        task = ledger.create(
            session_id="sess-abc",
            user_input="帮我写一份周报",
            task_type="agent",
        )

        # 更新状态
        ledger.mark_running(task.task_id)

        # 追加步骤
        ledger.add_step(task.task_id, step_type="THOUGHT", content="…")

        # 完成
        ledger.mark_completed(task.task_id, result_summary="已完成周报")

        # 查询
        tasks = ledger.list_tasks(session_id="sess-abc", limit=20)

        # 取消
        ledger.cancel_task(task.task_id)
    """

    # ── Schema ───────────────────────────────────────────────────────────────
    _DDL = """
    CREATE TABLE IF NOT EXISTS koto_tasks (
        task_id           TEXT PRIMARY KEY,
        session_id        TEXT NOT NULL,
        user_input        TEXT NOT NULL,
        status            TEXT NOT NULL DEFAULT 'pending',
        task_type         TEXT,
        source            TEXT NOT NULL DEFAULT 'agent',
        created_at        TEXT NOT NULL,
        started_at        TEXT,
        completed_at      TEXT,
        step_count        INTEGER NOT NULL DEFAULT 0,
        tool_calls        INTEGER NOT NULL DEFAULT 0,
        retry_count       INTEGER NOT NULL DEFAULT 0,
        error             TEXT,
        result_summary    TEXT,
        interrupt_requested INTEGER NOT NULL DEFAULT 0,
        cancel_requested    INTEGER NOT NULL DEFAULT 0,
        priority          INTEGER NOT NULL DEFAULT 1,
        metadata          TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_koto_tasks_session  ON koto_tasks(session_id);
    CREATE INDEX IF NOT EXISTS idx_koto_tasks_status   ON koto_tasks(status);
    CREATE INDEX IF NOT EXISTS idx_koto_tasks_created  ON koto_tasks(created_at);

    CREATE TABLE IF NOT EXISTS koto_task_steps (
        step_id     TEXT PRIMARY KEY,
        task_id     TEXT NOT NULL REFERENCES koto_tasks(task_id),
        step_index  INTEGER NOT NULL,
        step_type   TEXT NOT NULL,
        content     TEXT NOT NULL,
        tool_name   TEXT,
        tool_args   TEXT,
        observation TEXT,
        created_at  TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_koto_steps_task  ON koto_task_steps(task_id);

    CREATE TABLE IF NOT EXISTS koto_task_controls (
        control_id        TEXT PRIMARY KEY,
        cancel_requested  INTEGER NOT NULL DEFAULT 0,
        terminal_status   TEXT,
        updated_at        TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS koto_task_plans (
        run_id       TEXT PRIMARY KEY,
        payload      TEXT NOT NULL,
        status       TEXT NOT NULL DEFAULT 'in_progress',
        created_at   TEXT NOT NULL,
        updated_at   TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_koto_task_plans_status
      ON koto_task_plans(status);
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = _resolve_db_path(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()  # serialise concurrent SQLite access
        self._conn = self._open_conn()
        self._init_schema()
        logger.info(f"[TaskLedger] ✅ 初始化完成 → {self._db_path}")

    # ── 底层 DB ──────────────────────────────────────────────────────────────

    def _open_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_schema(self):
        self._conn.executescript(self._DDL)
        self._conn.executescript(JOURNAL_DDL)
        # 迁移旧表：追加可能不存在的列和索引
        _migrations = [
            "ALTER TABLE koto_tasks ADD COLUMN priority INTEGER NOT NULL DEFAULT 1",
            "CREATE INDEX IF NOT EXISTS idx_koto_tasks_priority ON koto_tasks(priority)",
            "ALTER TABLE koto_kernel_checkpoints ADD COLUMN owner_pid INTEGER",
            "ALTER TABLE koto_kernel_checkpoints ADD COLUMN owner_started REAL",
        ]
        for sql in _migrations:
            try:
                self._conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # 列已存在，忽略
        self._conn.commit()

    # ── 任务 CRUD ─────────────────────────────────────────────────────────────

    def create(
        self,
        session_id: str,
        user_input: str,
        task_type: Optional[str] = None,
        source: str = "agent",
        metadata: Optional[Dict[str, Any]] = None,
        priority: int = TaskPriority.NORMAL,
        task_id: Optional[str] = None,
    ) -> TaskRecord:
        """创建新任务记录，返回 TaskRecord 对象。

        ``task_id`` is normally generated by the ledger.  Streamed file tasks
        may provide a client-generated id so their progress stream can be
        resumed even before the first lifecycle event reaches the browser.
        """
        task = TaskRecord(
            task_id=str(task_id or uuid.uuid4()),
            session_id=session_id,
            user_input=user_input[:1000],  # 限制长度
            task_type=task_type,
            source=source,
            priority=int(priority),
            metadata=json.dumps(metadata or {}, ensure_ascii=False),
        )
        payload = {
            "task_id": task.task_id,
            "session_id": task.session_id,
            "user_input": task.user_input,
            "status": task.status.value,
            "task_type": task.task_type,
            "source": task.source,
            "created_at": task.created_at,
            "priority": task.priority,
            "metadata": task.metadata,
        }
        for attempt in range(5):
            try:
                with self._lock:
                    self._conn.execute(
                        """
                        INSERT INTO koto_tasks
                          (task_id, session_id, user_input, status, task_type,
                           source, created_at, step_count, tool_calls, retry_count,
                           interrupt_requested, cancel_requested, priority, metadata)
                        VALUES
                          (:task_id, :session_id, :user_input, :status, :task_type,
                           :source, :created_at, 0, 0, 0, 0, 0, :priority, :metadata)
                        """,
                        payload,
                    )
                    self._conn.commit()
                break
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == 4:
                    raise
                try:
                    with self._lock:
                        self._conn.rollback()
                except Exception:
                    pass
                time.sleep(0.1 * (attempt + 1))
        logger.debug(
            f"[TaskLedger] 创建任务 {task.task_id[:8]} session={session_id[:8]}"
        )
        return task

    def get(self, task_id: str, include_steps: bool = False) -> Optional[TaskRecord]:
        """按 task_id 查询。include_steps=True 时同时加载步骤列表。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM koto_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if not row:
                return None
            rec = self._row_to_record(row)
            if include_steps:
                rec.steps = self._get_steps(task_id)
        return rec

    def _row_to_record(self, row: sqlite3.Row) -> TaskRecord:
        d = dict(row)
        d["status"] = TaskStatus(d["status"])
        d["interrupt_requested"] = bool(d["interrupt_requested"])
        d["cancel_requested"] = bool(d["cancel_requested"])
        d.pop("steps", None)
        return TaskRecord(
            **{k: v for k, v in d.items() if k in TaskRecord.__dataclass_fields__}
        )

    def list_tasks(
        self,
        session_id: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        source: Optional[str] = None,
        date_from: Optional[str] = None,  # ISO 日期前缀，如 "2026-03-04"
        priority: Optional[int] = None,
        order_by: str = "created_at",  # "created_at" | "priority"
        limit: int = 50,
        offset: int = 0,
    ) -> List[TaskRecord]:
        """多条件查询任务列表。order_by='priority' 时按优先级降序+创建时间排序。"""
        clauses, params = [], []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if status:
            clauses.append("status = ?")
            params.append(status.value if hasattr(status, "value") else status)
        if source:
            clauses.append("source = ?")
            params.append(source)
        if date_from:
            clauses.append("created_at >= ?")
            params.append(date_from)
        if priority is not None:
            clauses.append("priority = ?")
            params.append(int(priority))

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        order = (
            "priority DESC, created_at ASC"
            if order_by == "priority"
            else "created_at DESC"
        )
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM koto_tasks {where} ORDER BY {order} LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def count(
        self,
        session_id: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        source: Optional[str] = None,
        date_from: Optional[str] = None,
    ) -> int:
        clauses, params = [], []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if status:
            clauses.append("status = ?")
            params.append(status.value if hasattr(status, "value") else status)
        if source:
            clauses.append("source = ?")
            params.append(source)
        if date_from:
            clauses.append("created_at >= ?")
            params.append(date_from)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock:
            row = self._conn.execute(
                f"SELECT COUNT(*) FROM koto_tasks {where}", params
            ).fetchone()
        return row[0] if row else 0

    # ── 状态变更 ──────────────────────────────────────────────────────────────

    def _update_fields(self, task_id: str, **kwargs):
        if not kwargs:
            return
        with self._lock:
            sets = ", ".join(f"{k} = ?" for k in kwargs)
            vals = list(kwargs.values()) + [task_id]
            self._conn.execute(f"UPDATE koto_tasks SET {sets} WHERE task_id = ?", vals)
            self._conn.commit()

    def _update_nonterminal_fields(self, task_id: str, **kwargs: Any) -> bool:
        if not kwargs:
            return False
        with self._lock:
            sets = ", ".join(f"{key} = ?" for key in kwargs)
            values = list(kwargs.values()) + [task_id]
            cursor = self._conn.execute(
                f"""UPDATE koto_tasks SET {sets}
                    WHERE task_id = ?
                      AND status NOT IN ('completed', 'failed', 'cancelled')""",
                values,
            )
            self._conn.commit()
        return bool(cursor.rowcount)

    def mark_running(self, task_id: str):
        changed = self._update_nonterminal_fields(
            task_id,
            status=TaskStatus.RUNNING.value,
            started_at=_now_iso(),
        )
        if changed:
            self._notify_status_change(task_id, TaskStatus.RUNNING)
        return changed

    def _transition_terminal(self, task_id: str, **fields: Any) -> bool:
        """Apply the first terminal transition and reject later rewrites."""
        with self._lock:
            sets = ", ".join(f"{key} = ?" for key in fields)
            values = list(fields.values()) + [task_id]
            cursor = self._conn.execute(
                f"""UPDATE koto_tasks SET {sets}
                    WHERE task_id = ?
                      AND status NOT IN ('completed', 'failed', 'cancelled')""",
                values,
            )
            self._conn.commit()
        return bool(cursor.rowcount)

    def mark_completed(self, task_id: str, result_summary: Optional[str] = None):
        changed = self._transition_terminal(
            task_id=task_id,
            status=TaskStatus.COMPLETED.value,
            completed_at=_now_iso(),
            result_summary=(result_summary or "")[:500],
        )
        if changed:
            self.mark_control_terminal(task_id, TaskStatus.COMPLETED.value)
            self._notify_status_change(task_id, TaskStatus.COMPLETED)
        return changed

    def mark_failed(self, task_id: str, error: str):
        changed = self._transition_terminal(
            task_id=task_id,
            status=TaskStatus.FAILED.value,
            completed_at=_now_iso(),
            error=str(error)[:1000],
        )
        if changed:
            self.mark_control_terminal(task_id, TaskStatus.FAILED.value)
            self._notify_status_change(task_id, TaskStatus.FAILED)
        return changed

    def mark_cancelled(self, task_id: str):
        changed = self._transition_terminal(
            task_id=task_id,
            status=TaskStatus.CANCELLED.value,
            completed_at=_now_iso(),
        )
        if changed:
            self.mark_control_terminal(task_id, TaskStatus.CANCELLED.value)
            self._notify_status_change(task_id, TaskStatus.CANCELLED)
        return changed

    def mark_waiting(self, task_id: str, reason: str = "human_in_loop"):
        """标记为等待人工确认。"""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT metadata, status FROM koto_tasks WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                if not row or row["status"] in {
                    TaskStatus.COMPLETED.value,
                    TaskStatus.FAILED.value,
                    TaskStatus.CANCELLED.value,
                }:
                    self._conn.rollback()
                    return False
                meta = json.loads(row["metadata"]) if row["metadata"] else {}
                meta["waiting_reason"] = reason
                self._conn.execute(
                    "UPDATE koto_tasks SET status = ?, metadata = ? WHERE task_id = ?",
                    (
                        TaskStatus.WAITING.value,
                        json.dumps(meta, ensure_ascii=False),
                        task_id,
                    ),
                )
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise
        self._notify_status_change(task_id, TaskStatus.WAITING)
        return True

    def increment_retries(self, task_id: str):
        with self._lock:
            cursor = self._conn.execute(
                """UPDATE koto_tasks
                   SET retry_count = retry_count + 1, status = ?
                   WHERE task_id = ?
                     AND status NOT IN ('completed', 'failed', 'cancelled')""",
                (TaskStatus.RETRYING.value, task_id),
            )
            self._conn.commit()
        return bool(cursor.rowcount)

    def set_priority(self, task_id: str, priority: int):
        """更新任务优先级（0=低/1=正常/2=高/3=紧急）。"""
        self._update_fields(task_id, priority=int(priority))
        logger.info(f"[TaskLedger] 优先级更新 task={task_id[:8]} → {priority}")

    def update_metadata(self, task_id: str, metadata: Dict[str, Any]):
        """Merge metadata keys into an existing task record."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT metadata FROM koto_tasks WHERE task_id = ?", (task_id,)
                ).fetchone()
                current = json.loads(row["metadata"]) if row and row["metadata"] else {}
                current.update(metadata or {})
                self._conn.execute(
                    "UPDATE koto_tasks SET metadata = ? WHERE task_id = ?",
                    (json.dumps(current, ensure_ascii=False), task_id),
                )
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    # ── 中断 / 取消控制 ───────────────────────────────────────────────────────

    def request_interrupt(self, task_id: str):
        """请求暂停任务，等待人工确认后可 resume。"""
        self._update_fields(task_id, interrupt_requested=1)
        logger.info(f"[TaskLedger] ⏸ 打断请求 → task {task_id[:8]}")

    def resume_task(self, task_id: str):
        """恢复被 interrupt 的任务。"""
        changed = self._update_nonterminal_fields(
            task_id,
            interrupt_requested=0,
            status=TaskStatus.RUNNING.value,
        )
        if changed:
            logger.info(f"[TaskLedger] ▶ 恢复任务 → task {task_id[:8]}")
        return changed

    def cancel_task(self, task_id: str) -> bool:
        """Persist a cancellation request, even before a task row exists.

        File-task ``run_id`` values and Kernel ``task_id`` values share this
        control table.  The upsert makes cancellation visible across workers
        and preserves a request that arrives just before task registration.
        Returns ``True`` only for the first request.
        """
        control_id = str(task_id or "").strip()
        if not control_id:
            return False
        now = _now_iso()
        with self._lock:
            previous = self._conn.execute(
                "SELECT cancel_requested FROM koto_task_controls WHERE control_id = ?",
                (control_id,),
            ).fetchone()
            self._conn.execute(
                """
                INSERT INTO koto_task_controls
                  (control_id, cancel_requested, terminal_status, updated_at)
                VALUES (?, 1, NULL, ?)
                ON CONFLICT(control_id) DO UPDATE SET
                  cancel_requested = 1,
                  updated_at = excluded.updated_at
                """,
                (control_id, now),
            )
            self._conn.execute(
                "UPDATE koto_tasks SET cancel_requested = 1 WHERE task_id = ?",
                (control_id,),
            )
            self._conn.commit()
        logger.info(f"[TaskLedger] ✖ 取消请求 → task {control_id[:8]}")
        return not bool(previous and previous["cancel_requested"])

    def is_cancel_requested(self, task_id: str) -> bool:
        """供执行线程轮询检查。"""
        control_id = str(task_id or "").strip()
        if not control_id:
            return False
        with self._lock:
            row = self._conn.execute(
                "SELECT cancel_requested FROM koto_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            control = self._conn.execute(
                "SELECT cancel_requested FROM koto_task_controls WHERE control_id = ?",
                (control_id,),
            ).fetchone()
        return bool(
            (row and row["cancel_requested"])
            or (control and control["cancel_requested"])
        )

    def mark_control_terminal(self, control_id: str, status: str) -> None:
        """Record one durable terminal state for a run/task control key."""
        clean = str(control_id or "").strip()
        if not clean:
            return
        normalized = str(status or "").strip().lower()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO koto_task_controls
                  (control_id, cancel_requested, terminal_status, updated_at)
                VALUES (?, 0, ?, ?)
                ON CONFLICT(control_id) DO UPDATE SET
                  terminal_status = COALESCE(koto_task_controls.terminal_status,
                                             excluded.terminal_status),
                  updated_at = excluded.updated_at
                """,
                (clean, normalized, _now_iso()),
            )
            self._conn.commit()

    # ── Durable file-task plans ──────────────────────────────────────────

    def upsert_task_plan(
        self,
        run_id: str,
        patch: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Transactionally merge a task-plan patch without losing fields."""
        clean = str(run_id or "").strip()
        if not clean:
            return {}
        now = _now_iso()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT payload, created_at FROM koto_task_plans WHERE run_id = ?",
                    (clean,),
                ).fetchone()
                current: Dict[str, Any] = {}
                if row and row["payload"]:
                    try:
                        decoded = json.loads(row["payload"])
                    except (TypeError, ValueError) as exc:
                        raise RuntimeError(
                            f"corrupt task plan for run_id={clean}"
                        ) from exc
                    if not isinstance(decoded, dict):
                        raise RuntimeError(f"invalid task plan for run_id={clean}")
                    current = decoded
                created_at = str(row["created_at"] if row else now)
                current.update(dict(patch or {}))
                current.update(
                    {
                        "run_id": clean,
                        "created_at": current.get("created_at") or created_at,
                        "updated_at": now,
                    }
                )
                status = str(current.get("status") or "in_progress")[:32]
                current["status"] = status
                encoded = json.dumps(current, ensure_ascii=False)
                self._conn.execute(
                    """
                    INSERT INTO koto_task_plans
                      (run_id, payload, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(run_id) DO UPDATE SET
                      payload = excluded.payload,
                      status = excluded.status,
                      updated_at = excluded.updated_at
                    """,
                    (clean, encoded, status, created_at, now),
                )
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise
        return dict(current)

    def get_task_plan(self, run_id: str) -> Optional[Dict[str, Any]]:
        clean = str(run_id or "").strip()
        if not clean:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM koto_task_plans WHERE run_id = ?", (clean,)
            ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"corrupt task plan for run_id={clean}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"invalid task plan for run_id={clean}")
        return payload

    def list_task_plans(
        self, *, status: Optional[str] = None, limit: int = 10
    ) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit or 10), 500))
        with self._lock:
            if status:
                rows = self._conn.execute(
                    """SELECT payload FROM koto_task_plans
                       WHERE status = ? ORDER BY updated_at DESC LIMIT ?""",
                    (str(status), safe_limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """SELECT payload FROM koto_task_plans
                       ORDER BY updated_at DESC LIMIT ?""",
                    (safe_limit,),
                ).fetchall()
        plans: List[Dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, ValueError) as exc:
                raise RuntimeError("corrupt task-plan ledger row") from exc
            if isinstance(payload, dict):
                plans.append(payload)
        return plans

    def is_interrupt_requested(self, task_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT interrupt_requested FROM koto_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return bool(row["interrupt_requested"]) if row else False

    # ── 步骤记录 ──────────────────────────────────────────────────────────────

    def add_step(
        self,
        task_id: str,
        step_type: str,
        content: str,
        tool_name: Optional[str] = None,
        tool_args: Optional[Dict[str, Any]] = None,
        observation: Optional[str] = None,
    ) -> StepRecord:
        """追加一条步骤记录，同时更新任务的 step_count / tool_calls 计数。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(step_index), -1) AS max_idx FROM koto_task_steps WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            step_index = (row["max_idx"] + 1) if row else 0

            step = StepRecord(
                task_id=task_id,
                step_index=step_index,
                step_type=step_type,
                content=content[:2000],
                tool_name=tool_name,
                tool_args=(
                    json.dumps(tool_args, ensure_ascii=False) if tool_args else None
                ),
                observation=(observation or "")[:2000] if observation else None,
            )
            self._conn.execute(
                """
                INSERT INTO koto_task_steps
                  (step_id, task_id, step_index, step_type, content,
                   tool_name, tool_args, observation, created_at)
                VALUES
                  (:step_id, :task_id, :step_index, :step_type, :content,
                   :tool_name, :tool_args, :observation, :created_at)
                """,
                asdict(step),
            )
            # 更新计数器
            if step_type == "ACTION":
                self._conn.execute(
                    "UPDATE koto_tasks SET step_count = step_count + 1, tool_calls = tool_calls + 1 WHERE task_id = ?",
                    (task_id,),
                )
            else:
                self._conn.execute(
                    "UPDATE koto_tasks SET step_count = step_count + 1 WHERE task_id = ?",
                    (task_id,),
                )
            self._conn.commit()
        return step

    def _get_steps(self, task_id: str) -> List[StepRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM koto_task_steps WHERE task_id = ? ORDER BY step_index ASC",
                (task_id,),
            ).fetchall()
        return [StepRecord(**dict(r)) for r in rows]

    def get_steps(self, task_id: str) -> List[StepRecord]:
        return self._get_steps(task_id)

    # ── 统计 ──────────────────────────────────────────────────────────────────

    def get_stats(self, date_from: Optional[str] = None) -> Dict[str, Any]:
        """返回任务运行统计摘要。"""
        where = f"WHERE created_at >= '{date_from}'" if date_from else ""
        with self._lock:
            rows = self._conn.execute(f"""
                SELECT status, COUNT(*) AS cnt
                FROM koto_tasks {where}
                GROUP BY status
                """).fetchall()
            by_status = {r["status"]: r["cnt"] for r in rows}
            total = sum(by_status.values())
            avg_row = self._conn.execute(f"""
                SELECT AVG(
                    (JULIANDAY(COALESCE(completed_at, datetime('now'))) - JULIANDAY(started_at)) * 86400
                ) AS avg_sec
                FROM koto_tasks
                {where}
                WHERE started_at IS NOT NULL
                """).fetchone()
        return {
            "total": total,
            "by_status": by_status,
            "avg_duration_seconds": round(avg_row["avg_sec"] or 0, 2),
        }

    # ── 清理 ──────────────────────────────────────────────────────────────────

    def purge_old(self, keep_days: int = 30):
        """删除超过 keep_days 天的已完成/已取消任务及其步骤。"""
        cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff_iso = cutoff.isoformat()
        try:
            with self._lock:
                self._conn.execute(
                    """
                    DELETE FROM koto_task_steps WHERE task_id IN (
                        SELECT task_id FROM koto_tasks
                        WHERE status IN ('completed', 'cancelled', 'failed')
                          AND created_at < ?
                    )
                    """,
                    (cutoff_iso,),
                )
                deleted = self._conn.execute(
                    """
                    DELETE FROM koto_tasks
                    WHERE status IN ('completed', 'cancelled', 'failed')
                      AND created_at < ?
                    """,
                    (cutoff_iso,),
                ).rowcount
                self._conn.commit()
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower():
                raise
            logger.warning("[TaskLedger] purge_old skipped due to db lock")
            try:
                with self._lock:
                    self._conn.rollback()
            except Exception:
                pass
            return 0
        logger.info(f"[TaskLedger] 清理 {deleted} 条历史任务（>{keep_days}天）")
        return deleted

    def cancel_stale_startup_health_tasks(self, timeout_seconds: float = 300.0) -> int:
        """
        Mark orphaned startup health-check jobs as cancelled.

        This is intentionally narrow: it only catches the built-in startup
        health preset and the historical source=agent child tasks created by
        that preset before JobRunner delegated without creating a second ledger
        entry.
        """
        timeout = max(0.0, float(timeout_seconds))
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT task_id, started_at, created_at, source, task_type, user_input, metadata
                FROM koto_tasks
                WHERE status = ?
                """,
                (TaskStatus.RUNNING.value,),
            ).fetchall()

        now = datetime.now()
        task_ids: List[str] = []
        for row in rows:
            started_raw = row["started_at"] or row["created_at"] or ""
            try:
                started_at = datetime.strptime(
                    str(started_raw)[:26], "%Y-%m-%dT%H:%M:%S.%f"
                )
            except Exception:
                continue
            if (now - started_at).total_seconds() < timeout:
                continue

            metadata = {}
            try:
                metadata = json.loads(row["metadata"] or "{}")
            except Exception:
                metadata = {}
            user_input = str(row["user_input"] or "")
            source = str(row["source"] or "")
            task_type = str(row["task_type"] or "")
            preset = str(metadata.get("preset_key") or "")
            trigger_name = str(metadata.get("trigger_name") or "")

            is_job_runner_health = (
                source == "job_runner"
                and task_type == "agent_query"
                and (
                    preset == "startup_runtime_health"
                    or "startup_runtime_health" in user_input
                    or trigger_name == "启动自检摘要"
                )
            )
            is_historical_agent_child = (
                source == "agent"
                and task_type == "agent"
                and "请总结当前 Koto 的后台运行状态、关键模块是否就绪" in user_input
            )
            if is_job_runner_health or is_historical_agent_child:
                task_ids.append(row["task_id"])

        if not task_ids:
            return 0

        completed_at = _now_iso()
        with self._lock:
            self._conn.executemany(
                """
                UPDATE koto_tasks
                SET status = ?, cancel_requested = 1, completed_at = ?
                WHERE task_id = ? AND status = ?
                """,
                [
                    (
                        TaskStatus.CANCELLED.value,
                        completed_at,
                        task_id,
                        TaskStatus.RUNNING.value,
                    )
                    for task_id in task_ids
                ],
            )
            self._conn.commit()
        for task_id in task_ids:
            self._notify_status_change(task_id, TaskStatus.CANCELLED)
        logger.info("[TaskLedger] 清理启动自检残留 running 任务 %d 条", len(task_ids))
        return len(task_ids)

    def cancel_stale_running_tasks(self, timeout_seconds: float = 86400.0) -> int:
        """Mark old running tasks as cancelled after a process restart."""
        timeout = max(0.0, float(timeout_seconds))
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT task_id, started_at, created_at
                FROM koto_tasks
                WHERE status = ?
                """,
                (TaskStatus.RUNNING.value,),
            ).fetchall()

        now = datetime.now()
        task_ids: List[str] = []
        for row in rows:
            started_raw = row["started_at"] or row["created_at"] or ""
            try:
                started_at = datetime.strptime(
                    str(started_raw)[:26], "%Y-%m-%dT%H:%M:%S.%f"
                )
            except Exception:
                continue
            if (now - started_at).total_seconds() >= timeout:
                task_ids.append(row["task_id"])

        if not task_ids:
            return 0

        completed_at = _now_iso()
        with self._lock:
            self._conn.executemany(
                """
                UPDATE koto_tasks
                SET status = ?, cancel_requested = 1, completed_at = ?
                WHERE task_id = ? AND status = ?
                """,
                [
                    (
                        TaskStatus.CANCELLED.value,
                        completed_at,
                        task_id,
                        TaskStatus.RUNNING.value,
                    )
                    for task_id in task_ids
                ],
            )
            self._conn.commit()
        for task_id in task_ids:
            self._notify_status_change(task_id, TaskStatus.CANCELLED)
        logger.info("[TaskLedger] 清理超时 running 孤儿任务 %d 条", len(task_ids))
        return len(task_ids)

    # ── ProgressBus 联动 ──────────────────────────────────────────────────────

    def _notify_status_change(self, task_id: str, new_status: TaskStatus):
        """当状态变化时，尝试通知 ProgressBus（懒加载，避免循环依赖）。"""
        try:
            from app.core.tasks.progress_bus import ProgressEvent, get_progress_bus

            bus = get_progress_bus()
            task = self.get(task_id)
            bus.publish(
                ProgressEvent(
                    task_id=task_id,
                    session_id=task.session_id if task else "",
                    event_type="status_change",
                    status=new_status.value,
                    message=f"任务状态：{new_status.value}",
                    progress=_STATUS_PROGRESS.get(new_status, 0),
                )
            )
        except Exception as e:
            logger.debug(f"[TaskLedger] _notify_status_change 跳过: {e}")


# 状态对应默认进度值
_STATUS_PROGRESS: Dict[TaskStatus, int] = {
    TaskStatus.PENDING: 0,
    TaskStatus.RUNNING: 10,
    TaskStatus.WAITING: 50,
    TaskStatus.RETRYING: 30,
    TaskStatus.COMPLETED: 100,
    TaskStatus.FAILED: 0,
    TaskStatus.CANCELLED: 0,
}


# ============================================================================
# 单例访问
# ============================================================================


def get_ledger(db_path: Optional[str] = None) -> TaskLedger:
    """返回全局 TaskLedger 单例（线程安全）。"""
    global _ledger_instance
    with _ledger_lock:
        if _ledger_instance is None:
            _ledger_instance = TaskLedger(db_path)
    return _ledger_instance
