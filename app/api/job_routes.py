# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Koto Jobs API Blueprint
========================
挂载前缀: /api/jobs

作业动作端点：
  POST   /api/jobs                          — 提交后台作业
  POST   /api/jobs/<task_id>/retry          — 重排 failed/cancelled 作业

状态查询、取消、恢复和 SSE 统一由 /api/tasks/<task_id> 提供。
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

job_bp = Blueprint("jobs", __name__, url_prefix="/api/jobs")


# ── 工具函数 ──────────────────────────────────────────────────────────────────


def _ok(data=None, **kw):
    body = {"ok": True}
    if data is not None:
        body["data"] = data
    body.update(kw)
    return jsonify(body)


def _err(msg: str, code: int = 400):
    return jsonify({"ok": False, "error": msg}), code


# ============================================================================
# 作业 CRUD
# ============================================================================


@job_bp.post("")
def create_job():
    """
    提交后台作业。

    Body (JSON):
      job_type         string  必填 — 作业类型（agent_query / workflow / auto_catalog）
      payload          object  可选 — 传给处理器的参数（依 job_type 而定）
      session_id       string  可选 — 关联会话 ID
      max_retries      int     可选 — 失败后最多重试次数（默认 0）
      timeout_seconds  float   可选 — 超时秒数（默认 300）
      metadata         object  可选 — 附加元数据

    常见 payload 示例：
      agent_query:  { "query": "帮我写一份周报", "history": [] }
      workflow:     { "workflow_id": "daily_report", "user_input": "Q1 销售汇报", "variables": {} }
      auto_catalog: { "source_dir": "C:/Downloads" }

    Returns:
      { ok: true, data: { task_id, job_type } }  HTTP 202
    """
    body = request.get_json(force=True, silent=True) or {}
    job_type = (body.get("job_type") or "").strip()
    if not job_type:
        return _err("job_type 不能为空")

    from app.core.jobs.job_runner import JobSpec, get_job_runner

    spec = JobSpec(
        job_type=job_type,
        payload=body.get("payload") or {},
        session_id=(body.get("session_id") or "api"),
        max_retries=int(body.get("max_retries", 0)),
        timeout_seconds=float(body.get("timeout_seconds", 300)),
        metadata=body.get("metadata"),
    )

    try:
        task_id = get_job_runner().submit(spec)
    except Exception as exc:
        logger.exception("[job_routes] submit 失败")
        return _err(str(exc), 500)

    return (
        _ok(
            {
                "task_id": task_id,
                "job_type": job_type,
                "task_url": f"/api/tasks/{task_id}",
                "stream_url": f"/api/tasks/{task_id}/stream",
            }
        ),
        202,
    )


@job_bp.post("/<task_id>/retry")
def retry_job(task_id: str):
    """将 failed / cancelled 作业重新入队。"""
    from app.core.jobs.job_runner import get_job_runner

    try:
        get_job_runner().retry(task_id)
    except LookupError as exc:
        return _err(str(exc), 404)
    except ValueError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("[job_routes] retry 失败")
        return _err(str(exc), 500)
    return _ok(
        {
            "task_id": task_id,
            "action": "requeued",
            "task_url": f"/api/tasks/{task_id}",
            "stream_url": f"/api/tasks/{task_id}/stream",
        }
    )
