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
            if action_type in ("polish", "translate", "summarize", "continue_writing"):
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

    @socketio.on("doc_ai_request", namespace="/doc")
    def on_doc_ai_request(data):
        """全格式工作区 AI 交互 — streaming text or code-exec (chart generation)."""
        from flask import request as _req
        sid = _req.sid
        prompt = data.get("prompt", "")
        context = data.get("context", "")          # document context (sent separately)
        selection = data.get("selection", "")      # Copilot-style pinned selection text
        file_type = data.get("file_type", "unknown")
        file_name = data.get("file_name", "")        # filename for system prompt context
        has_selection = data.get("has_selection", False)  # whether editor has a text selection
        history = data.get("history", [])            # [{role, content}] multi-turn history
        language = data.get("language", "")          # "python" | "r" | "" → text mode
        csv_data = data.get("csv_data", "")          # table CSV for chart context
        if not prompt:
            return
        # Combine document context with prompt
        if context:
            prompt = f"{context}\n[用户请求]: {prompt}"

        # ── Chart / code-exec mode ─────────────────────────────────────────
        if language in ("python", "r"):
            def _code_task():
                try:
                    from app.core.sandbox import run_python, run_r
                except ImportError as e:
                    socketio.emit("code_result",
                                  {"error": f"Sandbox 模块加载失败: {e}", "stdout": "",
                                   "stderr": "", "files": {}},
                                  namespace="/doc", to=sid)
                    return

                # Ask AI to write the code
                lang_label = "Python (matplotlib/pandas)" if language == "python" else "R (ggplot2)"
                gen_prompt = (
                    f"请根据以下任务，编写一段可以直接运行的 {lang_label} 代码。\n"
                    "要求：\n"
                    "1. 使用 matplotlib 或 pandas 绘图（Python）/ ggplot2（R）\n"
                    "2. 将生成的图表保存为当前目录下的 chart.png 文件\n"
                    "3. 对于 Python：使用 plt.savefig('chart.png', dpi=150, bbox_inches='tight')\n"
                    "4. 对于 R：使用 ggsave('chart.png', dpi=150)\n"
                    "5. 不要用 plt.show() 或任何 GUI 调用\n"
                    "6. 只输出代码，不要任何 markdown 代码块标记（不要 ```）\n\n"
                    f"任务描述：{prompt}\n"
                )
                if csv_data:
                    gen_prompt += f"\n表格数据（CSV 格式）：\n{csv_data}\n"

                # Emit "正在生成代码..." hint
                socketio.emit("agent_stream_chunk", {"chunk": f"🤖 正在为你生成 {language.upper()} 代码…\n"},
                              namespace="/doc", to=sid)

                code = _call_llm_sync(gen_prompt)
                if not code:
                    socketio.emit("code_result",
                                  {"error": "AI 代码生成失败，请检查 API Key 配置。",
                                   "stdout": "", "stderr": "", "files": {}},
                                  namespace="/doc", to=sid)
                    return

                # Strip markdown fences if model added them despite instructions
                import re as _re
                code = _re.sub(r'^```[a-z]*\n?', '', code.strip(), flags=_re.MULTILINE)
                code = code.strip().strip('`')

                # Echo generated code
                socketio.emit("agent_stream_chunk",
                              {"chunk": f"\n```{language}\n{code}\n```\n\n▶ 正在执行…\n"},
                              namespace="/doc", to=sid)

                # Execute
                if language == "python":
                    result = run_python(code)
                else:
                    result = run_r(code)

                socketio.emit("code_result", result, namespace="/doc", to=sid)

            socketio.start_background_task(_code_task)
            return

        # ── Normal text chat mode ──────────────────────────────────────────
        def _task():
            # ── Build system instruction (Koto-aligned, document-aware) ──
            file_ctx = f"文件名：{file_name}，" if file_name else ""
            selection_hint = (
                "用户当前有选中文字，如需修改文档请在回复后附带 <TOOL> 指令替换选区。"
                if has_selection else
                "用户当前无选区，如需修改文档请在回复后附带 <TOOL> 指令在光标处插入。"
            )
            system_instruction = (
                "你是 Koto 文档 AI 助手，直接运行在用户的文件工作区中。\n"
                f"当前文件类型：{file_type}。{file_ctx}\n"
                "你的职责：\n"
                "  1. 直接、准确地回答用户关于文档的问题。\n"
                "  2. 当用户要求修改文档内容时，在回复末尾附上操作指令（见下方格式）。\n"
                "  3. 回复使用 Markdown 格式，结构清晰。\n\n"
                "【文档修改指令格式】\n"
                "当需要修改文档时，在回复结尾单独一行附上：\n"
                "<TOOL>{\"type\": \"set_html\", \"value\": \"<p>新内容</p>\"}</TOOL>\n"
                "指令类型说明：\n"
                "  DOCX → set_html: value 为完整的 HTML 片段（支持 <h1>~<h6>, <p>, <strong>, <em>, <ul>, <ol>, <li>, <table>）\n"
                "  XLSX → set_cell: {\"type\":\"set_cell\",\"r\":行号,\"c\":列号,\"value\":\"值\"}\n"
                "         set_cells: {\"type\":\"set_cells\",\"cells\":[{\"r\":0,\"c\":0,\"value\":\"A1\"}]}\n"
                "  PPTX → set_pptx_text: {\"type\":\"set_pptx_text\",\"slide_index\":0,\"shape_id\":1,\"value\":\"新文字\"}\n"
                f"{selection_hint}"
            )

            # ── Build prompt with multi-turn history ──────────────────────
            # Assemble history (最多保留最近 10 轮，防止 token 超限)
            MAX_HISTORY_TURNS = 10
            recent_history = history[-MAX_HISTORY_TURNS * 2:] if history else []
            history_text = ""
            if recent_history:
                parts = []
                for turn in recent_history:
                    role = turn.get("role", "")
                    content = turn.get("content", "")
                    if role == "user":
                        parts.append(f"用户：{content}")
                    elif role == "assistant":
                        parts.append(f"Koto AI：{content}")
                history_text = "\n".join(parts) + "\n\n"

            # Build full prompt: optional selection context first, then history, then user message
            if selection:
                full_prompt = (
                    f"[用户选中的文字]\n\"{selection}\"\n\n"
                    f"{history_text}用户：{prompt}"
                )
            else:
                full_prompt = f"{history_text}用户：{prompt}"
            online_model = _pick_online_model()
            logger.warning("[DocAI] model=%s prompt_len=%d history_turns=%d sid=%s",
                           online_model, len(full_prompt), len(recent_history) // 2, sid)

            def _try_online():
                provider = _get_provider()
                gen = provider.generate_content(
                    prompt=full_prompt,
                    model=online_model,
                    system_instruction=system_instruction,
                    stream=True,
                )
                full = []
                for chunk in gen:
                    part = chunk.get("content", "")
                    if part:
                        full.append(part)
                        socketio.emit("agent_stream_chunk", {"chunk": part},
                                      namespace="/doc", to=sid)
                return "".join(full)

            def _try_local():
                if not _is_ollama_alive():
                    return None
                socketio.emit("agent_stream_chunk",
                              {"chunk": "⚡ 在线模型暂时繁忙，已切换至本地 AI…\n\n"},
                              namespace="/doc", to=sid)
                local = _get_local_provider()
                # Local Ollama: fold system_instruction into the prompt
                local_prompt = f"[系统指令]\n{system_instruction}\n\n{full_prompt}"
                gen = local.generate_content(prompt=local_prompt, stream=True)
                full = []
                for chunk in gen:
                    part = chunk.get("content", "") if isinstance(chunk, dict) else str(chunk)
                    if part:
                        full.append(part)
                        socketio.emit("agent_stream_chunk", {"chunk": part},
                                      namespace="/doc", to=sid)
                return "".join(full)

            result_text = None
            # Respect "use local only" setting — skip online entirely
            use_local_only = False
            try:
                from web.settings import SettingsManager as _SM
                use_local_only = bool(_SM().get("ai", "use_local_only"))
            except Exception:
                pass

            if use_local_only:
                try:
                    result_text = _try_local()
                except Exception as exc2:
                    logger.error("[WorkspaceAssistant] Local-only mode, local failed: %s", exc2)
                if not result_text:
                    socketio.emit("agent_task_complete",
                                  {"result": "❌ 本地模型不可用，请确认 Ollama 已启动并加载了模型。"},
                                  namespace="/doc", to=sid)
                    return
            else:
                try:
                    result_text = _try_online()
                except Exception as exc:
                    logger.warning("[DocAI] online failed: %s: %s", type(exc).__name__, exc)
                    if _is_online_failure(exc):
                        logger.warning("[WorkspaceAssistant] Online AI failed (%s), trying local…", exc)
                        try:
                            result_text = _try_local()
                        except Exception as exc2:
                            logger.error("[WorkspaceAssistant] Local fallback failed: %s", exc2)
                            result_text = None
                        if result_text is None:
                            socketio.emit("agent_task_complete",
                                          {"result": f"❌ AI 暂时不可用（在线模型不可用，本地模型也未运行）。请启动 Ollama 或配置有效的 API 密钥。"},
                                          namespace="/doc", to=sid)
                            return
                    else:
                        logger.error("[WorkspaceAssistant] AI task failed: %s", exc, exc_info=True)
                        socketio.emit("agent_task_complete",
                                      {"result": f"❌ AI 处理失败：{exc}"},
                                      namespace="/doc", to=sid)
                        return

            # ── Parse and emit any embedded tool calls ────────────────────
            clean_text, tool_calls = _parse_tool_calls(result_text or "")

            socketio.emit("agent_task_complete", {"result": clean_text},
                          namespace="/doc", to=sid)

            for tc in tool_calls:
                socketio.emit("doc_tool_call", tc, namespace="/doc", to=sid)

        socketio.start_background_task(_task)


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

def _parse_tool_calls(text: str):
    """
    Parse embedded <TOOL>JSON</TOOL> blocks from AI response text.
    Returns (clean_text, list_of_tool_call_dicts).
    Tool calls are stripped from the visible text before display.
    """
    import re
    import json as _json

    tool_calls = []
    pattern = re.compile(r'<TOOL>(.*?)</TOOL>', re.DOTALL)

    def _replace(m):
        raw = m.group(1).strip()
        try:
            tc = _json.loads(raw)
            if isinstance(tc, dict) and "type" in tc:
                tool_calls.append(tc)
        except Exception:
            logger.warning("[DocAI] Failed to parse tool call JSON: %.100s", raw)
        return ""  # remove from displayed text

    clean = pattern.sub(_replace, text).strip()
    return clean, tool_calls



_ONLINE_DOC_MODELS = [
    "gemini-3-flash-preview",  # 首选：最新快速模型
    "gemini-2.5-flash",        # 备用稳定模型
    "gemini-2.0-flash-lite",   # 轻量兜底
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
    return get_llm_provider()


def _is_ollama_alive() -> bool:
    """True if local Ollama is reachable within 2 seconds."""
    try:
        import urllib.request as _ur
        _ur.urlopen("http://localhost:11434/api/tags", timeout=2).close()
        return True
    except Exception:
        return False


def _get_local_provider():
    """Return OllamaLLMProvider with the best available local model.

    Queries /api/tags directly to avoid depending on LocalModelRouter which
    may not have a pick_best_chat_model() method.  Falls back to model=None
    (which uses OllamaLLMProvider's own auto-selection) if the query fails.
    """
    from app.core.llm.ollama_llm_provider import OllamaLLMProvider
    try:
        import urllib.request as _ur, json as _json
        with _ur.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            tags = _json.loads(r.read())
        models = [m["name"] for m in tags.get("models", [])]
        if models:
            # Prefer larger/better models by simple heuristic
            preferred = next(
                (m for m in models if any(k in m.lower() for k in ("7b", "8b", "13b", "14b", "32b", "70b"))),
                models[0]
            )
            logger.info("[DocAI] Using local model: %s", preferred)
            return OllamaLLMProvider(model=preferred)
    except Exception as e:
        logger.warning("[DocAI] Could not query Ollama model list: %s", e)
    return OllamaLLMProvider(model=None)


def _is_online_failure(exc: Exception) -> bool:
    """Return True if the exception is a recoverable online-availability failure.

    Includes hard API-key failures (400 INVALID_ARGUMENT / expired) so the
    handler automatically falls back to local Ollama instead of showing a raw
    error to the user.
    """
    s = str(exc).lower()
    return (
        "timed out" in s
        or "stream stalled" in s
        or "503" in s
        or "unavailable" in s
        or "timeout" in s
        or "resourceexhausted" in s
        or "resource_exhausted" in s
        or "429" in s
        or "overloaded" in s
        or "quota" in s
        # API key issues — treat as "online unavailable" so local Ollama takes over
        or "invalid_argument" in s
        or "api key" in s
        or "api_key" in s
        or "expired" in s
        or "400" in s
    )


def _stream_llm(emit, prompt, text):
    """
    Stream LLM output with dual-mode fallback:
      1. Try the best available online Gemini model.
      2. On timeout/503/unavailable → fall back to local Ollama if running.
    Returns the full assembled text on success, or None on failure.
    """
    full_prompt = f"{prompt}\n\n{text}"
    online_model = _pick_online_model()

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
            logger.error("[DocAssistant] LLM streaming failed (non-recoverable): %s", exc)
            emit("agent_execute_command", {
                "action": "show_message",
                "text": f"❌ AI 调用失败：{exc}",
                "is_error": True,
            }, namespace="/doc")
            emit("agent_task_complete", {"full_text": "", "error": str(exc)}, namespace="/doc")
            return None
        logger.warning("[DocAssistant] Online AI unavailable (%s), trying local…", exc)

    # ── Attempt 2: Local (Ollama) fallback ───────────────────────────────────
    if not _is_ollama_alive():
        emit("agent_execute_command", {
            "action": "show_message",
            "text": "❌ 在线 AI 暂时不可用，本地模型也未运行。请稍后重试或启动 Ollama。",
            "is_error": True,
        }, namespace="/doc")
        emit("agent_task_complete", {"full_text": "", "error": "all providers failed"}, namespace="/doc")
        return None

    try:
        emit("agent_stream_chunk",
             {"chunk": "⚡ 在线模型暂时繁忙，已切换至本地 AI…\n\n"},
             namespace="/doc")
        local = _get_local_provider()
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
        emit("agent_execute_command", {
            "action": "show_message",
            "text": f"❌ 在线和本地 AI 均不可用，请检查网络和 Ollama 状态。",
            "is_error": True,
        }, namespace="/doc")
        emit("agent_task_complete", {"full_text": "", "error": str(exc2)}, namespace="/doc")
        return None


def _call_llm_sync(prompt: str) -> str | None:
    """Non-streaming LLM call (e.g. code generation). Falls back to Ollama on failure."""
    online_model = _pick_online_model()
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

