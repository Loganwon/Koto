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
import re

logger = logging.getLogger(__name__)

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

        # Respect use_local_only: from payload override, or from user settings
        _req_local = payload.get("model_mode", data.get("model_mode", "")) == "local"
        if not _req_local:
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
                    "text": f"服务端处理失败: {exc}",
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
        model_mode = data.get("model_mode", "auto")  # 'local' | 'auto'
        # FloatingToolbar actions pass a pre-built system prompt via this field
        action_system_prompt = data.get("_action_system_prompt", "")  # overrides system_instruction
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
                    socketio.emit(
                        "code_result",
                        {
                            "error": f"Sandbox 模块加载失败: {e}",
                            "stdout": "",
                            "stderr": "",
                            "files": {},
                        },
                        namespace="/doc",
                    )
                    return

                # Ask AI to write the code
                lang_label = (
                    "Python (matplotlib/pandas)"
                    if language == "python"
                    else "R (ggplot2)"
                )
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
                socketio.emit(
                    "agent_stream_chunk",
                    {"chunk": f"🤖 正在为你生成 {language.upper()} 代码…\n"},
                    namespace="/doc",
                )

                code = _call_llm_sync(gen_prompt)
                if not code:
                    socketio.emit(
                        "code_result",
                        {
                            "error": "AI 代码生成失败，请检查 API Key 配置。",
                            "stdout": "",
                            "stderr": "",
                            "files": {},
                        },
                        namespace="/doc",
                    )
                    return

                # Strip markdown fences if model added them despite instructions
                import re as _re

                code = _re.sub(r"^```[a-z]*\n?", "", code.strip(), flags=_re.MULTILINE)
                code = code.strip().strip("`")

                # Echo generated code
                socketio.emit(
                    "agent_stream_chunk",
                    {"chunk": f"\n```{language}\n{code}\n```\n\n▶ 正在执行…\n"},
                    namespace="/doc",
                )

                # Execute
                if language == "python":
                    result = run_python(code)
                else:
                    result = run_r(code)

                socketio.emit("code_result", result, namespace="/doc")

            socketio.start_background_task(_code_task)
            return

        # ── Normal text chat mode ──────────────────────────────────────────
        def _task():
            import sys as _sys

            try:
                _task_body()
            except Exception as _task_exc:
                print(
                    f"[DocAI] _task EXCEPTION: {_task_exc!r}",
                    file=_sys.stderr,
                    flush=True,
                )
                socketio.emit(
                    "agent_task_complete",
                    {"full_text": "", "error": f"内部错误：{_task_exc}"},
                    namespace="/doc",
                )

        def _task_body():
            import time as _time

            # ── Progress helper ───────────────────────────────────────────────
            def _emit_progress(step, detail=""):
                socketio.emit(
                    "agent_progress",
                    {"step": step, "detail": detail, "ts": _time.time()},
                    namespace="/doc",
                    to=sid,
                )

            _emit_progress("analyzing", "正在分析上下文…")

            # ── Build system instruction ──────────────────────────────────────
            file_ctx = f"文件名：{file_name}，" if file_name else ""

            # FloatingToolbar actions (polish, translate, rewrite, etc.) send a
            # pre-built system prompt via _action_system_prompt.  When present,
            # skip the generic document-editing instruction so the AI focuses on
            # the text transformation task and does NOT output <TOOL> tags.
            if action_system_prompt:
                system_instruction = action_system_prompt

            elif output_mode == "chat":
                # Chat-only mode: plain conversation, no tool calls
                system_instruction = (
                    f"你是 Koto 文档 AI 助手。当前文件：{file_ctx}类型 {file_type}。\n"
                    "用户当前处于【仅对话模式】，你的回复只会显示在聊天栏，不会修改文档。\n"
                    "请直接用自然语言回答用户的问题或提供建议，支持 Markdown 格式。\n"
                    "不要输出任何 <TOOL> 标签或 JSON 指令。"
                )
            elif file_type == "pptx":
                # PPTX-specific: use set_pptx_text exclusively — never set_html
                if has_selection:
                    action_hint = (
                        "用户选中了某个文本框的文字（见[用户选中的文字]）。"
                        "修改时必须使用 set_pptx_text 指令，"
                        "slide_index 和 shape_id 从[PPT幻灯片内容]中读取，禁止使用 set_html。"
                    )
                else:
                    action_hint = (
                        "修改幻灯片文字必须使用 set_pptx_text 指令，"
                        "slide_index 和 shape_id 从[PPT幻灯片内容]中读取，禁止使用 set_html。"
                    )
                system_instruction = (
                    f"你是 Koto PPT AI 助手。当前文件：{file_ctx}类型 pptx。\n\n"
                    "【重要规则】\n"
                    "当用户要求修改、翻译、润色幻灯片文字时，必须在回复末尾输出修改指令。\n"
                    "不要只描述——直接输出指令让程序执行。\n\n"
                    "指令格式（必须一行完整输出）：\n"
                    '<TOOL>{"type":"set_pptx_text","slide_index":N,"shape_id":M,"value":"新内容"}</TOOL>\n\n'
                    "示例 — 修改标题：\n"
                    "上下文：[PPT幻灯片1内容, slide_index=0]\n"
                    '[shape_id=2 name="标题"]: 原标题\n'
                    "用户：把标题改成「季度总结」\n"
                    'AI：好的。<TOOL>{"type":"set_pptx_text","slide_index":0,"shape_id":2,"value":"季度总结"}</TOOL>\n\n'
                    f"{action_hint}\n"
                )
            else:
                if has_selection:
                    action_hint = "用户当前有选中文字。修改时用 set_html 替换选区内容。"
                else:
                    action_hint = "用户当前无选区。修改时用 set_html 在光标处插入内容。"
                # Concise, example-driven prompt that small local models can follow reliably
                system_instruction = (
                    f"你是 Koto 文档 AI 助手。当前文件：{file_ctx}类型 {file_type}。\n\n"
                    "【重要规则】\n"
                    "当用户要求插入、修改、翻译、润色等文档操作时，你必须在回复末尾输出修改指令。\n"
                    "不要只描述你会做什么——直接输出指令，让程序执行。\n\n"
                    "修改指令格式（必须完整、一行输出）：\n"
                    '<TOOL>{"type": "set_html", "value": "<p>内容</p>"}</TOOL>\n\n'
                    "示例 1 — 用户让你插入内容：\n"
                    "用户：写一行「你好世界」插入文档\n"
                    'AI：已插入。<TOOL>{"type": "set_html", "value": "<p>你好世界</p>"}</TOOL>\n\n'
                    "示例 2 — 用户让你翻译并插入：\n"
                    "用户：翻译成英文插入文档\n"
                    'AI：<TOOL>{"type": "set_html", "value": "<p>Hello world</p>"}</TOOL>\n\n'
                    "示例 3 — 用户说「在光标处插入」（明确插入指令）：\n"
                    "用户：请在光标处插入\n"
                    'AI：已插入。<TOOL>{"type": "set_html", "value": "<p>上一步生成的内容</p>"}</TOOL>\n\n'
                    f"{action_hint}\n"
                    "其他文件类型指令：\n"
                    '  XLSX → <TOOL>{"type":"set_cell","r":0,"c":0,"value":"值"}</TOOL>\n'
                    '  PPTX → <TOOL>{"type":"set_pptx_text","slide_index":0,"shape_id":1,"value":"新文字"}</TOOL>'
                )

            # ── Inject user memory context (L0-L3) ────────────────────────
            try:
                from app.core.app_context import ctx as _ctx
                _mem_mgr = _ctx.memory_manager
                if _mem_mgr is not None:
                    _mem_ctx = _mem_mgr.get_context_string(prompt, history=history)
                    if _mem_ctx:
                        system_instruction = f"{_mem_ctx}\n\n{system_instruction}"
            except Exception as _mem_exc:
                logger.debug("[DocAI] Memory injection skipped: %s", _mem_exc)

            # ── Build prompt with multi-turn history ──────────────────────
            # Assemble history (最多保留最近 10 轮，防止 token 超限)
            MAX_HISTORY_TURNS = 10
            recent_history = history[-MAX_HISTORY_TURNS * 2 :] if history else []
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

            # Build full prompt: optional table data + selection context + history + user message
            # csv_data is injected here so text-mode AI (summarize, translate, etc.)
            # can see structured table content — previously it was ignored (P3 fix).
            csv_block = f"[表格数据（CSV）]\n{csv_data}\n\n" if csv_data else ""
            if selection:
                full_prompt = (
                    f'[用户选中的文字]\n"{selection}"\n\n'
                    f"{csv_block}"
                    f"{history_text}用户：{prompt}"
                )
            else:
                full_prompt = f"{csv_block}{history_text}用户：{prompt}"
            online_model = _pick_online_model()
            logger.warning(
                "[DocAI] model=%s prompt_len=%d history_turns=%d sid=%s",
                online_model,
                len(full_prompt),
                len(recent_history) // 2,
                sid,
            )

            _emit_progress("generating", "正在生成回复…")

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
                        socketio.emit(
                            "agent_stream_chunk",
                            {"chunk": part},
                            namespace="/doc",
                        )
                return "".join(full)

            def _try_local():
                if not _is_ollama_alive():
                    return None
                local = _get_local_provider()
                # Local Ollama: fold system_instruction into the prompt
                local_prompt = f"[系统指令]\n{system_instruction}\n\n{full_prompt}"
                gen = local.generate_content(prompt=local_prompt, stream=True)
                full = []
                for chunk in gen:
                    part = (
                        chunk.get("content", "")
                        if isinstance(chunk, dict)
                        else str(chunk)
                    )
                    if part:
                        full.append(part)
                        socketio.emit(
                            "agent_stream_chunk",
                            {"chunk": part},
                            namespace="/doc",
                        )
                return "".join(full)

            result_text = None
            # Respect "use local only" setting — skip online entirely
            # Either the SettingsManager flag OR the per-request model_mode='local'
            use_local_only = model_mode == "local"
            if not use_local_only:
                try:
                    from web.settings import SettingsManager as _SM

                    use_local_only = bool(_SM().get("ai", "use_local_only"))
                except Exception:
                    pass

            if use_local_only:
                try:
                    result_text = _try_local()
                except Exception as exc2:
                    logger.error(
                        "[WorkspaceAssistant] Local-only mode, local failed: %s", exc2
                    )
                if not result_text:
                    socketio.emit(
                        "agent_task_complete",
                        {
                            "result": "❌ 本地模型未运行。请在终端执行：\n  ollama serve\n若尚未拉取模型，请先执行：\n  ollama pull qwen2.5:7b"
                        },
                        namespace="/doc",
                    )
                    return
            else:
                try:
                    result_text = _try_online()
                except Exception as exc:
                    logger.warning(
                        "[DocAI] online failed: %s: %s", type(exc).__name__, exc
                    )
                    if _is_online_failure(exc):
                        result_text = None  # will fall through to local below
                    else:
                        logger.error(
                            "[WorkspaceAssistant] AI task failed: %s",
                            exc,
                            exc_info=True,
                        )
                        socketio.emit(
                            "agent_task_complete",
                            {"full_text": "", "error": f"AI 处理失败：{exc}"},
                            namespace="/doc",
                        )
                        return

                # Fall back to local if online returned nothing (silent error) or failed
                if not result_text:
                    logger.warning(
                        "[WorkspaceAssistant] Online AI returned empty, trying local…"
                    )
                    socketio.emit(
                        "agent_execute_command",
                        {
                            "action": "show_message",
                            "text": "⚠️ 云端 AI 暂时不可用，已自动切换到本地模型 (Ollama)，响应速度可能较慢。",
                            "is_error": False,
                        },
                        namespace="/doc",
                        to=sid,
                    )
                    try:
                        result_text = _try_local()
                    except Exception as exc2:
                        logger.error(
                            "[WorkspaceAssistant] Local fallback failed: %s", exc2
                        )
                        result_text = None
                    if not result_text:
                        socketio.emit(
                            "agent_task_complete",
                            {
                                "full_text": "",
                                "error": "在线 AI 不可用，本地 Ollama 也未运行。\n请执行: ollama serve，或在 config/gemini_config.env 配置 API 密钥。"
                            },
                            namespace="/doc",
                        )
                        return

            # ── Parse and emit any embedded tool calls ────────────────────
            clean_text, tool_calls = _parse_tool_calls(result_text or "")

            # ── Fallback: user said "insert at cursor" but AI produced no tool call ──
            # Synthesise a set_html from the last assistant turn in history so the
            # content actually lands in the document instead of just being echoed.
            _INSERT_TRIGGERS = (
                "在光标处插入",
                "插入文档",
                "插入到文档",
                "请插入",
                "插入内容",
                "写入文档",
            )
            if (
                not tool_calls
                and file_type in ("docx", "pptx")
                and any(t in prompt for t in _INSERT_TRIGGERS)
            ):
                # Find the last assistant message that has substantive content
                last_ai_content = ""
                for turn in reversed(history or []):
                    if turn.get("role") == "assistant":
                        c = turn.get("content", "").strip()
                        # Strip any existing TOOL tags and short ack messages
                        c_clean = re.sub(
                            r"<TOOL>.*?</TOOL>", "", c, flags=re.DOTALL
                        ).strip()
                        if len(c_clean) > 10:
                            last_ai_content = c_clean
                            break
                if last_ai_content:
                    import html as _html

                    # Convert plain markdown-ish text to minimal HTML paragraphs
                    paragraphs = [
                        p.strip() for p in last_ai_content.split("\n") if p.strip()
                    ]
                    html_val = "".join(f"<p>{_html.escape(p)}</p>" for p in paragraphs)
                    tool_calls = [{"type": "set_html", "value": html_val}]
                    logger.info(
                        "[DocAI] Synthesised set_html from last assistant turn (insert fallback)"
                    )

            # Emit tool calls BEFORE task_complete so the browser has
            # pendingToolCall set when agent_task_complete fires.
            has_proposals = False
            if output_mode != "chat":
                # ── Construct proposals when user had a pinned selection ───────
                if selection and tool_calls:
                    proposals = []
                    for idx, tc in enumerate(tool_calls):
                        proposed = tc.get("value", "")
                        if proposed:
                            proposals.append({
                                "id": f"p_{idx}",
                                "original_text": selection,
                                "proposed_text": proposed,
                                "rationale": clean_text or "",
                                "tool_call": tc,
                            })
                    if proposals:
                        has_proposals = True
                        _emit_progress("formatting", "正在准备修改建议…")
                        socketio.emit(
                            "agent_proposals",
                            {"proposals": proposals, "summary": clean_text},
                            namespace="/doc",
                            to=sid,
                        )
                else:
                    for tc in tool_calls:
                        socketio.emit("doc_tool_call", tc, namespace="/doc", to=sid)

            _emit_progress("complete", "")
            socketio.emit(
                "agent_task_complete",
                {"result": clean_text, "has_proposals": has_proposals},
                namespace="/doc",
                to=sid,
            )

        socketio.start_background_task(_task)

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
            {"error": str(exc), "stdout": "", "stderr": "", "files": {}},
            namespace="/doc",
        )


# ── LLM helpers — 使用 Koto 统一 LLM Provider 体系 ────────────


def _parse_tool_calls(text: str):
    """
    Parse embedded <TOOL>JSON</TOOL> blocks from AI response text.
    Also catches bare JSON and code-fenced JSON emitted by smaller local models
    that don't reliably wrap with <TOOL> tags.
    Returns (clean_text, list_of_tool_call_dicts).
    Tool calls are stripped from the visible text before display.
    """
    import json as _json
    import re

    tool_calls = []
    _KNOWN_TYPES = {"set_html", "set_cell", "set_cells", "set_pptx_text"}

    def _try_parse(raw: str):
        raw = raw.strip()
        try:
            tc = _json.loads(raw)
            if isinstance(tc, dict) and tc.get("type") in _KNOWN_TYPES:
                tool_calls.append(tc)
                return True
        except Exception:
            pass
        return False

    # Pass 1: explicit <TOOL>…</TOOL> wrapper (preferred format)
    # Accept closing tag variants: </TOOL>, </ TOOL>, </tool>
    pattern = re.compile(r"<TOOL>(.*?)<\s*/\s*TOOL>", re.DOTALL | re.IGNORECASE)

    def _replace(m):
        _try_parse(m.group(1))
        return ""

    text = pattern.sub(_replace, text).strip()

    # Strip any orphaned opening/closing TOOL tags that didn't pair (model error)
    text = re.sub(r"<\s*/?\s*TOOL\s*>", "", text, flags=re.IGNORECASE).strip()

    # Pass 2: code-fenced JSON block  ```json {...} ```  or  ``` {...} ```
    fence_pat = re.compile(r"```(?:json)?\s*(\{[^`]+\})\s*```", re.DOTALL)

    def _replace_fence(m):
        if _try_parse(m.group(1)):
            return ""
        return m.group(0)

    text = fence_pat.sub(_replace_fence, text).strip()

    # Pass 3: bare JSON on its own line that looks like a tool call
    # Match lines starting with {"type": "set_html" ...} (greedy to closing brace)
    line_pat = re.compile(
        r'(?:^|\n)\s*(\{"type":\s*"(?:set_html|set_cell|set_cells|set_pptx_text)".*?\})\s*(?=\n|$)',
        re.DOTALL,
    )

    def _replace_line(m):
        if _try_parse(m.group(1)):
            return ""
        return m.group(0)

    text = line_pat.sub(_replace_line, text).strip()

    return text, tool_calls


_ONLINE_DOC_MODELS = [
    "gemini-3-flash-preview",  # 首选：最新快速模型
    "gemini-2.5-flash",  # 备用稳定模型
    "gemini-2.0-flash-lite",  # 轻量兜底
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
    """True if local Ollama is reachable within 2 seconds.

    Uses an explicit no-proxy opener so Windows system proxy settings
    (e.g. Clash / VPN) do not intercept the localhost connection.
    """
    try:
        import urllib.request as _ur

        # Bypass system proxy — Ollama is always on localhost
        _opener = _ur.build_opener(_ur.ProxyHandler({}))
        _opener.open("http://127.0.0.1:11434/api/tags", timeout=2).close()
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
        import json as _json
        import urllib.request as _ur

        # Bypass system proxy — Ollama is always on localhost
        _opener = _ur.build_opener(_ur.ProxyHandler({}))
        with _opener.open("http://127.0.0.1:11434/api/tags", timeout=3) as r:
            tags = _json.loads(r.read())
        models = [m["name"] for m in tags.get("models", [])]
        if models:
            # Prefer larger/better models by simple heuristic
            preferred = next(
                (
                    m
                    for m in models
                    if any(
                        k in m.lower() for k in ("7b", "8b", "13b", "14b", "32b", "70b")
                    )
                ),
                models[0],
            )
            logger.info("[DocAI] Using local model: %s", preferred)
            return OllamaLLMProvider(model=preferred)
    except Exception as e:
        logger.warning("[DocAI] Could not query Ollama model list: %s", e)
    return OllamaLLMProvider(model=None)


def _is_online_failure(exc: Exception) -> bool:
    """Return True if the exception is a recoverable online-availability failure.

    Checks both the string representation AND numeric status_code attribute so
    google.genai SDK errors (which carry exc.status_code) are caught even when
    their str() doesn't contain the status number.
    """
    # ── Numeric status code (google.genai / httpx exceptions) ────────────────
    _status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if _status_code is not None:
        try:
            _sc = int(_status_code)
            if _sc in (400, 429, 500, 503):
                return True
        except (TypeError, ValueError):
            pass

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
        # Region restriction — fall back to local instead of showing bare error
        or "location is not supported" in s
        or "failed_precondition" in s
        or "user_location_invalid" in s
        # Network-level failures (connection drop, deadline, disconnect)
        or "deadline_exceeded" in s
        or "server disconnected" in s
        or "disconnected without" in s
        or "connection reset" in s
        or "connection aborted" in s
        or "backend error" in s
        or "service temporarily unavailable" in s
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
            emit("agent_task_complete", {"full_text": "", "error": str(exc_lo)}, namespace="/doc")
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
                    "text": f"❌ AI 调用失败：{exc}",
                    "is_error": True,
                },
                namespace="/doc",
            )
            emit(
                "agent_task_complete",
                {"full_text": "", "error": str(exc)},
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
            {"full_text": "", "error": str(exc2)},
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
