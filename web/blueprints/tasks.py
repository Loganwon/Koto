# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Background task status API blueprint.

Routes:
  GET  /api/tasks              — List recent tasks
  GET  /api/tasks/<task_id>    — Get single task status
  POST /api/tasks/<task_id>/cancel — Cancel a running task
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from web.task_queue import task_queue

tasks_bp = Blueprint("tasks", __name__)


@tasks_bp.route("/api/tasks", methods=["GET"])
def list_tasks():
    status = __import__("flask").request.args.get("status", "")
    items = task_queue.get_all(status=status or None)
    return jsonify({"tasks": items, "count": len(items)})


@tasks_bp.route("/api/tasks/<task_id>", methods=["GET"])
def get_task(task_id: str):
    task = task_queue.get(task_id)
    if task is None:
        return jsonify({"error": "Task not found", "status": 404}), 404
    return jsonify(task.to_dict())


@tasks_bp.route("/api/tasks/<task_id>/cancel", methods=["POST"])
def cancel_task(task_id: str):
    cancelled = task_queue.cancel(task_id)
    if cancelled:
        return jsonify({"ok": True, "task_id": task_id, "message": "取消请求已提交"})
    task = task_queue.get(task_id)
    if task is None:
        return jsonify({"error": "Task not found", "status": 404}), 404
    return jsonify({
        "ok": False,
        "task_id": task_id,
        "message": f"无法取消：任务状态为 {task.status}",
    }), 409
