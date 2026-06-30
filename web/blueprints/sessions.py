# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Session management blueprint.

Routes:
  GET    /api/sessions              — List all chat sessions
  POST   /api/sessions              — Create a new session
  GET    /api/sessions/<name>       — Get session with full history
  DELETE /api/sessions/<name>       — Delete a session
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from flask import Blueprint, Response, jsonify, request

from web.runtime_context import get_brain, get_model_map, get_session_manager

_logger = logging.getLogger("koto.routes.sessions")

sessions_bp = Blueprint("sessions", __name__)


def _get_session_manager():
    return get_session_manager()


def _session_filename(session_name: str) -> str:
    normalized = str(session_name or "").strip().replace("\\", "_").replace("/", "_")
    normalized = normalized.removesuffix(".json") or f"chat_{int(time.time())}"
    return f"{normalized}.json"


def _compact_metadata(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {}
    allowed = {
        "task",
        "task_kind",
        "task_id",
        "run_id",
        "status",
        "task_request",
        "task_mode",
        "task_terminal_status",
        "test_structure",
        "saved_files",
        "source",
    }
    metadata: dict = {}
    for key in allowed:
        value = raw.get(key)
        if value in (None, "", [], {}):
            continue
        metadata[key] = value
    return metadata


def _history_entry_text(entry: object) -> str:
    if not isinstance(entry, dict):
        return ""
    direct = entry.get("content") or entry.get("text")
    if direct:
        return str(direct).strip()
    parts = entry.get("parts")
    if not isinstance(parts, list) or not parts:
        return ""
    first = parts[0]
    if isinstance(first, dict):
        return str(first.get("text") or first.get("content") or "").strip()
    return str(first or "").strip()


def _compact_text(text: str, limit: int = 96) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(limit - 1, 1)].rstrip() + "…"


def _is_file_task_entry(entry: dict) -> bool:
    task_kind = str(entry.get("task_kind") or entry.get("task") or "").strip().lower()
    return task_kind in {"file_task", "file-task"} or bool(entry.get("task_card_snapshot"))


def _task_status_label(status: object) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"done", "completed", "verified", "success", "succeeded"}:
        return "completed"
    if normalized in {"streaming", "running", "pending", "queued", "processing"}:
        return "running"
    if normalized in {"cancelled", "canceled"}:
        return "cancelled"
    if normalized in {"failed", "error", "blocked", "write_blocked", "tool_gap"}:
        return "failed"
    return normalized


def _session_preview(session_filename: str, history: list[object]) -> dict:
    session_id = str(session_filename or "").replace(".json", "")
    entries = [entry for entry in history if isinstance(entry, dict)]
    text_entries = [
        (entry, _history_entry_text(entry))
        for entry in entries
        if _history_entry_text(entry)
    ]
    first_user = next(
        (text for entry, text in text_entries if str(entry.get("role") or "").lower() == "user"),
        "",
    )
    last_entry, last_text = text_entries[-1] if text_entries else ({}, "")
    task_entries = [entry for entry in entries if _is_file_task_entry(entry)]
    latest_task = task_entries[-1] if task_entries else {}
    latest_task_status = _task_status_label(
        latest_task.get("task_terminal_status")
        or latest_task.get("status")
        or ""
    ) if isinstance(latest_task, dict) else ""
    return {
        "id": session_id,
        "title": _compact_text(first_user or session_id, 42),
        "preview": _compact_text(last_text, 110),
        "message_count": len(text_entries),
        "last_role": str(last_entry.get("role") or "") if isinstance(last_entry, dict) else "",
        "updated_at": str(last_entry.get("timestamp") or "") if isinstance(last_entry, dict) else "",
        "task_count": len(task_entries),
        "has_task_flow": bool(task_entries),
        "latest_task_status": latest_task_status,
        "latest_task_id": str(latest_task.get("task_id") or "").strip() if isinstance(latest_task, dict) else "",
        "latest_task_run_id": str(latest_task.get("run_id") or latest_task.get("task_run_id") or "").strip() if isinstance(latest_task, dict) else "",
    }


@sessions_bp.route("/api/sessions", methods=["GET"])
def get_sessions() -> Response:
    """List all unified AI sessions.
    ---
    tags:
      - Sessions
    responses:
      200:
        description: List of session names
        schema:
          type: object
          properties:
            sessions:
              type: array
              items:
                type: string
    """
    session_files = _get_session_manager().list_sessions()
    if str(request.args.get("preview") or "").lower() in {"1", "true", "yes"}:
        manager = _get_session_manager()
        previews = [
            _session_preview(session, manager.load_full(session))
            for session in session_files
        ]
        return jsonify({"sessions": previews})
    return jsonify({"sessions": [s.replace(".json", "") for s in session_files]})


@sessions_bp.route("/api/sessions", methods=["POST"])
def create_session() -> Response:
    """Create a new chat session.
    ---
    tags:
      - Sessions
    parameters:
      - in: body
        name: body
        schema:
          properties:
            name:
              type: string
              description: Optional session name
    responses:
      200:
        description: Session created
        schema:
          type: object
          properties:
            success:
              type: boolean
            session:
              type: string
    """
    data = request.json
    name = data.get("name", f"chat_{int(time.time())}")
    filename = _get_session_manager().create(name)
    return jsonify({"success": True, "session": filename.replace(".json", "")})


@sessions_bp.route("/api/sessions/<session_name>", methods=["GET"])
def get_session(session_name: str) -> Response:
    """Get a specific chat session with full history.
    ---
    tags:
      - Sessions
    parameters:
      - in: path
        name: session_name
        type: string
        required: true
    responses:
      200:
        description: Session data with conversation history
        schema:
          type: object
          properties:
            session:
              type: string
            history:
              type: array
              items:
                type: object
    """
    history = _get_session_manager().load_full(f"{session_name}.json")
    return jsonify({"session": session_name, "history": history})


@sessions_bp.route("/api/sessions/<session_name>/workspace-turn", methods=["POST"])
def append_workspace_turn(session_name: str) -> Response:
    """Append a completed workspace/file-task turn to a normal chat session."""
    body = request.get_json(silent=True) or {}
    user_text = str(body.get("user") or body.get("user_text") or "").strip()
    assistant_text = str(body.get("assistant") or body.get("assistant_text") or "").strip()
    if not user_text or not assistant_text:
        return jsonify({"success": False, "error": "缺少 user 或 assistant 内容"}), 400

    manager = _get_session_manager()
    filename = _session_filename(session_name)
    history = manager.load_full(filename)
    now = datetime.now().isoformat()
    user_entry = {
        "role": "user",
        "parts": [user_text],
        "timestamp": str(body.get("user_timestamp") or now),
        "source": "workspace",
    }
    attachments = body.get("attachments")
    if isinstance(attachments, list) and attachments:
        user_entry["attachments"] = attachments[:20]

    metadata = _compact_metadata(body.get("metadata"))
    task_label = str(
        metadata.get("task")
        or metadata.get("task_type")
        or metadata.get("task_kind")
        or "CHAT"
    ).strip().upper()
    if task_label in {"FILE-TASK", "FILE_TASK", "FILE"}:
        task_label = "FILE_TASK"
    elif task_label in {"WEB", "WEB_SEARCH", "SEARCH"}:
        task_label = "WEB_SEARCH"
    elif task_label not in {"CHAT", "FILE_TASK", "WEB_SEARCH"}:
        task_label = "CHAT"

    assistant_entry = {
        "role": "model",
        "parts": [assistant_text],
        "timestamp": str(body.get("assistant_timestamp") or now),
        "source": "workspace",
        "task": task_label,
    }
    snapshot = body.get("task_card_snapshot")
    if isinstance(snapshot, dict):
        snapshot_html = str(snapshot.get("html") or "").strip()
        if snapshot_html and "wa-task-run" in snapshot_html:
            assistant_entry["task_card_snapshot"] = {
                "html": snapshot_html[:200000],
                "fatal_error_text": str(snapshot.get("fatal_error_text") or "")[:2000],
            }
    assistant_entry.update(metadata)

    history.extend([user_entry, assistant_entry])
    manager.save(filename, history)
    return jsonify({"success": True, "session": filename.replace(".json", "")})


@sessions_bp.route("/api/sessions/<session_name>", methods=["DELETE"])
def delete_session(session_name: str) -> Response:
    """Delete a chat session.
    ---
    tags:
      - Sessions
    parameters:
      - in: path
        name: session_name
        type: string
        required: true
    responses:
      200:
        description: Deletion result
        schema:
          type: object
          properties:
            success:
              type: boolean
    """
    success = _get_session_manager().delete(f"{session_name}.json")
    return jsonify({"success": success})


# ---------------------------------------------------------------------------
# Extended session routes (rename + AI auto-title)
# ---------------------------------------------------------------------------


def _get_brain():
    return get_brain()


def _get_model_map():
    return get_model_map()


@sessions_bp.route("/api/sessions/<session_name>/rename", methods=["PATCH"])
def rename_session(session_name: str) -> Response:
    """Rename a chat session."""
    data = request.json or {}
    new_name = (data.get("new_name") or "").strip()
    if not new_name:
        return jsonify({"success": False, "error": "新名称不能为空"}), 400
    result = _get_session_manager().rename(f"{session_name}.json", new_name)
    if result["success"]:
        new_session = result["new_filename"].replace(".json", "")
        return jsonify({"success": True, "new_session": new_session})
    return jsonify({"success": False, "error": result.get("error", "重命名失败")}), 400


@sessions_bp.route("/api/sessions/<session_name>/auto-title", methods=["POST"])
def auto_title_session(session_name: str) -> Response:
    """Use AI to auto-generate a concise title for a session."""
    full_history = _get_session_manager().load_full(f"{session_name}.json")
    if not full_history:
        return jsonify({"success": False, "error": "会话为空"}), 400

    snippets: list[str] = []
    for entry in full_history[:4]:
        role = entry.get("role", "")
        parts = entry.get("parts", [])
        text = parts[0] if parts else ""
        if role == "user":
            snippets.append(f"用户：{text[:200]}")
        elif role == "model":
            snippets.append(f"助手：{text[:200]}")
        if len(snippets) >= 2:
            break

    if not snippets:
        return jsonify({"success": False, "error": "无内容可生成标题"}), 400

    context = "\n".join(snippets)
    prompt = (
        f"请根据以下对话内容，生成一个简洁的中文标题（8个字以内，不加引号，不加标点，"
        f"直接输出标题文字）：\n\n{context}"
    )
    try:
        title_model = _get_model_map().get("CHAT", "gemini-2.5-flash")
        result = _get_brain().chat([], prompt, model=title_model, auto_model=False)
        raw_title = (result.get("response") or "").strip()
        raw_title = raw_title.strip("\"'「」《》【】\n").split("\n")[0].strip()
        if not raw_title or len(raw_title) > 30:
            return jsonify({"success": False, "error": "生成标题无效"}), 500
        return jsonify({"success": True, "title": raw_title})
    except Exception as e:
        _logger.warning("auto_title_session error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500
