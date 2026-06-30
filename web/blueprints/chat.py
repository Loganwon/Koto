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

from web.runtime_context import (
    get_brain,
    get_chat_stream_handler,
    get_client_proxy,
    get_default_chat_system_instruction,
    get_interrupt_flags,
    get_interrupt_manager,
    get_local_executor,
    get_model_map,
    get_session_manager,
    get_smart_dispatcher,
    get_types,
    get_utils,
    get_web_searcher,
    resolve_requested_model_id,
)

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
    locked_task = data.get("locked_task")
    locked_model = data.get("locked_model", "auto")

    if not session_name or not str(user_input or "").strip():
        return jsonify({"error": "Missing session or message"}), 400

    utils = get_utils()
    session_manager = get_session_manager()
    model_map = get_model_map()
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

    result = get_brain().chat(
        history,
        user_input,
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
    handler = get_chat_stream_handler()
    if not callable(handler):
        return jsonify({"error": "Chat stream service is unavailable"}), 503
    return handler()


@chat_bp.route("/api/chat/file", methods=["POST"])
def chat_with_file() -> Response:
    """Handle file upload and chat requests."""
    session_name = request.form.get("session")
    user_input = request.form.get("message", "")
    files = request.files.getlist("file")

    _logger.info("[FILE UPLOAD DEBUG] ========== 接收到文件上传请求 ==========")
    _logger.info("[FILE UPLOAD DEBUG] request.files keys: %s", list(request.files.keys()))
    _logger.info("[FILE UPLOAD DEBUG] request.files.getlist('file'): %s 个文件", len(files))
    for index, file_obj in enumerate(files):
        _logger.info(
            "[FILE UPLOAD DEBUG]   %s. %s",
            index + 1,
            file_obj.filename if file_obj else "None",
        )

    if not files:
        single_file = request.files.get("file")
        if single_file:
            files = [single_file]
            _logger.info(
                "[FILE UPLOAD DEBUG] 使用单文件模式，文件: %s",
                single_file.filename,
            )

    locked_task = request.form.get("locked_task")
    locked_model = request.form.get("locked_model", "cloud")
    if str(locked_model or "").strip().lower() in {"", "auto"}:
        locked_model = "cloud"
    stream_mode = request.form.get("stream", "").lower() in ("1", "true", "yes")

    _logger.info("[FILE UPLOAD DEBUG] 最终 files 列表: %s 个文件", len(files))
    _logger.info("[FILE UPLOAD DEBUG] 判断: len(files) > 1 = %s", len(files) > 1)

    if not session_name or not files:
        return jsonify({"error": "Missing session or file"}), 400
    if len(files) > 10:
        return jsonify({"error": "最多一次上传 10 个文件"}), 400

    from web.chat_file_handlers import (
        handle_multi_file_chat_request,
        handle_single_file_chat_request,
    )

    if len(files) > 1:
        return handle_multi_file_chat_request(
            app_module=None,
            session_name=session_name,
            user_input=user_input,
            files=files,
            locked_task=locked_task,
            locked_model=locked_model,
            stream_mode=stream_mode,
        )
    return handle_single_file_chat_request(
        app_module=None,
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
    if not session_name:
        return jsonify({"error": "Missing session"}), 400

    get_interrupt_manager().set_interrupt(session_name)
    get_interrupt_flags()[session_name] = True

    if task_id:
        try:
            from task_scheduler import get_task_scheduler

            get_task_scheduler().cancel_task(task_id)
            _logger.debug("[INTERRUPT] Cancel task_id=%s", task_id)
        except Exception as e:
            _logger.debug("[INTERRUPT] cancel task failed: %s", e)

    return jsonify({"success": True, "message": "Chat interrupted"})


@chat_bp.route("/api/chat/reset-interrupt", methods=["POST"])
def reset_interrupt() -> Response:
    """重置中断标志"""
    session_name: str | None = (request.json or {}).get("session")
    if session_name:
        get_interrupt_manager().reset(session_name)
        flags = get_interrupt_flags()
        if session_name in flags:
            del flags[session_name]
    return jsonify({"success": True})


@chat_bp.route("/api/mini/chat", methods=["POST"])
def mini_chat() -> Response:
    """迷你模式专用聊天 API — 使用与完整版相同的任务分配和执行逻辑"""
    data = request.json or {}
    user_input: str = data.get("message", "").strip()
    if not user_input:
        return jsonify({"error": "消息不能为空"}), 400

    utils = get_utils()
    session_manager = get_session_manager()
    brain = get_brain()
    model_map = get_model_map()
    client = get_client_proxy()
    types = get_types()

    user_input = utils.sanitize_string(user_input)
    session_name = "MiniKoto_Quick"
    history = session_manager.load(f"{session_name}.json")

    task_type, route_method, context_info = get_smart_dispatcher().analyze(
        user_input, history
    )
    _logger.debug(
        "[MINI_CHAT] SmartDispatcher: task_type='%s', method='%s'",
        task_type,
        route_method,
    )

    response_text: str = ""
    is_error = False
    used_model = "unknown"

    try:
        if task_type == "WEB_SEARCH":
            _mini_skill_prompt = (context_info or {}).get("skill_prompt")
            search_result = get_web_searcher().search_with_grounding(
                user_input, skill_prompt=_mini_skill_prompt
            )
            response_text = search_result.get("response", "")
            used_model = "gemini-2.5-flash (Google Search)"
            if (
                not search_result.get("success")
                or utils.is_failure_output(response_text)
                or "搜索失败" in response_text
            ):
                fix_query_prompt = (
                    "请把用户需求改写成更适合搜索的简短关键词或查询语句，只输出查询语句。\n"
                    f"用户需求: {user_input}"
                )
                try:
                    fix_resp = client.models.generate_content(
                        model="gemini-2.5-flash-lite",
                        contents=fix_query_prompt,
                        config=types.GenerateContentConfig(
                            temperature=0.2, max_output_tokens=64
                        ),
                    )
                    fixed_query = (fix_resp.text or user_input).strip()
                    search_result = get_web_searcher().search_with_grounding(fixed_query)
                    response_text = search_result.get("response", "")
                except Exception as e:
                    _logger.debug("[MINI_CHAT] 修正查询失败: %s", e)
            if not response_text or utils.is_failure_output(response_text):
                is_error = True
                response_text = f"搜索失败：无法获取 '{user_input}' 的实时信息"

        elif task_type == "SYSTEM":
            try:
                exec_result = get_local_executor().execute(user_input)
                response_text = exec_result.get("message", "命令执行失败")
                if exec_result.get("details"):
                    response_text += f"\n\n{exec_result['details']}"
                used_model = "LocalExecutor"
                is_error = not exec_result.get("success", False)
                if is_error or utils.is_failure_output(response_text):
                    fix_prompt = utils.build_fix_prompt(
                        "SYSTEM", user_input, response_text
                    )
                    try:
                        fix_resp = client.models.generate_content(
                            model="gemini-2.5-flash",
                            contents=fix_prompt,
                            config=types.GenerateContentConfig(
                                system_instruction=get_default_chat_system_instruction(),
                                temperature=0.4,
                                max_output_tokens=1000,
                            ),
                        )
                        response_text = fix_resp.text or response_text
                        used_model = "gemini-2.5-flash (fallback)"
                        is_error = False
                    except Exception as e:
                        _logger.debug("[MINI_CHAT] AI 修正失败: %s", e)
            except Exception as e:
                _logger.error("[MINI_CHAT] ❌ 系统命令执行出错: %s", e)
                response_text = f"系统命令执行出错：{str(e)}"
                used_model = "LocalExecutor"
                is_error = True

        else:
            model = model_map.get(task_type, model_map["CHAT"])
            result = brain.chat(
                history, user_input, model=model, auto_model=False, task_type=task_type
            )
            response_text = result.get("response", "")
            used_model = result.get("model", model)
            is_error = response_text.startswith("Error:") or response_text.startswith("❌")
            # Fallback on HTTP errors (404 model unavailable, 503 overloaded, etc.)
            _needs_fallback = is_error and any(
                code in response_text for code in ("404", "503", "UNAVAILABLE", "INVALID")
            )
            if _needs_fallback:
                for fallback_model in ["gemini-2.5-flash", "gemini-2.5-flash-lite"]:
                    try:
                        result = brain.chat(
                            history, user_input, model=fallback_model, auto_model=False
                        )
                        _fb_resp = result.get("response", "")
                        if _fb_resp and not _fb_resp.startswith("Error:") and not _fb_resp.startswith("❌"):
                            response_text = _fb_resp
                            used_model = fallback_model
                            is_error = False
                            break
                    except Exception:
                        continue

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
