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
import re
import threading
import time
from datetime import datetime
from typing import Any

from flask import Blueprint, Response, jsonify, request

from web.runtime_context import get_brain, get_model_map, get_session_manager

_logger = logging.getLogger("koto.routes.sessions")

sessions_bp = Blueprint("sessions", __name__)
_workspace_turn_lock = threading.RLock()
_SESSION_HISTORY_SCHEMA_VERSION = 2
_NUMBERED_TASK_TITLE_RE = re.compile(r"^(?:任务|对话|历史)?\s*#?\s*[\d一二三四五六七八九十]+$", re.IGNORECASE)
_TITLE_PREFIX_RE = re.compile(r"^(?:标题|任务标题|历史标题)\s*[:：]\s*", re.IGNORECASE)


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
        "task_title",
        "title",
        "task_kind",
        "task_id",
        "turn_id",
        "run_id",
        "status",
        "task_request",
        "task_mode",
        "task_request_kind",
        "task_family",
        "task_operation_kind",
        "task_execution_mode",
        "task_selected_recipe",
        "task_output_mode",
        "task_target_file_type",
        "task_terminal_status",
        "test_structure",
        "task_visible_trace",
        "completed_task",
        "partial",
        "skip_model_context",
        "schema_version",
        "history_schema_version",
        "task_context",
        "task_contract",
        "task_request_payload",
        "pending_task_label",
        "pending_task_payload",
        "task_file_changes",
        "model_context_text",
        "memory_summary",
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


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _compact_json_value(value: object, depth: int = 0) -> object:
    if depth > 4:
        return ""
    if value in (None, "", [], {}):
        return value
    if isinstance(value, str):
        return _compact_text(value, 1200 if depth == 0 else 500)
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, list):
        return [_compact_json_value(item, depth + 1) for item in value[:20]]
    if isinstance(value, dict):
        compacted: dict[str, Any] = {}
        for key, item in list(value.items())[:40]:
            if item in (None, "", [], {}):
                continue
            compacted[str(key)] = _compact_json_value(item, depth + 1)
        return compacted
    return _compact_text(str(value), 500)


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


def _normalize_history_entry(entry: object) -> object:
    if not isinstance(entry, dict):
        return entry
    normalized = dict(entry)
    normalized["schema_version"] = int(normalized.get("schema_version") or _SESSION_HISTORY_SCHEMA_VERSION)
    text = _history_entry_text(normalized)
    if text and not isinstance(normalized.get("parts"), list):
        normalized["parts"] = [text]
    task_kind = str(normalized.get("task_kind") or normalized.get("task") or "").strip().lower()
    if normalized.get("task_card_snapshot") and not task_kind:
        normalized["task_kind"] = "file_task"
    if normalized.get("test_structure") and not normalized.get("task_terminal_status"):
        structure = normalized.get("test_structure")
        if isinstance(structure, dict) and structure.get("terminal_status"):
            normalized["task_terminal_status"] = structure.get("terminal_status")
    if _truthy(normalized.get("partial")):
        normalized["skip_model_context"] = True
    return normalized


def _normalize_history(history: list[object]) -> list[object]:
    return [_normalize_history_entry(entry) for entry in history if isinstance(entry, dict)]


def _compact_text(text: str, limit: int = 96) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(limit - 1, 1)].rstrip() + "…"


def _clean_generated_title(raw: object, limit: int = 24) -> str:
    title = str(raw or "").strip()
    if not title:
        return ""
    title = title.splitlines()[0].strip()
    title = _TITLE_PREFIX_RE.sub("", title)
    title = title.strip(" \"'「」《》【】[]()（）{}<>.,，。!！?？、;；")
    title = " ".join(title.split())
    if not title or _NUMBERED_TASK_TITLE_RE.match(title):
        return ""
    return _compact_text(title, limit)


def _attachment_names(attachments: object) -> list[str]:
    if not isinstance(attachments, list):
        return []
    names: list[str] = []
    for item in attachments[:5]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("path") or "").strip()
        if name:
            names.append(name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1])
    return names


def _fallback_task_title(user_text: str, metadata: dict, attachments: object) -> str:
    request = str(metadata.get("task_request") or user_text or "").strip()
    if request:
        return _clean_generated_title(request, 24) or "任务记录"
    names = _attachment_names(attachments)
    if names:
        return _clean_generated_title(f"{names[0]} 处理", 24) or "文件任务记录"
    return "任务记录"


def _raw_title_from_model_result(result: object) -> str:
    if isinstance(result, dict):
        for key in ("response", "content", "text", "title"):
            value = result.get(key)
            if value:
                return str(value)
    return str(result or "")


def _generate_workspace_task_title(user_text: str, assistant_text: str, metadata: dict, attachments: object) -> str:
    explicit = _clean_generated_title(metadata.get("task_title") or metadata.get("title") or "", 24)
    if explicit:
        return explicit

    fallback = _fallback_task_title(user_text, metadata, attachments)
    names = ", ".join(_attachment_names(attachments))
    prompt = (
        "请为下面这次任务历史生成一个和内容相关的中文标题。\n"
        "要求：6到14个字；不要编号；不要使用“任务1”“对话2”这类名字；"
        "不要加引号或标点；只输出标题文字。\n\n"
        f"用户请求：{_compact_text(user_text, 300)}\n"
        f"相关文件：{_compact_text(names, 160)}\n"
        f"任务类型：{_compact_text(str(metadata.get('task_kind') or metadata.get('task') or ''), 80)}\n"
        f"执行结果：{_compact_text(assistant_text, 300)}"
    )
    try:
        title_model = _get_model_map().get("CHAT", "gemini-2.5-flash")
        result = _get_brain().chat([], prompt, model=title_model, auto_model=False)
        generated = _clean_generated_title(_raw_title_from_model_result(result), 24)
        if generated:
            return generated
    except Exception as exc:
        _logger.debug("workspace task title generation skipped: %s", exc)
    return fallback


def _task_entry_title(entry: object) -> str:
    if not isinstance(entry, dict):
        return ""
    return _clean_generated_title(
        entry.get("task_title")
        or entry.get("title")
        or entry.get("task_request")
        or "",
        42,
    )


def _task_context_summary(metadata: dict, attachments: object) -> str:
    parts: list[str] = []
    names = _attachment_names(attachments)
    if names:
        parts.append("文件: " + "、".join(names[:5]))
    ctx = metadata.get("task_context")
    if isinstance(ctx, dict):
        selected = ctx.get("selection") or ctx.get("selected_text") or ctx.get("selection_preview")
        if selected:
            parts.append("选区: " + _compact_text(str(selected), 120))
        source = ctx.get("selection_source") or ctx.get("source") or ctx.get("rangeA1") or ctx.get("range")
        if source:
            parts.append("来源: " + _compact_text(str(source), 80))
    changes = metadata.get("task_file_changes")
    if isinstance(changes, list) and changes:
        changed = []
        for item in changes[:5]:
            if isinstance(item, dict):
                changed.append(str(item.get("path") or item.get("name") or "").strip())
        changed = [item for item in changed if item]
        if changed:
            parts.append("变更: " + "、".join(changed))
    return "；".join(parts)


def _build_task_memory_summary(
    *,
    title: str,
    user_text: str,
    assistant_text: str,
    metadata: dict,
    attachments: object,
) -> str:
    lines = [
        f"任务标题: {title or _fallback_task_title(user_text, metadata, attachments)}",
        f"用户请求: {_compact_text(user_text, 220)}",
    ]
    context = _task_context_summary(metadata, attachments)
    if context:
        lines.append(f"上下文: {context}")
    status = str(metadata.get("task_terminal_status") or metadata.get("status") or "").strip()
    if status:
        lines.append(f"状态: {status}")
    if assistant_text:
        lines.append(f"结果: {_compact_text(assistant_text, 320)}")
    return "\n".join(line for line in lines if line.strip())


def _start_task_memory_reflection(
    *,
    session_name: str,
    user_text: str,
    assistant_text: str,
    metadata: dict,
) -> None:
    if _truthy(metadata.get("partial")) or _truthy(metadata.get("skip_model_context")):
        return
    if not user_text or not assistant_text:
        return
    try:
        from web.memory_runtime import _start_memory_extraction

        history = [
            {"role": "user", "parts": [user_text]},
            {"role": "model", "parts": [assistant_text]},
        ]
        _start_memory_extraction(
            user_text,
            assistant_text,
            history=history,
            task_type=str(metadata.get("task_kind") or metadata.get("task") or "FILE_TASK"),
            session_name=session_name,
        )
    except Exception as exc:
        _logger.debug("workspace task memory reflection skipped: %s", exc)


def _is_file_task_entry(entry: dict) -> bool:
    task_kind = str(entry.get("task_kind") or entry.get("task") or "").strip().lower()
    return task_kind in {"file_task", "file-task"} or bool(entry.get("task_card_snapshot"))


def _history_entry_blob(entry: object) -> str:
    if not isinstance(entry, dict):
        return ""
    parts = [
        str(entry.get("id") or ""),
        str(entry.get("turn_id") or ""),
        str(entry.get("run_id") or entry.get("task_run_id") or ""),
        str(entry.get("task_id") or ""),
        _history_entry_text(entry),
    ]
    snapshot = entry.get("task_card_snapshot")
    if isinstance(snapshot, dict):
        parts.append(str(snapshot.get("html") or ""))
        parts.append(str(snapshot.get("fatal_error_text") or ""))
    structure = entry.get("test_structure")
    if isinstance(structure, dict):
        parts.extend(
            [
                str(structure.get("run_id") or ""),
                str(structure.get("final_summary") or ""),
                str(structure.get("technical_entrypoint") or ""),
            ]
        )
    return "\n".join(parts)


def _is_mock_workspace_history(history: list[object]) -> bool:
    for entry in history:
        blob = _history_entry_blob(entry)
        if not blob:
            continue
        lowered = blob.lower()
        if "browser_supervisor" in lowered or 'data-task-run-id="browser_' in lowered:
            return True
        if "mocked file task" in lowered:
            return True
        if (
            isinstance(entry, dict)
            and (entry.get("task_card_snapshot") or entry.get("test_structure"))
            and any(marker in blob for marker in ("模拟监管任务", "模拟任务", "模拟刷新"))
        ):
            return True
    return False


def _task_status_label(status: object) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"done", "completed", "verified", "success", "succeeded"}:
        return "completed"
    if normalized in {"streaming", "running", "pending", "queued", "processing"}:
        return "running"
    if normalized == "awaiting_confirmation":
        return "awaiting_confirmation"
    if normalized == "waiting":
        return "waiting"
    if normalized in {"cancelled", "canceled"}:
        return "cancelled"
    if normalized in {
        "failed",
        "error",
        "blocked",
        "write_blocked",
        "tool_gap",
        "no_file_change",
        "model_unavailable",
        "quality_gate_failed",
    }:
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
    latest_task_title = _task_entry_title(latest_task)
    latest_task_status = _task_status_label(
        latest_task.get("task_terminal_status")
        or latest_task.get("status")
        or ""
    ) if isinstance(latest_task, dict) else ""
    return {
        "id": session_id,
        "title": _compact_text(latest_task_title or first_user or session_id, 42),
        "preview": _compact_text(last_text, 110),
        "message_count": len(text_entries),
        "last_role": str(last_entry.get("role") or "") if isinstance(last_entry, dict) else "",
        "updated_at": str(last_entry.get("timestamp") or "") if isinstance(last_entry, dict) else "",
        "task_count": len(task_entries),
        "has_task_flow": bool(task_entries),
        "latest_task_title": latest_task_title,
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
        previews = []
        for session in session_files:
            history = _normalize_history(manager.load_full(session))
            if _is_mock_workspace_history(history):
                continue
            previews.append(_session_preview(session, history))
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
    history = _normalize_history(_get_session_manager().load_full(f"{session_name}.json"))
    return jsonify({"session": session_name, "schema_version": _SESSION_HISTORY_SCHEMA_VERSION, "history": history})


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
    now = datetime.now().isoformat()
    metadata = _compact_metadata(body.get("metadata"))
    for rich_key in (
        "task_context",
        "task_contract",
        "task_request_payload",
        "pending_task_payload",
        "task_file_changes",
        "saved_files",
    ):
        if rich_key in metadata:
            metadata[rich_key] = _compact_json_value(metadata[rich_key])
    is_partial = _truthy(metadata.get("partial"))
    if is_partial:
        metadata["skip_model_context"] = True
    turn_key = str(
        body.get("turn_id")
        or body.get("id")
        or metadata.get("turn_id")
        or metadata.get("run_id")
        or metadata.get("task_id")
        or ""
    ).strip()
    user_entry = {
        "role": "user",
        "parts": [user_text],
        "timestamp": str(body.get("user_timestamp") or now),
        "source": "workspace",
        "schema_version": _SESSION_HISTORY_SCHEMA_VERSION,
    }
    attachments = body.get("attachments")
    if isinstance(attachments, list) and attachments:
        user_entry["attachments"] = attachments[:20]
    if turn_key:
        user_entry["turn_id"] = turn_key

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
    if not is_partial and task_label != "CHAT" and "skip_model_context" not in metadata:
        metadata["skip_model_context"] = False

    task_title = _clean_generated_title(metadata.get("task_title") or metadata.get("title") or "", 24)
    should_title_task = (task_label != "CHAT" or body.get("task_card_snapshot")) and not is_partial
    if should_title_task and not task_title:
        task_title = _generate_workspace_task_title(user_text, assistant_text, metadata, attachments)

    assistant_entry = {
        "role": "model",
        "parts": [assistant_text],
        "timestamp": str(body.get("assistant_timestamp") or now),
        "source": "workspace",
        "task": task_label,
        "schema_version": _SESSION_HISTORY_SCHEMA_VERSION,
    }
    if task_title:
        assistant_entry["title"] = task_title
        assistant_entry["task_title"] = task_title
        metadata["title"] = task_title
        metadata["task_title"] = task_title
    if not is_partial and (task_label != "CHAT" or body.get("task_card_snapshot")):
        memory_summary = _build_task_memory_summary(
            title=task_title,
            user_text=user_text,
            assistant_text=assistant_text,
            metadata=metadata,
            attachments=attachments,
        )
        assistant_entry["model_context_text"] = memory_summary
        assistant_entry["memory_summary"] = memory_summary
        metadata["model_context_text"] = memory_summary
        metadata["memory_summary"] = memory_summary
    if turn_key:
        assistant_entry["id"] = turn_key
        assistant_entry["turn_id"] = turn_key
    snapshot = body.get("task_card_snapshot")
    if isinstance(snapshot, dict):
        snapshot_html = str(snapshot.get("html") or "").strip()
        if snapshot_html and "wa-task-run" in snapshot_html:
            assistant_entry["task_card_snapshot"] = {
                "html": snapshot_html[:200000],
                "fatal_error_text": str(snapshot.get("fatal_error_text") or "")[:2000],
            }
    assistant_entry.update(metadata)

    with _workspace_turn_lock:
        history = _normalize_history(manager.load_full(filename))
        if turn_key:
            match_index = next(
                (
                    index
                    for index, entry in enumerate(history)
                    if isinstance(entry, dict)
                    and str(entry.get("role") or "").lower() in {"model", "assistant", "ai"}
                    and turn_key
                    in {
                        str(entry.get("id") or "").strip(),
                        str(entry.get("turn_id") or "").strip(),
                        str(entry.get("run_id") or entry.get("task_run_id") or "").strip(),
                        str(entry.get("task_id") or "").strip(),
                    }
                ),
                -1,
            )
            if match_index >= 0:
                user_index = match_index - 1
                if user_index >= 0 and isinstance(history[user_index], dict) and str(history[user_index].get("role") or "").lower() == "user":
                    previous_user = history[user_index]
                    user_entry["timestamp"] = str(previous_user.get("timestamp") or user_entry["timestamp"])
                    history[user_index] = {**previous_user, **user_entry}
                else:
                    history.insert(match_index, user_entry)
                    match_index += 1
                previous_assistant = history[match_index] if isinstance(history[match_index], dict) else {}
                history[match_index] = {**previous_assistant, **assistant_entry}
            else:
                history.extend([user_entry, assistant_entry])
        else:
            history.extend([user_entry, assistant_entry])
        manager.save(filename, history)
    if not is_partial and (task_label != "CHAT" or body.get("task_card_snapshot")):
        _start_task_memory_reflection(
            session_name=filename.replace(".json", ""),
            user_text=user_text,
            assistant_text=str(metadata.get("memory_summary") or assistant_text),
            metadata=metadata,
        )
    response_payload = {"success": True, "session": filename.replace(".json", "")}
    if task_title:
        response_payload["task_title"] = task_title
    memory_summary = str(metadata.get("memory_summary") or metadata.get("model_context_text") or "").strip()
    if memory_summary:
        response_payload["memory_summary"] = memory_summary
    return jsonify(response_payload)


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
