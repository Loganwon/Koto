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

from app.core.agent import llm_provider_helpers
from app.core.llm.model_mode import is_explicit_model_mode, normalize_model_mode
from app.core.security.output_validator import sanitize_user_visible_text
from app.core.shared import llm_helpers

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

        # ── Agent Loop path (unified agent) ─────────
        _use_agent_loop = data.get("_use_agent_loop", True)
        if not _use_agent_loop:
            try:
                from app.core.config.user_settings import SettingsManager as _SM
                _use_agent_loop = bool(_SM().get("ai", "use_agent_loop"))
            except Exception:
                pass

        # ── DocAgent path (new multi-file document processor) ─────────
        _use_doc_agent = data.get("_use_doc_agent", False)
        if not _use_doc_agent:
            try:
                from app.core.config.user_settings import SettingsManager as _SM
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

        code = llm_provider_helpers.call_llm_sync(gen_prompt, use_local_only=use_local_only)
        if code is None:
            emit(
                "agent_execute_command",
                {
                    "action": "show_message",
                    "text": "❌ LLM 代码生成失败，请检查 DEEPSEEK_API_KEY 配置。",
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


_ONLINE_DOC_MODELS = ["deepseek-chat"]


def _pick_online_model() -> str:
    """Use the current CHAT model when available; otherwise use the preferred fallback."""
    try:
        from app.core.llm.model_selection import get_configured_cloud_model

        m = get_configured_cloud_model(task_type="CHAT", fallback_model=_ONLINE_DOC_MODELS[0])
        if m:
            return m
    except Exception:
        pass
    return _ONLINE_DOC_MODELS[0]


def _get_provider():
    """Return the configured online LLMProvider."""
    from app.core.llm.provider_factory import get_llm_provider
    from app.core.llm.model_selection import get_provider_for_model_mode

    model = _pick_online_model()
    return get_llm_provider(
        provider=get_provider_for_model_mode("cloud"),
        model=model,
        allow_local_fallback=False,
    )


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
        if not llm_helpers.is_ollama_alive():
            emit(
                "agent_execute_command",
                {"action": "show_message", "text": "❌ 本地模式下 Ollama 未运行，请启动 Ollama。", "is_error": True},
                namespace="/doc",
            )
            emit("agent_task_complete", {"full_text": "", "error": "ollama not running"}, namespace="/doc")
            return None
        try:
            local = llm_helpers.get_local_provider()
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
        if not llm_helpers.is_online_failure(exc):
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
    if not llm_helpers.is_ollama_alive():
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
        local = llm_helpers.get_local_provider()
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


# ══════════════════════════════════════════════════════════════
# Agent Loop Bridge — maps AgentEvent → WebSocket emit()
# ══════════════════════════════════════════════════════════════

def _run_agent_loop(socketio, sid, data: dict) -> None:
    """
    Run a doc_ai_request through the DocWebSocketLoopExecutor.
    Maps AgentEvent objects to existing WebSocket events for
    backward-compatible frontend consumption.
    """
    from app.core.agent.doc_websocket_loop_executor import DocWebSocketLoopExecutor

    request = _build_doc_agent_request(sid, data)
    for event in DocWebSocketLoopExecutor().iter_events(request, _get_session_queue()):
        _emit_agent_event(socketio, sid, event)


def _build_doc_agent_request(sid: str, data: dict) -> "AgentRequest":
    """Build an AgentRequest from raw WebSocket data."""
    from app.core.agent.lifecycle import AgentRequest
    return AgentRequest(
        prompt=str(data.get("prompt") or ""),
        session_id=sid or "",
        file_type=str(data.get("file_type") or "unknown"),
        file_name=str(data.get("file_name") or ""),
        context=str(data.get("context") or ""),
        selection=str(data.get("selection") or ""),
        has_selection=bool(data.get("has_selection", False)),
        history=data.get("history") if isinstance(data.get("history"), list) else [],
        output_mode=str(data.get("output_mode") or "inline"),
        model_mode=normalize_model_mode(data.get("model_mode"), default="auto"),
        language=str(data.get("language") or ""),
        csv_data=str(data.get("csv_data") or ""),
        action_type=str(data.get("_action_type") or ""),
        action_system_prompt=str(data.get("_action_system_prompt") or ""),
        live_doc=bool(data.get("live_doc", False)),
        live_mode=str(data.get("live_mode") or "replace"),
    )


def _emit_agent_event(socketio, sid, event) -> None:
    """Map a single AgentEvent to one or more WebSocket emit calls."""
    from app.core.agent.doc_websocket_event_mapper import emit_agent_event

    emit_agent_event(socketio, sid, event)


# Singleton session queue
_session_queue = None

def _get_session_queue():
    global _session_queue
    if _session_queue is None:
        from app.core.agent.session_queue import SessionQueue
        _session_queue = SessionQueue(global_concurrency=4)
    return _session_queue


# ══════════════════════════════════════════════════════════════
# DocAgent Integration — document processing
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
