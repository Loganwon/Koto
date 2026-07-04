from __future__ import annotations

import json
import logging
import re
import time

from flask import Blueprint, Response, jsonify, request, stream_with_context

from web.runtime_context import (
    get_configured_local_model_id,
    get_client_proxy,
    get_create_client,
    get_local_executor,
    get_model_id,
    get_smart_dispatcher,
    get_types,
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

_WORKSPACE_ROUTE_JUDGE_INSTRUCTION = """你是 Koto 文件助手的统一路由判断器。

你的任务是根据用户输入、当前文件上下文、选区和最近对话，判断应该进入哪条产品路径。

第一层只允许两类 route_kind:
- direct_response: 只需要直接回应或轻量产品动作，不需要结构化任务流程。包括 chat、web_search、能确定目标的 open_file、受控本地系统动作 system_action。
- complex_task: 涉及文件内容读取、文件生成/修改/批注/转换/对比，或需要多步骤处理、监管、核验的任务。

第二层 route 只表示 direct_response 或 complex_task 内的具体执行路径:
- light_chat: direct_response，普通对话、概念解释、追问、无需文件执行过程的回答。
- web_search: direct_response，需要外部实时信息、网页资料、来源核查或联网检索的回答。
- open_file: direct_response，用户的主要意图是打开本地文件，且上下文中能确定目标文件。
- system_action: direct_response，用户的主要意图是执行受控本地系统动作，例如查看时间/系统状态，或打开白名单桌面应用。
- file_task: complex_task，需要读取、分析、生成、修改、批注、转换、对比或保存文件；或者需要展示结构化任务流程。

重要原则:
- 你必须基于语义和上下文判断，不能因为单个词直接决定 route。
- 词汇信号只能作为提示，不是规则。例如时效词、价格、新闻、天气、打开、生成、修改、总结、分析、文件名等都只是线索。
- 如果用户只是闲聊或问通用知识，即使旁边有打开的文档，也可以选择 light_chat。
- 如果用户要求处理当前文档、附件、选区或产出文件，应选择 file_task。
- 如果回答必须知道当前文件/附件/选区里的具体内容，即使用户只要求总结、解释、问答或只读分析，也应选择 file_task；不要用 light_chat 代替真实文件读取。
- 如果用户需要实时/最新/网页来源，应选择 web_search。

只输出 JSON:
{
  "route_kind": "direct_response | complex_task",
  "route": "light_chat | web_search | file_task | open_file | system_action",
  "task_type": "CHAT | WEB_SEARCH | FILE_TASK | SYSTEM",
  "confidence": 0.0,
  "reason": "一句话说明",
  "target_path": null,
  "hint": null
}
"""


def _safe_sse(payload: dict) -> str:
    return safe_editor_sse(payload)


def _sse_response(stream):
    return Response(
        stream_with_context(stream),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _compact_route_text(value, limit: int = 1200) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _compact_workspace_route_payload(data: dict) -> dict:
    history = data.get("history") if isinstance(data.get("history"), list) else []
    files = data.get("files") if isinstance(data.get("files"), list) else []
    compact_files = []
    for item in files[:8]:
        if not isinstance(item, dict):
            continue
        compact_files.append(
            {
                "name": _compact_route_text(item.get("name"), 160),
                "path": _compact_route_text(item.get("path"), 240),
                "type": _compact_route_text(item.get("type") or item.get("file_type"), 40),
                "target": bool(item.get("target")),
                "content_preview": _compact_route_text(item.get("content") or item.get("content_preview"), 600),
            }
        )

    compact_history = []
    for turn in history[-8:]:
        if not isinstance(turn, dict):
            continue
        compact_history.append(
            {
                "role": _compact_route_text(turn.get("role"), 24),
                "content": _compact_route_text(turn.get("content") or turn.get("text"), 900),
            }
        )

    current_file = data.get("current_file") if isinstance(data.get("current_file"), dict) else None
    return {
        "message": _compact_route_text(data.get("text") or data.get("message"), 2000),
        "has_selection": bool(data.get("has_selection")),
        "selection_preview": _compact_route_text(data.get("selection_preview"), 800),
        "files": compact_files,
        "current_file": {
            "name": _compact_route_text(current_file.get("name"), 160),
            "path": _compact_route_text(current_file.get("path"), 240),
            "type": _compact_route_text(current_file.get("type") or current_file.get("file_type"), 40),
        }
        if current_file
        else None,
        "history": compact_history,
    }


def _extract_route_response_text(response) -> str:
    if isinstance(response, dict):
        for key in ("content", "text", "response", "message"):
            text = response.get(key)
            if isinstance(text, str) and text.strip():
                return text.strip()
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        joined = "".join(str(getattr(part, "text", "") or "") for part in parts).strip()
        if joined:
            return joined
    return ""


def _parse_route_json(raw: str) -> dict | None:
    source = str(raw or "").strip()
    if not source:
        return None
    try:
        parsed = json.loads(source)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", source)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


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


def _workspace_route_from_task_type(task_type: str) -> str:
    normalized = str(task_type or "").strip().upper()
    if normalized == "WEB_SEARCH":
        return "web_search"
    if normalized == "SYSTEM":
        return "system_action"
    if normalized == "CHAT":
        return "light_chat"
    if normalized in _WORKSPACE_FILE_TASK_ROUTE_TYPES:
        return "file_task"
    return "file_task"


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
        local_executor = get_local_executor()
    except Exception:
        from web.local_executor import LocalExecutor as local_executor
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


def _fallback_workspace_route(data: dict) -> dict:
    text = str(data.get("text") or data.get("message") or "").strip()
    history = data.get("history") if isinstance(data.get("history"), list) else []
    files = data.get("files") if isinstance(data.get("files"), list) else []
    current_file = data.get("current_file") if isinstance(data.get("current_file"), dict) else None
    file_type = ""
    for item in files:
        if isinstance(item, dict) and (item.get("type") or item.get("file_type")):
            file_type = str(item.get("type") or item.get("file_type") or "")
            break
    if not file_type and current_file:
        file_type = str(current_file.get("type") or current_file.get("file_type") or "")
    file_context = {
        "has_file": bool(files or current_file or data.get("has_selection")),
        "file_type": file_type,
    }
    try:
        try:
            dispatcher = get_smart_dispatcher()
        except RuntimeError:
            from app.core.routing.smart_dispatcher import SmartDispatcher as dispatcher

        task_type, route_method, context_info = dispatcher.analyze(
            text,
            history,
            file_context=file_context,
        )
        route = _workspace_route_from_task_type(task_type)
        canonical_task_type = _canonical_workspace_task_type(route, task_type)
        return {
            "ok": True,
            "route_kind": _canonical_workspace_route_kind(route),
            "base_task_type": "DIRECT_RESPONSE"
            if _canonical_workspace_route_kind(route) == "direct_response"
            else "COMPLEX_TASK",
            "route": route,
            "task_type": canonical_task_type,
            "source_task_type": str(task_type or "").strip().upper()
            if str(task_type or "").strip().upper() != canonical_task_type
            else "",
            "confidence": 0.0,
            "reason": "模型路由不可用，已使用后端 SmartDispatcher 兜底。",
            "target_path": "",
            "hint": (context_info or {}).get("skill_prompt") if isinstance(context_info, dict) else None,
            "route_source": str(route_method or "smart_dispatcher_fallback"),
            "keyword_policy": "hint_only",
        }
    except Exception as exc:
        _logger.warning("[workspace-route] fallback dispatcher failed: %s", exc)
        return {
            "ok": True,
            "route_kind": "complex_task",
            "base_task_type": "COMPLEX_TASK",
            "route": "file_task",
            "task_type": "FILE_TASK",
            "confidence": 0.0,
            "reason": "路由服务暂不可用，保持文件任务路径。",
            "target_path": "",
            "hint": None,
            "route_source": "fallback:file_task",
            "keyword_policy": "hint_only",
        }


def _model_workspace_route(data: dict) -> dict | None:
    requested_model = str(data.get("model_id") or "").strip()
    requested_mode = normalize_model_mode(data.get("model_mode"), default="deepseek")
    payload = _compact_workspace_route_payload(data)
    prompt = "请判断以下 Koto 工作区消息应该进入哪条路径。\n\n上下文 JSON:\n" + json.dumps(
        payload,
        ensure_ascii=False,
    )
    try:
        from app.core.llm.model_selection import get_provider_for_model_mode
        route_provider = get_provider_for_model_mode(requested_mode)
    except Exception:
        route_provider = "deepseek" if requested_mode == "deepseek" else "gemini"

    if route_provider == "deepseek" or requested_model.lower().startswith("deepseek"):
        from app.core.llm.deepseek_config import DEEPSEEK_DEFAULT_MODEL
        from app.core.llm.provider_factory import get_llm_provider

        model_id = requested_model or DEEPSEEK_DEFAULT_MODEL
        provider = get_llm_provider(provider="deepseek", model=model_id)
        response = provider.generate_content(
            prompt=prompt,
            model=model_id,
            system_instruction=_WORKSPACE_ROUTE_JUDGE_INSTRUCTION,
            temperature=0.1,
            max_tokens=600,
            extra_body={"thinking": {"type": "disabled"}},
            response_format={"type": "json_object"},
        )
        parsed = _parse_route_json(_extract_route_response_text(response))
        return _normalize_workspace_route(parsed, source=f"model:{model_id}")

    client = get_client_proxy()
    types = get_types()
    if client is None or types is None or not hasattr(client, "models"):
        return None

    model_id = resolve_requested_model_id(
        requested_model,
        fallback_model=get_model_id("CHAT", "gemini-2.5-flash"),
        task_type="CHAT",
    )
    config = types.GenerateContentConfig(
        system_instruction=_WORKSPACE_ROUTE_JUDGE_INSTRUCTION,
        max_output_tokens=220,
        temperature=0.1,
        response_mime_type="application/json",
    )
    source_model_id = model_id
    try:
        response = client.models.generate_content(
            model=model_id,
            contents=prompt,
            config=config,
        )
    except Exception as exc:
        exc_text = str(exc)
        if (
            "model is required" not in exc_text
            and "Ollama" not in exc_text
            and "not found" not in exc_text
            and "not supported for generateContent" not in exc_text
        ):
            raise
        create_client = get_create_client()
        if not callable(create_client):
            raise
        cloud_model_id = model_id if model_id.startswith("gemini-") else "gemini-2.5-flash"
        source_model_id = cloud_model_id
        response = create_client().models.generate_content(
            model=cloud_model_id,
            contents=prompt,
            config=config,
        )
    parsed = _parse_route_json(_extract_route_response_text(response))
    return _normalize_workspace_route(parsed, source=f"model:{source_model_id}")


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
    model_mode = normalize_model_mode(data.get("model_mode"), default="deepseek")
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


def _agent_step_events(step) -> list[dict]:
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
    """Model-first workspace assistant route decision."""
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
                "route_decision_ms": round((time.perf_counter() - started_at) * 1000, 2),
            }
        )
        result["performance"] = performance
        return jsonify(result)

    deterministic_route = _deterministic_workspace_route(data)
    if deterministic_route:
        return _timed_route_response(deterministic_route, "deterministic")
    try:
        model_route = _model_workspace_route(data)
        if model_route:
            return _timed_route_response(model_route, "model")
    except Exception as exc:
        _logger.warning("[workspace-route] model route failed: %s", exc)
    return _timed_route_response(_fallback_workspace_route(data), "fallback")


@editor_ai_bp.route("/api/editor/ai/agent", methods=["POST"])
def editor_ai_agent():
    """SSE wrapper for the structured editor agent route."""
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
              for payload in _agent_step_events(step):
                  yield _safe_sse(payload)
      except Exception as exc:
          _logger.exception("[editor-ai] structured agent failed")
          yield _safe_sse({"type": "error", "text": f"Agent 处理失败：{exc}"})

    return _sse_response(generate())


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
            return _sse_response(iter([_safe_sse({"type": "error", "text": "没有选中文本或全文上下文"})]))
    if action == "custom_instruction" and not (selection or full_text or instruction):
        return _sse_response(iter([_safe_sse({"type": "error", "text": "请输入指令或选择文本"})]))

    def generate():
        try:
            from app.core.agent.legacy_loop_facade import iter_editor_agent_events

            agent_request = _editor_agent_request_from_payload(data)
            for event in iter_editor_agent_events(agent_request):
                yield _safe_sse(_agent_event_payload(event))
        except Exception as exc:
            _logger.exception("[editor-ai] stream failed")
            yield _safe_sse({"type": "error", "text": f"AI 处理失败：{exc}"})

    return _sse_response(generate())


@editor_ai_bp.route("/api/editor/ai/task-stream", methods=["POST"])
def editor_ai_task_stream():
    """Koto-native file task stream."""
    data = request.get_json(silent=True) or {}
    task = (data.get("task") or data.get("instruction") or "").strip()
    if not task:
        return jsonify({"error": "Missing 'task' parameter"}), 400
    data["task"] = task
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
    try:
        from app.core.skills.registry import SkillRegistry
        file_type = request.args.get("file_type", "").strip().lower()
        all_skills = SkillRegistry.list_all()
        enabled = [s for s in all_skills if s.get("enabled", True)]
        if file_type:
            enabled = [s for s in enabled if file_type in (s.get("file_types") or s.get("tags") or [])]
        return jsonify({"skills": enabled})
    except Exception:
        _logger.exception("[editor-ai] skill-list failed")
        return jsonify({"skills": []})
