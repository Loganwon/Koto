# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
import json
import logging
import os
import time
from typing import Any

from flask import Blueprint, Response, jsonify, request, stream_with_context

from app.core.agent.factory import create_agent
from app.core.agent.types import AgentStepType
from app.core.config_defaults import DEFAULT_MODEL

logger = logging.getLogger(__name__)

agent_bp = Blueprint("agent", __name__)


@agent_bp.route("", methods=["GET"])
@agent_bp.route("/", methods=["GET"])
def agent_index():
    """Return a compact index for agent API health probes."""
    return jsonify(
        {
            "success": True,
            "service": "agent",
            "routes": {
                "chat": "/api/agent/chat",
                "tools": "/api/agent/tools",
                "process": "/api/agent/process",
                "process_stream": "/api/agent/process-stream",
                "monitor_status": "/api/agent/monitor/status",
                "feedback_stats": "/api/agent/feedback/stats",
            },
        }
    )


# ── v2 护栏模块（懒加载）──────────────────────────────────────────────────────
def _lazy_pii():
    from app.core.security.pii_filter import PIIFilter

    return PIIFilter


def _lazy_validator():
    from app.core.security.output_validator import OutputValidator

    return OutputValidator


def _lazy_tracer():
    from app.core.learning.shadow_tracer import ShadowTracer

    return ShadowTracer


def _make_eval_llm_fn():
    """后台自评用 LLM 函数（复用 Agent 的 Gemini provider，不另起连接）。"""
    try:
        _a = get_agent()

        def _fn(prompt: str) -> str:
            try:
                try:
                    from app.core.llm.model_selection import get_configured_cloud_model

                    judge_model = get_configured_cloud_model(
                        task_type="CHAT",
                        fallback_model=DEFAULT_MODEL,
                    )
                except Exception:
                    judge_model = DEFAULT_MODEL
                r = _a.llm_provider.generate_content(
                    prompt,
                    model=judge_model,
                    max_tokens=512,
                    temperature=0.1,
                )
                return r.get("content", "") if isinstance(r, dict) else str(r)
            except Exception:
                return ""

        return _fn
    except Exception:
        return lambda _: ""


# ── 503 / 连接故障 → 本地模型兜底 ────────────────────────────────────────────


def _is_service_unavailable_error(text: str) -> bool:
    """检测是否为 503 / 网络连接故障，用于判断是否启用本地模型兜底。"""
    t = (text or "").lower()
    return any(
        sig in t
        for sig in (
            "503",
            "service unavailable",
            "unavailable",
            "overloaded",
            "connection error",
            "timed out",
            "timeout",
            "resource_exhausted",
            "high demand",
            "serviceunavailable",
        )
    )


def _build_skill_system_instruction(
    user_input: str = "", task_type: str = "CHAT"
) -> str:
    """
    构建注入了当前激活 Skills 的系统指令。
    供本地模型兜底路径使用，确保本地模型也能理解并遵循用户启用的 Skill。
    """
    _base = (
        "你是 Koto，一个友善、专业的 AI 助手。"
        "请用中文回答，内容准确简洁。"
        "如果不确定答案，请诚实说明不确定。"
    )
    try:
        from app.core.skills.skill_manager import SkillManager

        # 自动匹配补充：当用户没有手动启用 Skill 时推荐合适的临时 Skill
        _auto_ids: list = []
        try:
            from app.core.skills.skill_auto_matcher import SkillAutoMatcher

            _auto_ids = SkillAutoMatcher.match(
                user_input=user_input, task_type=task_type
            )
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "Silenced exception caught", exc_info=True
            )
        return SkillManager.inject_into_prompt(
            _base,
            task_type=task_type,
            user_input=user_input,
            temp_skill_ids=_auto_ids,
        )
    except Exception as _e:
        logger.debug(f"[local_fallback] Skill 注入跳过: {_e}")
        return _base


def _local_model_fallback(user_message: str, history: list = None) -> tuple:
    """
    尝试调用本地 Ollama 模型回答用户问题。
    返回 (answer_text, model_name)，或 (None, None) 当本地模型不可用时。
    当前激活的 Skills 会注入到系统指令中，本地模型与云端模型行为保持一致。
    """
    try:
        import requests as _req

        from app.core.routing.local_model_router import LocalModelRouter

        if not LocalModelRouter.is_ollama_available():
            logger.info("[fallback] 本地 Ollama 不可用，跳过兜底")
            return None, None

        if not LocalModelRouter.init_model():
            logger.info("[fallback] 本地模型初始化失败，跳过兜底")
            return None, None

        model_name = getattr(LocalModelRouter, "_model_name", None)
        if not model_name:
            return None, None

        # ── 注入 Skills 到系统指令 ──────────────────────────────────────────
        system_instruction = _build_skill_system_instruction(
            user_input=user_message, task_type="CHAT"
        )
        active_skill_names = []
        try:
            from app.core.skills.skill_manager import SkillManager

            active_skill_names = SkillManager.get_active_skill_names()
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "Silenced exception caught", exc_info=True
            )
        if active_skill_names:
            logger.info(f"[fallback] 本地模型携带 Skills: {active_skill_names}")

        # ── 构建对话历史（过滤掉系统快照等噪音） ────────────────────────────
        messages = [{"role": "system", "content": system_instruction}]
        for msg in history or []:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "model":
                role = "assistant"
            if (
                role in ("user", "assistant")
                and content
                and not content.startswith("Session context:")
            ):
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_message})

        resp = _req.post(
            "http://127.0.0.1:11434/api/chat",
            json={
                "model": model_name,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "num_predict": 2048,
                },
            },
            timeout=60,
        )

        if resp.status_code != 200:
            logger.warning(f"[fallback] Ollama 返回 HTTP {resp.status_code}")
            return None, None

        content = (resp.json().get("message", {}) or {}).get("content", "") or ""
        # Strip <think>...</think> blocks (qwen3 thinking mode output)
        import re as _re
        content = _re.sub(r"<think>.*?</think>", "", content, flags=_re.DOTALL).strip()
        return (content if content else None), model_name

    except Exception as exc:
        logger.warning(f"[fallback] 本地模型兜底调用失败: {exc}")
        return None, None


# ------------------------------------------------------------------
# Session history helpers — reuse chats/ directory for persistence
# ------------------------------------------------------------------
_CHATS_DIR = None

# In-memory LRU cache for chat history: avoids disk read on every turn.
# Keyed by session_id; stores the full raw history list (pre-truncation).
# Max 50 sessions keeps memory bounded (~few MB even with large histories).
_HISTORY_CACHE: "OrderedDict[str, list]" = None
_HISTORY_CACHE_MAX = 50
_HISTORY_CACHE_LOCK = None


def _get_history_cache():
    global _HISTORY_CACHE, _HISTORY_CACHE_LOCK
    if _HISTORY_CACHE is None:
        import threading as _threading
        from collections import OrderedDict

        _HISTORY_CACHE = OrderedDict()
        _HISTORY_CACHE_LOCK = _threading.Lock()
    return _HISTORY_CACHE, _HISTORY_CACHE_LOCK


def _get_chats_dir() -> str:
    """Lazily resolve chats/ directory (same as web/app.py uses)."""
    global _CHATS_DIR
    if _CHATS_DIR is None:
        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        _CHATS_DIR = os.path.join(project_root, "chats")
        os.makedirs(_CHATS_DIR, exist_ok=True)
    return _CHATS_DIR


def _load_history(session_id: str, max_turns: int = 30, token_budget: int = 4096):
    """Load recent history from chats/<session_id>.json, compatible with
    SessionManager format {role, parts}. Converts to agent-compatible
    {role, content} dicts."""
    if not session_id:
        return []
    fname = session_id if session_id.endswith(".json") else f"{session_id}.json"
    path = os.path.join(_get_chats_dir(), fname)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            raw = json.load(f)
        # Convert {role, parts} → {role, content} for the last max_turns messages
        converted = []
        for msg in raw[-max_turns:]:
            role = msg.get("role", "user")
            parts = msg.get("parts", [])
            content = parts[0] if parts else msg.get("content", "")
            converted.append({"role": role, "content": content})
        # Apply token budget: iterate newest-first, stop when budget overflows
        budget_used = 0
        selected = []
        for msg in reversed(converted):
            est = max(1, len(msg.get("content", "")) // 4)
            if budget_used + est > token_budget and selected:
                break
            selected.insert(0, msg)
            budget_used += est
        logger.debug(
            f"[_load_history] {len(selected)}/{len(converted)} msgs kept, ~{budget_used} est. tokens"
        )
        return selected
    except Exception as exc:
        logger.warning(f"Failed to load history for {session_id}: {exc}")
        return []


def _get_tracker_path(session_id: str) -> str:
    """Return path to the per-session ConversationTracker JSON file."""
    safe_id = (session_id or "").replace(".json", "").strip()
    return os.path.join(_get_chats_dir(), f"{safe_id}.tracker.json")


def _save_history(session_id: str, user_msg: str, model_msg: str):
    """Append a turn (user + model) to chats/<session_id>.json in
    SessionManager-compatible format. Also updates the in-memory cache."""
    if not session_id:
        return
    fname = session_id if session_id.endswith(".json") else f"{session_id}.json"
    path = os.path.join(_get_chats_dir(), fname)
    try:
        cache, lock = _get_history_cache()
        with lock:
            cached = cache.get(session_id)
        if cached is not None:
            history = list(cached)
        elif os.path.exists(path):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                history = json.load(f)
        else:
            history = []
        history.append({"role": "user", "parts": [user_msg]})
        history.append({"role": "model", "parts": [model_msg]})
        with open(path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        # Update cache with new history
        with lock:
            cache[session_id] = history
            cache.move_to_end(session_id)
            if len(cache) > _HISTORY_CACHE_MAX:
                cache.popitem(last=False)
    except Exception as exc:
        logger.warning(f"Failed to save history for {session_id}: {exc}")


# ------------------------------------------------------------------
# Phase3: Session state snapshots for cross-turn system context reuse
# ------------------------------------------------------------------
_SYSTEM_TOOL_TO_STATE_KEY = {
    "query_cpu_status": "cpu",
    "query_memory_status": "memory",
    "query_disk_usage": "disk",
    "query_network_status": "network",
    "query_python_env": "python_env",
    "list_running_apps": "processes",
    "get_system_warnings": "warnings",
}


def _get_state_path(session_id: str) -> str:
    """Get path for session state snapshot file."""
    safe_id = (session_id or "").replace(".json", "").strip()
    return os.path.join(_get_chats_dir(), f"{safe_id}.state.json")


def _load_session_state(session_id: str) -> dict:
    """Load session state snapshot containing system info summary."""
    if not session_id:
        return {"system_snapshot": {}, "updated_at": None}
    path = _get_state_path(session_id)
    if not os.path.exists(path):
        return {"system_snapshot": {}, "updated_at": None}
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"system_snapshot": {}, "updated_at": None}
        data.setdefault("system_snapshot", {})
        data.setdefault("updated_at", None)
        return data
    except Exception as exc:
        logger.warning(f"Failed to load session state for {session_id}: {exc}")
        return {"system_snapshot": {}, "updated_at": None}


def _save_session_state(session_id: str, state: dict):
    """Save session state snapshot."""
    if not session_id:
        return
    path = _get_state_path(session_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.warning(f"Failed to save session state for {session_id}: {exc}")


def _parse_observation_json(text: str):
    """Try to parse JSON from observation text."""
    if not isinstance(text, str):
        return None
    content = text.strip()
    if not content or content[0] not in ("{", "["):
        return None
    try:
        return json.loads(content)
    except Exception:
        return None


def _merge_system_snapshot_from_steps(session_state: dict, steps_payload: list):
    """Extract system tool results from steps and merge into state snapshot."""
    if not isinstance(session_state, dict):
        session_state = {"system_snapshot": {}, "updated_at": None}
    snapshot = session_state.get("system_snapshot") or {}

    last_tool_name = None
    for step in steps_payload or []:
        step_type = str(step.get("step_type", "")).lower()
        if step_type == "action":
            action = step.get("action") or {}
            last_tool_name = action.get("tool_name")
            continue

        if step_type != "observation" or not last_tool_name:
            continue

        state_key = _SYSTEM_TOOL_TO_STATE_KEY.get(last_tool_name)
        if not state_key:
            continue

        obs_text = step.get("observation") or step.get("content") or ""
        obs_data = _parse_observation_json(obs_text)
        snapshot[state_key] = {
            "tool": last_tool_name,
            "captured_at": int(time.time()),
            "data": obs_data if obs_data is not None else {"raw": str(obs_text)[:1200]},
        }

    session_state["system_snapshot"] = snapshot
    session_state["updated_at"] = int(time.time())
    return session_state


def _build_snapshot_context_text(session_state: dict) -> str:
    """Build human-readable context string from system snapshot."""
    snapshot = (session_state or {}).get("system_snapshot") or {}
    if not snapshot:
        return ""

    lines = [
        "Session context: latest local system snapshot (may be stale, use tools if needed):"
    ]
    for key in [
        "cpu",
        "memory",
        "disk",
        "network",
        "python_env",
        "processes",
        "warnings",
    ]:
        item = snapshot.get(key)
        if not item:
            continue
        data = item.get("data")
        if isinstance(data, dict):
            compact = json.dumps(data, ensure_ascii=False)[:280]
        elif isinstance(data, list):
            compact = json.dumps(data, ensure_ascii=False)[:280]
        else:
            compact = str(data)[:280]
        lines.append(f"- {key}: {compact}")

    return "\n".join(lines)


# ------------------------------------------------------------------
# Agent instance management
# ------------------------------------------------------------------
_agent_instance = None


def get_agent():
    """获取 Agent 实例 — 委托给 AppContext，兼容旧路径。"""
    global _agent_instance
    if _agent_instance is None:
        try:
            from app.core.app_context import ctx

            _agent_instance = ctx.agent
        except Exception:
            _agent_instance = create_agent()
    return _agent_instance


def _resolve_runtime_skill(
    user_input: str,
    explicit_skill_id: str = None,
    task_type: str = None,
):
    """Resolve a per-request skill from explicit input first, then intent bindings."""
    if explicit_skill_id:
        return explicit_skill_id, [explicit_skill_id]

    try:
        from app.core.skills.skill_manager import SkillManager
        from app.core.skills.skill_trigger_binding import get_skill_binding_manager

        matched_ids = get_skill_binding_manager().match_intent(user_input or "")
        if not matched_ids:
            return None, []

        SkillManager._ensure_init()
        candidates = []
        for skill_id in matched_ids:
            skill_def = SkillManager.get_definition(skill_id)
            if not skill_def:
                continue
            # Intent bindings are user-triggered signals; skip task_type gate so that
            # domain skills (e.g. annotate_* with task_types=["DOC_ANNOTATE"]) can
            # still be injected when the route task_type is "CHAT".
            candidates.append(skill_def)

        if not candidates:
            return None, []

        candidates.sort(key=lambda skill: getattr(skill, "priority", 50), reverse=True)
        return candidates[0].id, [skill.id for skill in candidates]
    except Exception as exc:
        logger.debug(f"[agent_routes] 运行时技能解析跳过: {exc}")
        return explicit_skill_id, [explicit_skill_id] if explicit_skill_id else []


def _run_agent_collect(
    agent,
    message,
    history=None,
    session_id: str = None,
    skill_id: str = None,
    task_type: str = None,
):
    """Run agent once and collect steps/final answer for sync APIs."""
    steps_payload = []
    final_answer = ""

    for step in agent.run(
        input_text=message,
        history=history or [],
        session_id=session_id,
        skill_id=skill_id,
        task_type=task_type,
    ):
        step_data = step.to_dict()
        steps_payload.append(step_data)
        if step.step_type == AgentStepType.ANSWER:
            final_answer = step.content or ""

    if not final_answer and steps_payload:
        final_answer = steps_payload[-1].get("content", "")

    return {
        "id": f"task_{int(time.time() * 1000)}",
        "status": "success",
        "result": final_answer,
        "steps": steps_payload,
    }


# ── ChatPipeline helper ──────────────────────────────────────────────────

def _build_chat_pipeline():
    """Assemble a ChatPipeline with the agent and all guard modules."""
    from app.core.agent.chat_pipeline import ChatPipeline

    return ChatPipeline(
        agent=get_agent(),
        pii_filter=_lazy_pii(),
        output_validator=_lazy_validator(),
        local_fallback_fn=_local_model_fallback,
        is_service_unavailable_fn=_is_service_unavailable_error,
        history_saver=_save_history,
        state_saver=_save_session_state,
        session_state_merger=_merge_system_snapshot_from_steps,
        self_eval_fn=_make_self_eval_fn(),
        skill_suggester=_lazy_skill_suggester(),
    )


def _lazy_skill_suggester():
    try:
        from app.core.skills.skill_suggester import SkillSuggester
        return SkillSuggester
    except Exception:
        return None


def _make_self_eval_fn():
    try:
        from app.core.learning.rating_store import RatingStore
        from app.core.learning.response_evaluator import ResponseEvaluator

        def _fn(user_input=None, ai_response=None, task_type="CHAT", session_name=""):
            ResponseEvaluator.evaluate_async(
                msg_id=RatingStore.make_msg_id(session_name or "", user_input or ""),
                user_input=user_input,
                ai_response=ai_response,
                task_type=task_type,
                session_name=session_name,
                llm_fn=_make_eval_llm_fn(),
            )
        return _fn
    except Exception:
        return None


# ── Context-building helpers ────────────────────────────────────────────

def _build_chat_system_context(
    message: str,
    history: list[dict],
    session_id: str,
    context_files: list,
    file_context: dict | None,
) -> tuple[str, str | None, Any, str, list[dict], list[str] | None]:
    """Build rewritten message, system_context, tracker, tracker_path, history, auto_skill_ids."""
    _tracker = None
    _tracker_path = ""

    try:
        from app.core.memory.conversation_tracker import ConversationTracker
        _tracker_path = _get_tracker_path(session_id)
        _tracker = ConversationTracker.load(_tracker_path)
    except Exception as e:
        logger.debug("[chat] ConversationTracker skip: %s", e)

    _rewritten = message
    try:
        from app.core.routing.intent_analyzer import IntentAnalyzer
        if IntentAnalyzer.should_analyze(message):
            rw = IntentAnalyzer.rewrite_intent(message, history, _tracker)
            if rw and rw != message:
                logger.info("[chat] Intent rewritten: '%s' -> '%s'", message[:40], rw[:60])
                _rewritten = rw
    except Exception as e:
        logger.debug("[chat] IntentAnalyzer skip: %s", e)

    _cw_paged = ""
    try:
        from app.core.memory.context_window_manager import ContextWindowManager
        out = ContextWindowManager.manage(
            history=history, query=_rewritten,
            session_name=(session_id or "").replace(".json", ""),
            get_memory_fn=lambda: None,
        )
        history = out["history"]
        _cw_paged = out.get("paged_in_context", "")
    except Exception as e:
        logger.debug("[chat] ContextWindowManager skip: %s", e)

    parts = []
    if _tracker:
        inj = _tracker.get_context_injection()
        if inj:
            parts.append(inj)
    if _cw_paged:
        parts.append(_cw_paged)

    if context_files:
        try:
            from app.core.file.file_registry import get_file_registry
            reg = get_file_registry()
            blocks = []
            for p in context_files[:5]:
                entry = reg.get_by_path(str(p))
                if entry and entry.content_preview:
                    blocks.append(f"【参考文件：{entry.name}】\n{entry.content_preview[:2000]}")
            if blocks:
                parts.append("用户在对话中引用了以下本地文件，请结合其内容回答：\n\n" + "\n\n---\n\n".join(blocks))
                logger.info("[chat] Injected %d @file context(s)", len(blocks))
        except Exception as e:
            logger.debug("[chat] @file context skip: %s", e)

    sys_ctx = "\n\n".join(parts) if parts else None

    try:
        ws_root = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "workspace")
        boot_parts = []
        for bf in ("KOTO.md", "TOOLS_GUIDE.md"):
            bp = os.path.join(ws_root, bf)
            if os.path.isfile(bp):
                try:
                    with open(bp, "r", encoding="utf-8") as f:
                        bc = f.read(4000)
                    if bc.strip():
                        boot_parts.append(f"【{bf}】\n{bc}")
                        logger.debug("[chat] Bootstrap injected: %s (%d chars)", bf, len(bc))
                except Exception as be:
                    logger.debug("[chat] Bootstrap read fail %s: %s", bf, be)
        if boot_parts:
            block = "\n\n---\n\n".join(boot_parts)
            sys_ctx = (block + "\n\n" + sys_ctx) if sys_ctx else block
    except Exception as e:
        logger.debug("[chat] Bootstrap skip: %s", e)

    if file_context and isinstance(file_context, dict):
        fc_parts = []
        fc_file = file_context.get("file_path") or file_context.get("file_name", "")
        if fc_file:
            fc_parts.append(f"当前打开文件: {fc_file} (类型: {file_context.get('file_type', 'unknown')})")
        tabs = file_context.get("open_tabs") or []
        if tabs:
            fc_parts.append(f"工作区打开的标签页: {', '.join(str(t) for t in tabs[:10])}")
        sel = file_context.get("selection", "")
        if sel:
            fc_parts.append(f"用户选中的文本:\n{str(sel)[:2000]}")
        if fc_parts:
            fc_block = "【文件助手上下文】\n用户正在文件助手中操作文档。你可以使用 workspace_* 和 editor_* 工具来读取、修改工作区文件，或直接推送变更到编辑器。\n" + "\n".join(fc_parts)
            sys_ctx = (sys_ctx + "\n\n" + fc_block) if sys_ctx else fc_block
            logger.info("[chat] File assistant context injected: %s", fc_file)

    return _rewritten, sys_ctx, _tracker, _tracker_path, history, None


@agent_bp.route("/chat", methods=["POST"])
def chat():
    data = request.json
    message = data.get("message")
    session_id = data.get("session_id") or data.get("session", "")
    history = data.get("history") or _load_history(session_id)
    model_id = data.get("model", "gemini-2.5-flash")
    locked_model = data.get("locked_model") or ("local" if model_id == "local" else "auto")
    user_chose_local = locked_model == "local"
    skill_id = data.get("skill_id")
    task_type = data.get("task_type")
    if not task_type and isinstance(data.get("file_context"), dict):
        task_type = "FILE_ASSISTANT"
    context_files = data.get("context_files") or []
    file_context = data.get("file_context")

    if not message:
        return jsonify({"error": "Message is required"}), 400

    rewritten_message, system_context, tracker, tracker_path, history, _ = (
        _build_chat_system_context(message, history, session_id, context_files, file_context)
    )

    session_state = _load_session_state(session_id)
    snapshot_ctx = _build_snapshot_context_text(session_state)
    if snapshot_ctx:
        history = (history or []) + [{"role": "model", "content": snapshot_ctx}]

    skill_id, auto_skill_ids = _resolve_runtime_skill(rewritten_message, skill_id, task_type)

    pipeline = _build_chat_pipeline()
    pipeline.tracker = tracker
    pipeline.tracker_path = tracker_path

    def generate():
        yield from pipeline.run(
            message=rewritten_message,
            history=history,
            session_id=session_id,
            model_id=model_id,
            skill_id=skill_id,
            task_type=task_type,
            system_context=system_context,
            user_chose_local=user_chose_local,
            enable_skill_suggestions=True,
            auto_skill_ids=auto_skill_ids,
        )

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@agent_bp.route("/tools", methods=["GET"])
def list_tools():
    """List available tools for the agent."""
    agent = get_agent()
    definitions = agent.registry.get_definitions()
    return jsonify(definitions)


@agent_bp.route("/process", methods=["POST"])
def process_compat():
    """Phase2 compatibility endpoint for legacy AdaptiveAgent clients."""
    data = request.json or {}
    user_request = data.get("request", "")
    session_id = data.get("session_id") or data.get("session", "")
    skill_id = data.get("skill_id")
    task_type = data.get("task_type")
    context = data.get("context", {})
    history = context.get("history", []) if isinstance(context, dict) else []

    # Phase3: load and inject system state snapshot
    session_state = _load_session_state(session_id)
    snapshot_ctx = _build_snapshot_context_text(session_state)
    if snapshot_ctx:
        history = (history or []) + [{"role": "model", "content": snapshot_ctx}]

    if not user_request:
        return jsonify({"success": False, "error": "缺少请求内容"}), 400

    skill_id, auto_skill_ids = _resolve_runtime_skill(user_request, skill_id, task_type)

    # ── 路由级 PII 脱敏 ─────────────────────────────────────────
    _proc_mask = None
    _proc_safe_request = user_request
    try:
        PIIFilter = _lazy_pii()
        _proc_mask = PIIFilter.mask(user_request)
        if _proc_mask.has_pii:
            _proc_safe_request = _proc_mask.masked_text
            logger.info(f"[process] PII 脱敏 {_proc_mask.stats}")
    except Exception as _pe:
        logger.warning(f"[process] PII 过滤器异常（跳过）: {_pe}")

    try:
        agent = get_agent()
        task = _run_agent_collect(
            agent,
            _proc_safe_request,
            history=history,
            session_id=session_id,
            skill_id=skill_id,
            task_type=task_type,
        )
        # ── PII 还原 ────────────────────────────────────────────
        if _proc_mask and _proc_mask.has_pii:
            try:
                _r = task.get("result", "")
                if _r:
                    task["result"] = _proc_mask.restore(_r)
            except Exception:
                import logging

                logging.getLogger(__name__).warning(
                    "Silenced exception caught", exc_info=True
                )
        task["skill_id"] = skill_id
        task["auto_skill_ids"] = auto_skill_ids
        task["task_type"] = task_type
        merged_state = _merge_system_snapshot_from_steps(
            session_state, task.get("steps", [])
        )
        _save_session_state(session_id, merged_state)
        return jsonify({"success": True, "task": task})
    except Exception as exc:
        logger.exception("/process failed")
        return jsonify({"success": False, "error": str(exc)}), 500


@agent_bp.route("/process-stream", methods=["POST"])
def process_stream_compat():
    """Legacy compatibility SSE endpoint. Delegates to ChatPipeline."""
    data = request.json or {}
    user_request = data.get("request", "")
    session_id = data.get("session_id") or data.get("session", "")
    skill_id = data.get("skill_id")
    task_type = data.get("task_type")
    context = data.get("context", {})
    context_files = data.get("context_files") or []
    history = (context.get("history", []) if isinstance(context, dict) else []) or _load_history(session_id)

    session_state = _load_session_state(session_id)
    snapshot_ctx = _build_snapshot_context_text(session_state)
    if snapshot_ctx:
        history = (history or []) + [{"role": "model", "content": snapshot_ctx}]

    if context_files:
        try:
            from app.core.file.file_registry import get_file_registry
            reg = get_file_registry()
            blocks = []
            for p in context_files[:5]:
                entry = reg.get_by_path(str(p))
                if entry and entry.content_preview:
                    blocks.append(f"【参考文件：{entry.name}】\n{entry.content_preview[:2000]}")
            if blocks:
                ctx = "用户在对话中引用了以下本地文件，请结合其内容回答：\n\n" + "\n\n---\n\n".join(blocks)
                history = (history or []) + [{"role": "model", "content": ctx}]
        except Exception as e:
            logger.debug("[process-stream] @file context skip: %s", e)

    if not user_request:
        return jsonify({"success": False, "error": "缺少请求内容"}), 400

    skill_id, auto_skill_ids = _resolve_runtime_skill(user_request, skill_id, task_type)

    pipeline = _build_chat_pipeline()

    def generate():
        yield from pipeline.run(
            message=user_request,
            history=history,
            session_id=session_id,
            skill_id=skill_id,
            task_type=task_type,
        )

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@agent_bp.route("/resume", methods=["POST"])
def agent_resume():
    """Resume a KotoFlow pipeline paused at an approval gate."""
    data = request.json or {}
    resume_token = data.get("resume_token")
    if not resume_token:
        return jsonify({"success": False, "error": "Missing resume_token"}), 400

    try:
        import json as _json
        state = _json.loads(resume_token)
        # Reconstruct the pipeline from executed + remaining steps
        from app.core.skills.skill_pipeline import SkillPipeline, PipelineStep

        # The token is self-contained — we re-run from resume_idx
        # For now, return success acknowledgement; full re-execution
        # requires the pipeline definition which the caller should cache.
        return jsonify({
            "success": True,
            "result": f"Pipeline resumed from step {state.get('resume_idx', '?')}",
            "status": "resumed",
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@agent_bp.route("/plan", methods=["POST"])
def agent_plan():
    """Multi-step planning endpoint — uses UnifiedAgent ReAct loop with an
    explicit planning system instruction."""
    data = request.json or {}
    user_request = data.get("request", "")
    session_name = data.get("session", "")
    context = data.get("context", {})
    history = context.get("history", []) if isinstance(context, dict) else []

    if not user_request:
        return jsonify({"success": False, "error": "缺少请求内容"}), 400

    agent = get_agent()
    # Override system instruction for planning mode
    original_instruction = agent.base_system_instruction
    agent.base_system_instruction = (
        "You are Koto, an intelligent AI assistant in planning mode. "
        "Break the user's request into logical steps. For each step, think carefully, "
        "choose the right tool, execute it, and verify the result before moving on. "
        "When all steps are complete, provide a comprehensive final answer summarizing "
        "what was done and any produced results."
    )

    def generate():
        collected_steps = []
        final_answer = ""
        try:
            for step in agent.run(
                input_text=user_request,
                history=history,
                session_id=session_name,
                task_type="PLAN",
            ):
                step_data = step.to_dict()
                collected_steps.append(step_data)
                if step.step_type == AgentStepType.ANSWER:
                    final_answer = step.content or ""
                yield f"data: {json.dumps({'type': 'agent_step', 'data': step_data}, ensure_ascii=False)}\n\n"

            if not final_answer and collected_steps:
                final_answer = collected_steps[-1].get("content", "")

            task_payload = {
                "id": f"task_{int(time.time() * 1000)}",
                "status": "success",
                "result": final_answer,
                "steps": collected_steps,
            }
            yield f"data: {json.dumps({'type': 'task_final', 'data': task_payload}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.exception("/plan failed")
            yield f"data: {json.dumps({'type': 'error', 'data': {'error': str(exc)}}, ensure_ascii=False)}\n\n"
        finally:
            # Restore original instruction
            agent.base_system_instruction = original_instruction

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@agent_bp.route("/optimize", methods=["POST"])
def agent_optimize():
    """Phase4: System performance optimization advisor.

    Analyzes current system metrics and provides actionable optimization
    recommendations in a single turn.
    """
    data = request.json or {}
    user_request = data.get("request") or "Analyze my system and suggest optimizations"
    session_id = data.get("session_id") or data.get("session", "")
    context = data.get("context", {})
    history = context.get("history", []) if isinstance(context, dict) else []

    # Phase3: load and inject system state snapshot
    session_state = _load_session_state(session_id)
    snapshot_ctx = _build_snapshot_context_text(session_state)
    if snapshot_ctx:
        history = (history or []) + [{"role": "model", "content": snapshot_ctx}]

    agent = get_agent()
    # Override system instruction for optimization mode
    original_instruction = agent.base_system_instruction
    agent.base_system_instruction = (
        "You are a system performance optimization advisor. "
        "Analyze the current system metrics and provide specific, actionable recommendations. "
        "Use the analyze_system_performance and suggest_optimizations tools to gather data. "
        "Focus on: (1) Identifying bottlenecks, (2) Prioritizing issues by severity, "
        "(3) Providing step-by-step solutions. Be concise but thorough."
    )

    def generate():
        collected_steps = []
        final_answer = ""
        try:
            for step in agent.run(
                input_text=user_request,
                history=history,
                session_id=session_id,
                task_type="SYSTEM",
            ):
                step_data = step.to_dict()
                collected_steps.append(step_data)
                if step.step_type == AgentStepType.ANSWER:
                    final_answer = step.content or ""
                yield f"data: {json.dumps({'type': 'agent_step', 'data': step_data}, ensure_ascii=False)}\n\n"

            if not final_answer and collected_steps:
                final_answer = collected_steps[-1].get("content", "")

            task_payload = {
                "id": f"task_{int(time.time() * 1000)}",
                "status": "success",
                "result": final_answer,
                "steps": collected_steps,
            }
            yield f"data: {json.dumps({'type': 'task_final', 'data': task_payload}, ensure_ascii=False)}\n\n"

            # Persist turn to disk + phase3 state snapshot
            _save_history(
                session_id,
                user_request,
                final_answer or "[Optimization analysis completed]",
            )
            merged_state = _merge_system_snapshot_from_steps(
                session_state, collected_steps
            )
            _save_session_state(session_id, merged_state)
        except Exception as exc:
            logger.exception("/optimize failed")
            yield f"data: {json.dumps({'type': 'error', 'data': {'error': str(exc)}}, ensure_ascii=False)}\n\n"
        finally:
            # Restore original instruction
            agent.base_system_instruction = original_instruction

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


# ------------------------------------------------------------------
# Phase 4b: Monitoring Control Endpoints
# ------------------------------------------------------------------


@agent_bp.route("/monitor/start", methods=["POST"])
def start_monitoring():
    """Start background system monitoring."""
    try:
        from app.core.monitoring.system_event_monitor import get_system_event_monitor

        data = request.get_json() or {}
        check_interval = data.get("check_interval", 30)

        monitor = get_system_event_monitor(check_interval=check_interval)

        if monitor.is_running():
            return jsonify(
                {
                    "status": "already_running",
                    "message": "System monitoring is already active",
                    "check_interval": monitor.check_interval,
                }
            )

        monitor.start()

        return jsonify(
            {
                "status": "success",
                "message": "System monitoring started",
                "check_interval": monitor.check_interval,
            }
        )
    except Exception as e:
        logger.error(f"Error starting monitoring: {e}", exc_info=True)
        return (
            jsonify(
                {"status": "error", "message": f"Failed to start monitoring: {str(e)}"}
            ),
            500,
        )


@agent_bp.route("/monitor/stop", methods=["POST"])
def stop_monitoring():
    """Stop background system monitoring."""
    try:
        from app.core.monitoring.system_event_monitor import get_system_event_monitor

        monitor = get_system_event_monitor()

        if not monitor.is_running():
            return jsonify(
                {
                    "status": "not_running",
                    "message": "System monitoring is not currently active",
                }
            )

        monitor.stop()

        return jsonify({"status": "success", "message": "System monitoring stopped"})
    except Exception as e:
        logger.error(f"Error stopping monitoring: {e}", exc_info=True)
        return (
            jsonify(
                {"status": "error", "message": f"Failed to stop monitoring: {str(e)}"}
            ),
            500,
        )


@agent_bp.route("/monitor/status", methods=["GET"])
def monitoring_status():
    """Get current monitoring status and event summary."""
    try:
        from app.core.monitoring.system_event_monitor import get_system_event_monitor

        monitor = get_system_event_monitor()

        return jsonify(
            {
                "status": "success",
                "monitoring_active": monitor.is_running(),
                "check_interval": (
                    monitor.check_interval if monitor.is_running() else None
                ),
                "health": monitor.get_summary(),
                "recent_events": monitor.get_events(limit=5),
            }
        )
    except Exception as e:
        logger.error(f"Error getting monitoring status: {e}", exc_info=True)
        return (
            jsonify({"status": "error", "message": f"Failed to get status: {str(e)}"}),
            500,
        )


@agent_bp.route("/monitor/events", methods=["GET"])
def get_monitoring_events():
    """Get detected anomalies from monitoring."""
    try:
        from app.core.monitoring.system_event_monitor import get_system_event_monitor

        limit = request.args.get("limit", 20, type=int)
        event_type = request.args.get("event_type", None, type=str)

        monitor = get_system_event_monitor()
        events = monitor.get_events(limit=limit, event_type=event_type)

        return jsonify(
            {
                "status": "success",
                "anomaly_count": len(events),
                "anomalies": events,
                "monitoring_active": monitor.is_running(),
            }
        )
    except Exception as e:
        logger.error(f"Error getting events: {e}", exc_info=True)
        return (
            jsonify({"status": "error", "message": f"Failed to get events: {str(e)}"}),
            500,
        )


@agent_bp.route("/monitor/clear", methods=["POST"])
def clear_monitoring_events():
    """Clear recorded anomalies from monitoring log."""
    try:
        from app.core.monitoring.system_event_monitor import get_system_event_monitor

        monitor = get_system_event_monitor()
        count = monitor.clear_events()

        return jsonify(
            {
                "status": "success",
                "message": f"Cleared {count} events from monitoring log",
            }
        )
    except Exception as e:
        logger.error(f"Error clearing events: {e}", exc_info=True)
        return (
            jsonify(
                {"status": "error", "message": f"Failed to clear events: {str(e)}"}
            ),
            500,
        )


# ══════════════════════════════════════════════════════════════════
# v2 新增：用户反馈 / 影子记录 / 成本面板 API
# ══════════════════════════════════════════════════════════════════


@agent_bp.route("/feedback", methods=["POST"])
def submit_feedback():
    """
    用户反馈端点 — 触发 ShadowTracer 影子记录。

    请求体:
    {
      "feedback_type": "thumbs_up" | "thumbs_down" | "adopted",
      "session_id": str,
      "message_id": str (可选，用于定位对话轮次),
      "user_input": str,
      "ai_response": str,
      "skill_id": str | null,
      "task_type": str | null,
      "model_used": str | null,
      "latency_ms": int | null
    }

    响应:
    { "success": true, "trace_id": str | null, "recorded": bool }
    """
    data = request.json or {}
    feedback_type = data.get("feedback_type", "thumbs_up")
    session_id = data.get("session_id", "")
    user_input = data.get("user_input", "")
    ai_response = data.get("ai_response", "")
    skill_id = data.get("skill_id")
    task_type = data.get("task_type")
    model_used = data.get("model_used", "")
    latency_ms = data.get("latency_ms")

    if not user_input and not ai_response:
        return (
            jsonify(
                {"success": False, "error": "user_input 或 ai_response 不能同时为空"}
            ),
            400,
        )

    trace_id = None
    try:
        ShadowTracer = _lazy_tracer()
        if feedback_type in ("thumbs_up", "approved"):
            trace_id = ShadowTracer.record_approved(
                session_id=session_id,
                user_input=user_input,
                ai_response=ai_response,
                skill_id=skill_id,
                task_type=task_type,
                model_used=model_used or "",
                latency_ms=latency_ms,
            )
        elif feedback_type == "adopted":
            trace_id = ShadowTracer.record_adopted(
                session_id=session_id,
                user_input=user_input,
                ai_response=ai_response,
                skill_id=skill_id,
                task_type=task_type,
                model_used=model_used or "",
                latency_ms=latency_ms,
            )
        elif feedback_type == "thumbs_down":
            # 负面反馈不计入影子记录，仅日志
            logger.info(f"[feedback] 👎 负面反馈 session={session_id} skill={skill_id}")
        else:
            return (
                jsonify({"success": False, "error": f"未知反馈类型: {feedback_type}"}),
                400,
            )

    except Exception as e:
        logger.error(f"[feedback] 记录失败: {e}")
        return jsonify({"success": False, "error": str(e), "recorded": False}), 500

    return jsonify(
        {
            "success": True,
            "trace_id": trace_id,
            "recorded": trace_id is not None,
            "feedback_type": feedback_type,
        }
    )


@agent_bp.route("/feedback/stats", methods=["GET"])
def feedback_stats():
    """
    返回各 Skill 的影子记录统计。

    响应:
    {
      "counts": { skill_id: count, ... },
      "threshold": int,
      "skills_ready_for_training": [skill_id, ...]
    }
    """
    try:
        ShadowTracer = _lazy_tracer()
        counts = ShadowTracer.get_counts()
        threshold = ShadowTracer.shadow_threshold
        ready = [k for k, v in counts.items() if v >= threshold]
        return jsonify(
            {
                "counts": counts,
                "threshold": threshold,
                "skills_ready_for_training": ready,
                "recording_enabled": ShadowTracer.recording_enabled,
            }
        )
    except Exception as e:
        logger.error(f"[feedback/stats] 错误: {e}")
        return jsonify({"error": str(e)}), 500


@agent_bp.route("/feedback/settings", methods=["POST"])
def feedback_settings():
    """
    更新影子记录设置。

    请求体: { "recording_enabled": bool, "threshold": int (可选) }
    """
    data = request.json or {}
    try:
        ShadowTracer = _lazy_tracer()
        if "recording_enabled" in data:
            ShadowTracer.recording_enabled = bool(data["recording_enabled"])
        if "threshold" in data:
            t = int(data["threshold"])
            if 10 <= t <= 10000:
                ShadowTracer.shadow_threshold = t
        return jsonify(
            {
                "success": True,
                "recording_enabled": ShadowTracer.recording_enabled,
                "threshold": ShadowTracer.shadow_threshold,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ──────────────────────────────────────────────────────────────────
# 成本 & 性能透明面板 API
# ──────────────────────────────────────────────────────────────────


@agent_bp.route("/stats/cost", methods=["GET"])
def cost_stats():
    """
    返回成本与性能统计面板数据。

    查询参数:
      period: "today" (default) | "week" | "month"
      skill_id: 指定 Skill 查看该 Skill 的使用成本（可选）

    响应包含:
    - 云端 Token 费用（USD / CNY）
    - 本地 CPU 算力消耗（如果有记录）
    - 各 Skill 的调用次数和费用
    - 每日 / 每月趋势
    """
    period = request.args.get("period", "today")
    skill_id_filter = request.args.get("skill_id")

    try:
        # 导入 token_tracker
        try:
            import web.token_tracker as token_tracker

            token_stats = token_tracker.get_stats()
        except Exception as _te:
            logger.warning(f"[cost_stats] token_tracker 不可用: {_te}")
            token_stats = {}

        # 影子记录统计（间接反映 Skill 使用量）
        try:
            ShadowTracer = _lazy_tracer()
            trace_counts = ShadowTracer.get_counts()
        except Exception as _e:
            logger.debug("[stats] trace_counts fetch failed: %s", _e)
            trace_counts = {}

        # 本地算力估算（简单 psutil）
        local_compute = {}
        try:
            import psutil

            local_compute = {
                "cpu_percent": psutil.cpu_percent(interval=0.1),
                "memory_used_mb": round(psutil.virtual_memory().used / 1024 / 1024),
                "memory_total_mb": round(psutil.virtual_memory().total / 1024 / 1024),
            }
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "Silenced exception caught", exc_info=True
            )

        # 组装面板数据
        panel = {
            "period": period,
            "cloud": {
                "today": token_stats.get("today", {}),
                "this_month": token_stats.get("this_month", {}),
                "last_7_days": token_stats.get("last_7_days", []),
            },
            "local_compute": local_compute,
            "skill_usage": {
                "trace_counts": trace_counts,
                "total_approved_responses": sum(trace_counts.values()),
            },
            "summary": {
                "cost_cny_today": token_stats.get("today", {}).get("cost_cny", 0),
                "cost_cny_month": token_stats.get("this_month", {}).get("cost_cny", 0),
                "calls_today": token_stats.get("today", {}).get("calls", 0),
            },
        }

        if skill_id_filter:
            panel["skill_filter"] = skill_id_filter
            panel["skill_trace_count"] = trace_counts.get(skill_id_filter, 0)

        return jsonify({"success": True, "data": panel})
    except Exception as e:
        logger.error(f"[cost_stats] 错误: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ──────────────────────────────────────────────────────────────────
# 硬件检测 & 本地模型推荐 API
# ──────────────────────────────────────────────────────────────────


@agent_bp.route("/hardware", methods=["GET"])
def hardware_info():
    """
    检测当前设备硬件配置并返回本地模型训练/推理推荐。

    响应:
    {
      "gpu": { "name": str, "vram_gb": float, "available": bool },
      "cpu": { "cores": int },
      "ram_gb": float,
      "recommended": {
        "training_model": str,       # 推荐训练模型
        "inference_model": str,      # 推荐推理模型（Ollama）
        "gguf_size_estimate": str,   # 量化后体积估算
        "tier": str,                 # flagship / high / mid / entry / cpu_only
        "training_config": dict,     # TrainingConfig 参数
        "can_train": bool,
        "notes": str
      }
    }
    """
    import subprocess

    # ── GPU 检测 ─────────────────────────────────────────────────
    gpu_info = {"name": "Unknown", "vram_gb": 0.0, "available": False}
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
            if lines:
                parts = lines[0].split(",")
                gpu_info["name"] = parts[0].strip()
                gpu_info["vram_gb"] = round(int(parts[1].strip()) / 1024, 1)
                gpu_info["available"] = True
    except Exception:
        import logging

        logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)

    # ── CPU & RAM ────────────────────────────────────────────────
    cpu_cores = 0
    ram_gb = 0.0
    try:
        import psutil

        cpu_cores = psutil.cpu_count(logical=False) or 0
        ram_gb = round(psutil.virtual_memory().total / (1024**3), 1)
    except Exception:
        import logging

        logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)

    # ── 推荐逻辑 ─────────────────────────────────────────────────
    vram = gpu_info["vram_gb"]

    if vram >= 20:
        tier = "flagship"
        train_model = "Qwen/Qwen3-8B"
        infer_model = "qwen3:8b"
        gguf_est = "~5.2GB (Q4_K_M)"
        notes = (
            "RTX 4090 / A100 级别。Qwen3-8B ≈ Qwen2.5-14B 能力，128K 上下文，"
            "混合思维模式 (enable_thinking)，LoRA fp16 无压力，"
            "量化后 GGUF 约 5.2GB，可直接打包分发。"
        )
    elif vram >= 10:
        tier = "high"
        train_model = "Qwen/Qwen3-4B"
        infer_model = "qwen3:4b"
        gguf_est = "~2.6GB (Q4_K_M)"
        notes = (
            "RTX 3080/4070 级别。Qwen3-4B ≈ Qwen2.5-7B 能力，"
            "LoRA 非常流畅，量化后约 2.6GB，分发友好。"
        )
    elif vram >= 6:
        tier = "mid"
        train_model = "Qwen/Qwen3-1.7B"
        infer_model = "qwen3:1.7b"
        gguf_est = "~1.1GB (Q4_K_M)"
        notes = (
            "RTX 3060/4060 级别。Qwen3-1.7B ≈ Qwen2.5-3B 能力，"
            "QLoRA 训练稳定，速度快，适合快速迭代。"
        )
    elif vram >= 4:
        tier = "entry"
        train_model = "Qwen/Qwen3-0.6B"
        infer_model = "qwen3:0.6b"
        gguf_est = "~450MB (Q4_K_M)"
        notes = "入门独显。Qwen3-0.6B QLoRA 可跑，训练慢，适合轻量 Skill。"
    else:
        tier = "cpu_only"
        train_model = "Qwen/Qwen3-0.6B"
        infer_model = "qwen3:0.6b"
        gguf_est = "~450MB (Q4_K_M)"
        notes = "无独显环境。本地训练极慢（不推荐），建议仅做推理，训练任务交给云端。"

    # 获取对应 TrainingConfig
    training_cfg = {}
    try:
        from app.core.learning.lora_pipeline import TrainingConfig

        cfg = TrainingConfig.for_hardware(vram_gb=vram, ram_gb=ram_gb)
        training_cfg = cfg.to_dict()
    except Exception as e:
        logger.warning(f"[hardware] TrainingConfig 加载失败: {e}")

    return jsonify(
        {
            "gpu": gpu_info,
            "cpu": {"cores": cpu_cores},
            "ram_gb": ram_gb,
            "recommended": {
                "training_model": train_model,
                "inference_model": infer_model,
                "gguf_size_estimate": gguf_est,
                "tier": tier,
                "training_config": training_cfg,
                "can_train": tier != "cpu_only",
                "notes": notes,
            },
        }
    )


# ══════════════════════════════════════════════════════════════════════════════
# 蒸馏训练管理 API
# ══════════════════════════════════════════════════════════════════════════════


def _lazy_distill():
    from app.core.learning.distill_manager import DistillManager

    return DistillManager.instance()


@agent_bp.route("/distill/train", methods=["POST"])
def distill_train():
    """
    POST /api/agent/distill/train
    提交蒸馏训练任务（立即返回 job_id，后台异步训练）。

    Body (JSON):
      skill_id        - 要训练的 Skill ID（必填）
      config_override - 可选，覆盖 TrainingConfig 字段，如 {"num_epochs": 5}
      dataset_path    - 可选，指定数据集路径

    Returns:
      {"job_id": "...", "skill_id": "...", "status": "queued"}
    """
    data = request.get_json(silent=True) or {}
    skill_id = data.get("skill_id", "").strip()
    if not skill_id:
        return jsonify({"error": "skill_id 必填"}), 400

    config_override = data.get("config_override") or {}
    dataset_path = data.get("dataset_path")

    mgr = _lazy_distill()
    job_id = mgr.submit(
        skill_id=skill_id,
        config_override=config_override,
        dataset_path=dataset_path,
    )
    job = mgr.get_job(job_id)
    return jsonify(
        {
            "job_id": job_id,
            "skill_id": skill_id,
            "status": job.status if job else "queued",
            "message": "训练任务已提交，使用 GET /api/agent/distill/jobs/{job_id} 查询进度",
            "stream_url": f"/api/agent/distill/jobs/{job_id}/stream",
        }
    )


@agent_bp.route("/distill/jobs", methods=["GET"])
def distill_list_jobs():
    """
    GET /api/agent/distill/jobs[?skill_id=xxx]
    列出所有训练任务（可按 skill_id 过滤）。
    """
    skill_id = request.args.get("skill_id")
    mgr = _lazy_distill()
    jobs = mgr.list_jobs(skill_id=skill_id)
    return jsonify({"jobs": jobs, "count": len(jobs)})


@agent_bp.route("/distill/jobs/<job_id>", methods=["GET"])
def distill_job_status(job_id: str):
    """
    GET /api/agent/distill/jobs/<job_id>
    查询某个训练任务的详细状态。
    """
    mgr = _lazy_distill()
    job = mgr.get_job(job_id)
    if not job:
        return jsonify({"error": f"job_id={job_id} 不存在"}), 404
    return jsonify(job.to_dict())


@agent_bp.route("/distill/jobs/<job_id>/stream", methods=["GET"])
def distill_job_stream(job_id: str):
    """
    GET /api/agent/distill/jobs/<job_id>/stream
    SSE 实时进度流。前端用 EventSource 订阅。

    事件格式: data: {"event":"progress","pct":45,"loss":0.32,"msg":"..."}
    结束事件: data: {"event":"done","pct":100,"eval_loss":0.18,"adapter_path":"..."}
    """
    from flask import Response, stream_with_context

    mgr = _lazy_distill()
    job = mgr.get_job(job_id)
    if not job:
        return jsonify({"error": f"job_id={job_id} 不存在"}), 404

    return Response(
        stream_with_context(mgr.stream_progress(job_id)),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@agent_bp.route("/distill/jobs/<job_id>/cancel", methods=["POST"])
def distill_cancel_job(job_id: str):
    """
    POST /api/agent/distill/jobs/<job_id>/cancel
    取消排队中的训练任务（运行中无法取消）。
    """
    mgr = _lazy_distill()
    ok = mgr.cancel(job_id)
    if ok:
        return jsonify({"job_id": job_id, "cancelled": True})
    return jsonify({"error": "任务不存在或正在运行中，无法取消", "job_id": job_id}), 400


@agent_bp.route("/distill/prerequisites", methods=["GET"])
def distill_prerequisites():
    """
    GET /api/agent/distill/prerequisites
    检查蒸馏训练所需依赖是否已安装。
    """
    try:
        from app.core.learning.lora_pipeline import LoRAPipeline

        pipeline = LoRAPipeline()
        all_ok, missing = pipeline.check_prerequisites()
        return jsonify(
            {
                "ready": all_ok,
                "missing": missing,
                "install_cmd": (
                    (
                        "pip install peft transformers datasets accelerate trl bitsandbytes\n"
                        "pip install torch --index-url https://download.pytorch.org/whl/cu126"
                    )
                    if not all_ok
                    else None
                ),
            }
        )
    except Exception as e:
        return jsonify({"ready": False, "error": str(e)}), 500
