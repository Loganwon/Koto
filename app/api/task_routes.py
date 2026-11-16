# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Koto Task Management API Routes
=================================
提供对 TaskLedger 和 ProgressBus 的 REST / SSE 接口。

挂载到父 Flask 应用后，所有路由前缀为 /api/tasks

端点总览:
  GET    /api/tasks                        — 查询任务列表（支持筛选）
  GET    /api/tasks/stats                  — 汇总统计
  GET    /api/tasks/<task_id>              — 查询单个任务（含步骤）
  POST   /api/tasks/<task_id>/cancel       — 请求取消任务
  POST   /api/tasks/<task_id>/interrupt    — 请求暂停（Human-in-loop）
  POST   /api/tasks/<task_id>/resume       — 恢复暂停的任务
  GET    /api/tasks/<task_id>/stream       — SSE 实时进度流
  DELETE /api/tasks/<task_id>              — 删除任务记录
  POST   /api/tasks/purge                  — 清理旧任务（管理接口）
"""

from __future__ import annotations

import json
import logging
import time

from flask import Blueprint, Response, jsonify, request, stream_with_context

from app.core.tasks.progress_bus import get_progress_bus
from app.core.tasks.task_ledger import TaskStatus, get_ledger

logger = logging.getLogger(__name__)

task_bp = Blueprint("tasks", __name__)


# ── 工具函数 ──────────────────────────────────────────────────────────────────


def _ok(data=None, **kwargs):
    body = {"ok": True}
    if data is not None:
        body["data"] = data
    body.update(kwargs)
    return jsonify(body)


def _err(message: str, code: int = 400):
    return jsonify({"ok": False, "error": message}), code


def _safe_metadata_dict(raw_metadata) -> dict:
    if isinstance(raw_metadata, dict):
        return raw_metadata
    try:
        parsed = json.loads(str(raw_metadata or "{}"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _artifact_result_from_task_metadata(metadata: dict) -> dict:
    for event_key in ("terminal_event", "waiting_event", "last_event"):
        event = metadata.get(event_key)
        if not isinstance(event, dict):
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        artifact_result = payload.get("artifact_result")
        if isinstance(artifact_result, dict) and artifact_result:
            return artifact_result
    return {}


def _serialize_task(task, *, include_steps: bool = False) -> dict:
    data = task.to_dict()
    metadata = _safe_metadata_dict(data.get("metadata"))
    artifact_result = _artifact_result_from_task_metadata(metadata)
    if artifact_result:
        data["artifact_result"] = artifact_result
    if include_steps:
        data["steps"] = [s.to_dict() for s in getattr(task, "steps", [])]
    return data


# ============================================================================
# 路由
# ============================================================================


@task_bp.get("")
def list_tasks():
    """
    查询任务列表。

    Query params:
      session_id  — 按会话过滤
      status      — 按状态过滤（pending/running/completed/failed/cancelled/waiting）
      source      — 按来源过滤（agent/scheduler/…）
      date_from   — 起始日期前缀，如 2026-03-04
      priority    — 按优先级过滤（0=低/1=正常/2=高/3=紧急）
      order_by    — 排序字段（created_at 默认 | priority 按优先级降序）
      limit       — 每页数量（默认 50，最大 200）
      offset      — 分页偏移
    """
    ledger = get_ledger()
    session_id = request.args.get("session_id") or None
    status_raw = request.args.get("status") or None
    source = request.args.get("source") or None
    date_from = request.args.get("date_from") or None
    priority_raw = request.args.get("priority") or None
    order_by = request.args.get("order_by", "created_at")
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    status = None
    if status_raw:
        try:
            status = TaskStatus(status_raw)
        except ValueError:
            return _err(f"无效状态值: {status_raw}")

    priority = None
    if priority_raw is not None:
        try:
            priority = int(priority_raw)
        except ValueError:
            return _err(f"无效优先级值: {priority_raw}")

    if order_by not in ("created_at", "priority"):
        order_by = "created_at"

    tasks = ledger.list_tasks(
        session_id=session_id,
        status=status,
        source=source,
        date_from=date_from,
        priority=priority,
        order_by=order_by,
        limit=limit,
        offset=offset,
    )
    total = ledger.count(session_id=session_id, status=status, date_from=date_from)
    return _ok(
        data=[_serialize_task(t) for t in tasks],
        total=total,
        limit=limit,
        offset=offset,
    )


@task_bp.get("/stats")
def get_stats():
    """
    返回任务执行统计信息。

    Query params:
      date_from — 统计起始日期前缀
    """
    ledger = get_ledger()
    date_from = request.args.get("date_from") or None
    stats = ledger.get_stats(date_from=date_from)
    return _ok(data=stats)


@task_bp.get("/<task_id>")
def get_task(task_id: str):
    """查询单个任务详情，包含步骤明细。"""
    ledger = get_ledger()
    task = ledger.get(task_id, include_steps=True)
    if not task:
        return _err("任务不存在", 404)
    data = _serialize_task(task, include_steps=True)
    latest = ledger.latest_run_event(task_id)
    if latest:
        data["last_event"] = latest
        data["run_id"] = latest.get("run_id")
        data["last_event_seq"] = latest.get("seq")
    checkpoint = ledger.get_kernel_checkpoint(task_id)
    if checkpoint:
        data["recovery"] = {
            "run_id": checkpoint["run_id"],
            "phase": checkpoint["phase"],
            "resumable": checkpoint["resumable"],
            "active": bool(
                task.status
                not in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
                and checkpoint.get("owner_id")
                and checkpoint.get("lease_until", 0) > time.time()
            ),
            "revision": checkpoint["revision"],
        }
    return _ok(data=data)


@task_bp.get("/<task_id>/events")
def get_task_events(task_id: str):
    """Read durable facts with the same cursor used by the live SSE stream."""
    ledger = get_ledger()
    if ledger.get(task_id) is None:
        return _err("任务不存在", 404)
    try:
        after_seq = max(0, int(request.args.get("after_seq", 0)))
        limit = max(1, min(10000, int(request.args.get("limit", 1000))))
    except (TypeError, ValueError):
        return _err("after_seq 和 limit 必须是整数")
    return _ok(
        data=ledger.list_run_events(
            task_id,
            request.args.get("run_id") or None,
            after_seq=after_seq,
            limit=limit,
        )
    )


@task_bp.post("/<task_id>/cancel")
def cancel_task(task_id: str):
    """
    请求取消任务。

    Agent 执行线程会在下一次步骤开始前检查取消标志并中止。
    """
    ledger = get_ledger()
    body = request.get_json(silent=True) or {}
    task = ledger.get(task_id)
    if not task:
        run_id = str(body.get("run_id") or "").strip()
        if not run_id:
            return _err("任务不存在", 404)
        try:
            ledger.bind_run_identity(task_id, run_id, str(body.get("session_id") or ""))
        except ValueError as exc:
            return _err(str(exc), 409)
        # Preserve a stop that races with initial stream registration.  It is
        # a request, not evidence that a potentially concurrent write stopped.
        ledger.cancel_task(task_id)
        if run_id:
            ledger.cancel_task(run_id)
        return (
            _ok(
                data={
                    "task_id": task_id,
                    "run_id": run_id,
                    "cancel_requested": True,
                    "status": "pending",
                },
                message="取消请求已登记，等待执行器确认",
            ),
            202,
        )
    if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
        return _ok(
            data={
                "status": task.status.value,
                "cancel_requested": task.cancel_requested,
            },
            message="任务已结束",
        )
    metadata = _safe_metadata_dict(task.metadata)
    run_id = str(body.get("run_id") or metadata.get("run_id") or "").strip()
    if (
        body.get("run_id")
        and metadata.get("run_id")
        and str(body["run_id"]) != str(metadata["run_id"])
    ):
        return _err("运行标识已更新，未取消新的任务执行", 409)
    ledger.cancel_task(task_id)
    if run_id:
        ledger.cancel_task(run_id)
    return _ok(
        data={
            "task_id": task_id,
            "run_id": run_id,
            "cancel_requested": True,
            "status": task.status.value,
        },
        message="正在停止，等待当前操作安全结束",
    )


@task_bp.post("/<task_id>/interrupt")
def interrupt_task(task_id: str):
    """
    请求暂停任务，进入 Human-in-Loop 状态。

    Body JSON (可选):
      {"reason": "需要确认操作"}
    """
    ledger = get_ledger()
    task = ledger.get(task_id)
    if not task:
        return _err("任务不存在", 404)
    if task.status not in (TaskStatus.RUNNING, TaskStatus.PENDING):
        return _err(f"任务当前状态为 {task.status.value}，无法打断")

    body = request.get_json(silent=True) or {}
    reason = body.get("reason", "human_in_loop")
    ledger.request_interrupt(task_id)
    ledger.mark_waiting(task_id, reason=reason)

    # 发布暂停事件到进度总线
    try:
        bus = get_progress_bus()
        from app.core.tasks.progress_bus import ProgressEvent

        bus.publish(
            ProgressEvent(
                task_id=task_id,
                session_id=task.session_id,
                event_type="interrupt",
                status=TaskStatus.WAITING.value,
                message=f"任务已暂停等待确认：{reason}",
                progress=0,
            )
        )
    except Exception as _pe:
        import logging as _logging

        _logging.getLogger(__name__).debug(
            "[TaskAPI] 进度事件发布失败 (task_id=%s): %s", task_id, _pe
        )

    return _ok(message="任务已进入等待确认状态")


@task_bp.post("/<task_id>/resume")
def resume_task(task_id: str):
    """
    恢复被暂停的任务。

    Body JSON (可选):
      {"approved": true, "comment": "确认操作"}
    """
    ledger = get_ledger()
    task = ledger.get(task_id)
    if not task:
        return _err("任务不存在", 404)
    checkpoint = ledger.get_kernel_checkpoint(task_id)
    if checkpoint and task.status not in {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }:
        body = request.get_json(silent=True) or {}
        if body.get("approved") is False:
            ledger.cancel_task(task_id)
            ledger.cancel_task(checkpoint["run_id"])
            return (
                _ok(
                    data={"cancel_requested": True},
                    message="已记录停止请求，未恢复执行",
                ),
                202,
            )
        if not checkpoint["resumable"]:
            return _err(
                "上次写操作的结果尚未核实，不能自动重放；请先检查实际文件状态", 409
            )
        if (task.interrupt_requested or task.status == TaskStatus.WAITING) and body.get(
            "approved"
        ) is not True:
            return _err("任务正在等待明确确认，尚未恢复", 409)
        try:
            from app.core.jobs.job_runner import get_job_runner

            get_job_runner().resume_kernel(
                task_id,
                run_id=checkpoint["run_id"],
                approved=body.get("approved") is True,
            )
        except (LookupError, ValueError) as exc:
            return _err(str(exc), 409)
        return (
            _ok(
                data={
                    "task_id": task_id,
                    "run_id": checkpoint["run_id"],
                    "status": "pending",
                },
                message="已从持久检查点安排继续执行",
            ),
            202,
        )
    if task.status != TaskStatus.WAITING:
        return _err(f"任务当前状态为 {task.status.value}，不处于等待状态")

    body = request.get_json(silent=True) or {}
    approved = body.get("approved")

    if approved is None:
        return _err("请明确提供 approved，任务仍在等待确认", 409)

    if approved is True:
        ledger.resume_task(task_id)
        try:
            bus = get_progress_bus()
            from app.core.tasks.progress_bus import ProgressEvent

            bus.publish(
                ProgressEvent(
                    task_id=task_id,
                    session_id=task.session_id,
                    event_type="resume",
                    status=TaskStatus.RUNNING.value,
                    message="用户已确认，任务恢复执行",
                    progress=0,
                )
            )
        except Exception as _pe:
            import logging as _logging

            _logging.getLogger(__name__).debug(
                "[TaskAPI] resume 事件发布失败 (task_id=%s): %s", task_id, _pe
            )
        return _ok(message="任务已恢复执行")
    else:
        ledger.cancel_task(task_id)
        ledger.mark_cancelled(task_id)
        return _ok(message="用户拒绝确认，任务已取消")


@task_bp.get("/<task_id>/stream")
def stream_progress(task_id: str):
    """
    SSE 实时进度流。

    客户端示例（JavaScript）::

        const es = new EventSource(`/api/tasks/${taskId}/stream`);
        es.addEventListener('progress', e => console.log(JSON.parse(e.data)));
        es.addEventListener('timeout',  () => es.close());

    Query params:
      timeout  — 最长监听秒数（默认 300，0=永不超时）
      replay   — 是否回放历史事件（默认 true）
    """
    ledger = get_ledger()
    task = ledger.get(task_id)
    if not task:
        return _err("任务不存在", 404)

    bus = get_progress_bus()
    try:
        timeout = max(0.0, min(float(request.args.get("timeout", 300)), 3600.0))
        after_seq = max(0, int(request.args.get("after_seq", 0)))
    except (TypeError, ValueError):
        return _err("timeout 和 after_seq 必须是有效数字")
    replay = request.args.get("replay", "true").lower() != "false"
    run_id = request.args.get("run_id") or None
    last_id = str(request.headers.get("Last-Event-ID") or "").strip()
    if last_id:
        try:
            last_run, last_seq = last_id.rsplit(":", 1)
            if run_id and run_id != last_run:
                return _err("Last-Event-ID 与 run_id 不匹配")
            run_id = run_id or last_run
            after_seq = max(after_seq, int(last_seq))
        except (ValueError, TypeError):
            return _err("Last-Event-ID 无效")
    latest = ledger.latest_run_event(task_id, run_id)

    def generate():
        if latest or run_id or after_seq:
            yield from bus.stream_events(
                task_id,
                timeout=timeout,
                replay=replay,
                after_seq=after_seq,
                run_id=run_id,
                event_loader=ledger.list_run_events,
                session_id=task.session_id,
            )
        else:
            yield from bus.stream_events(task_id, timeout=timeout, replay=replay)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@task_bp.delete("/<task_id>")
def delete_task(task_id: str):
    """
    软删除任务（标记为 cancelled）并清理进度总线历史。
    实际数据库行保留，可通过 purge 接口清理。
    """
    ledger = get_ledger()
    task = ledger.get(task_id)
    if not task:
        return _err("任务不存在", 404)
    if task.status == TaskStatus.RUNNING:
        return _err("任务正在执行中，请先取消再删除")
    ledger.cancel_task(task_id)
    ledger.mark_cancelled(task_id)
    get_progress_bus().cleanup(task_id, delay=0)
    return _ok(message="任务已删除")


@task_bp.post("/purge")
def purge_tasks():
    """
    清理旧任务（管理接口）。

    Body JSON (可选):
      {"keep_days": 30}   — 保留最近 N 天的任务（默认 30）
    """
    body = request.get_json(silent=True) or {}
    keep_days = int(body.get("keep_days", 30))
    ledger = get_ledger()
    deleted = ledger.purge_old(keep_days=keep_days)
    return _ok(data={"deleted": deleted}, message=f"已清理 {deleted} 条历史任务")


@task_bp.post("/<task_id>/priority")
def set_task_priority(task_id: str):
    """
    设置任务优先级。

    Body JSON:
      {"priority": 2}   — 0=低 / 1=正常 / 2=高 / 3=紧急
    """
    ledger = get_ledger()
    task = ledger.get(task_id)
    if not task:
        return _err("任务不存在", 404)
    body = request.get_json(silent=True) or {}
    try:
        priority = int(body["priority"])
        if priority not in (0, 1, 2, 3):
            raise ValueError
    except (KeyError, ValueError, TypeError):
        return _err("请提供合法的 priority 字段（0/1/2/3）")
    ledger.set_priority(task_id, priority)
    label = {0: "低", 1: "正常", 2: "高", 3: "紧急"}.get(priority, str(priority))
    return _ok(message=f"任务优先级已设置为「{label}」")
