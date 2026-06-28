# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Background Agent API Blueprint
================================
挂载前缀: /api/bg-agent

类似 Claude Cowork 的自主任务代理接口：
  POST   /api/bg-agent/submit              — 提交目标，AI 规划 + 执行
  GET    /api/bg-agent/<task_id>           — 获取任务状态 + 计划
  GET    /api/bg-agent/<task_id>/stream    — SSE 实时进度流
  POST   /api/bg-agent/<task_id>/approve   — 批准计划（当 human_review=true 时）
  POST   /api/bg-agent/<task_id>/reject    — 拒绝计划（取消任务）
  POST   /api/bg-agent/<task_id>/cancel    — 取消正在执行的任务
  GET    /api/bg-agent/list               — 列出当前 session 的任务
"""

from __future__ import annotations

import logging
import time

from flask import Blueprint, Response, jsonify, request, stream_with_context

logger = logging.getLogger(__name__)

bg_agent_bp = Blueprint("bg_agent", __name__, url_prefix="/api/bg-agent")

# ── 单例 BackgroundAgent（按 session_id 分隔）────────────────────────────────
_agents: dict = {}
_agents_lock = __import__("threading").Lock()


def _get_agent(session_id: str = "default"):
    """获取或创建指定 session 的 BackgroundAgent 实例。"""
    with _agents_lock:
        if session_id not in _agents:
            from app.core.agent.background_agent import BackgroundAgent
            _agents[session_id] = BackgroundAgent(session_id=session_id)
        return _agents[session_id]


def _ok(data=None, **kw):
    body = {"ok": True}
    if data is not None:
        body["data"] = data
    body.update(kw)
    return jsonify(body)


def _err(msg: str, code: int = 400):
    return jsonify({"ok": False, "error": msg}), code


def _serialize_status(status) -> dict:
    """将 BackgroundTaskStatus dataclass 序列化为 JSON-safe dict。"""
    plan_data = None
    if status.plan:
        plan_data = {
            "plan_id": status.plan.plan_id,
            "goal": status.plan.goal,
            "reasoning": status.plan.reasoning,
            "estimated_minutes": status.plan.estimated_minutes,
            "steps": [
                {
                    "step_id": s.step_id,
                    "title": s.title,
                    "description": s.description,
                    "tool_hint": s.tool_hint,
                    "depends_on": s.depends_on,
                    "can_parallel": s.can_parallel,
                    "status": s.status.value if hasattr(s.status, "value") else s.status,
                    "result": s.result,
                    "error": s.error,
                    "started_at": s.started_at,
                    "finished_at": s.finished_at,
                }
                for s in status.plan.steps
            ],
        }
    artifact_result = getattr(status, "artifact_result", None)
    if artifact_result is None:
        try:
            from app.core.artifacts import build_background_artifact_result

            artifact_result = build_background_artifact_result(
                task_id=status.task_id,
                goal=status.goal,
                phase=status.phase,
                final_report=status.final_report,
                error=status.error,
                steps=status.plan.steps if status.plan else None,
            )
        except Exception:
            artifact_result = None
    return {
        "task_id": status.task_id,
        "goal": status.goal,
        "session_id": status.session_id,
        "phase": status.phase,
        "plan": plan_data,
        "steps_total": status.steps_total,
        "steps_done": status.steps_done,
        "current_step": status.current_step,
        "final_report": status.final_report,
        "error": status.error,
        "submitted_at": status.submitted_at,
        "updated_at": status.updated_at,
        "artifact_result": (
            artifact_result.to_dict()
            if hasattr(artifact_result, "to_dict")
            else artifact_result
        ),
    }


# ============================================================================
# 提交任务
# ============================================================================


@bg_agent_bp.get("")
@bg_agent_bp.get("/")
def bg_agent_index():
    """Return a compact status document for module root probes."""
    return _ok(
        {
            "service": "background-agent",
            "routes": {
                "submit": "/api/bg-agent/submit",
                "list": "/api/bg-agent/list",
                "task": "/api/bg-agent/<task_id>",
                "stream": "/api/bg-agent/<task_id>/stream",
            },
        },
        sessions=len(_agents),
    )


@bg_agent_bp.post("/submit")
def submit_task():
    """
    提交后台自主任务。

    Body (JSON):
      goal                  string  必填 — 任务目标描述
      context               object  可选 — 额外上下文（文件路径、工作区等）
      human_review          bool    可选 — 生成计划后等待用户审批（默认 true）
      session_id            string  可选 — 会话 ID（默认 "default"）

    Returns:
      { ok: true, data: { task_id, phase } }  HTTP 202
    """
    body = request.get_json(force=True, silent=True) or {}
    goal = (body.get("goal") or "").strip()
    if not goal:
        return _err("goal 不能为空")

    session_id = (body.get("session_id") or "default").strip()
    human_review = bool(body.get("human_review", True))
    context = body.get("context") or {}

    agent = _get_agent(session_id)
    try:
        task_id = agent.submit(
            goal=goal,
            context=context,
            human_review_before_execute=human_review,
        )
    except Exception as exc:
        logger.exception("[bg_agent_routes] submit 失败")
        return _err(str(exc), 500)

    return _ok({"task_id": task_id, "phase": "planning"}), 202


# ============================================================================
# 查询任务状态
# ============================================================================


@bg_agent_bp.get("/<task_id>")
def get_task(task_id: str):
    """获取任务状态、计划和执行进度。"""
    # 遍历所有 agent 实例查找任务
    with _agents_lock:
        agents_snapshot = dict(_agents)

    for agent in agents_snapshot.values():
        status = agent.get_status(task_id)
        if status:
            return _ok(_serialize_status(status))

    return _err("任务不存在", 404)


@bg_agent_bp.get("/<task_id>/artifact")
def get_task_artifact(task_id: str):
    """获取任务的标准化 ArtifactResult。"""
    with _agents_lock:
        agents_snapshot = dict(_agents)

    for agent in agents_snapshot.values():
        status = agent.get_status(task_id)
        if status:
            serialized = _serialize_status(status)
            return _ok(serialized.get("artifact_result") or {})

    return _err("任务不存在", 404)


# ============================================================================
# SSE 实时进度流
# ============================================================================


@bg_agent_bp.get("/<task_id>/stream")
def stream_task(task_id: str):
    """
    SSE 实时进度流。
    事件格式: data: {"event_type": "...", "message": "...", "task_id": "..."}
    """
    try:
        from app.core.tasks.progress_bus import get_progress_bus
        bus = get_progress_bus()
    except Exception:
        # ProgressBus 不可用时，返回空流
        def _empty():
            yield "data: {}\n\n"
        return Response(stream_with_context(_empty()), mimetype="text/event-stream")

    def gen():
        yield from bus.stream_events(task_id, timeout=600, replay=True)

    return Response(
        stream_with_context(gen()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================================
# 审批 / 拒绝 / 取消
# ============================================================================


@bg_agent_bp.post("/<task_id>/approve")
def approve_task(task_id: str):
    """批准执行计划，任务继续执行。"""
    with _agents_lock:
        agents_snapshot = dict(_agents)

    for agent in agents_snapshot.values():
        if agent.get_status(task_id):
            try:
                agent.approve_plan(task_id)
            except KeyError:
                return _err("任务不存在", 404)
            except Exception as exc:
                return _err(str(exc), 500)
            return _ok({"task_id": task_id, "action": "approved"})

    return _err("任务不存在", 404)


@bg_agent_bp.post("/<task_id>/reject")
def reject_task(task_id: str):
    """拒绝计划并取消任务。"""
    body = request.get_json(force=True, silent=True) or {}
    feedback = (body.get("feedback") or "").strip()

    with _agents_lock:
        agents_snapshot = dict(_agents)

    for agent in agents_snapshot.values():
        if agent.get_status(task_id):
            try:
                agent.reject_plan(task_id, feedback)
            except Exception as exc:
                return _err(str(exc), 500)
            return _ok({"task_id": task_id, "action": "rejected"})

    return _err("任务不存在", 404)


@bg_agent_bp.post("/<task_id>/cancel")
def cancel_task(task_id: str):
    """取消正在执行的任务。"""
    with _agents_lock:
        agents_snapshot = dict(_agents)

    for agent in agents_snapshot.values():
        if agent.get_status(task_id):
            try:
                agent.cancel(task_id)
            except Exception as exc:
                return _err(str(exc), 500)
            return _ok({"task_id": task_id, "action": "cancelled"})

    return _err("任务不存在", 404)


# ============================================================================
# 列出任务
# ============================================================================


@bg_agent_bp.get("/list")
def list_tasks():
    """
    列出当前所有 session 的 BackgroundAgent 任务。

    Query params:
      session_id  — 过滤指定会话（可选）
      limit       — 最多返回条数（默认 20）
    """
    session_filter = request.args.get("session_id")
    limit = min(int(request.args.get("limit", 20)), 100)

    results = []
    with _agents_lock:
        agents_snapshot = dict(_agents)

    for sid, agent in agents_snapshot.items():
        if session_filter and sid != session_filter:
            continue
        for task_id, status in list(agent._tasks.items()):
            results.append(_serialize_status(status))

    # 按提交时间倒序
    results.sort(key=lambda x: x.get("submitted_at", 0), reverse=True)
    return _ok(data=results[:limit], total=len(results))
