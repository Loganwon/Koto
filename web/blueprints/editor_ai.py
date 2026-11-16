from __future__ import annotations

import json
import logging
import re
import time

from flask import Blueprint, Response, jsonify, request, stream_with_context

from app.core.llm.local_model_runtime import get_configured_local_model_tag
from app.core.llm.model_mode import normalize_model_mode
from app.core.llm.model_selection import (
    get_configured_cloud_model,
    resolve_requested_model_id,
)
from app.core.llm.provider_compat import types as provider_types
from web.tasks.local_executor import LocalExecutor
from app.core.services.editor_ai_text import clean_selection_text
from app.core.services.file_task_stream import stream_file_task_request
from web.sse.sanitizer import safe_sse as _safe_sse



def _sse_response(stream):
    """Wrap a generator into a Flask SSE (Server-Sent Events) Response."""
    return Response(
        stream_with_context(stream),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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


_WORKSPACE_ROUTE_NAMES = {
    "light_chat",
    "web_search",
    "file_task",
    "open_file",
    "system_action",
}
_WORKSPACE_DIRECT_RESPONSE_ROUTES = {
    "light_chat",
    "web_search",
    "open_file",
    "system_action",
}
_WORKSPACE_FILE_TASK_ROUTE_TYPES = {
    "AGENT",
    "CODER",
    "DOC_ANNOTATE",
    "FILE_EDIT",
    "FILE_GEN",
    "FILE_OP",
    "FILE_SEARCH",
    "FILE_TASK",
    "MEETING_EXTRACT",
    "MULTI_STEP",
    "PAINTER",
    "RESEARCH",
    "VISION",
}

def _compact_route_text(text, max_chars: int) -> str:
    """Normalize free-form route metadata so UI state stays compact."""
    if text is None:
        return ""
    normalized = " ".join(str(text).split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1] + "\u2026"


def _normalize_workspace_route(data: dict | None, *, source: str, fallback_task_type: str = "") -> dict | None:
    if not isinstance(data, dict):
        return None
    route = str(data.get("route") or "").strip().lower()
    if route not in _WORKSPACE_ROUTE_NAMES:
        return None
    raw_task_type = str(data.get("task_type") or fallback_task_type or "").strip().upper()
    if raw_task_type == "SYSTEM" and route == "file_task":
        route = "system_action"
    target_path = str(data.get("target_path") or "").strip()
    if route == "open_file" and not target_path:
        route = "file_task"
    route_kind = _canonical_workspace_route_kind(route, data.get("route_kind"))
    task_type = _canonical_workspace_task_type(route, raw_task_type)
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = min(max(confidence, 0.0), 1.0)
    normalized = {
        "ok": True,
        "route_kind": route_kind,
        "base_task_type": "DIRECT_RESPONSE" if route_kind == "direct_response" else "COMPLEX_TASK",
        "route": route,
        "task_type": task_type,
        "source_task_type": raw_task_type if raw_task_type and raw_task_type != task_type else "",
        "confidence": confidence,
        "reason": _compact_route_text(data.get("reason"), 280),
        "target_path": target_path,
        "hint": _compact_route_text(data.get("hint"), 180) or None,
        "route_source": source,
        "keyword_policy": "hint_only",
    }
    if data.get("skip_ai_intent_adjudicator") is True:
        normalized["skip_ai_intent_adjudicator"] = True
    return normalized


def _canonical_workspace_route_kind(route: str, route_kind: str = "") -> str:
    normalized_route = str(route or "").strip().lower()
    normalized_kind = str(route_kind or "").strip().lower()
    if normalized_kind in {"direct_response", "complex_task"}:
        if normalized_kind == "direct_response" and normalized_route == "file_task":
            return "complex_task"
        if normalized_kind == "complex_task" and normalized_route in _WORKSPACE_DIRECT_RESPONSE_ROUTES:
            return "direct_response"
        return normalized_kind
    if normalized_route in _WORKSPACE_DIRECT_RESPONSE_ROUTES:
        return "direct_response"
    return "complex_task"


def _canonical_workspace_task_type(route: str, task_type: str = "") -> str:
    normalized_route = str(route or "").strip().lower()
    normalized_task = str(task_type or "").strip().upper()
    if normalized_route == "web_search":
        return "WEB_SEARCH"
    if normalized_route == "system_action":
        return "SYSTEM"
    if normalized_route == "light_chat":
        return "CHAT"
    if normalized_route in {"file_task", "open_file"}:
        return "FILE_TASK"
    if normalized_task in {"CHAT", "WEB_SEARCH"}:
        return normalized_task
    if normalized_task in _WORKSPACE_FILE_TASK_ROUTE_TYPES:
        return "FILE_TASK"
    return "FILE_TASK"



_FILE_CONTEXT_TASK_RE = re.compile(
    r"(?:当前(?:打开的?)?(?:文件|文档|表格|演示稿)?|这个(?:文件|文档|表格|演示稿)|"
    r"已打开|附件|选区|读取|阅读|查看|总结|概括|归纳|分析|检查|提取|改写|润色|"
    r"翻译|批注|修订|写入|写回|修改|更新|处理|基于|文件|文档|表格|演示稿|"
    r"pdf|docx?|xlsx?|pptx?|txt|md|csv)",
    re.IGNORECASE,
)
_EXPLICIT_FILE_REFERENCE_RE = re.compile(
    r"[\w\u4e00-\u9fff ._()\[\]{}~@#$%^&+=,;!-]{1,180}"
    r"\.(?:pdf|docx?|xlsx?|xlsm|pptx?|txt|md|csv)\b",
    re.IGNORECASE,
)


def _workspace_has_file_context(data: dict) -> bool:
    files = data.get("files") if isinstance(data.get("files"), list) else []
    current_file = data.get("current_file") if isinstance(data.get("current_file"), dict) else None
    if files or data.get("has_selection"):
        return True
    if not current_file:
        return False
    return any(
        str(current_file.get(key) or "").strip()
        for key in ("path", "name", "id", "type", "file_type", "content")
    )


def _workspace_mentions_explicit_task_file(text: str) -> bool:
    return bool(_EXPLICIT_FILE_REFERENCE_RE.search(str(text or "")))


def _deterministic_workspace_route(data: dict) -> dict | None:
    text = str(data.get("text") or data.get("message") or "").strip()
    if not text:
        return None
    try:
        local_executor = LocalExecutor
    except Exception:
        from web.tasks.local_executor import LocalExecutor as local_executor
    if local_executor and local_executor.is_system_command(text):
        return _normalize_workspace_route(
            {
                "route_kind": "direct_response",
                "route": "system_action",
                "task_type": "SYSTEM",
                "confidence": 0.99,
                "reason": "确定性系统动作短路，无需模型路由。",
            },
            source="deterministic:system",
        )
    if _workspace_has_file_context(data) and _FILE_CONTEXT_TASK_RE.search(text):
        return _normalize_workspace_route(
            {
                "route_kind": "complex_task",
                "route": "file_task",
                "task_type": "FILE_TASK",
                "confidence": 0.99,
                "reason": "已有文件上下文且请求明确处理文件，无需模型路由。",
                "skip_ai_intent_adjudicator": True,
            },
            source="deterministic:file_context",
        )
    if _workspace_mentions_explicit_task_file(text) and _FILE_CONTEXT_TASK_RE.search(text):
        return _normalize_workspace_route(
            {
                "route_kind": "complex_task",
                "route": "file_task",
                "task_type": "FILE_TASK",
                "confidence": 0.99,
                "reason": "请求中明确包含文件名且需要文件处理，无需模型路由。",
                "skip_ai_intent_adjudicator": True,
            },
            source="deterministic:explicit_file_reference",
        )
    return None



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

    action_labels = {
        "polish": "润色",
        "translate": "翻译",
        "summary": "总结",
        "check": "检查",
        "rewrite": "改写",
        "continue": "续写",
    }
    label = action_labels.get(action, "")
    if label and selection.startswith(label + "："):
        selection = selection[len(label) + 1:].lstrip()
    elif label and selection.startswith(label + ":"):
        selection = selection[len(label) + 1:].lstrip()
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
    from app.core.agent.kernel import AgentRequest

    action = str(data.get("action") or "").strip().lower()
    selection = str(data.get("selection") or "")
    instruction = str(data.get("instruction") or "")
    full_text = str(data.get("full_text") or data.get("context") or "")
    model_mode = normalize_model_mode(data.get("model_mode"), default="deepseek")
    model_id = str(data.get("model_id") or "").strip()
    preferred_model = resolve_requested_model_id(
        model_id,
        fallback_model=get_configured_cloud_model(fallback_model="deepseek-chat"),
        task_type="CHAT",
    )
    local_model = ""
    try:
        local_model = get_configured_local_model_tag()
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
            "action_type": action,
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
        result_text = str(payload.get("result") or payload.get("text") or "").strip()
        if result_text:
            payload["can_insert"] = True
            payload["action_type"] = data.get("action_type") or ""
        return payload
    if event_type == "error":
        return {"type": "error", "text": data.get("text", "AI 处理失败，请稍后重试。")}
    if event_type == "status_message":
        return {"type": "info", "text": data.get("text", ""), "is_error": data.get("is_error", False)}
    if event_type == "code_result":
        return {"type": "code_result", **data}
    return {"type": event_type, **data}


@editor_ai_bp.route("/api/editor/ai/history", methods=["GET"])
def editor_ai_history():
    """Return editor AI conversation history for the current session."""
    try:
        from flask import session
        chat_history = session.get("koto_editor_chat_history", [])
        session_id = session.get("koto_session_id", "")
        return jsonify({"history": chat_history, "session_id": session_id})
    except Exception:
        return jsonify({"history": [], "session_id": ""})


@editor_ai_bp.route("/api/workspace/ai/route-intent", methods=["POST"])
def workspace_ai_route_intent():
    """Resolve explicit transport facts; let FileTaskRuntime judge ambiguity."""
    data = request.get_json(silent=True) or {}
    text = str(data.get("text") or data.get("message") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "Missing message"}), 400
    started_at = time.perf_counter()

    def _timed_route_response(payload: dict, route_path: str):
        result = dict(payload)
        performance = (
            dict(result.get("performance"))
            if isinstance(result.get("performance"), dict)
            else {}
        )
        performance.update(
            {
                "route_path": route_path,
                "route_decision_ms": round(
                    (time.perf_counter() - started_at) * 1000, 2
                ),
            }
        )
        result["performance"] = performance
        return jsonify(result)

    deterministic_route = _deterministic_workspace_route(data)
    if deterministic_route:
        return _timed_route_response(deterministic_route, "deterministic")

    result = {
        "ok": True,
        "route_kind": "complex_task",
        "base_task_type": "COMPLEX_TASK",
        "route": "file_task",
        "task_type": "FILE_TASK",
        "source_task_type": "",
        "confidence": 1.0,
        "reason": "模糊工作区请求交由 FileTaskRuntime 的模型与工具循环判断。",
        "target_path": "",
        "hint": None,
        "route_source": "kernel_default",
        "keyword_policy": "hint_only",
    }
    return _timed_route_response(result, "kernel_default")

def _stream_editor_quick_action(data: dict):
    """Stream a validated editor quick action without re-reading the request."""
    data = dict(data or {})
    action = str(data.get("action") or "").strip().lower()
    if action not in _EDITOR_AI_STREAM_ACTIONS:
        return jsonify({"error": f"Unsupported editor AI action: {action}"}), 400

    raw_selection = str(data.get("selection") or "")
    selection = clean_selection_text(raw_selection).strip()
    data["selection"] = selection
    full_text = str(data.get("full_text") or data.get("context") or "").strip()
    instruction = str(data.get("instruction") or "").strip()
    if action in {"polish", "translate", "summary", "check", "rewrite", "continue"}:
        if not selection and not full_text:
            return _sse_response(iter([_safe_sse({"type": "error", "text": "没有选中文本或全文上下文"})]))
    if action == "custom_instruction" and not (selection or full_text or instruction):
        return _sse_response(iter([_safe_sse({"type": "error", "text": "请输入指令或选择文本"})]))

    def generate():
        try:
            from app.core.agent.editor_loop_executor import EditorLoopExecutor

            agent_request = _editor_agent_request_from_payload(data)
            for event in EditorLoopExecutor().iter_events(agent_request):
                yield _safe_sse(_agent_event_payload(event))
        except Exception as exc:
            _logger.exception("[editor-ai] stream failed")
            yield _safe_sse({"type": "error", "text": f"AI 处理失败：{exc}"})

    return _sse_response(generate())


@editor_ai_bp.route("/api/editor/ai/stream", methods=["POST"])
def editor_ai_stream():
    """Stream editor quick-action output through the unified AgentLoop."""
    return _stream_editor_quick_action(request.get_json(silent=True) or {})


@editor_ai_bp.route("/api/editor/ai/task-stream", methods=["POST"])
def editor_ai_task_stream():
    """Koto-native file task stream."""
    data = request.get_json(silent=True) or {}
    task = (data.get("task") or data.get("instruction") or "").strip()
    if not task:
        return jsonify({"error": "Missing 'task' parameter"}), 400
    data["task"] = task

    # This endpoint has one lifecycle contract: every request is persisted in
    # TaskLedger and emits the canonical file-task SSE sequence.  Text quick
    # actions used to fall back to the non-persisted editor stream here.  The
    # workspace task runner would then try to resume the client-generated task
    # id through /api/tasks/<id>/stream and receive a 404 because no ledger row
    # existed.  /api/editor/ai/stream remains the explicit editor-only API.
    return _sse_response(stream_file_task_request(data))


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
        return _sse_response(iter([_safe_sse({"type": "error", "text": "缺少数据内容"})]))

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

    return _sse_response(generate())
