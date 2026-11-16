# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Koto JobRunner — 后台作业执行器
================================
将持久化的 TaskLedger 条目转化为真正可后台执行的作业：

- 提交：submit(JobSpec) → task_id，立即入队
- 执行：线程池执行，每个作业都绑定 TaskLedger 生命周期
- 进度：通过 ProgressBus 向前端/SSE 推送实时步骤
- 控制：取消、暂停（interrupt）、恢复 — 与 TaskLedger 信号位联动
- 重试：失败时按 max_retries + 指数退避自动重排
- 崩溃恢复：启动时自动检测 PENDING/job_runner 任务并重排

作业类型 (job_type) 与内置处理器：
  "agent_query"   — 通过 KernelAgent 执行用户查询
  "workflow"      — 通过 TaskPlanner 执行多步工作流
  "auto_catalog"  — 触发自动整理任务

自定义处理器注册：
    runner = get_job_runner()
    runner.register_handler("my_type", lambda ctx: do_something(ctx))
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# 数据结构
# ============================================================================


@dataclass
class JobSpec:
    """描述一个待提交的作业。"""

    job_type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    max_retries: int = 0
    timeout_seconds: float = 300.0
    metadata: Optional[Dict[str, Any]] = None
    priority: int = 1  # TaskPriority 整数值（0=低/1=正常/2=高/3=紧急），数值越大越优先


@dataclass
class JobContext:
    """
    传给每个处理器的执行上下文。

    用法：
        def my_handler(ctx: JobContext) -> Optional[str]:
            ctx.step("THOUGHT", "开始处理...", progress=10)
            if ctx.is_cancelled(): return "已取消"
            result = do_work(ctx.payload)
            ctx.step("ANSWER", result[:200], progress=100)
            return result[:500]
    """

    task_id: str
    session_id: str
    payload: Dict[str, Any]
    ledger: Any  # TaskLedger
    bus: Any  # ProgressBus

    def is_cancelled(self) -> bool:
        """供处理器轮询：外部是否已请求取消。"""
        return self.ledger.is_cancel_requested(self.task_id)

    def is_interrupted(self) -> bool:
        """供处理器轮询：外部是否已请求暂停（Human-in-loop）。"""
        return self.ledger.is_interrupt_requested(self.task_id)

    def step(
        self,
        step_type: str,
        content: str,
        progress: int = 0,
        tool_name: Optional[str] = None,
    ):
        """
        记录一个执行步骤并广播到 ProgressBus。

        Args:
            step_type: THOUGHT / ACTION / OBSERVATION / ANSWER / ERROR
            content:   步骤文本
            progress:  0-100 进度百分比
            tool_name: 若是工具调用，传入工具名
        """
        try:
            self.ledger.add_step(
                self.task_id,
                step_type=step_type,
                content=content,
                tool_name=tool_name,
            )
        except Exception as _e:
            logger.warning("[JobContext] TaskLedger 记录步骤失败: %s", _e)
        try:
            detail = None
            task = self.ledger.get(self.task_id)
            metadata = (
                json.loads(task.metadata or "{}")
                if task and isinstance(task.metadata, str)
                else {}
            )
            run_id = str(metadata.get("run_id") or self.task_id)
            event = self.ledger.append_run_event(
                self.task_id,
                run_id,
                "agent_step",
                {
                    "data": {
                        "step_type": str(step_type).lower(),
                        "content": content,
                        "metadata": {"progress": progress, "tool_name": tool_name},
                    }
                },
            )
            if isinstance(event, dict):
                detail = {"event": event}
            self.bus.publish_step(
                task_id=self.task_id,
                session_id=self.session_id,
                step_type=step_type,
                content=content,
                progress=progress,
                tool_name=tool_name,
                detail=detail,
            )
        except Exception as _e:
            logger.warning("[JobContext] ProgressBus 发布步骤失败: %s", _e)


# ============================================================================
# JobRunner
# ============================================================================


class JobRunner:
    """
    后台作业执行器（线程池 + 优先队列）。

    使用示例：
        runner = get_job_runner()
        task_id = runner.submit(JobSpec(
            job_type="agent_query",
            payload={"query": "帮我写一份周报"},
            session_id="sess-abc",
        ))
        # 通过 GET /api/tasks/<task_id>/stream 跟踪进度
    """

    def __init__(self, max_workers: int = 4):
        self._max_workers = max_workers
        # (priority, timestamp, task_id, spec)
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="koto_job"
        )
        self._handlers: Dict[str, Callable[[JobContext], Optional[str]]] = {}
        self._running = False
        self._dispatcher_thread: Optional[threading.Thread] = None

    # ── 生命周期 ──────────────────────────────────────────────────────────────

    def start(self):
        self._running = True
        self._dispatcher_thread = threading.Thread(
            target=self._dispatch_loop, daemon=True, name="koto_job_dispatcher"
        )
        self._dispatcher_thread.start()
        # 延迟恢复（等 TaskLedger 初始化完成）
        threading.Thread(
            target=self._recover_stale_tasks, daemon=True, name="koto_job_recovery"
        ).start()
        logger.info("[JobRunner] ✅ 启动，max_workers=%d", self._max_workers)

    def stop(self):
        self._running = False
        self._executor.shutdown(wait=False)

    # ── 注册处理器 ────────────────────────────────────────────────────────────

    def register_handler(
        self, job_type: str, fn: Callable[[JobContext], Optional[str]]
    ):
        """
        注册自定义作业类型处理器。

        处理器签名：fn(ctx: JobContext) -> Optional[str]
        返回值为 result_summary（最多 500 字），None 也可以。
        若处理器需要报错，直接 raise 即可，JobRunner 会捕获并标记失败。
        """
        self._handlers[job_type] = fn
        logger.debug("[JobRunner] 注册处理器: %s", job_type)

    def submit_continuation(self, consume: Callable[[], Any]):
        """Adopt an already-running producer after its viewing socket closes.

        The caller retains the original generator and its trusted invocation
        context.  This schedules no new task and never restarts its model/tool
        loop; the existing pool simply continues consuming that same producer.
        """
        if not callable(consume):
            raise TypeError("continuation must be callable")
        return self._executor.submit(consume)

    # ── 提交作业 ──────────────────────────────────────────────────────────────

    def submit(self, spec: JobSpec) -> str:
        """
        创建 TaskLedger 条目并入队。
        返回 task_id，作为后续查询/控制的唯一标识。
        """
        from app.core.tasks.task_ledger import get_ledger

        ledger = get_ledger()

        # 将 payload 序列化为 user_input（TaskLedger 的文本字段）
        user_input_str = json.dumps(spec.payload, ensure_ascii=False)[:1000]

        # 优先级映射：数值越大越优先。PriorityQueue 用最小堆，故用负数表示高优先
        _priority_int = max(0, min(3, int(spec.priority)))

        task = ledger.create(
            session_id=spec.session_id or "system",
            user_input=user_input_str,
            task_type=spec.job_type,
            source="job_runner",
            priority=_priority_int,
            metadata={
                "job_type": spec.job_type,
                "max_retries": spec.max_retries,
                "timeout_seconds": spec.timeout_seconds,
                **(spec.metadata or {}),
                "job_payload": json.loads(json.dumps(spec.payload, ensure_ascii=False)),
                "run_id": str((spec.metadata or {}).get("run_id") or uuid.uuid4().hex),
            },
        )

        # PriorityQueue 最小堆：用 (3 - priority) 保证高优先级先出队
        self._queue.put((3 - _priority_int, time.time(), task.task_id, spec))
        logger.info(
            "[JobRunner] 作业入队 task_id=%s type=%s priority=%d",
            task.task_id[:8],
            spec.job_type,
            _priority_int,
        )
        return task.task_id

    def retry(self, task_id: str) -> str:
        """Requeue a failed or cancelled job using its persisted task metadata."""
        from app.core.tasks.task_ledger import TaskStatus, get_ledger

        ledger = get_ledger()
        task = ledger.get(task_id)
        if task is None:
            raise LookupError("作业不存在")
        if task.status not in (TaskStatus.FAILED, TaskStatus.CANCELLED):
            raise ValueError(
                f"只能重试 failed/cancelled 作业，当前状态: {task.status.value}"
            )

        metadata = json.loads(task.metadata or "{}")
        job_type = metadata.get("job_type") or task.task_type
        if not job_type:
            raise ValueError("无法确定 job_type，无法重试")
        payload = metadata.get("job_payload")
        if not isinstance(payload, dict):
            try:
                payload = json.loads(task.user_input)
            except (TypeError, json.JSONDecodeError):
                payload = {"raw": task.user_input}

        ledger._update_fields(
            task_id,
            status=TaskStatus.PENDING.value,
            error=None,
            cancel_requested=0,
            completed_at=None,
        )
        previous_runs = list(metadata.get("previous_runs") or [])
        previous_runs.append(
            {"run_id": metadata.get("run_id") or task_id, "status": task.status.value}
        )
        metadata.update(
            {"previous_runs": previous_runs[-20:], "run_id": uuid.uuid4().hex}
        )
        ledger.update_metadata(task_id, metadata)
        ledger.clear_cancel_for_retry(task_id)
        spec = JobSpec(
            job_type=job_type,
            payload=payload,
            session_id=task.session_id,
            max_retries=int(metadata.get("max_retries", 0)),
            timeout_seconds=float(metadata.get("timeout_seconds", 300.0)),
            priority=int(getattr(task, "priority", 1)),
            metadata=metadata,
        )
        priority = max(0, min(3, int(spec.priority)))
        self._queue.put((3 - priority, time.time(), task_id, spec))
        return task_id

    def resume_kernel(
        self, task_id: str, *, run_id: Optional[str] = None, approved: bool = False
    ) -> str:
        """Continue a saved Kernel state through this runner's existing pool.

        This never reconstructs a fresh request from a result summary and never
        replays an unconfirmed write.  A durable lease prevents two workers
        from continuing the same run at once.
        """
        from app.core.tasks.task_ledger import get_ledger

        ledger = get_ledger()
        task = ledger.get(task_id)
        if task is None:
            raise LookupError("任务不存在")
        if (
            task.interrupt_requested or task.status.value == "waiting"
        ) and not approved:
            raise ValueError("任务正在等待明确确认，不能自动恢复")
        checkpoint = ledger.get_kernel_checkpoint(task_id, run_id)
        if not checkpoint:
            raise ValueError("没有可恢复的内核检查点")
        if not checkpoint["resumable"]:
            raise ValueError("工具副作用尚未核实，不能自动重放")
        owner_id = f"kernel-resume-{uuid.uuid4()}"
        claimed = ledger.claim_kernel_checkpoint(
            task_id, owner_id, run_id=checkpoint["run_id"]
        )
        if not claimed:
            raise ValueError("任务仍在执行、已结束或已请求取消，不能重复恢复")
        try:
            self._executor.submit(self._continue_kernel, task_id, claimed, owner_id)
        except BaseException:
            ledger.release_kernel_checkpoint(task_id, checkpoint["run_id"], owner_id)
            raise
        return task_id

    def _continue_kernel(self, task_id: str, checkpoint: Dict[str, Any], owner_id: str):
        from app.core.agent.kernel_agent_service import get_kernel_agent
        from app.core.tasks.progress_bus import ProgressEvent, get_progress_bus
        from app.core.tasks.task_ledger import get_ledger

        ledger, bus = get_ledger(), get_progress_bus()
        task = ledger.get(task_id)
        run_id = checkpoint["run_id"]
        stopped = threading.Event()

        def heartbeat():
            while not stopped.wait(10.0):
                if not ledger.renew_kernel_lease(task_id, run_id, owner_id):
                    return

        threading.Thread(
            target=heartbeat, daemon=True, name=f"kernel-lease-{task_id[:8]}"
        ).start()

        def save(state):
            snapshot = dict(state)
            for identity_key in ("model_mode", "requires_authorization"):
                if identity_key in checkpoint["state"]:
                    snapshot[identity_key] = checkpoint["state"][identity_key]
            ledger.save_kernel_checkpoint(task_id, run_id, snapshot, owner_id=owner_id)
            ledger.renew_kernel_lease(task_id, run_id, owner_id)

        try:
            if task is None:
                return
            state = checkpoint["state"]
            if state.get("requires_authorization"):
                ledger.mark_waiting(task_id, reason="恢复需要重新建立原调用权限")
                return
            if state.get("runtime_adapter") == "file_task":
                self._continue_file_task(task, state, owner_id)
                return
            ledger.resume_task(task_id)
            agent = get_kernel_agent(
                local=str(state.get("model_mode") or "") == "local",
                model_id=str(state.get("model_id") or "") or None,
            )
            answer = ""
            failed = False
            for step in agent.run(
                input_text=task.user_input,
                session_id=task.session_id,
                task_type=task.task_type or "AGENT",
                task_id=task_id,
                run_id=run_id,
                resume_state=state,
                checkpoint_callback=save,
                stream_events=True,
            ):
                data = step.to_dict()
                kind = str(data.get("step_type") or "").lower()
                if kind == "answer":
                    answer = str(data.get("content") or "")
                if kind == "error":
                    failed = True
                from app.core.agent.kernel_step_events import project_agent_step

                event_type, payload = project_agent_step(data)
                event = ledger.append_run_event(task_id, run_id, event_type, payload)
                bus.publish(
                    ProgressEvent.from_run_event(event, session_id=task.session_id)
                )
            status = (
                "cancelled"
                if ledger.is_cancel_requested(task_id)
                else "failed" if failed else "completed"
            )
            event = ledger.append_run_event(
                task_id,
                run_id,
                "run.finished",
                {
                    "status": status,
                    "summary": answer,
                    "completed_task": status == "completed",
                },
            )
            bus.publish(ProgressEvent.from_run_event(event, session_id=task.session_id))
        except Exception as exc:
            from app.core.agent.file_task_checkpoint import FileTaskCheckpointConflict

            if isinstance(exc, FileTaskCheckpointConflict):
                blocked = dict(checkpoint["state"])
                blocked["recovery_conflict"] = str(exc)
                ledger.save_kernel_checkpoint(
                    task_id, run_id, blocked, resumable=False, owner_id=owner_id
                )
                ledger.mark_waiting(task_id, reason=str(exc))
                event = ledger.append_run_event(
                    task_id,
                    run_id,
                    "run.waiting",
                    {"status": "waiting", "summary": str(exc), "recoverable": True},
                )
                bus.publish(
                    ProgressEvent.from_run_event(
                        event, session_id=task.session_id if task else ""
                    )
                )
                return
            logger.exception(
                "[JobRunner] Kernel continuation failed task_id=%s", task_id
            )
            ledger.mark_failed(task_id, str(exc)[:1000])
            try:
                event = ledger.append_run_event(
                    task_id,
                    run_id,
                    "run.finished",
                    {
                        "status": "failed",
                        "completed_task": False,
                        "summary": "恢复执行失败",
                        "error": str(exc)[:1000],
                    },
                )
                bus.publish(
                    ProgressEvent.from_run_event(
                        event, session_id=task.session_id if task else ""
                    )
                )
            except ValueError:
                pass  # A previous terminal event wins.
        finally:
            stopped.set()
            ledger.release_kernel_checkpoint(task_id, run_id, owner_id)

    def _continue_file_task(
        self, task: Any, state: Dict[str, Any], owner_id: str
    ) -> None:
        """Rebuild the file adapter, including its validator and finalization."""
        from app.core.agent.file_task_checkpoint import restore_file_task_receipts
        from app.core.agent.file_task_contract import FileTaskRequest
        from app.core.services.file_task_stream import (
            _build_file_task_orchestrator,
            _iter_file_task_stream_output,
        )

        restore_file_task_receipts(state)
        original = dict(state["file_task_request"])
        options = dict(original.get("options") or {})
        options["_kernel_resume_state"] = state
        options["_checkpoint_owner"] = owner_id
        original.update(
            {"task_id": task.task_id, "run_id": state["run_id"], "options": options}
        )
        request_payload = FileTaskRequest.from_mapping(original)
        orchestrator = _build_file_task_orchestrator(
            workspace_root=str(state.get("workspace_root") or "") or None
        )
        # The same domain stream persists events, validates outputs and records
        # the terminal fact; this branch must not append a generic final event.
        for _ in _iter_file_task_stream_output(
            request_payload, orchestrator.run(request_payload)
        ):
            pass

    # ── 内部执行循环 ──────────────────────────────────────────────────────────

    def _dispatch_loop(self):
        while self._running:
            try:
                _, _, task_id, spec = self._queue.get(timeout=1.0)
                self._executor.submit(self._run_job, task_id, spec)
            except queue.Empty:
                continue
            except Exception as exc:
                logger.error("[JobRunner] dispatch 异常: %s", exc)

    def _run_job(self, task_id: str, spec: JobSpec):
        from app.core.tasks.progress_bus import get_progress_bus
        from app.core.tasks.task_ledger import get_ledger

        ledger = get_ledger()
        bus = get_progress_bus()

        handler = self._handlers.get(spec.job_type)
        if not handler:
            ledger.mark_failed(task_id, f"未知 job_type: {spec.job_type!r}")
            self._publish_job_terminal(ledger, bus, task_id, "failed")
            return

        ctx = JobContext(
            task_id=task_id,
            session_id=spec.session_id or "system",
            payload=spec.payload,
            ledger=ledger,
            bus=bus,
        )

        ledger.mark_running(task_id)
        try:
            if ledger.is_cancel_requested(task_id) is True:
                ledger.mark_cancelled(task_id)
                self._publish_job_terminal(ledger, bus, task_id, "cancelled")
                return
            result_summary = handler(ctx)
            if ledger.is_cancel_requested(task_id):
                ledger.mark_cancelled(task_id)
            else:
                current = ledger.get(task_id)
                if (
                    not current
                    or str(getattr(current.status, "value", current.status))
                    != "waiting"
                ):
                    ledger.mark_completed(task_id, result_summary=result_summary)
            self._publish_job_terminal(
                ledger, bus, task_id, "completed", summary=result_summary or ""
            )
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error("[JobRunner] 作业失败 task_id=%s: %s", task_id[:8], exc)

            task = ledger.get(task_id)
            if task:
                meta = json.loads(task.metadata or "{}")
                max_retries = meta.get("max_retries", 0)
                if task.retry_count < max_retries:
                    ledger.increment_retries(task_id)
                    delay = min(60, 2**task.retry_count)
                    logger.info("[JobRunner] %ds 后重试 task_id=%s", delay, task_id[:8])

                    def _requeue(_tid=task_id, _spec=spec, _delay=delay):
                        time.sleep(_delay)
                        self._queue.put((5, time.time(), _tid, _spec))

                    threading.Thread(target=_requeue, daemon=True).start()
                    return

            ledger.mark_failed(task_id, f"{type(exc).__name__}: {exc}\n\n{tb}"[:1000])
            self._publish_job_terminal(ledger, bus, task_id, "failed", summary=str(exc))

            # 发布运维事件
            try:
                from app.core.ops.ops_event_bus import get_ops_bus

                get_ops_bus().emit(
                    "job_failed",
                    {
                        "task_id": task_id,
                        "job_type": spec.job_type,
                        "error": str(exc)[:300],
                    },
                )
            except Exception as _e:
                logger.debug("[JobRunner] OpsEventBus 发布 job_failed 事件失败: %s", _e)

    @staticmethod
    def _publish_job_terminal(
        ledger: Any, bus: Any, task_id: str, fallback_status: str, *, summary: str = ""
    ) -> None:
        """Publish the sole journal terminal from the ledger's actual status."""
        from app.core.tasks.progress_bus import ProgressEvent

        task = ledger.get(task_id)
        metadata = (
            json.loads(task.metadata or "{}")
            if task and isinstance(task.metadata, str)
            else {}
        )
        run_id = str(metadata.get("run_id") or task_id)
        status = (
            str(getattr(task.status, "value", task.status)) if task else fallback_status
        )
        if status not in {"completed", "failed", "cancelled", "waiting"}:
            status = fallback_status
        latest = ledger.latest_run_event(task_id, run_id)
        if isinstance(latest, dict):
            from app.core.tasks.task_journal import _terminal_event

            if _terminal_event(latest):
                return
        event = ledger.append_run_event(
            task_id,
            run_id,
            "run.waiting" if status == "waiting" else "run.finished",
            {
                "status": status,
                "summary": summary,
                "completed_task": status == "completed",
            },
        )
        if isinstance(event, dict):
            bus.publish(
                ProgressEvent.from_run_event(
                    event, session_id=task.session_id if task else ""
                )
            )

    def _recover_stale_tasks(self):
        """启动时将上次未完成的 PENDING 作业重新入队（崩溃恢复）。"""
        time.sleep(5)
        try:
            from app.core.tasks.task_ledger import TaskStatus, get_ledger

            ledger = get_ledger()
            for checkpoint in ledger.list_kernel_checkpoints(expired_only=True):
                if checkpoint["resumable"]:
                    try:
                        self.resume_kernel(
                            checkpoint["task_id"], run_id=checkpoint["run_id"]
                        )
                    except ValueError:
                        pass  # Claimed by another worker or durably cancelled.
                else:
                    ledger.mark_waiting(
                        checkpoint["task_id"],
                        reason="上次工具写入结果待核实，已保留检查点",
                    )
            try:
                ledger.cancel_stale_running_tasks(timeout_seconds=86400.0)
            except Exception as exc:
                logger.debug("[JobRunner] running 孤儿任务清理跳过: %s", exc)
            try:
                ledger.cancel_stale_startup_health_tasks(timeout_seconds=300.0)
            except Exception as exc:
                logger.debug("[JobRunner] 启动自检残留清理跳过: %s", exc)
            stale = ledger.list_tasks(
                status=TaskStatus.PENDING, source="job_runner", limit=100
            )
            for task in stale:
                meta = json.loads(task.metadata or "{}")
                checkpoint = ledger.get_kernel_checkpoint(
                    task.task_id, str(meta.get("run_id") or task.task_id)
                )
                if checkpoint is not None:
                    # Recovery above already claimed this continuation (or
                    # retained an unsafe write for reconciliation). Never also
                    # enqueue the original request from the beginning.
                    continue
                job_type = meta.get("job_type") or task.task_type
                if not job_type:
                    continue
                payload = meta.get("job_payload")
                if not isinstance(payload, dict):
                    try:
                        payload = json.loads(task.user_input)
                    except Exception:
                        payload = {"raw": task.user_input}
                spec = JobSpec(
                    job_type=job_type,
                    payload=payload,
                    session_id=task.session_id,
                    max_retries=meta.get("max_retries", 0),
                    timeout_seconds=meta.get("timeout_seconds", 300.0),
                    priority=getattr(task, "priority", 1),
                    metadata=meta,
                )
                _p = max(0, min(3, int(spec.priority)))
                self._queue.put((3 - _p, time.time(), task.task_id, spec))
                logger.info("[JobRunner] 恢复挂起任务 task_id=%s", task.task_id[:8])
        except Exception as exc:
            logger.warning("[JobRunner] 崩溃恢复失败: %s", exc)


# ============================================================================
# 单例
# ============================================================================

_runner: Optional[JobRunner] = None
_runner_lock = threading.Lock()


def get_job_runner() -> JobRunner:
    """获取全局 JobRunner 单例，首次调用时初始化并注册内置处理器。"""
    global _runner
    if _runner is None:
        with _runner_lock:
            if _runner is None:
                _runner = JobRunner()
                _register_builtin_handlers(_runner)
                _runner.start()
    return _runner


# ============================================================================
# 内置处理器
# ============================================================================


def _register_builtin_handlers(runner: JobRunner):
    runner.register_handler("agent_query", _handle_agent_query)
    runner.register_handler("workflow", _handle_workflow)
    runner.register_handler("auto_catalog", _handle_auto_catalog)
    runner.register_handler("proactive_tick", _handle_proactive_tick)


def _handle_agent_query(ctx: JobContext) -> Optional[str]:
    """通过 KernelAgent 执行自然语言查询。"""
    query = ctx.payload.get("query", "")
    if not query:
        raise ValueError("payload.query 不能为空")

    history = ctx.payload.get("history") or []
    ctx.step("THOUGHT", f"开始处理查询: {query[:120]}", progress=5)

    try:
        from app.core.agent.kernel_agent_service import get_kernel_agent
        from app.core.agent.types import AgentStepType

        agent = get_kernel_agent()
        final_answer = ""
        record = ctx.ledger.get(ctx.task_id)
        metadata = (
            json.loads(record.metadata or "{}")
            if record and isinstance(record.metadata, str)
            else {}
        )
        run_id = str(metadata.get("run_id") or ctx.task_id)
        for step in agent.run(
            input_text=query,
            history=history,
            session_id=ctx.session_id,
            record_task=False,
            task_ledger=ctx.ledger,
            task_id=ctx.task_id,
            run_id=run_id,
            stream_events=True,
        ):
            step_data = step.to_dict()
            from app.core.agent.kernel_step_events import project_agent_step
            from app.core.tasks.progress_bus import ProgressEvent

            event_type, payload = project_agent_step(step_data)
            event = ctx.ledger.append_run_event(
                ctx.task_id, run_id, event_type, payload
            )
            if isinstance(event, dict):
                ctx.bus.publish(
                    ProgressEvent.from_run_event(event, session_id=ctx.session_id)
                )
            if str(step_data.get("step_type") or "").lower() != "stream":
                ctx.ledger.add_step(
                    ctx.task_id,
                    step_type=str(step_data.get("step_type") or ""),
                    content=str(step_data.get("content") or ""),
                )
            if step.step_type == AgentStepType.ANSWER:
                final_answer = step.content or ""
        return final_answer[:500]
    except Exception as exc:
        raise RuntimeError(f"agent_query 执行失败: {exc}") from exc


def _handle_workflow(ctx: JobContext) -> Optional[str]:
    """通过 TaskPlanner 生成并执行多步工作流。"""
    workflow_id = ctx.payload.get("workflow_id", "")
    user_input = ctx.payload.get("user_input", "")
    variables = ctx.payload.get("variables") or {}

    if not workflow_id and not user_input:
        raise ValueError("workflow_id 或 user_input 至少提供一个")

    ctx.step("THOUGHT", f"启动工作流: {workflow_id or user_input[:30]}", progress=5)
    try:
        from app.core.tasks.task_planner import TaskPlanner

        planner = TaskPlanner()
        plan_input = f"{workflow_id}: {user_input}" if workflow_id else user_input
        from app.core.llm.langchain_adapter import KotoLangChainLLM

        llm = KotoLangChainLLM(model_id="deepseek-chat")

        plan = planner.plan_with_llm(
            task_id=ctx.session_id or "",
            user_input=plan_input,
            llm_provider=llm,
        )
        if plan is None or len(plan.steps) == 0:
            return "无法生成工作流计划"

        def _step_executor(step, context):
            prompt = step.executor_prompt or step.description
            if context:
                ctx_text = "\n".join(
                    f"[{k}]: {str(v)[:300]}" for k, v in context.items()
                )
                prompt = f"## 已完成上下文\n{ctx_text}\n\n## 当前任务\n{prompt}"
            resp = llm.generate_content(model="deepseek-chat", contents=prompt)
            return getattr(resp, "text", str(resp))

        outputs = []
        for event in planner.execute_plan(
            plan, _step_executor, cancel_check=ctx.is_cancelled
        ):
            if event.get("event") == "step_done":
                outputs.append(str(event.get("result", ""))[:200])
                ctx.step(
                    "THOUGHT",
                    event.get("step_name", ""),
                    progress=min(90, (ctx.progress or 0) + 10),
                )

        summary = "\n".join(outputs)[:500] or "工作流完成"
        ctx.step("ANSWER", summary, progress=100)
        return summary
    except Exception as exc:
        raise RuntimeError(f"workflow 执行失败: {exc}") from exc


def _handle_auto_catalog(ctx: JobContext) -> Optional[str]:
    """触发文件自动整理任务。"""
    source_dir = ctx.payload.get("source_dir", "")
    ctx.step("THOUGHT", f"自动整理: {source_dir or '默认目录'}", progress=5)
    try:
        from app.core.services.auto_catalog_scheduler import AutoCatalogScheduler

        scheduler = AutoCatalogScheduler(
            settings_file=str(ctx.payload.get("settings_file") or "") or None
        )
        # 如果指定了 source_dir，临时覆盖配置
        if source_dir:
            scheduler.config.setdefault("auto_catalog", {}).setdefault(
                "source_directories", []
            )
            if source_dir not in scheduler.config["auto_catalog"]["source_directories"]:
                scheduler.config["auto_catalog"]["source_directories"].insert(
                    0, source_dir
                )
        result = scheduler.execute_auto_catalog()
        summary = str(result)[:300] if result else "整理完成"
        ctx.step("ANSWER", summary, progress=100)
        return summary
    except Exception as exc:
        raise RuntimeError(f"auto_catalog 失败: {exc}") from exc


def _create_proactive_llm() -> Callable[[str], str]:
    """Create the optional short-form LLM used by proactive background checks."""
    from app.core.llm.model_selection import get_configured_cloud_model
    from app.core.llm.provider_factory import get_llm_provider

    model_id = get_configured_cloud_model(
        task_type="CHAT",
        fallback_model="deepseek-chat",
    )
    provider = get_llm_provider(
        model=model_id,
        allow_local_fallback=False,
    )

    def _llm(prompt: str) -> str:
        response = provider.generate_content(
            prompt=prompt,
            model=model_id,
            stream=False,
            temperature=0.7,
            max_tokens=80,
            timeout=15,
        )
        if isinstance(response, dict):
            text = str(response.get("content") or response.get("text") or "")
        elif isinstance(response, str):
            text = response
        else:
            text = ""

        try:
            from app.core.security.output_validator import OutputValidator

            validated = OutputValidator.validate(text=text)
            if validated.is_blocked:
                logger.warning(
                    "[proactive_tick] llm 输出被拦截: %s",
                    validated.reasons,
                )
                return ""
            return validated.text
        except Exception:
            return text

    return _llm


def _handle_proactive_tick(ctx: JobContext) -> Optional[str]:
    """触发主动交互巡检：检查是否有需要主动推送的消息。"""
    ctx.step("THOUGHT", "开始主动交互巡检", progress=10)
    try:
        # 尝试获取 LLM 函数（非必须）
        llm_fn = None
        try:
            llm_fn = _create_proactive_llm()
        except Exception as _e:
            logger.warning("[JobRunner] proactive_tick LLM 初始化失败: %s", _e)

        from app.core.agent.proactive_agent import get_proactive_agent

        agent = get_proactive_agent()
        agent.tick(llm_fn=llm_fn)
        pending = agent.pending()
        summary = f"巡检完成，待推送消息 {len(pending)} 条"
        ctx.step("ANSWER", summary, progress=100)
        return summary
    except Exception as exc:
        raise RuntimeError(f"proactive_tick 失败: {exc}") from exc
