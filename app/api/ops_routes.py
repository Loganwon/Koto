# -*- coding: utf-8 -*-
"""
Koto Ops REST API — /api/ops
======================================
运维与健康监测端点。

端点列表：
  GET  /api/ops/health          — 完整健康快照（含子系统状态）
  GET  /api/ops/readiness       — 就绪探针（Kubernetes / load balancer）
  GET  /api/ops/metrics         — 评估指标（作业统计 / 事件统计）
  GET  /api/ops/incidents       — 最近运维事件（来自 OpsEventBus）
  GET  /api/ops/triggers/status — 调度器触发器状态概览
  GET  /api/ops/remediation     — 当前自愈规则列表
  POST /api/ops/remediation/<name>/toggle  — 启用/禁用某条规则
  POST /api/ops/gc              — 手动触发 GC（调试用）
"""

from __future__ import annotations

import gc
import logging
from datetime import datetime
from typing import Any, Dict

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

ops_bp = Blueprint("ops", __name__, url_prefix="/api/ops")


# ── 健康 / 就绪 ───────────────────────────────────────────────────────────────


@ops_bp.route("/health", methods=["GET"])
def health():
    """
    完整健康快照。
    healthy → HTTP 200; degraded → 200; unhealthy → 503
    """
    try:
        from app.core.ops.health_snapshot import get_health_snapshot

        snap = get_health_snapshot().collect()
        code = 503 if snap["status"] == "unhealthy" else 200
        return jsonify(snap), code
    except Exception as exc:
        logger.error("[ops/health] %s", exc)
        return jsonify({"status": "unhealthy", "error": str(exc)}), 503


@ops_bp.route("/readiness", methods=["GET"])
def readiness():
    """
    简单就绪探针。仅检查应用层是否可以处理请求。
    返回 200 {"ready": true} 或 503。
    """
    try:
        from app.core.ops.health_snapshot import get_health_snapshot

        ready = get_health_snapshot().is_ready()
        if ready:
            return (
                jsonify({"ready": True, "timestamp": datetime.now().isoformat()}),
                200,
            )
        return jsonify({"ready": False, "timestamp": datetime.now().isoformat()}), 503
    except Exception as exc:
        return jsonify({"ready": False, "error": str(exc)}), 503


# ── 指标 ──────────────────────────────────────────────────────────────────────


@ops_bp.route("/metrics", methods=["GET"])
def metrics():
    """聚合运行指标（作业统计 + 事件统计 + 调度器统计）。"""
    data: Dict[str, Any] = {}

    # 作业统计
    try:
        from app.core.tasks.task_ledger import TaskStatus, get_ledger

        ledger = get_ledger()
        running_tasks = ledger.list_tasks(status=TaskStatus.RUNNING, limit=20)
        pending_tasks = ledger.list_tasks(status=TaskStatus.PENDING, limit=20)
        data["jobs"] = {
            "running": ledger.count(status=TaskStatus.RUNNING),
            "pending": ledger.count(status=TaskStatus.PENDING),
            "completed": ledger.count(status=TaskStatus.COMPLETED),
            "failed": ledger.count(status=TaskStatus.FAILED),
            "cancelled": ledger.count(status=TaskStatus.CANCELLED),
            "running_list": [
                {
                    "id": t.task_id[:8],
                    "type": t.task_type or "agent",
                    "input": (t.user_input or "")[:40],
                }
                for t in running_tasks
            ],
            "pending_list": [
                {
                    "id": t.task_id[:8],
                    "type": t.task_type or "agent",
                    "input": (t.user_input or "")[:40],
                }
                for t in pending_tasks
            ],
        }
    except Exception as exc:
        data["jobs"] = {"error": str(exc)}

    # 调度器触发器统计
    try:
        from app.core.jobs.trigger_registry import get_trigger_registry

        triggers = get_trigger_registry().list_all()
        data["triggers"] = {
            "total": len(triggers),
            "enabled": sum(1 for t in triggers if t.enabled),
            "errored": sum(1 for t in triggers if t.last_error),
            "total_fires": sum(t.run_count for t in triggers),
        }
    except Exception as exc:
        data["triggers"] = {"error": str(exc)}

    # 运维事件统计
    try:
        from app.core.ops.ops_event_bus import get_ops_bus

        data["ops_events"] = get_ops_bus().get_stats()
    except Exception as exc:
        data["ops_events"] = {"error": str(exc)}

    data["timestamp"] = datetime.now().isoformat(timespec="milliseconds")
    return jsonify(data), 200


# ── 运维事件（Incidents）─────────────────────────────────────────────────────


@ops_bp.route("/incidents", methods=["GET"])
def incidents():
    """
    返回最近运维事件。
    Query params:
      n        — 条数，默认 100
      severity — 筛选等级 (info|warning|error|critical)
      type     — 筛选事件类型
    """
    n = int(request.args.get("n", 100))
    severity_filter = request.args.get("severity")
    type_filter = request.args.get("type")

    try:
        from app.core.ops.ops_event_bus import get_ops_bus

        events = get_ops_bus().get_recent(n)
        if severity_filter:
            events = [e for e in events if e.severity == severity_filter]
        if type_filter:
            events = [e for e in events if e.event_type == type_filter]
        return (
            jsonify(
                {
                    "count": len(events),
                    "events": [
                        {
                            "event_type": e.event_type,
                            "severity": e.severity,
                            "source": e.source,
                            "timestamp": e.timestamp,
                            "detail": e.detail,
                        }
                        for e in events
                    ],
                }
            ),
            200,
        )
    except Exception as exc:
        logger.error("[ops/incidents] %s", exc)
        return jsonify({"error": str(exc)}), 500


# ── 调度器状态 ────────────────────────────────────────────────────────────────


@ops_bp.route("/triggers/status", methods=["GET"])
def triggers_status():
    """触发器调度器状态概览。"""
    try:
        from app.core.jobs.trigger_registry import get_trigger_registry

        reg = get_trigger_registry()
        triggers = reg.list_all()
        return (
            jsonify(
                {
                    "scheduler_running": reg._running,
                    "trigger_count": len(triggers),
                    "triggers": [
                        {
                            "trigger_id": t.trigger_id,
                            "name": t.name,
                            "type": t.trigger_type,
                            "job_type": t.job_type,
                            "enabled": t.enabled,
                            "run_count": t.run_count,
                            "last_run": t.last_run,
                            "last_error": t.last_error,
                        }
                        for t in triggers
                    ],
                }
            ),
            200,
        )
    except Exception as exc:
        logger.error("[ops/triggers/status] %s", exc)
        return jsonify({"error": str(exc)}), 500


# ── 自愈规则 ──────────────────────────────────────────────────────────────────


@ops_bp.route("/remediation", methods=["GET"])
def list_remediation():
    """列出所有自愈规则及其执行统计。"""
    try:
        from app.core.ops.remediation_policy import get_remediation_policy

        rules = get_remediation_policy().list_rules()
        return jsonify({"rules": rules}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@ops_bp.route("/remediation/<name>/toggle", methods=["POST"])
def toggle_remediation(name: str):
    """
    启用 / 禁用某条自愈规则。
    Body: {"enabled": true|false}
    """
    try:
        from app.core.ops.remediation_policy import get_remediation_policy

        body = request.get_json(silent=True) or {}
        enabled = bool(body.get("enabled", True))
        get_remediation_policy().enable_rule(name, enabled)
        return jsonify({"name": name, "enabled": enabled}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── 手动 GC（调试工具）───────────────────────────────────────────────────────


@ops_bp.route("/gc", methods=["POST"])
def manual_gc():
    """手动触发 Python GC（仅用于调试）。"""
    collected = gc.collect()
    return (
        jsonify(
            {"collected_objects": collected, "timestamp": datetime.now().isoformat()}
        ),
        200,
    )


# ── 全局统计汇总（任务 / 目标 / 作业 / 技能）─────────────────────────────────


@ops_bp.route("/system/stats", methods=["GET"])
def system_stats():
    """
    聚合 TaskLedger / GoalManager / JobRunner / SkillRatings 的全局统计。

    返回结构::

        {
          "tasks":  { "total": N, "by_status": {...}, "by_priority": {...}, "high_priority_pending": [...] },
          "goals":  { "total": N, "active": N, "completed": N, "failed": N, "by_category": {...} },
          "jobs":   { "queue_size": N, "worker_count": N },
          "skills": { "total_rated": N, "avg_rating": F, "top5": [...] },
          "timestamp": "..."
        }
    """
    result: Dict[str, Any] = {}

    # ── 任务统计 ──────────────────────────────────────────────────────────────
    try:
        from app.core.tasks.task_ledger import TaskPriority, TaskStatus, get_ledger

        ledger = get_ledger()

        by_status: Dict[str, int] = {}
        for st in TaskStatus:
            cnt = ledger.count(status=st)
            if cnt:
                by_status[st.value] = cnt
        total_tasks = sum(by_status.values())

        by_priority: Dict[str, int] = {}
        for label, pval in (("low", 0), ("normal", 1), ("high", 2), ("urgent", 3)):
            cnt = ledger.count(priority=pval)
            if cnt:
                by_priority[label] = cnt

        # 最多列出 5 条高/紧急 pending 任务供仪表板展示
        high_prio_pending = []
        try:
            rows = ledger.list_tasks(
                status=TaskStatus.PENDING,
                priority=TaskPriority.HIGH,
                order_by="priority",
                limit=5,
            )
            high_prio_pending = [
                {
                    "task_id": t.task_id[:8],
                    "task_type": t.task_type or "agent",
                    "priority": t.priority,
                    "input": (t.user_input or "")[:60],
                }
                for t in rows
            ]
        except Exception:
            import logging; logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)

        result["tasks"] = {
            "total": total_tasks,
            "by_status": by_status,
            "by_priority": by_priority,
            "high_priority_pending": high_prio_pending,
        }
    except Exception as exc:
        result["tasks"] = {"error": str(exc)}

    # ── 目标统计 ──────────────────────────────────────────────────────────────
    try:
        from app.core.goal.goal_manager import GoalStatus, get_goal_manager

        gm = get_goal_manager()
        total_goals = gm.count()
        by_category: Dict[str, int] = {}
        for goal in gm.list_goals(limit=200):
            by_category[goal.category] = by_category.get(goal.category, 0) + 1

        result["goals"] = {
            "total": total_goals,
            "active": gm.count(status=GoalStatus.ACTIVE),
            "waiting_user": gm.count(status=GoalStatus.WAITING_USER),
            "paused": gm.count(status=GoalStatus.PAUSED),
            "completed": gm.count(status=GoalStatus.COMPLETED),
            "failed": gm.count(status=GoalStatus.FAILED),
            "by_category": by_category,
        }
    except Exception as exc:
        result["goals"] = {"error": str(exc)}

    # ── 作业队列统计 ──────────────────────────────────────────────────────────
    try:
        from app.core.jobs.job_runner import get_job_runner

        runner = get_job_runner()
        result["jobs"] = {
            "queue_size": runner._queue.qsize(),
            "worker_count": runner._max_workers,
        }
    except Exception as exc:
        result["jobs"] = {"error": str(exc)}

    # ── 技能评分统计 ──────────────────────────────────────────────────────────
    try:
        import json
        from pathlib import Path

        ratings_path = (
            Path(__file__).parent.parent.parent / "config" / "skill_ratings.json"
        )
        ratings: Dict[str, Any] = {}
        if ratings_path.exists():
            with open(ratings_path, encoding="utf-8") as f:
                ratings = json.load(f)

        rated_skills = []
        for sid, rdata in ratings.items():
            if isinstance(rdata, dict):
                avg = rdata.get("avg", 0.0)
                n = rdata.get("n", 0)
            else:
                avg = float(rdata)
                n = 1
            rated_skills.append({"skill_id": sid, "avg_rating": round(avg, 2), "n": n})

        rated_skills.sort(key=lambda x: x["avg_rating"], reverse=True)
        all_ratings = [s["avg_rating"] for s in rated_skills if s["n"] > 0]
        overall_avg = round(sum(all_ratings) / len(all_ratings), 2) if all_ratings else 0.0

        result["skills"] = {
            "total_rated": len(rated_skills),
            "avg_rating": overall_avg,
            "top5": rated_skills[:5],
        }
    except Exception as exc:
        result["skills"] = {"error": str(exc)}

    result["timestamp"] = datetime.now().isoformat(timespec="milliseconds")
    return jsonify(result), 200
