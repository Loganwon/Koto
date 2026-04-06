# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Chat interaction blueprint.

Routes:
  POST /api/chat/interrupt       — Interrupt current chat generation
  POST /api/chat/reset-interrupt — Reset interrupt flag
  POST /api/mini/chat            — Mini mode chat (compact UI)

Heavy endpoints (/api/chat, /api/chat/stream, /api/chat/file) remain in
web/app.py pending a larger streaming-architecture refactor.
"""

import logging

from flask import Blueprint, Response, jsonify, request

_logger = logging.getLogger("koto.routes.chat")

chat_bp = Blueprint("chat", __name__)


# ---------------------------------------------------------------------------
# Lazy accessors – avoid circular imports by pulling from web.app at runtime
# ---------------------------------------------------------------------------


def _app():
    """Return the web.app module (for mutable globals)."""
    import web.app as _mod

    return _mod


def _get_interrupt_manager():
    from web.app import _interrupt_manager

    return _interrupt_manager


def _get_interrupt_flags():
    from web.app import _interrupt_flags

    return _interrupt_flags


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@chat_bp.route("/api/chat/interrupt", methods=["POST"])
def interrupt_chat() -> Response:
    """中断当前对话生成"""
    payload = request.json or {}
    session_name: str | None = payload.get("session")
    task_id: str | None = payload.get("task_id")
    if not session_name:
        return jsonify({"error": "Missing session"}), 400

    _get_interrupt_manager().set_interrupt(session_name)
    _get_interrupt_flags()[session_name] = True

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
        _get_interrupt_manager().reset(session_name)
        flags = _get_interrupt_flags()
        if session_name in flags:
            del flags[session_name]
    return jsonify({"success": True})


@chat_bp.route("/api/mini/chat", methods=["POST"])
def mini_chat() -> Response:
    """迷你模式专用聊天 API — 使用与完整版相同的任务分配和执行逻辑"""
    _a = _app()
    data = request.json or {}
    user_input: str = data.get("message", "").strip()
    if not user_input:
        return jsonify({"error": "消息不能为空"}), 400

    user_input = _a.Utils.sanitize_string(user_input)
    session_name = "MiniKoto_Quick"
    history = _a.session_manager.load(f"{session_name}.json")

    task_type, route_method, context_info = _a.SmartDispatcher.analyze(
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
            search_result = _a.WebSearcher.search_with_grounding(
                user_input, skill_prompt=_mini_skill_prompt
            )
            response_text = search_result.get("response", "")
            used_model = "gemini-2.5-flash (Google Search)"
            if (
                not search_result.get("success")
                or _a.Utils.is_failure_output(response_text)
                or "搜索失败" in response_text
            ):
                fix_query_prompt = (
                    "请把用户需求改写成更适合搜索的简短关键词或查询语句，只输出查询语句。\n"
                    f"用户需求: {user_input}"
                )
                try:
                    fix_resp = _a.client.models.generate_content(
                        model="gemini-2.0-flash-lite",
                        contents=fix_query_prompt,
                        config=_a.types.GenerateContentConfig(
                            temperature=0.2, max_output_tokens=64
                        ),
                    )
                    fixed_query = (fix_resp.text or user_input).strip()
                    search_result = _a.WebSearcher.search_with_grounding(fixed_query)
                    response_text = search_result.get("response", "")
                except Exception as e:
                    _logger.debug("[MINI_CHAT] 修正查询失败: %s", e)
            if not response_text or _a.Utils.is_failure_output(response_text):
                is_error = True
                response_text = f"搜索失败：无法获取 '{user_input}' 的实时信息"

        elif task_type == "SYSTEM":
            try:
                exec_result = _a.LocalExecutor.execute(user_input)
                response_text = exec_result.get("message", "命令执行失败")
                if exec_result.get("details"):
                    response_text += f"\n\n{exec_result['details']}"
                used_model = "LocalExecutor"
                is_error = not exec_result.get("success", False)
                if is_error or _a.Utils.is_failure_output(response_text):
                    fix_prompt = _a.Utils.build_fix_prompt(
                        "SYSTEM", user_input, response_text
                    )
                    try:
                        fix_resp = _a.client.models.generate_content(
                            model="gemini-2.5-flash",
                            contents=fix_prompt,
                            config=_a.types.GenerateContentConfig(
                                system_instruction=_a._get_DEFAULT_CHAT_SYSTEM_INSTRUCTION(),
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
            model = _a.MODEL_MAP.get(task_type, _a.MODEL_MAP["CHAT"])
            result = _a.brain.chat(
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
                for fallback_model in ["gemini-2.5-flash", "gemini-3-flash-preview"]:
                    try:
                        result = _a.brain.chat(
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
        _a.session_manager.append_and_save(
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
