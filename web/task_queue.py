# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Lightweight background task queue with status polling.

Zero external dependencies — uses ``threading`` + ``queue``.
Tasks run in a bounded thread pool; status is pollable via REST.

Usage::

    from web.task_queue import task_queue

    task_id = task_queue.submit(
        "analyze_report",
        lambda: analyze_large_file("/path/to/report.xlsx"),
        on_complete=lambda tid, result: notify_user(tid),
    )
    # Returns immediately. Client polls GET /api/tasks/{task_id}
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

_logger = logging.getLogger("koto.tasks")


@dataclass
class BackgroundTask:
    """Track a single background task's lifecycle."""

    task_id: str
    name: str
    status: str = "pending"  # pending | running | completed | failed | cancelled
    progress: float = 0.0    # 0.0 - 1.0
    message: str = ""
    result: Any = None
    error: str = ""
    created_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None

    def to_dict(self) -> dict:
        elapsed = time.monotonic() - self.created_at
        return {
            "task_id": self.task_id,
            "name": self.name,
            "status": self.status,
            "progress": round(self.progress, 3),
            "message": self.message,
            "error": self.error,
            "elapsed_ms": int(elapsed * 1000),
            "has_result": self.result is not None,
        }


class TaskQueue:
    """Thread-pool-backed task queue with status tracking."""

    def __init__(self, max_workers: int = 4, task_ttl_seconds: int = 600) -> None:
        self._max_workers = max_workers
        self._task_ttl = task_ttl_seconds
        self._lock = threading.Lock()
        self._tasks: dict[str, BackgroundTask] = {}
        self._queue: queue.Queue = queue.Queue()
        self._workers: list[threading.Thread] = []
        self._running = False

    def start(self) -> None:
        """Launch worker threads."""
        if self._running:
            return
        self._running = True
        for i in range(self._max_workers):
            t = threading.Thread(target=self._worker_loop, name=f"koto-task-{i}", daemon=True)
            t.start()
            self._workers.append(t)
        _logger.info("[TaskQueue] started with %d workers", self._max_workers)

    def shutdown(self, wait: bool = True, timeout: float = 5.0) -> None:
        """Gracefully stop workers."""
        self._running = False
        for _ in self._workers:
            self._queue.put(None)  # poison pill
        if wait:
            for t in self._workers:
                t.join(timeout=timeout)
        _logger.info("[TaskQueue] shut down")

    def submit(
        self,
        name: str,
        fn: Callable[[], Any],
        *,
        on_complete: Callable[[str, Any], None] | None = None,
        on_error: Callable[[str, Exception], None] | None = None,
    ) -> str:
        """Submit a callable for background execution. Returns task_id immediately."""
        task_id = uuid.uuid4().hex[:12]
        task = BackgroundTask(task_id=task_id, name=name, status="pending")
        with self._lock:
            self._tasks[task_id] = task
        self._queue.put((task_id, fn, on_complete, on_error))
        _logger.info("[TaskQueue] submitted %s (%s)", name, task_id)
        return task_id

    def get(self, task_id: str) -> BackgroundTask | None:
        with self._lock:
            return self._tasks.get(task_id)

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if task and task.status in ("pending", "running"):
                task.status = "cancelled"
                task.message = "任务已取消"
                task.finished_at = time.monotonic()
                return True
        return False

    def get_all(self, status: str | None = None) -> list[dict]:
        with self._lock:
            items = list(self._tasks.values())
        if status:
            items = [t for t in items if t.status == status]
        items.sort(key=lambda t: t.created_at, reverse=True)
        return [t.to_dict() for t in items[:50]]

    # -- internal --

    def _worker_loop(self) -> None:
        while self._running:
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                self._cleanup_expired()
                continue

            if item is None:
                break

            task_id, fn, on_complete, on_error = item
            self._execute(task_id, fn, on_complete, on_error)
            self._queue.task_done()

    def _execute(
        self,
        task_id: str,
        fn: Callable[[], Any],
        on_complete: Callable | None,
        on_error: Callable | None,
    ) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            if task.status == "cancelled":
                return
            task.status = "running"
            task.message = "处理中..."

        try:
            result = fn()
            with self._lock:
                if task.status == "cancelled":
                    return
                task.status = "completed"
                task.progress = 1.0
                task.result = result
                task.message = "完成"
                task.finished_at = time.monotonic()
            if on_complete:
                try:
                    on_complete(task_id, result)
                except Exception:
                    _logger.exception("[TaskQueue] on_complete callback failed")
        except Exception as exc:
            with self._lock:
                task.status = "failed"
                task.error = str(exc)
                task.message = f"失败: {exc}"
                task.finished_at = time.monotonic()
            _logger.exception("[TaskQueue] task %s failed: %s", task_id, exc)
            if on_error:
                try:
                    on_error(task_id, exc)
                except Exception:
                    pass

    def _cleanup_expired(self) -> None:
        now = time.monotonic()
        with self._lock:
            expired = [
                tid for tid, t in self._tasks.items()
                if t.finished_at and (now - t.finished_at) > self._task_ttl
            ]
            for tid in expired:
                del self._tasks[tid]


# Singleton
task_queue = TaskQueue(max_workers=4, task_ttl_seconds=600)
