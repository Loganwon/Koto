# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Chat interaction blueprint.

Routes:
  POST /api/chat                 — Non-streaming chat
  POST /api/chat/file            — Upload file(s) and chat with extracted context
  POST /api/chat/interrupt       — Interrupt current chat generation
  POST /api/chat/reset-interrupt — Reset interrupt flag
  POST /api/mini/chat            — Mini mode chat (compact UI)

The heavy chat implementation still lives in web/app.py while the route
registration has moved here.
"""

import logging

from flask import Blueprint, Response, jsonify, request

from app.core.llm.model_selection import resolve_requested_model_id
from web.runtime_context import service_registry

_logger = logging.getLogger("koto.routes.chat")

chat_bp = Blueprint("chat", __name__)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@chat_bp.route("/api/chat", methods=["POST"])
def chat() -> Response:
    """Handle non-streaming chat requests."""
    data = request.get_json(silent=True) or {}
    session_name = data.get("session")
    user_input = data.get("message", "")
    file_path = data.get("file_path", "")

    # Support direct file path reading via FileProcessor (same format as upload)
    _file_data_for_brain = None
    if file_path:
        try:
            import os as _chat_os
            _resolved = _chat_os.path.abspath(_chat_os.path.expanduser(file_path))
            if not _chat_os.path.exists(_resolved):
                return jsonify({"error": f"File not found: {_resolved}"}), 404
            _size_mb = _chat_os.path.getsize(_resolved) / (1024 * 1024)
            if _size_mb > 10:
                return jsonify({"error": f"File too large ({_size_mb:.1f}MB). Max 10MB for direct reads."}), 413
            from web.files.file_processor import FileProcessor as _FP
            _raw = _FP.process_file(_resolved)
            _formatted, _fd = _FP.format_result_for_chat(_raw, user_input or "")
            user_input = _formatted
            _file_data_for_brain = _fd
        except Exception as _e:
            return jsonify({"error": f"Failed to read file: {str(_e)}"}), 500
    
    locked_task = data.get("locked_task")
    locked_model = data.get("locked_model", "auto")

    if not session_name or not str(user_input or "").strip():
        return jsonify({"error": "Missing session or message"}), 400

    # ?? Provider availability check ????????????????????????????????????
    try:
        from app.core.llm.provider_factory import list_available_providers
        available = list_available_providers()
        if not available:
            _logger.warning("[chat] No LLM provider available; returning 503")
            return jsonify({
                "error": "??????? AI ?????",
                "error_code": "NO_PROVIDER",
                "guide": {
                    "title": "Koto 尚未配置可用的 AI 服务",
                    "options": [
                        {
                            "name": "配置 DeepSeek API Key",
                            "url": "https://platform.deepseek.com/api_keys",
                            "desc": "启用云端对话、代码和文件任务"
                        },
                        {
                            "name": "安装本地模型（Ollama）",
                            "url": "https://ollama.com/download",
                            "desc": "在本机运行受支持的本地模型"
                        }
                    ],
                    "setup": "在设置中保存密钥，或切换到已经安装的本地模型。"
                },
            }), 503
    except ImportError:
        _logger.debug("[chat] provider_factory not importable, skipping pre-check")

    utils = service_registry.utils
    session_manager = service_registry.session_manager
    model_map = service_registry.model_map
    user_input = utils.sanitize_string(user_input)
    full_history = session_manager.load_full(f"{session_name}.json")
    if hasattr(session_manager, "_trim_history"):
        history = session_manager._trim_history(full_history)
    else:
        history = full_history

    task_type = str(locked_task or "CHAT").strip().upper() or "CHAT"
    fallback_model = model_map.get(task_type, model_map.get("CHAT", ""))
    requested_model = str(locked_model or "").strip()
    model = resolve_requested_model_id(
        requested_model,
        fallback_model=fallback_model,
        task_type=task_type,
    )
    auto_model = not bool(requested_model) or requested_model.lower() in {"auto", "cloud"}
    try:
        from app.core.llm.provider_factory import get_local_model_tag, is_local_mode

        if is_local_mode():
            model = get_local_model_tag() or model
            auto_model = False
    except Exception as exc:
        _logger.debug("[chat] configured local model lookup skipped: %s", exc)

    result = service_registry.brain.chat(
        history,
        user_input,
        file_data=_file_data_for_brain,
        model=model,
        auto_model=auto_model,
        task_type=task_type,
    )

    response_text = str(result.get("response", "") or "")
    used_model = result.get("model", model)
    saved_files = []
    if task_type == "CODER" and response_text:
        pkgs = utils.detect_required_packages(response_text)
        if pkgs:
            install_result = utils.auto_install_packages(pkgs)
            result["package_install"] = install_result

    if response_text:
        session_manager.append_and_save(
            f"{session_name}.json",
            user_input,
            response_text,
            task=task_type,
            model_name=used_model,
            saved_files=saved_files,
        )

    return jsonify(result)


@chat_bp.route("/api/chat/stream", methods=["POST"])
def chat_stream() -> Response:
    """Stream chat response via the configured SSE handler."""
    return service_registry.chat_stream_handler()


@chat_bp.route("/api/chat/file", methods=["POST"])
def chat_with_file() -> Response:
    """Handle file upload and chat requests (multipart form data).

    Form fields: session, message, locked_task, locked_model, file (one or more).
    """
    session_name = request.form.get("session")
    user_input = request.form.get("message", "")
    files = request.files.getlist("file")
    locked_task = request.form.get("locked_task")
    locked_model = request.form.get("locked_model", "auto")

    if not session_name or not files:
        return jsonify({"error": "Missing session or file"}), 400
    if len(files) > 10:
        return jsonify({"error": "?????? 10 ???"}), 400

    from web.chat_file_handlers import (
        handle_multi_file_chat_request,
        handle_single_file_chat_request,
    )

    _app_mod = None

    if len(files) > 1:
        return handle_multi_file_chat_request(
            app_module=_app_mod,
            session_name=session_name,
            user_input=user_input,
            files=files,
            locked_task=locked_task,
            locked_model=locked_model,
        )
    return handle_single_file_chat_request(
        app_module=_app_mod,
        session_name=session_name,
        user_input=user_input,
        file=files[0],
        locked_task=locked_task,
        locked_model=locked_model,
    )

@chat_bp.route("/api/chat/interrupt", methods=["POST"])
def interrupt_chat() -> Response:
    """中断当前对话生成"""
    payload = request.json or {}
    session_name: str | None = payload.get("session")
    task_id: str | None = payload.get("task_id")
    run_id = str(payload.get("run_id") or "").strip()
    if not session_name:
        return jsonify({"error": "Missing session"}), 400

    # KernelAgent observes durable cancellation, whereas explicit legacy task
    # contracts still observe the session interrupt flag below. Keep both
    # transports connected to their existing owners during compatibility.
    from app.core.tasks.task_ledger import TaskStatus, get_ledger

    ledger = get_ledger()
    if task_id and run_id:
        try:
            ledger.bind_run_identity(task_id, run_id, session_id=session_name)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 409
    pending_cancel = False
    if task_id:
        task = ledger.get(task_id)
        if task is None and run_id:
            pending_cancel = True
        elif task is None or task.session_id != session_name:
            return jsonify({"error": "Task not found in this session"}), 404
    else:
        running = ledger.list_tasks(
            session_id=session_name, status=TaskStatus.RUNNING,
            source="kernel_agent", limit=1,
        )
        task_id = running[0].task_id if running else None
    if task_id:
        ledger.cancel_task(task_id)
        if run_id:
            ledger.cancel_task(run_id)

    service_registry.interrupt_manager.set_interrupt(session_name)
    service_registry.interrupt_flags[session_name] = True

    if task_id:
        _logger.debug("[INTERRUPT] Task stream interruption requested: %s", task_id)

    response = {"success": True, "message": "Chat interrupted", "task_id": task_id}
    if pending_cancel:
        response.update(run_id=run_id, cancel_requested=True, status="pending")
    return jsonify(response), 202 if pending_cancel else 200


@chat_bp.route("/api/chat/reset-interrupt", methods=["POST"])
def reset_interrupt() -> Response:
    """重置中断标志"""
    session_name: str | None = (request.json or {}).get("session")
    if session_name:
        service_registry.interrupt_manager.reset(session_name)
        flags = service_registry.interrupt_flags
        if session_name in flags:
            del flags[session_name]
    return jsonify({"success": True})


@chat_bp.route("/api/mini/chat", methods=["POST"])
def mini_chat() -> Response:
    """Mini-mode text chat with a stable, non-agent transport contract."""
    data = request.json or {}
    user_input: str = data.get("message", "").strip()
    if not user_input:
        return jsonify({"error": "消息不能为空"}), 400

    utils = service_registry.utils
    session_manager = service_registry.session_manager
    brain = service_registry.brain
    model_map = service_registry.model_map

    user_input = utils.sanitize_string(user_input)
    session_name = "MiniKoto_Quick"
    history = session_manager.load(f"{session_name}.json")

    task_type = "CHAT"
    route_method = "Stable mini chat boundary"

    response_text: str = ""
    is_error = False
    used_model = "unknown"

    try:
        model = model_map.get("CHAT", "deepseek-chat")
        result = brain.chat(
            history, user_input, model=model, auto_model=False, task_type="CHAT"
        )
        response_text = result.get("response", "")
        used_model = result.get("model", model)
        is_error = response_text.startswith("Error:") or response_text.startswith("❌")
        if is_error and any(
            code in response_text for code in ("404", "503", "UNAVAILABLE", "INVALID")
        ):
            result = brain.chat(
                history,
                user_input,
                model="deepseek-chat",
                auto_model=False,
                task_type="CHAT",
            )
            fallback_text = result.get("response", "")
            if fallback_text and not fallback_text.startswith(("Error:", "❌")):
                response_text = fallback_text
                used_model = "deepseek-chat"
                is_error = False

    except Exception as e:
        _logger.error("[MINI_CHAT] ❌ 执行出错: %s", e)
        is_error = True
        response_text = f"Error: {str(e)}"

    if response_text:
        session_manager.append_and_save(
            f"{session_name}.json", user_input, response_text
        )

    _logger.info(
        "[MINI_CHAT] ✅ 完成: task_type=%s, model=%s, success=%s",
        task_type,
        used_model,
        not is_error,
    )
    return jsonify(
        {
            "success": not is_error,
            "response": response_text,
            "model": used_model,
            "task_type": task_type,
            "route_method": route_method,
            "error": response_text if is_error else "",
        }
    )

@chat_bp.route("/api/response/rate", methods=["POST"])
def rate_response() -> Response:
    """Save user rating for an AI response.

    JSON body: {msg_id, stars, comment, session_name, user_input, ai_response, task_type}
    """
    data = request.get_json(silent=True) or {}
    msg_id = str(data.get("msg_id") or "").strip()
    stars = int(data.get("stars", 0))
    comment = str(data.get("comment") or "").strip()
    session_name = str(data.get("session_name") or data.get("session") or "").strip()
    user_input = str(data.get("user_input") or data.get("user_msg") or "").strip()
    ai_response = str(data.get("ai_response") or data.get("assistant_msg") or "").strip()
    task_type = str(data.get("task_type") or "CHAT").strip().upper() or "CHAT"

    if not msg_id or stars < 1 or stars > 5:
        return jsonify({"error": "msg_id and stars (1-5) are required"}), 400

    try:
        from app.core.learning.rating_store import RatingStore

        rs = RatingStore()
        if not msg_id:
            msg_id = RatingStore.make_msg_id(session_name, user_input)
        rs.save_user_rating(
            msg_id=msg_id,
            stars=stars,
            comment=comment,
            session_name=session_name,
            user_input=user_input,
            ai_response=ai_response,
        )
        _logger.info("Rating saved: msg_id=%s stars=%d task=%s", msg_id, stars, task_type)
        return jsonify({"ok": True})
    except Exception as exc:
        _logger.warning("Failed to save rating: %s", exc)
        return jsonify({"error": str(exc)}), 500
