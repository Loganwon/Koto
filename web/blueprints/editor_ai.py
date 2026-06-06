from __future__ import annotations

import logging

from flask import Blueprint, Response, jsonify, request, stream_with_context

from web.runtime_context import (
    get_configured_local_model_id,
    get_model_id,
    normalize_model_mode,
    resolve_requested_model_id,
    safe_editor_sse,
    stream_file_task_request,
)


editor_ai_bp = Blueprint("editor_ai", __name__)
_logger = logging.getLogger("koto.routes.editor_ai")

_EDITOR_AI_STREAM_ACTIONS = {
    "polish",
    "translate",
    "summary",
    "find_replace",
    "find_reference",
    "check",
    "rewrite",
    "continue",
    "custom_instruction",
    "chart",
}


def _safe_sse(payload: dict) -> str:
    return safe_editor_sse(payload)


def _truncate_context(text: str, max_chars: int = 12000) -> str:
    text = str(text or "")
    if len(text) <= max_chars:
        return text
    head = text[: max_chars // 2]
    tail = text[-(max_chars // 2) :]
    return f"{head}\n\n...[已省略中间内容]...\n\n{tail}"


def _build_editor_prompt(
    action: str,
    selection: str,
    instruction: str = "",
    full_text: str = "",
) -> str:
    """Build the prompt used by editor quick actions."""
    action = str(action or "").strip().lower()
    selection = str(selection or "")
    instruction = str(instruction or "")
    context = _truncate_context(full_text)

    parts = []
    if context:
        parts.append(f"文档全文上下文：\n{context}")
    if selection:
        parts.append(f"当前选中文本：\n{selection}")
    if instruction:
        parts.append(f"用户补充要求：\n{instruction}")

    body = "\n\n".join(parts).strip() or selection or context or instruction
    prompts = {
        "polish": "请润色当前选中文本，保持原意，提升表达清晰度和自然度。只输出润色后的文本。",
        "translate": "请翻译当前文本。若用户未指定目标语言，默认翻译为英文。只输出译文。",
        "summary": "请总结文本的核心观点，输出简洁清晰的要点。",
        "check": "请检查文本中的错别字、语病、事实疑点和表达问题，并给出修改建议。",
        "rewrite": "请在不改变核心含义的前提下改写文本，使表达更顺畅。",
        "continue": "请基于上下文自然续写，保持风格一致。",
        "custom_instruction": "请严格按照用户补充要求处理文本。",
        "find_reference": "请为文本中的关键论述寻找可核查的参考、引用或来源线索，并用列表输出。",
        "find_replace": (
            "请根据用户要求在全文中查找并建议替换内容。必须输出 JSON，格式为："
            '{"replacements":[{"from":"原文","to":"替换文本"}],"summary":"说明"}。'
        ),
        "chart": (
            "请根据 CSV 数据生成 Python matplotlib 图表代码。要求设置中文字体回退："
            "Microsoft YaHei、SimHei、Noto Sans CJK SC、DejaVu Sans；设置 "
            "matplotlib.rcParams['axes.unicode_minus']=False；保存 chart.png，dpi=220。"
        ),
    }
    return f"{prompts.get(action, prompts['custom_instruction'])}\n\n{body}".strip()


def _editor_agent_request_from_payload(data: dict):
    from app.core.agent.lifecycle import AgentRequest

    action = str(data.get("action") or "").strip().lower()
    selection = str(data.get("selection") or "")
    instruction = str(data.get("instruction") or "")
    full_text = str(data.get("full_text") or data.get("context") or "")
    model_mode = normalize_model_mode(data.get("model_mode"), default="cloud")
    model_id = str(data.get("model_id") or "").strip()
    preferred_model = resolve_requested_model_id(
        model_id,
        fallback_model=get_model_id("CHAT", ""),
        task_type="CHAT",
    )
    local_model = ""
    try:
        local_model = get_configured_local_model_id()
    except Exception as exc:
        _logger.debug("[editor-ai] local model config unavailable: %s", exc)

    prompt = _build_editor_prompt(action, selection, instruction, full_text)
    return AgentRequest(
        prompt=prompt,
        session_id=str(data.get("session_id") or ""),
        file_type=str(data.get("file_type") or ""),
        file_name=str(data.get("file_name") or ""),
        context=full_text,
        selection=selection,
        has_selection=bool(selection.strip()),
        history=data.get("history") if isinstance(data.get("history"), list) else [],
        output_mode=str(data.get("output_mode") or "inline"),
        model_mode=model_mode,
        language=str(data.get("lang") or data.get("language") or ""),
        csv_data=str(data.get("csv_data") or data.get("data_context") or ""),
        action_type=action,
        action_system_prompt=prompt,
        live_doc=bool(data.get("live_doc")),
        live_mode=str(data.get("live_mode") or "replace"),
        extra={
            "preferred_model": preferred_model,
            "local_model": local_model,
        },
    )


def _agent_event_payload(event) -> dict:
    event_type = getattr(getattr(event, "type", None), "value", None) or str(
        getattr(event, "type", "")
    )
    data = dict(getattr(event, "data", {}) or {})

    if event_type == "stream_chunk":
        return {"type": "token", "content": data.get("chunk", ""), "text": data.get("chunk", "")}
    if event_type == "stream_block":
        return {"type": "token", "content": data.get("text", ""), "text": data.get("text", "")}
    if event_type == "task_complete":
        payload = {"type": "done", **data}
        if "result" not in payload and "text" in payload:
            payload["result"] = payload["text"]
        return payload
    if event_type == "error":
        return {"type": "error", "text": data.get("text", "AI 处理失败，请稍后重试。")}
    if event_type == "status_message":
        return {"type": "info", "text": data.get("text", ""), "is_error": data.get("is_error", False)}
    if event_type == "code_result":
        return {"type": "code_result", **data}
    return {"type": event_type, **data}


def _legacy_agent_step_events(step) -> list[dict]:
    step_type = getattr(getattr(step, "step_type", None), "value", None) or str(
        getattr(step, "step_type", "")
    )
    content = str(getattr(step, "content", "") or "")
    if "THOUGHT" in step_type or step_type == "thought":
        return [
            {"type": "thought", "content": content, "text": content},
            {"type": "step_start", "step_id": "thought", "text": content or "开始分析"},
        ]
    if "ACTION" in step_type or step_type == "action":
        action = getattr(step, "action", None)
        tool_name = str(getattr(action, "tool_name", "") or "")
        tool_args = getattr(action, "tool_args", {}) or {}
        return [
            {
                "type": "tool_call",
                "tool_name": tool_name,
                "tool_args": tool_args,
                "content": content,
                "text": content,
            }
        ]
    if "OBSERVATION" in step_type or step_type == "observation":
        observation = str(getattr(step, "observation", "") or content)
        return [
            {"type": "tool_result", "content": observation, "text": observation},
            {"type": "step_done", "step_id": "action", "text": observation or "工具执行完成"},
        ]
    if "ANSWER" in step_type or step_type == "answer":
        return [
            {"type": "token", "content": content, "text": content},
            {"type": "done", "result": content},
        ]
    return [{"type": "info", "text": content}]


@editor_ai_bp.route("/api/editor/ai/history", methods=["GET"])
def editor_ai_history():
    """Runtime-only editor AI history compatibility endpoint."""
    return jsonify({"history": [], "session_id": ""})


@editor_ai_bp.route("/api/editor/ai/agent", methods=["POST"])
def editor_ai_agent():
    """Compatibility SSE wrapper for the legacy structured editor agent route."""
    data = request.get_json(silent=True) or {}
    query = str(data.get("query") or data.get("task") or data.get("prompt") or "").strip()
    full_text = str(data.get("full_text") or data.get("context") or "").strip()
    session_id = str(data.get("session_id") or "").strip()

    def generate():
      try:
          from app.api.agent_routes import get_agent

          agent = get_agent()
          system_context = full_text if full_text else None
          for step in agent.run(query, session_id=session_id or None, system_context=system_context):
              for payload in _legacy_agent_step_events(step):
                  yield _safe_sse(payload)
      except Exception as exc:
          _logger.exception("[editor-ai] legacy agent failed")
          yield _safe_sse({"type": "error", "text": f"Agent 处理失败：{exc}"})

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@editor_ai_bp.route("/api/editor/ai/stream", methods=["POST"])
def editor_ai_stream():
    """Stream editor quick-action output through the unified AgentLoop."""
    data = request.get_json(silent=True) or {}
    action = str(data.get("action") or "").strip().lower()
    if action not in _EDITOR_AI_STREAM_ACTIONS:
        return jsonify({"error": f"Unsupported editor AI action: {action}"}), 400

    selection = str(data.get("selection") or "").strip()
    full_text = str(data.get("full_text") or data.get("context") or "").strip()
    instruction = str(data.get("instruction") or "").strip()
    if action in {"polish", "translate", "summary", "check", "rewrite", "continue"}:
        if not selection and not full_text:
            return Response(
                stream_with_context(iter([_safe_sse({"type": "error", "text": "没有选中文本或全文上下文"})])),
                mimetype="text/event-stream",
            )
    if action == "custom_instruction" and not (selection or full_text or instruction):
        return Response(
            stream_with_context(iter([_safe_sse({"type": "error", "text": "请输入指令或选择文本"})])),
            mimetype="text/event-stream",
        )

    def generate():
        try:
            from app.core.agent.agent_loop import KotoAgentLoop

            agent_request = _editor_agent_request_from_payload(data)
            for event in KotoAgentLoop().run(agent_request):
                yield _safe_sse(_agent_event_payload(event))
        except Exception as exc:
            _logger.exception("[editor-ai] stream failed")
            yield _safe_sse({"type": "error", "text": f"AI 处理失败：{exc}"})

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@editor_ai_bp.route("/api/editor/ai/task-stream", methods=["POST"])
def editor_ai_task_stream():
    """Koto-native file task stream."""
    data = request.get_json(silent=True) or {}
    task = (data.get("task") or data.get("instruction") or "").strip()
    if not task:
        return jsonify({"error": "Missing 'task' parameter"}), 400
    data["task"] = task
    return Response(
        stream_with_context(stream_file_task_request(data)),
        mimetype="text/event-stream",
    )


@editor_ai_bp.route("/api/editor/ai/task-stream/cancel", methods=["POST"])
def editor_ai_task_stream_cancel():
    """Request cancellation of an in-flight file task by run_id."""
    from app.core.agent.file_task_runtime import request_cancel

    data = request.get_json(silent=True) or {}
    run_id = str(data.get("run_id") or "").strip()
    if not run_id:
        return jsonify({"error": "Missing 'run_id'"}), 400
    registered = request_cancel(run_id)
    return jsonify({"ok": True, "run_id": run_id, "registered": registered})


@editor_ai_bp.route("/api/editor/ai/chart", methods=["POST"])
def editor_ai_chart():
    """Generate and execute chart code with structured progress events."""
    data = request.get_json(silent=True) or {}
    data_context = str(data.get("data_context") or data.get("csv_data") or data.get("selection") or "").strip()
    instruction = str(data.get("instruction") or "生成图表").strip()
    lang = str(data.get("lang") or data.get("language") or "python").strip().lower()
    if lang not in {"python", "r"}:
        lang = "python"
    if not data_context:
        return Response(
            stream_with_context(iter([_safe_sse({"type": "error", "text": "缺少数据内容"})])),
            mimetype="text/event-stream",
        )

    def _default_python_code() -> str:
        csv_literal = repr(data_context)
        title = instruction.replace("'", "\\'")[:80]
        return (
            "import io\n"
            "import pandas as pd\n"
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            "matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Noto Sans CJK SC', 'DejaVu Sans']\n"
            "matplotlib.rcParams['axes.unicode_minus'] = False\n"
            f"df = pd.read_csv(io.StringIO({csv_literal}))\n"
            "ax = df.plot(kind='bar', x=df.columns[0], y=df.columns[1:]) if len(df.columns) > 1 else df.plot(kind='bar')\n"
            f"ax.set_title('{title}')\n"
            "plt.tight_layout()\n"
            "plt.savefig('chart.png', dpi=220, bbox_inches='tight')\n"
        )

    def generate():
        try:
            yield _safe_sse({"type": "step_start", "step_id": "generate_code", "text": "生成图表代码"})
            code = str(data.get("code") or "").strip() or _default_python_code()
            yield _safe_sse({"type": "code", "lang": lang, "code": code})
            yield _safe_sse({"type": "step_done", "step_id": "generate_code", "text": "代码已生成"})
            yield _safe_sse({"type": "step_start", "step_id": "execute_code", "text": "执行代码"})

            if lang == "r":
                from app.core.sandbox import run_r

                result = run_r(code)
            else:
                from app.core.sandbox import run_python

                result = run_python(code)

            if result.get("stdout"):
                yield _safe_sse({"type": "stdout", "text": result.get("stdout", "")})
            if result.get("stderr"):
                yield _safe_sse({"type": "stderr", "text": result.get("stderr", "")})
            for name, content in (result.get("files") or {}).items():
                yield _safe_sse({"type": "image", "name": name, "data": content})
            if result.get("error"):
                yield _safe_sse({"type": "step_error", "step_id": "execute_code", "error": result.get("error")})
            else:
                yield _safe_sse({"type": "step_done", "step_id": "execute_code", "text": "执行完成"})
            yield _safe_sse({"type": "done", "result": result})
        except Exception as exc:
            _logger.exception("[editor-ai] chart failed")
            yield _safe_sse({"type": "error", "text": f"图表生成失败：{exc}"})

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@editor_ai_bp.route("/api/editor/ai/chart-rerun", methods=["POST"])
def editor_ai_chart_rerun():
    """Compatibility JSON endpoint for rerunning already-generated chart code."""
    data = request.get_json(silent=True) or {}
    code = str(data.get("code") or "").strip()
    lang = str(data.get("lang") or data.get("language") or "python").strip().lower()
    if not code:
        return jsonify({"stdout": "", "stderr": "", "files": {}, "error": "缺少代码内容"})
    if lang not in {"python", "r"}:
        lang = "python"
    try:
        if lang == "r":
            from app.core.sandbox import run_r

            result = run_r(code)
        else:
            from app.core.sandbox import run_python

            result = run_python(code)
        return jsonify(result)
    except Exception as exc:
        _logger.exception("[editor-ai] chart rerun failed")
        return jsonify({"stdout": "", "stderr": "", "files": {}, "error": f"图表代码执行失败：{exc}"})


@editor_ai_bp.route("/api/editor/ai/skill-list", methods=["GET"])
def editor_skill_list():
    """Return editor toolbar skills backed by the native runtime."""
    return jsonify({"skills": []})
