# ══════════════════════════════════════════════════════════════
# socket_handler.py — v2: Real Streaming LLM + Code Execution
#
# Design principles:
#   1. NO mock fallbacks — if LLM fails, emit a clear error and stop.
#   2. ALL text results stream via agent_stream_chunk events (typewriter).
#   3. agent_task_complete always carries full_text so the frontend can
#      attach apply-buttons; the backend never mutates the document directly.
#   4. code_exec runs user/AI-generated code in the sandbox and emits a
#      code_result event with stdout, stderr, and base64-encoded output files.
# ══════════════════════════════════════════════════════════════

import logging

from app.core.llm.model_mode import is_explicit_model_mode, normalize_model_mode
from app.core.security.output_validator import sanitize_user_visible_text
from app.core.shared.tool_parser import parse_tool_calls, stringify_tool_result  # noqa: F401
from app.core.shared.llm_helpers import (  # noqa: F401
    is_online_failure as _is_online_failure_shared,
    is_ollama_alive as _is_ollama_alive_shared,
    get_local_provider as _get_local_provider_shared,
)

logger = logging.getLogger(__name__)


def _safe_user_error_text(text, fallback: str) -> str:
    return sanitize_user_visible_text(text, fallback=fallback, treat_as_error=True)


def _safe_user_preview_text(text, fallback: str) -> str:
    return sanitize_user_visible_text(text, fallback=fallback)

def register_socket_events(socketio):
    """Register all /doc namespace WebSocket event handlers."""

    # Default namespace connect/disconnect (required so python-socketio test clients
    # don't raise ConnectionError when they implicitly join the default namespace)
    @socketio.on("connect")
    def on_default_connect():
        pass

    @socketio.on("connect", namespace="/doc")
    def on_connect():
        logger.info("[DocAssistant] client connected")

    @socketio.on("disconnect", namespace="/doc")
    def on_disconnect():
        logger.info("[DocAssistant] client disconnected")

    @socketio.on("client_request", namespace="/doc")
    def on_client_request(data):
        from flask_socketio import emit

        action_type = data.get("type", "")
        payload = data.get("payload", {})
        logger.info("[DocAssistant] request: %s", action_type)

        requested_mode_raw = payload.get("model_mode", data.get("model_mode", ""))
        requested_mode = normalize_model_mode(requested_mode_raw, default="auto")

        # Explicit request mode wins; legacy settings only apply to auto/omitted requests.
        _req_local = requested_mode == "local"
        if not _req_local and not is_explicit_model_mode(requested_mode_raw):
            try:
                _req_local = bool(_SM().get("ai", "use_local_only"))
            except Exception:
                pass

        try:
            if action_type == "custom_instruction":
                _handle_custom(emit, payload, use_local_only=_req_local)
            elif action_type == "code_exec":
                _handle_code_exec(emit, payload, use_local_only=_req_local)
            else:
                emit(
                    "agent_execute_command",
                    {
                        "action": "show_message",
                        "text": f"未知操作类型: {action_type}",
                        "is_error": True,
                    },
                    namespace="/doc",
                )
        except Exception as exc:
            logger.exception("[DocAssistant] unhandled error: %s", exc)
            emit(
                "agent_execute_command",
                {
                    "action": "show_message",
                    "text": _safe_user_error_text(
                        f"服务端处理失败: {exc}",
                        "服务端处理失败，请稍后重试。",
                    ),
                    "is_error": True,
                },
                namespace="/doc",
            )

    @socketio.on("doc_ai_request", namespace="/doc")
    def on_doc_ai_request(data):
        """全格式工作区 AI 交互 — streaming text or code-exec (chart generation)."""
        from flask import request as _req

        sid = _req.sid
        prompt = data.get("prompt", "")
        context = data.get("context", "")  # document context (sent separately)
        selection = data.get("selection", "")  # Copilot-style pinned selection text
        file_type = data.get("file_type", "unknown")
        file_name = data.get("file_name", "")  # filename for system prompt context
        has_selection = data.get(
            "has_selection", False
        )  # whether editor has a text selection
        history = data.get("history", [])  # [{role, content}] multi-turn history
        language = data.get("language", "")  # "python" | "r" | "" → text mode
        csv_data = data.get("csv_data", "")  # table CSV for chart context
        output_mode = data.get("output_mode", "inline")  # 'inline' | 'chat'
        model_mode = normalize_model_mode(data.get("model_mode"), default="auto")  # 'local' | 'cloud' | 'auto'
        # FloatingToolbar actions pass a pre-built system prompt via this field
        action_system_prompt = data.get("_action_system_prompt", "")  # overrides system_instruction
        if not prompt:
            return

        # ── Agent Loop path (OpenClaw-inspired unified agent) ─────────
        _use_agent_loop = data.get("_use_agent_loop", True)
        if not _use_agent_loop:
            try:
                from web.settings import SettingsManager as _SM
                _use_agent_loop = bool(_SM().get("ai", "use_agent_loop"))
            except Exception:
                pass

        # ── DocAgent path (new multi-file document processor) ─────────
        _use_doc_agent = data.get("_use_doc_agent", False)
        if not _use_doc_agent:
            try:
                from web.settings import SettingsManager as _SM
                _use_doc_agent = bool(_SM().get("ai", "use_doc_agent"))
            except Exception:
                pass

        # DocAgent takes priority if enabled
        if _use_doc_agent:
            def _doc_agent_task():
                try:
                    _run_doc_agent(socketio, sid, data)
                except Exception as _da_exc:
                    logger.exception("[DocAI] DocAgent error: %s", _da_exc)
                    socketio.emit(
                        "agent_task_complete",
                        {"full_text": "", "error": f"DocAgent 错误：{_da_exc}"},
                        namespace="/doc", to=sid,
                    )
            socketio.start_background_task(_doc_agent_task)
            return

        # agent_loop is the standard path; always active unless DocAgent took over
        def _agent_loop_task():
            try:
                _run_agent_loop(socketio, sid, data)
            except Exception as _al_exc:
                logger.exception("[DocAI] Agent loop error: %s", _al_exc)
                socketio.emit(
                    "agent_task_complete",
                    {"full_text": "", "error": f"Agent loop 错误：{_al_exc}"},
                    namespace="/doc", to=sid,
                )
        socketio.start_background_task(_agent_loop_task)
        return

    # ── /files namespace (智能文件库 watchdog real-time updates) ──────────────────
    @socketio.on("connect", namespace="/files")
    def on_files_connect():
        logger.info("[FileLib] /files client connected")

    @socketio.on("disconnect", namespace="/files")
    def on_files_disconnect():
        logger.info("[FileLib] /files client disconnected")


# ── Handlers (custom_instruction / code_exec) ─────────────────────
# Note: polish/translate/rewrite/etc. are now handled by the on_doc_ai_request
# path (SocketBridge maps them to doc_ai_request for full streaming + history).
# Only custom_instruction and code_exec still use the client_request fallback.


def _handle_custom(emit, payload, use_local_only: bool = False):
    """Stream result for an arbitrary user instruction."""
    instruction = payload.get("instruction", "").strip()
    context = payload.get("context") or {}
    context_text = (context.get("text") or "").strip()

    if not instruction:
        emit(
            "agent_execute_command",
            {
                "action": "show_message",
                "text": "指令为空。",
                "is_error": True,
            },
            namespace="/doc",
        )
        return

    combined = instruction
    if context_text:
        combined += f"\n\n当前选中的上下文内容：\n{context_text}"

    prompt = "你是 Koto 文件助手。请根据用户的指令处理，直接输出结果："
    full_result = _stream_llm(emit, prompt, combined, use_local_only=use_local_only)
    if full_result is None:
        return

    emit(
        "agent_task_complete",
        {
            "full_text": full_result,
            "message": None,
        },
        namespace="/doc",
    )


# ── Code execution handler ────────────────────────────────────


def _handle_code_exec(emit, payload, use_local_only: bool = False):
    """
    Execute user/AI-supplied Python or R code in the sandbox.
    The AI may also generate code via LLM before executing it.
    """
    from app.core.sandbox import run_python, run_r

    code = payload.get("code", "").strip()
    language = payload.get("language", "python").lower()
    auto_generate = payload.get("auto_generate", False)

    # If auto_generate: use AI to write the code first
    if auto_generate:
        user_instruction = payload.get("instruction", "")
        data_context = payload.get("data_context", "")
        if not user_instruction:
            emit(
                "agent_execute_command",
                {
                    "action": "show_message",
                    "text": "未提供代码生成指令。",
                    "is_error": True,
                },
                namespace="/doc",
            )
            return

        gen_prompt = (
            f"请根据以下任务描述，编写一段可直接运行的 {language} 代码。\n"
            "只输出代码内容，不要加任何 markdown 代码块标记（``` 等）：\n\n"
            f"任务：{user_instruction}"
        )
        if data_context:
            gen_prompt += f"\n\n数据上下文：\n{data_context}"

        code = _call_llm_sync(gen_prompt, use_local_only=use_local_only)
        if code is None:
            emit(
                "agent_execute_command",
                {
                    "action": "show_message",
                    "text": "❌ LLM 代码生成失败，请检查 GEMINI_API_KEY 配置。",
                    "is_error": True,
                },
                namespace="/doc",
            )
            return

        # Echo the generated code to the panel
        emit(
            "agent_execute_command",
            {
                "action": "show_message",
                "text": f"```{language}\n{code}\n```",
            },
            namespace="/doc",
        )

    if not code:
        emit(
            "agent_execute_command",
            {
                "action": "show_message",
                "text": "代码为空。",
                "is_error": True,
            },
            namespace="/doc",
        )
        return

    # Run in sandbox
    try:
        if language in ("python", "py"):
            result = run_python(code)
        elif language in ("r",):
            result = run_r(code)
        else:
            result = {
                "error": f"不支持的语言: {language}",
                "stdout": "",
                "stderr": "",
                "files": {},
            }

        emit("code_result", result, namespace="/doc")
    except Exception as exc:
        logger.exception("[DocAssistant] sandbox error: %s", exc)
        emit(
            "code_result",
            {
                "error": _safe_user_error_text(str(exc), "代码执行失败，请稍后重试。"),
                "stdout": "",
                "stderr": "",
                "files": {},
            },
            namespace="/doc",
        )


# ── LLM helpers — 使用 Koto 统一 LLM Provider 体系 ────────────


# Delegate to the shared implementation
_parse_tool_calls = parse_tool_calls


_ONLINE_DOC_MODELS = [
    "gemini-3-flash-preview",  # 首选：当前主聊天模型
    "gemini-2.5-flash",        # 稳定快速回退
    "gemini-2.5-flash-lite",   # 轻量兜底
]


def _pick_online_model() -> str:
    """直接使用 MODEL_MAP[CHAT]，保持与 Koto 主体一致；若取不到则用首选。"""
    try:
        from web.app import MODEL_MAP  # type: ignore

        m = MODEL_MAP.get("CHAT", "")
        if m:
            return m
    except Exception:
        pass
    return _ONLINE_DOC_MODELS[0]


def _get_provider():
    """Return the configured online LLMProvider."""
    from app.core.llm.provider_factory import get_llm_provider

    return get_llm_provider(provider="gemini", allow_local_fallback=False)


# Delegate to shared implementations – kept as module-level aliases so any
# existing code inside this file (and monkeypatch-based tests) can still
# reference the bare names.
_is_ollama_alive = _is_ollama_alive_shared
_get_local_provider = _get_local_provider_shared
_is_online_failure = _is_online_failure_shared


def _stream_llm(emit, prompt, text, use_local_only: bool = False):
    """
    Stream LLM output with dual-mode fallback:
      1. Try the best available online Gemini model.
      2. On timeout/503/unavailable → fall back to local Ollama if running.
    Returns the full assembled text on success, or None on failure.
    """
    full_prompt = f"{prompt}\n\n{text}"
    online_model = _pick_online_model()

    # ── Local-only mode: skip cloud entirely ─────────────────────────────────
    if use_local_only:
        if not _is_ollama_alive():
            emit(
                "agent_execute_command",
                {"action": "show_message", "text": "❌ 本地模式下 Ollama 未运行，请启动 Ollama。", "is_error": True},
                namespace="/doc",
            )
            emit("agent_task_complete", {"full_text": "", "error": "ollama not running"}, namespace="/doc")
            return None
        try:
            local = _get_local_provider()
            gen = local.generate_content(prompt=full_prompt, stream=True)
            full = []
            for chunk in gen:
                part = chunk.get("content", "") if isinstance(chunk, dict) else str(chunk)
                if part:
                    full.append(part)
                    emit("agent_stream_chunk", {"chunk": part}, namespace="/doc")
            return "".join(full) if full else ""
        except Exception as exc_lo:
            logger.error("[DocAssistant] Local-only stream failed: %s", exc_lo)
            emit(
                "agent_task_complete",
                {
                    "full_text": "",
                    "error": _safe_user_error_text(
                        str(exc_lo),
                        "本地 AI 调用失败，请检查 Ollama 后重试。",
                    ),
                },
                namespace="/doc",
            )
            return None

    # ── Attempt 1: Online ────────────────────────────────────────────────────
    try:
        provider = _get_provider()
        gen = provider.generate_content(
            prompt=full_prompt,
            model=online_model,
            stream=True,
        )
        full = []
        for chunk in gen:
            part = chunk.get("content", "")
            if part:
                full.append(part)
                emit("agent_stream_chunk", {"chunk": part}, namespace="/doc")
        return "".join(full) if full else ""
    except Exception as exc:
        if not _is_online_failure(exc):
            logger.error(
                "[DocAssistant] LLM streaming failed (non-recoverable): %s", exc
            )
            emit(
                "agent_execute_command",
                {
                    "action": "show_message",
                    "text": _safe_user_error_text(
                        f"❌ AI 调用失败：{exc}",
                        "❌ AI 调用失败，请稍后重试。",
                    ),
                    "is_error": True,
                },
                namespace="/doc",
            )
            emit(
                "agent_task_complete",
                {
                    "full_text": "",
                    "error": _safe_user_error_text(str(exc), "AI 调用失败，请稍后重试。"),
                },
                namespace="/doc",
            )
            return None
        logger.warning("[DocAssistant] Online AI unavailable (%s), trying local…", exc)

    # ── Attempt 2: Local (Ollama) fallback ───────────────────────────────────
    if not _is_ollama_alive():
        emit(
            "agent_execute_command",
            {
                "action": "show_message",
                "text": "❌ 在线 AI 暂时不可用，本地模型也未运行。请稍后重试或启动 Ollama。",
                "is_error": True,
            },
            namespace="/doc",
        )
        emit(
            "agent_task_complete",
            {"full_text": "", "error": "all providers failed"},
            namespace="/doc",
        )
        return None

    try:
        local = _get_local_provider()
        # Notify user the system is falling back to local model
        emit(
            "agent_execute_command",
            {
                "action": "show_message",
                "text": "⚠️ 云端 AI 暂时不可用，已自动切换到本地模型 (Ollama)，响应速度可能较慢。",
                "is_error": False,
            },
            namespace="/doc",
        )
        gen = local.generate_content(prompt=full_prompt, stream=True)
        full = []
        for chunk in gen:
            part = chunk.get("content", "") if isinstance(chunk, dict) else str(chunk)
            if part:
                full.append(part)
                emit("agent_stream_chunk", {"chunk": part}, namespace="/doc")
        return "".join(full) if full else ""
    except Exception as exc2:
        logger.error("[DocAssistant] Local fallback also failed: %s", exc2)
        emit(
            "agent_execute_command",
            {
                "action": "show_message",
                "text": f"❌ 在线和本地 AI 均不可用，请检查网络和 Ollama 状态。",
                "is_error": True,
            },
            namespace="/doc",
        )
        emit(
            "agent_task_complete",
            {
                "full_text": "",
                "error": _safe_user_error_text(
                    str(exc2),
                    "本地 AI 调用失败，请检查 Ollama 后重试。",
                ),
            },
            namespace="/doc",
        )
        return None


def _call_llm_sync(prompt: str, use_local_only: bool = False) -> str | None:
    """Non-streaming LLM call (e.g. code generation). Falls back to Ollama on failure."""
    online_model = _pick_online_model()
    # ── Local-only mode ───────────────────────────────────────────────────────
    if use_local_only:
        if not _is_ollama_alive():
            logger.error("[DocAssistant] Local-only sync: Ollama not running")
            return None
        try:
            local = _get_local_provider()
            result = local.generate_content(prompt=prompt, stream=False)
            return result.get("content", "") if isinstance(result, dict) else str(result)
        except Exception as exc_lo:
            logger.error("[DocAssistant] Local-only sync failed: %s", exc_lo)
            return None
    # ── Attempt 1: Online ────────────────────────────────────────────────────
    try:
        provider = _get_provider()
        result = provider.generate_content(
            prompt=prompt,
            model=online_model,
            stream=False,
        )
        return result.get("content", "")
    except Exception as exc:
        if not _is_online_failure(exc):
            logger.error("[DocAssistant] LLM sync call failed: %s", exc)
            return None
        logger.warning("[DocAssistant] Online sync AI failed (%s), trying local…", exc)

    # ── Attempt 2: Local fallback ─────────────────────────────────────────────
    if not _is_ollama_alive():
        logger.error("[DocAssistant] No online model and Ollama unavailable")
        return None
    try:
        local = _get_local_provider()
        result = local.generate_content(prompt=prompt, stream=False)
        return result.get("content", "") if isinstance(result, dict) else str(result)
    except Exception as exc2:
        logger.error("[DocAssistant] Local sync fallback failed: %s", exc2)
        return None


# ══════════════════════════════════════════════════════════════
# Agent Loop Bridge — maps AgentEvent → WebSocket emit()
# ══════════════════════════════════════════════════════════════

def _run_agent_loop(socketio, sid, data: dict) -> None:
    """
    Run a doc_ai_request through the unified KotoAgentLoop.
    Maps AgentEvent objects to existing WebSocket events for
    backward-compatible frontend consumption.
    """
    from app.core.agent.agent_loop import KotoAgentLoop
    from app.core.agent.hooks import HookRegistry
    from app.core.agent.lifecycle import AgentRequest, EventType
    from app.core.agent.pipeline_hooks import register_pipeline_hooks
    from app.core.agent.session_queue import SessionQueue

    # Build AgentRequest from raw WS data
    request = AgentRequest(
        prompt=data.get("prompt", ""),
        session_id=sid or "",
        file_type=data.get("file_type", "unknown"),
        file_name=data.get("file_name", ""),
        context=data.get("context", ""),
        selection=data.get("selection", ""),
        has_selection=data.get("has_selection", False),
        history=data.get("history", []),
        output_mode=data.get("output_mode", "inline"),
        model_mode=normalize_model_mode(data.get("model_mode"), default="auto"),
        language=data.get("language", ""),
        csv_data=data.get("csv_data", ""),
        action_type=data.get("_action_type", ""),
        action_system_prompt=data.get("_action_system_prompt", ""),
        live_doc=data.get("live_doc", False),
        live_mode=data.get("live_mode", "replace"),
    )

    # Set up hooks
    registry = HookRegistry()
    register_pipeline_hooks(registry)

    # Create loop
    loop = KotoAgentLoop(hook_registry=registry)

    # Per-session serialization
    _sq = _get_session_queue()
    with _sq.acquire(request.session_id):
        for event in loop.run(request):
            _emit_agent_event(socketio, sid, event)


def _emit_agent_event(socketio, sid, event) -> None:
    """Map a single AgentEvent to one or more WebSocket emit calls."""
    from app.core.agent.lifecycle import EventType

    etype = event.type
    d = event.data
    ns = "/doc"

    if etype == EventType.STREAM_CHUNK:
        chunk = d.get("chunk", "")
        socketio.emit("agent_stream_chunk", {"chunk": chunk}, namespace=ns, to=sid)
        # Parallel live-doc channel: only when caller opted in
        if d.get("live_doc"):
            socketio.emit("doc_live_chunk", {
                "chunk": chunk,
                "mode": d.get("live_mode", "replace"),
                "request_id": d.get("request_id", ""),
            }, namespace=ns, to=sid)

    elif etype == EventType.LIVE_DOC_COMMIT:
        socketio.emit("doc_live_commit", {
            "full_text": d.get("full_text", ""),
            "mode": d.get("live_mode", "replace"),
            "original_selection": d.get("original_selection", ""),
            "request_id": d.get("request_id", ""),
        }, namespace=ns, to=sid)

    elif etype == EventType.TASK_COMPLETE:
        socketio.emit("agent_task_complete", {
            "result": d.get("result", ""),
            "has_proposals": d.get("has_proposals", False),
            "error": d.get("error", ""),
        }, namespace=ns, to=sid)

    elif etype == EventType.PHASE:
        socketio.emit("agent_phase", {
            "phases": d.get("phases", []),
            "current": d.get("current", ""),
            "status": d.get("status", ""),
        }, namespace=ns, to=sid)

    elif etype == EventType.THOUGHT:
        socketio.emit("agent_event", {
            "type": "thought",
            "text": d.get("text", ""),
        }, namespace=ns, to=sid)

    elif etype == EventType.PLAN:
        socketio.emit("agent_event", {
            "type": "plan",
            "steps": d.get("steps", []),
        }, namespace=ns, to=sid)

    elif etype == EventType.STEP_START:
        socketio.emit("agent_event", {
            "type": "step_start",
            "step_id": d.get("step_id", ""),
            "text": d.get("text", ""),
        }, namespace=ns, to=sid)

    elif etype == EventType.STEP_PROGRESS:
        socketio.emit("agent_event", {
            "type": "step_progress",
            "step_id": d.get("step_id", ""),
            "detail": d.get("detail", ""),
        }, namespace=ns, to=sid)

    elif etype == EventType.STEP_DONE:
        socketio.emit("agent_event", {
            "type": "step_done",
            "step_id": d.get("step_id", ""),
            "text": d.get("text", ""),
        }, namespace=ns, to=sid)

    elif etype == EventType.STEP_ERROR:
        socketio.emit("agent_event", {
            "type": "step_error",
            "step_id": d.get("step_id", ""),
            "error": _safe_user_error_text(
                d.get("error", ""),
                "处理失败，请稍后重试。",
            ),
        }, namespace=ns, to=sid)

    elif etype == EventType.TOOL_CALL:
        tool_call = d.get("tool_call", {}) or {}
        socketio.emit("agent_event", {
            "type": "tool_call",
            "tool_name": tool_call.get("name", ""),
            "tool_args": tool_call.get("args", {}),
        }, namespace=ns, to=sid)

    elif etype == EventType.TOOL_RESULT:
        socketio.emit("agent_event", {
            "type": "tool_result",
            "tool_name": d.get("tool_name", ""),
            "result_preview": _safe_user_preview_text(
                d.get("result_preview", ""),
                "工具已执行。",
            ),
        }, namespace=ns, to=sid)

    elif etype == EventType.STATUS_MESSAGE:
        text = d.get("text", "")
        is_error = d.get("is_error", False)
        if is_error:
            socketio.emit("agent_execute_command", {
                "action": "show_message",
                "text": _safe_user_error_text(text, "AI 调用失败，请稍后重试。"),
                "is_error": True,
            }, namespace=ns, to=sid)
        else:
            socketio.emit("agent_progress", {
                "step": "status",
                "detail": _safe_user_preview_text(text, "处理中…"),
            }, namespace=ns, to=sid)

    elif etype == EventType.PROPOSAL:
        socketio.emit("agent_proposals", {
            "proposals": d.get("proposals", []),
            "summary": d.get("summary", ""),
        }, namespace=ns, to=sid)

    elif etype == EventType.DOC_TOOL_CALL:
        socketio.emit("doc_tool_call", d, namespace=ns, to=sid)

    elif etype == EventType.SKILL_SUGGESTIONS:
        socketio.emit("skill_suggestions", {
            "suggestions": d.get("suggestions", []),
        }, namespace=ns, to=sid)

    elif etype == EventType.RAG_INFO:
        socketio.emit("rag_info", d, namespace=ns, to=sid)
        socketio.emit("agent_event", {
            "type": "rag_info",
            **d,
        }, namespace=ns, to=sid)

    elif etype == EventType.CODE_RESULT:
        socketio.emit("code_result", d, namespace=ns, to=sid)

    elif etype == EventType.ERROR:
        socketio.emit("agent_task_complete", {
            "full_text": "", "error": d.get("text", "未知错误"),
        }, namespace=ns, to=sid)

    elif etype in (EventType.LIFECYCLE_START, EventType.LIFECYCLE_END):
        # New lifecycle events — emit for frontend observability
        socketio.emit("agent_lifecycle", {
            "type": etype.value, **d,
        }, namespace=ns, to=sid)

    # Other event types (THOUGHT, PLAN, etc.) are logged but not emitted yet
    # to maintain backward compatibility with the existing frontend.


# Singleton session queue
_session_queue = None

def _get_session_queue():
    global _session_queue
    if _session_queue is None:
        from app.core.agent.session_queue import SessionQueue
        _session_queue = SessionQueue(global_concurrency=4)
    return _session_queue


# ══════════════════════════════════════════════════════════════
# DocAgent Integration — OpenClaw-style document processing
# ══════════════════════════════════════════════════════════════

def _run_doc_agent(socketio, sid, data: dict) -> None:
    """
    Run a doc_ai_request through the new DocAgent.

    DocAgent provides:
    - LLM-driven task planning with multi-file context
    - Step-by-step execution with progress streaming
    - File change tracking for frontend highlighting
    - Task completion verification
    """
    from app.core.agent.doc_agent import DocAgent, DocTask, FileHandle, DocEventType
    from app.core.agent.doc_event_emitter import DocEventEmitter

    # Build FileHandle objects from data
    files = []

    # Add main file context
    file_path = data.get("file_path", "")
    file_type = data.get("file_type", "unknown")
    file_name = data.get("file_name", "")
    context = data.get("context", "")
    selection = data.get("selection", "")

    if file_path or context:
        files.append(FileHandle(
            path=file_path or file_name or "document",
            file_type=file_type,
            content_snapshot=context[:5000] if context else "",
            selection=selection if selection else None,
        ))

    # Add additional files from open_tabs
    open_tabs = data.get("open_tabs", [])
    for tab in open_tabs[:5]:  # Limit to 5 files
        tab_path = tab.get("path", tab.get("name", ""))
        if tab_path and tab_path != file_path:
            files.append(FileHandle(
                path=tab_path,
                file_type=tab.get("type", ""),
                content_snapshot=tab.get("content", "")[:2000] if tab.get("content") else "",
            ))

    # Build DocTask
    task = DocTask(
        id=data.get("task_id", ""),
        prompt=data.get("prompt", ""),
        files=files,
        permissions={"read", "write", "annotate"},
        session_id=sid,
        history=data.get("history", []),
        options={
            "model_mode": normalize_model_mode(data.get("model_mode"), default="auto"),
            "output_mode": data.get("output_mode", "inline"),
        },
    )

    # Create emitter and agent
    emitter = DocEventEmitter(socketio, sid, namespace="/doc")
    emitter.set_task_id(task.id)

    agent = DocAgent(emitter=emitter)

    # Run and emit events
    for event in agent.run(task):
        _emit_doc_agent_event(socketio, sid, event, emitter)


def _emit_doc_agent_event(socketio, sid, event, emitter) -> None:
    """Map DocAgent events to WebSocket emit calls."""
    from app.core.agent.doc_agent import DocEventType

    etype = event.event_type
    data = event.data
    ns = "/doc"

    if etype == DocEventType.PLAN_START:
        socketio.emit("doc_plan_start", {
            "task_id": event.task_id,
            **data,
        }, namespace=ns, to=sid)

    elif etype == DocEventType.PLAN_CREATED:
        socketio.emit("doc_plan_created", {
            "task_id": event.task_id,
            **data,
        }, namespace=ns, to=sid)

    elif etype == DocEventType.STEP_START:
        socketio.emit("doc_step_start", {
            "task_id": event.task_id,
            "step_id": event.step_id,
            **data,
        }, namespace=ns, to=sid)

    elif etype == DocEventType.STEP_PROGRESS:
        socketio.emit("doc_step_progress", {
            "task_id": event.task_id,
            "step_id": event.step_id,
            **data,
        }, namespace=ns, to=sid)

    elif etype == DocEventType.STEP_DONE:
        socketio.emit("doc_step_done", {
            "task_id": event.task_id,
            "step_id": event.step_id,
            **data,
        }, namespace=ns, to=sid)

    elif etype == DocEventType.STEP_ERROR:
        socketio.emit("doc_step_error", {
            "task_id": event.task_id,
            "step_id": event.step_id,
            **data,
        }, namespace=ns, to=sid)

    elif etype == DocEventType.TOOL_CALL:
        socketio.emit("doc_tool_call", {
            "task_id": event.task_id,
            "step_id": event.step_id,
            **data,
        }, namespace=ns, to=sid)

    elif etype == DocEventType.TOOL_RESULT:
        socketio.emit("doc_tool_result", {
            "task_id": event.task_id,
            "step_id": event.step_id,
            **data,
        }, namespace=ns, to=sid)

    elif etype == DocEventType.FILE_CHANGE:
        socketio.emit("doc_file_change", {
            "task_id": event.task_id,
            "step_id": event.step_id,
            **data,
        }, namespace=ns, to=sid)

    elif etype == DocEventType.HIGHLIGHT:
        socketio.emit("doc_highlight", {
            "task_id": event.task_id,
            **data,
        }, namespace=ns, to=sid)

    elif etype == DocEventType.USER_CONFIRM:
        socketio.emit("doc_user_confirm", {
            "task_id": event.task_id,
            **data,
        }, namespace=ns, to=sid)

    elif etype == DocEventType.REPLAN:
        socketio.emit("doc_replan", {
            "task_id": event.task_id,
            **data,
        }, namespace=ns, to=sid)

    elif etype == DocEventType.THOUGHT:
        # Stream to chat area
        text = data.get("text", "")
        if text:
            socketio.emit("agent_stream_chunk", {
                "chunk": text,
            }, namespace=ns, to=sid)

    elif etype == DocEventType.STREAM_CHUNK:
        socketio.emit("agent_stream_chunk", {
            "chunk": data.get("chunk", ""),
        }, namespace=ns, to=sid)

    elif etype == DocEventType.VERIFICATION:
        socketio.emit("doc_verification", {
            "task_id": event.task_id,
            **data,
        }, namespace=ns, to=sid)

    elif etype == DocEventType.TASK_COMPLETE:
        socketio.emit("agent_task_complete", {
            "task_id": event.task_id,
            "full_text": data.get("summary", ""),
            **data,
        }, namespace=ns, to=sid)

    elif etype == DocEventType.ERROR:
        socketio.emit("doc_error", {
            "task_id": event.task_id,
            **data,
        }, namespace=ns, to=sid)
        # Also emit task_complete with error for frontend compatibility
        socketio.emit("agent_task_complete", {
            "full_text": "",
            "error": data.get("message", "未知错误"),
        }, namespace=ns, to=sid)
