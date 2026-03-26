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

logger = logging.getLogger(__name__)

# ── Prompts ────────────────────────────────────────────────────
PROMPTS = {
    "polish": (
        "你是一名专业编辑。请对以下文本进行润色，使其更加流畅、优雅，保持原意不变。"
        "只输出润色后的文本，不要添加任何解释或额外内容："
    ),
    "translate": (
        "请将以下文本翻译（中文→英文，英文→中文）。"
        "只输出翻译结果，不要添加原文或任何解释："
    ),
    "summarize": (
        "请对以下文档内容生成一份简洁的中文摘要，包含关键论点和要点，"
        "摘要控制在 200 字以内："
    ),
    "continue_writing": (
        "你是一名优秀的写作助手。请根据以下已有文本，自然地继续写下去（100-200字），"
        "保持语气和风格一致，衔接流畅。直接输出续写内容，不要重复原文："
    ),
    "rewrite": (
        "你是专业编辑。请对以下文本进行改写：使表达更简洁有力、逻辑更清晰，"
        "保留核心意思但可以调整结构和措辞。只输出改写后的文本，不要添加任何解释："
    ),
    "annotate": (
        "请为以下文本生成简洁的补充注释，格式为【注：…】，说明其关键含义、背景知识"
        "或重要性，控制在 60 字以内。只输出注释内容："
    ),
}


def register_socket_events(socketio):
    """Register all /doc namespace WebSocket event handlers."""

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

        try:
            if action_type in ("polish", "translate", "summarize", "continue_writing",
                           "rewrite", "annotate"):
                _handle_text_action(emit, action_type, payload)
            elif action_type == "custom_instruction":
                _handle_custom(emit, payload)
            elif action_type == "code_exec":
                _handle_code_exec(emit, payload)
            else:
                emit("agent_execute_command", {
                    "action": "show_message",
                    "text": f"未知操作类型: {action_type}",
                    "is_error": True,
                }, namespace="/doc")
        except Exception as exc:
            logger.exception("[DocAssistant] unhandled error: %s", exc)
            emit("agent_execute_command", {
                "action": "show_message",
                "text": f"服务端处理失败: {exc}",
                "is_error": True,
            }, namespace="/doc")


# ── Core text handler (streaming) ─────────────────────────────

def _handle_text_action(emit, action_type, payload):
    """Stream a text transformation result back to the client."""
    text = payload.get("text", "").strip()
    if not text:
        emit("agent_execute_command", {
            "action": "show_message", "text": "输入文本为空。", "is_error": True,
        }, namespace="/doc")
        return

    prompt = PROMPTS[action_type]
    full_result = _stream_llm(emit, prompt, text)

    if full_result is None:
        # Error already emitted inside _stream_llm
        return

    emit("agent_task_complete", {
        "full_text": full_result,
        "message": None,
    }, namespace="/doc")


def _handle_custom(emit, payload):
    """Stream result for an arbitrary user instruction."""
    instruction = payload.get("instruction", "").strip()
    context = payload.get("context") or {}
    context_text = (context.get("text") or "").strip()

    if not instruction:
        emit("agent_execute_command", {
            "action": "show_message", "text": "指令为空。", "is_error": True,
        }, namespace="/doc")
        return

    combined = instruction
    if context_text:
        combined += f"\n\n当前选中的上下文内容：\n{context_text}"

    prompt = "你是 Koto 文件助手。请根据用户的指令处理，直接输出结果："
    full_result = _stream_llm(emit, prompt, combined)
    if full_result is None:
        return

    emit("agent_task_complete", {
        "full_text": full_result,
        "message": None,
    }, namespace="/doc")


# ── Code execution handler ────────────────────────────────────

def _handle_code_exec(emit, payload):
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
            emit("agent_execute_command", {
                "action": "show_message", "text": "未提供代码生成指令。", "is_error": True,
            }, namespace="/doc")
            return

        gen_prompt = (
            f"请根据以下任务描述，编写一段可直接运行的 {language} 代码。\n"
            "只输出代码内容，不要加任何 markdown 代码块标记（``` 等）：\n\n"
            f"任务：{user_instruction}"
        )
        if data_context:
            gen_prompt += f"\n\n数据上下文：\n{data_context}"

        code = _call_llm_sync(gen_prompt)
        if code is None:
            emit("agent_execute_command", {
                "action": "show_message",
                "text": "❌ LLM 代码生成失败，请检查 GEMINI_API_KEY 配置。",
                "is_error": True,
            }, namespace="/doc")
            return

        # Echo the generated code to the panel
        emit("agent_execute_command", {
            "action": "show_message",
            "text": f"```{language}\n{code}\n```",
        }, namespace="/doc")

    if not code:
        emit("agent_execute_command", {
            "action": "show_message", "text": "代码为空。", "is_error": True,
        }, namespace="/doc")
        return

    # Run in sandbox
    try:
        if language in ("python", "py"):
            result = run_python(code)
        elif language in ("r",):
            result = run_r(code)
        else:
            result = {"error": f"不支持的语言: {language}", "stdout": "", "stderr": "", "files": {}}

        emit("code_result", result, namespace="/doc")
    except Exception as exc:
        logger.exception("[DocAssistant] sandbox error: %s", exc)
        emit("code_result", {"error": str(exc), "stdout": "", "stderr": "", "files": {}}, namespace="/doc")


# ── LLM helpers — 使用 Koto 统一 LLM Provider 体系 ────────────

_DOC_MODEL = "gemini-3-flash-preview"


def _get_provider():
    """Return the configured LLMProvider (respects API key, retries, fallbacks)."""
    from app.core.llm.provider_factory import get_llm_provider
    return get_llm_provider()


def _stream_llm(emit, prompt, text):
    """
    Stream LLM output chunk-by-chunk via agent_stream_chunk events.
    Uses Koto's GeminiProvider with retry/fallback support.
    Returns the full assembled text on success, or None on failure.
    """
    try:
        provider = _get_provider()
        gen = provider.generate_content(
            prompt=f"{prompt}\n\n{text}",
            model=_DOC_MODEL,
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
        logger.error("[DocAssistant] LLM streaming failed: %s", exc)
        emit("agent_execute_command", {
            "action": "show_message",
            "text": f"❌ AI 调用失败：{exc}",
            "is_error": True,
        }, namespace="/doc")
        emit("agent_task_complete", {"full_text": "", "error": str(exc)}, namespace="/doc")
        return None


def _call_llm_sync(prompt):
    """Non-streaming LLM call (e.g. code generation). Returns text or None."""
    try:
        provider = _get_provider()
        result = provider.generate_content(
            prompt=prompt,
            model=_DOC_MODEL,
            stream=False,
        )
        return result.get("content", "")
    except Exception as exc:
        logger.error("[DocAssistant] LLM sync call failed: %s", exc)
        return None

