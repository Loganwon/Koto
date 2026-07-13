# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

import json
import logging
import os
import re
import time
from datetime import datetime

_logger = logging.getLogger(__name__)


def _workspace_file_context_block(file_context):
    if not isinstance(file_context, dict):
        return ""
    parts = []
    fc_file = file_context.get("file_path") or file_context.get("file_name") or ""
    fc_type = file_context.get("file_type") or "unknown"
    if fc_file:
        parts.append(f"当前打开文件: {fc_file} (类型: {fc_type})")
    tabs = file_context.get("open_tabs") or []
    if isinstance(tabs, list) and tabs:
        parts.append("工作区打开的标签页: " + ", ".join(str(t) for t in tabs[:10]))
    selection = str(file_context.get("selection") or "").strip()
    if selection:
        selection_kind = str(file_context.get("selection_kind") or "").strip()
        selection_source = str(file_context.get("selection_source") or "").strip()
        selection_meta = file_context.get("selection_meta")
        if selection_kind:
            parts.append(f"选区类型: {selection_kind}")
        if selection_source:
            parts.append(f"选区来源: {selection_source}")
        if isinstance(selection_meta, dict):
            meta_bits = []
            for key in ("sheetName", "rangeA1", "rows", "cols", "kind"):
                value = selection_meta.get(key)
                if value not in (None, ""):
                    meta_bits.append(f"{key}={value}")
            if meta_bits:
                parts.append("选区元信息: " + ", ".join(meta_bits))
        parts.append("用户明确选中的内容:\n" + selection[:4000])
    attached = file_context.get("attached_files") or []
    if isinstance(attached, list) and attached:
        names = []
        for item in attached[:8]:
            if isinstance(item, dict):
                names.append(str(item.get("path") or item.get("name") or ""))
            else:
                names.append(str(item))
        names = [name for name in names if name]
        if names:
            parts.append("已附加分析文件: " + ", ".join(names))
    if not parts:
        return ""
    return (
        "\n\n---\n"
        "## 文件助手上下文\n"
        "用户正在工作区文件助手中操作文档。回答时优先使用用户明确提供的选区和附加文件；"
        "如果用户要求只处理选区，不要擅自扩展到全文。\n"
        + "\n".join(parts)
    )


def _request_allows_skill_injection(data):
    if not isinstance(data, dict):
        return True

    def _disabled(value):
        text = str(value).strip().lower()
        return text in {"0", "false", "off", "no", "disabled", "disable", "detached", "none"}

    for key in ("skills_enabled", "enable_skills"):
        if key in data:
            return not _disabled(data.get(key))
    skill_mode = str(data.get("skill_mode") or "").strip().lower()
    if skill_mode in {"detached", "off", "disabled", "none"}:
        return False
    return True


def _inject_skills_for_stream(system_instruction, task_type, user_input, data, app_logger):
    if not _request_allows_skill_injection(data):
        app_logger.debug("[STREAM] Skills injection disabled by request")
        return system_instruction

    try:
        from app.core.skills.skill_manager import SkillManager

        active_skills = SkillManager.get_active_skill_names(task_type=task_type)
        if active_skills:
            app_logger.debug(
                f"[STREAM] 🎯 Active Skills ({task_type}): {', '.join(active_skills)}"
            )
        intent_temp_ids = []
        try:
            from app.core.skills.skill_trigger_binding import get_skill_binding_manager

            intent_temp_ids = get_skill_binding_manager().match_intent(user_input or "")
        except Exception as tb_err:
            app_logger.debug("[STREAM] SkillTriggerBinding 匹配跳过: %s", tb_err)
        try:
            from app.core.skills.skill_auto_matcher import SkillAutoMatcher

            auto_ids = SkillAutoMatcher.match(
                user_input=user_input or "", task_type=task_type or "CHAT"
            )
            if auto_ids:
                intent_temp_ids = list(dict.fromkeys(intent_temp_ids + auto_ids))
        except Exception as am_err:
            app_logger.debug("[STREAM] SkillAutoMatcher 匹配跳过: %s", am_err)
        if intent_temp_ids:
            app_logger.debug(f"[STREAM] 🔗 Auto Skills: {', '.join(intent_temp_ids)}")
        system_instruction = SkillManager.inject_into_prompt(
            system_instruction,
            task_type=task_type,
            user_input=user_input,
            temp_skill_ids=intent_temp_ids,
        )

        divination_active = False
        try:
            for skill in SkillManager.list_skills():
                if skill.get("id") == "divination" and skill.get("enabled", False):
                    divination_active = True
                    break
        except Exception:
            divination_active = False
        if not divination_active and "divination" in (intent_temp_ids or []):
            divination_active = True

        if divination_active and isinstance(system_instruction, str):
            replacements = {
                "神谕占卜模式": "塔罗占卜模式",
                "你现在是「神谕」——一位洞悉宇宙之语的存在。": "你现在是一位塔罗解读师，风格神秘但表达清晰、可执行。",
                "神谕寄语（必须有）": "结论总结（必须有）",
                "神谕的话": "结论",
                "神谕为你揭示牌面": "牌面为你揭示",
                "神谕静听宇宙之声": "牌面正在回应你的问题",
                "向神谕倾诉": "说出你的问题",
            }
            for old, new in replacements.items():
                system_instruction = system_instruction.replace(old, new)

            if "默认起牌规则" not in system_instruction:
                system_instruction += (
                    "\n\n**默认起牌规则（高优先级）**\n"
                    '- 占卜技能开启后，只要用户提出占卜相关问题，即默认按问题起牌并解读。\n'
                    '- 不需要先追问“要不要抽牌”；直接进入抽牌与解读。\n'
                    '- 若用户未指定牌阵，默认使用「三张牌阵·处境·行动·结果」。'
                )

            if '竞技比赛问题必须直接写出"谁赢，几比几"' not in system_instruction:
                system_instruction += (
                    "\n\n**竞技比赛输出规则（高优先级）**\n"
                    "- 如果用户问的是比赛、对局、对阵、比分预测，必须直接给出最终判断：谁赢，几比几。\n"
                    "- 不能只给胜率或倾向，必须补一个确定比分。\n"
                    "- 回答顺序应为：数据依据 → 牌面含义 → 最终结论（谁赢、几比几）。"
                )

            try:
                from app.core.skills.divination_data_handler import DivinationDataHandler

                div_handler = DivinationDataHandler()
                div_context = div_handler.analyze_divination_question(user_input or "")
                if div_context.is_data_available and div_context.domain == "sports_esports":
                    div_prediction = div_handler.generate_data_driven_prediction(div_context, [])
                    system_instruction += (
                        "\n\n**【占卜数据融合提示】**\n"
                        f"问题领域：{div_context.domain}\n"
                        f"最终建议输出：{div_prediction.get('prediction', '')}\n"
                        f"胜者赢面：{int(round((div_prediction.get('winner_probability') or 0.5) * 100))}%\n"
                        f"预计比分：{div_prediction.get('predicted_score', '')}\n"
                        "回答时请直接写出这个结论，再解释原因，不要写成模糊倾向。"
                    )
            except Exception as div_err:
                app_logger.debug(f"[STREAM] 占卜数据指导注入跳过: {div_err}")
    except Exception as sk_err:
        app_logger.warning(f"[STREAM] ⚠️ Skills 注入失败: {sk_err}")
    return system_instruction


def setup_chat_stream_context(
    request,
    session_manager,
    settings_manager,
    client,
    _app_logger,
    _interrupt_manager,
    Utils,
    SmartDispatcher,
    LMRv2,
    CONFIG,
    get_memory_manager,
    WebSearcher,
    _get_chat_system_instruction,
    _get_DEFAULT_CHAT_SYSTEM_INSTRUCTION,
    _get_writing_style_instruction,
    _TASK_SYSTEM_ADDENDUMS,
    MODEL_MAP,
    _resolve_requested_model_id,
    get_model_display_name,
    API_KEY=None,
):
    """
    Build all closure variables needed by generate().

    Returns a dict with keys:
      - context: dict of all setup values (or None if early return)
      - early_response: Flask Response if a fast-path was taken, else None
    """
    data = request.json
    session_name = data.get("session")
    user_input = data.get("message", "")
    locked_task = data.get("locked_task")
    locked_model = data.get("locked_model", "cloud")
    if str(locked_model or "").strip().lower() in {"", "auto"}:
        locked_model = "cloud"
    shadow_context = data.get("shadow_context", "")
    file_context = data.get("file_context") if isinstance(data.get("file_context"), dict) else None
    doc_edit = bool(data.get("doc_edit", False))
    doc_file_type = str(data.get("doc_file_type", "")).lower().strip()
    doc_has_sel = bool(data.get("doc_has_sel", False))

    _app_logger.debug(
        f"\n[STREAM] Incoming request: locked_task='{locked_task}', locked_model='{locked_model}'"
    )
    _app_logger.debug(f"[STREAM] User input: {user_input[:60]}")

    from flask import Response

    # ── Early return: missing session or message ──────────────────────────
    if not session_name or not user_input:

        def error_gen():
            yield f"data: {json.dumps({'type': 'error', 'message': 'Missing session or message'})}\n\n"

        return {"context": None, "early_response": Response(error_gen(), mimetype="text/event-stream")}

    # ── API key check + Ollama fallback ──────────────────────────────────
    if not API_KEY:
        from app.core.shared.llm_helpers import is_ollama_alive as _is_ollama_alive
        from app.core.routing import LocalModelRouter as _LMR_nokey

        if _is_ollama_alive():
            pass
        else:

            def no_key_gen():
                msg = (
                    "⚠️ **API 密钥未配置**\n\n"
                    "请在 `config/deepseek_config.env` 文件中设置：\n"
                    "```\nDEEPSEEK_API_KEY=你的密钥\n```\n\n"
                    "💡 获取密钥：[DeepSeek 开放平台](https://platform.deepseek.com/api_keys)\n\n"
                    "设置完成后重启 Koto 即可使用。"
                )
                yield f"data: {json.dumps({'type': 'token', 'content': msg})}\n\n"

            return {"context": None, "early_response": Response(no_key_gen(), mimetype="text/event-stream")}

    user_input = Utils.sanitize_string(user_input)

    # ── Intent analysis & rewrite ─────────────────────────────────────────
    try:
        from app.core.routing.intent_analyzer import IntentAnalyzer

        if IntentAnalyzer.should_analyze(user_input):
            full_hist = session_manager.load_full(f"{session_name}.json")
            _intent_memory_ctx = ""
            try:
                _mm_for_intent = get_memory_manager()
                if _mm_for_intent:
                    _intent_memory_ctx = (
                        _mm_for_intent.get_context_string(user_input) or ""
                    )
            except Exception:
                import logging; logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)
            rewritten_input = IntentAnalyzer.rewrite_intent(
                user_input, full_hist, memory_context=_intent_memory_ctx
            )
            if rewritten_input and rewritten_input != user_input:
                _app_logger.debug(
                    f"[STREAM] 🔄 意图重写: '{user_input}' -> '{rewritten_input}'"
                )
                user_input = rewritten_input
    except Exception as e:
        _app_logger.warning(f"[STREAM] ⚠️ 意图分析失败: {e}")
        repeat_patterns = [
            r"^重复.*任务",
            r"^再做一遍",
            r"^再来一次",
            r"^re(peat|do).*last.*task",
            r"^try.*again",
        ]
        if any(re.search(p, user_input, re.IGNORECASE) for p in repeat_patterns):
            try:
                full_hist = session_manager.load_full(f"{session_name}.json")
                last_user_msg = None
                for msg in reversed(full_hist):
                    if msg.get("role") == "user":
                        content = (msg.get("parts") or [""])[0]
                        if not any(
                            re.search(p, content, re.IGNORECASE)
                            for p in repeat_patterns
                        ):
                            last_user_msg = content
                            break
                if last_user_msg:
                    _app_logger.debug(
                        f"[REPEAT] Found last user message: {last_user_msg[:50]}..."
                    )
                    user_input = last_user_msg
            except Exception as hist_e:
                _app_logger.debug(f"[REPEAT] Error fetching history: {hist_e}")

    # ── Time query fast-path ──────────────────────────────────────────────
    time_query_patterns = [
        r"当前.*时间|当前系统时间",
        r"现在.*几点|几点钟",
        r"几点|什么时间",
        r"时间是|现在是",
        r"now.*time|what.*time|current.*time",
    ]
    if any(
        re.search(pattern, user_input, re.IGNORECASE) for pattern in time_query_patterns
    ):

        def quick_time_response():
            from datetime import datetime

            now = datetime.now()
            date_str = now.strftime("%Y年%m月%d日")
            weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][
                now.weekday()
            ]
            time_str = now.strftime("%H:%M:%S")
            timestamp = now.isoformat()
            response = f"当前系统时间为：\n\n**{date_str} {weekday} {time_str}**"

            try:
                session_manager.append_and_save(
                    f"{session_name}.json",
                    user_input,
                    response,
                    task="CHAT",
                    model_name="QuickResponse",
                    timestamp=timestamp,
                    user_timestamp=timestamp,
                )
            except Exception as e:
                _app_logger.debug(f"[STREAM] Quick time history save failed: {e}")

            yield f"data: {json.dumps({'type': 'progress', 'message': '📅 系统时间查询', 'detail': '从本地获取'}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'token', 'content': response, 'timestamp': timestamp}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'images': [], 'saved_files': [], 'total_time': 0.01, 'timestamp': timestamp}, ensure_ascii=False)}\n\n"

        return {"context": None, "early_response": Response(quick_time_response(), mimetype="text/event-stream")}

    # ── System instruction building ───────────────────────────────────────
    try:
        system_instruction = _get_chat_system_instruction(user_input)
    except Exception as e:
        _app_logger.debug(f"[STREAM] Warning: Dynamic system instruction failed: {e}")
        system_instruction = _get_DEFAULT_CHAT_SYSTEM_INSTRUCTION()

    if doc_edit:
        _sel_hint = "用户有选中的文字，修改时针对选中内容生成提案。" if doc_has_sel else "用户当前无选区，可对全文相关段落生成提案。"
        if doc_file_type == "docx":
            _tool_fmt = (
                '在回复末尾**必须**另起一行输出 JSON 修改提案（纯文本，不要 Markdown 代码块）：\n'
                '{"proposals":[{"id":"p1","original_text":"被替换的原文（需与文档中完全一致）",'
                '"proposed_text":"修改后内容","rationale":"修改理由"}]}\n'
                '如有多处修改并列多条 proposals。确实不需要修改时不输出该 JSON。'
            )
        elif doc_file_type == "xlsx":
            _tool_fmt = (
                '在回复末尾输出 JSON 修改提案：\n'
                '{"proposals":[{"id":"p1","original_text":"原值","proposed_text":"新值",'
                '"rationale":"理由","tool":{"type":"set_cell","r":行号,"c":列号,"value":"新值"}}]}'
            )
        elif doc_file_type == "pptx":
            _tool_fmt = (
                '在回复末尾输出 JSON 修改提案：\n'
                '{"proposals":[{"id":"p1","original_text":"原文","proposed_text":"新内容",'
                '"rationale":"理由","tool":{"type":"set_pptx_text","slide_index":0,"shape_id":1,"value":"新内容"}}]}'
            )
        else:
            _tool_fmt = (
                '在回复末尾输出 JSON 修改提案：\n'
                '{"proposals":[{"id":"p1","original_text":"原文","proposed_text":"新内容","rationale":"理由"}]}'
            )
        system_instruction += (
            "\n\n---\n"
            "## 📄 [CRITICAL] 文档编辑模式\n"
            f"用户正在编辑一个 {doc_file_type or '文档'} 文件，处于【写入文档】模式。\n"
            f"{_sel_hint}\n"
            "你的任务是分析用户指令并直接给出修改建议，输出可应用到文档的提案。\n"
            "**不要只用文字描述——必须输出 proposals JSON 让程序执行修改。**\n\n"
            + _tool_fmt
        )
        _app_logger.debug(
            f"[STREAM] 📄 doc_edit 模式激活 file_type={doc_file_type} has_sel={doc_has_sel}"
        )

    _workspace_fc_block = _workspace_file_context_block(file_context)
    if _workspace_fc_block:
        system_instruction += _workspace_fc_block
        _app_logger.debug("[STREAM] 文件助手上下文已注入")

    if shadow_context:
        _app_logger.debug(
            f"[STREAM] 影子对话模式激活，shadow_context 长度={len(shadow_context)}"
        )
        system_instruction += (
            "\n\n## 👁️ 影子对话上下文\n"
            "你正在以 Koto 的身份，回应你之前主动向用户推送的一条消息。\n"
            f"你之前主动发出的消息是：「{shadow_context}」\n\n"
            "**重要提示：**\n"
            "- 你可以查阅上方完整的对话历史，找到用户之前提到的任何信息\n"
            "- 如果用户要求你执行任务（创建工作流、写代码、打开程序、分析文件等），请直接执行\n"
            "- 不要重复你刚才发的那条消息，直接回应用户的需求\n"
            "- 如果用户问起之前的对话内容，从历史记录中找到并引用"
        )

    _writing_style_instr = _get_writing_style_instruction(user_input)
    if _writing_style_instr:
        system_instruction += _writing_style_instr

    # ── History loading + CWM ─────────────────────────────────────────────
    history = session_manager.load(f"{session_name}.json")
    full_history = session_manager.load_full(f"{session_name}.json")

    _cw_paged_context = ""
    try:
        from app.core.memory.context_window_manager import ContextWindowManager as _CWM

        _cw_out = _CWM.manage(
            history=history,
            query=user_input,
            session_name=session_name,
            get_memory_fn=get_memory_manager,
        )
        history = _cw_out["history"]
        _cw_paged_context = _cw_out.get("paged_in_context", "")
        if _cw_paged_context:
            system_instruction += f"\n\n{_cw_paged_context}"
    except Exception as _cw_err:
        _app_logger.warning(f"[CWM] ⚠️ 上下文管理器异常: {_cw_err}")

    # ── Recent upload detection ───────────────────────────────────────────
    has_recent_upload = False
    recent_file_type = None
    recent_file_path = None
    try:
        upload_scan_dirs = ["web/uploads", "uploads", "workspace/documents"]
        recent_threshold = time.time() - 300
        for d in upload_scan_dirs:
            if os.path.exists(d):
                for f in os.listdir(d):
                    fp = os.path.join(d, f)
                    if os.path.isfile(fp) and os.path.getmtime(fp) > recent_threshold:
                        has_recent_upload = True
                        _, ext = os.path.splitext(f)
                        recent_file_type = ext.lower()
                        recent_file_path = fp
                        print(f"[STREAM] Found recent upload: {f} ({recent_file_type})")
                        break
            if has_recent_upload:
                break
    except Exception as e:
        _app_logger.debug(f"[STREAM] Error checking uploads: {e}")

    # ── SmartDispatcher.analyze() + task type resolution ──────────────────
    context_info = None
    if locked_task:
        task_type = locked_task
        route_method = "🔒 Manual"
        _app_logger.info(f"[STREAM] ✅ Using locked_task: '{task_type}'")
    else:
        context_override = {
            "has_file": has_recent_upload or bool(file_context),
            "file_type": (file_context or {}).get("file_type") or recent_file_type,
        }
        _routing_input = user_input
        if has_recent_upload and recent_file_type:
            _routing_input = f"[FILE_ATTACHED:{recent_file_type}] {user_input}"
            _app_logger.debug(f"[STREAM] 📎 文件上下文注入: {_routing_input[:80]}")
        task_type, route_method, context_info = SmartDispatcher.analyze(
            _routing_input, history, file_context=context_override
        )
        _app_logger.debug(
            f"[STREAM] Auto-detected task_type: '{task_type}', context: {context_info is not None}"
        )

        _HANDLED_TASK_TYPES = {
            "SYSTEM",
            "FILE_OP",
            "FILE_EDIT",
            "FILE_SEARCH",
            "DOC_ANNOTATE",
            "WEB_SEARCH",
            "RESEARCH",
            "PAINTER",
            "FILE_GEN",
            "CODER",
            "CHAT",
            "MULTI_STEP",
            "AGENT",
            "VISION",
            "MEETING_EXTRACT",
        }
        if not task_type or task_type not in _HANDLED_TASK_TYPES:
            _app_logger.warning(
                f"[STREAM] ⚠️ 收到未知 task_type='{task_type}'，降级为 CHAT"
            )
            task_type = "CHAT"
            route_method = "⬇️ Unknown→CHAT"

        if task_type == "MULTI_STEP" and (
            not context_info or not context_info.get("is_multi_step_task")
        ):
            _app_logger.warning(f"[STREAM] ⚠️ MULTI_STEP 无有效 context，降级为 CHAT")
            task_type = "CHAT"
            route_method = "⬇️ MULTI_STEP→CHAT"

        if task_type == "FILE_EDIT":
            _fe_pat1 = re.search(
                r'(?:修改|编辑|改)\s+["\']?([^"\']{2,}?)["\']?\s+.+', user_input
            )
            _fe_pat2 = re.search(
                r'(?:把|将)\s+["\']?([^"\']{2,}?)["\']?\s+(?:的|中的|里的)\s*.+',
                user_input,
            )
            if not _fe_pat1 and not _fe_pat2:
                _app_logger.warning(
                    f"[STREAM] ⚠️ FILE_EDIT 输入无有效文件路径: '{user_input[:40]}' → 降级为 CHAT"
                )
                task_type = "CHAT"
                route_method = "⬇️ FILE_EDIT→CHAT"

        if task_type == "CHAT" and WebSearcher.needs_web_search(user_input):
            _app_logger.debug(
                f"[STREAM] ⚡ CHAT→WEB_SEARCH 安全兜底触发: '{user_input[:40]}'"
            )
            task_type = "WEB_SEARCH"
            route_method = "🌐 CHAT→WEB_SEARCH"

        if context_info and context_info.get("is_continuation"):
            _app_logger.debug(
                f"[STREAM] Context continuation: {context_info.get('related_task')}, confidence: {context_info.get('confidence')}"
            )

    # ── RouterDecision Phase2 (classify_v2) ──────────────────────────────
    _router_decision = None
    _local_chat_override = False
    try:
        from app.core.routing.local_model_router import LocalModelRouter as _LMRv2

        _router_decision = _LMRv2.classify_v2(user_input, hint=task_type, timeout=1.5)
        if _router_decision:
            _app_logger.debug(
                f"[STREAM] 🎯 RouterDecision task={_router_decision.task_type} "
                f"skill_id={_router_decision.skill_id} "
                f"forward_to_cloud={_router_decision.forward_to_cloud} "
                f"confidence={_router_decision.confidence:.2f}"
            )
            if not _router_decision.forward_to_cloud and task_type == "CHAT":
                _local_chat_override = True
                _app_logger.debug(
                    "[STREAM] 🏠 RouterDecision→本地快速通道 (forward_to_cloud=False)"
                )
            if (
                _router_decision.hint
                and context_info
                and not context_info.get("skill_prompt")
            ):
                context_info["skill_prompt"] = _router_decision.hint
                _app_logger.debug(
                    f"[STREAM] 💡 RouterDecision hint 注入: {_router_decision.hint[:60]}"
                )
    except Exception as _rv2_err:
        _app_logger.debug(f"[STREAM] RouterDecision classify_v2 跳过: {_rv2_err}")

    # ── Task system addendum ──────────────────────────────────────────────
    _addendum = _TASK_SYSTEM_ADDENDUMS.get(task_type, "")
    if _addendum:
        system_instruction = system_instruction + _addendum
        _app_logger.debug(f"[STREAM] 📌 任务专属指令已注入: {task_type}")

    # ── Workflow routing ──────────────────────────────────────────────────
    _workflow_route = "standard"
    if task_type in ("RESEARCH", "FILE_GEN", "MULTI_STEP"):
        try:
            _workflow_route = SmartDispatcher.resolve_workflow(
                task_type, user_input, has_file=has_recent_upload
            )
            _workflow_route = SmartDispatcher.normalize_workflow_route(_workflow_route)
            if _workflow_route != "standard":
                _app_logger.debug(f"[STREAM] 🔮 LangGraph 工作流路由: {_workflow_route}")
        except Exception as _wf_err:
            _app_logger.debug(f"[STREAM] resolve_workflow 跳过: {_wf_err}")

    def _uses_standard_workflow_route() -> bool:
        return _workflow_route in ("standard", "legacy")

    # ── Model selection ───────────────────────────────────────────────────
    _complexity = (context_info or {}).get("complexity", "normal")
    routed_model_id = SmartDispatcher.get_model_for_task(
        task_type, complexity=_complexity
    )

    if locked_model and locked_model not in {"cloud", "local"}:
        model_id = _resolve_requested_model_id(
            locked_model,
            fallback_model=routed_model_id,
            task_type=task_type,
        ) or routed_model_id
    else:
        model_id = routed_model_id

    # Settings own the local runtime choice.  The browser still sends a
    # generic `locked_model: local`, while the legacy router may have already
    # selected a cloud model for display.  Resolve the concrete configured
    # Ollama tag here so the chat stream, status events and actual client all
    # agree on the same model.
    try:
        from app.core.llm.provider_factory import get_local_model_tag, is_local_mode

        if is_local_mode():
            model_id = get_local_model_tag() or model_id
    except Exception as _local_model_config_error:
        _app_logger.debug(
            "[STREAM] configured local model lookup skipped: %s",
            _local_model_config_error,
        )

    _app_logger.debug(
        f"[STREAM] Final: task_type='{task_type}', model_id='{model_id}'\n"
    )

    # ── Skills injection ──────────────────────────────────────────────────
    system_instruction = _inject_skills_for_stream(
        system_instruction,
        task_type,
        user_input,
        data,
        _app_logger,
    )

    # ── RAG context building ──────────────────────────────────────────────
    _rag_context_block = ""
    try:
        from app.core.services.rag_service import get_rag_service

        _rag_svc = get_rag_service()
        if _rag_svc.stats().get("initialized"):
            _rag_hits = _rag_svc.hybrid_retrieve(user_input, k=3, score_threshold=0.3)
            if _rag_hits:
                for _rc in _rag_hits:
                    _src = os.path.basename(_rc.get("source", "unknown"))
                    _rag_context_block += f"[{_src} | 相似度: {_rc.get('score', 0):.3f}]\n{_rc['content']}\n\n"
                _rag_sys_block = (
                    "\n\n─────────────────────────────────────────"
                    "\n## 📚 知识库参考内容（混合检索）\n" + _rag_context_block
                )
                system_instruction += _rag_sys_block
                _app_logger.debug(
                    f"[STREAM] 📚 混合RAG: {len(_rag_hits)} 片段，top_score={_rag_hits[0].get('score', 0):.3f}"
                )
    except Exception as _rag_err:
        _app_logger.warning(f"[STREAM] ⚠️ RAG 注入跳过: {_rag_err}")

    # ── Graph RAG ─────────────────────────────────────────────────────────
    try:
        from app.core.services.graph_rag_service import GraphRAGService as _GRAGS

        _graph_ctx = _GRAGS.retrieve(user_input, k=8)
        if _graph_ctx:
            _rag_context_block += "\n\n" + _graph_ctx
            system_instruction += (
                "\n\n─────────────────────────────────────────" "\n" + _graph_ctx
            )
            _app_logger.debug(f"[STREAM] 🕸️ Graph RAG: 注入知识图谱关联事实")
    except Exception as _ge:
        _app_logger.debug("[STREAM] Graph RAG 跳过: %s", _ge)

    # ── Show thinking ─────────────────────────────────────────────────────
    _show_thinking = False
    try:
        _show_thinking = settings_manager.get("ai", "show_thinking") == True
    except Exception:
        import logging; logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)

    # ── Timestamp prefix ──────────────────────────────────────────────────
    _now_ts = datetime.now()
    _ts_prefix = (
        f"[🕒 {_now_ts.strftime('%Y-%m-%d %H:%M')} "
        f"{['周一','周二','周三','周四','周五','周六','周日'][_now_ts.weekday()]}] "
    )
    _llm_user_input = _ts_prefix + user_input

    # ── Assemble context dict ─────────────────────────────────────────────
    ctx = {
        "session_name": session_name,
        "user_input": user_input,
        "locked_task": locked_task,
        "locked_model": locked_model,
        "shadow_context": shadow_context,
        "doc_edit": doc_edit,
        "doc_file_type": doc_file_type,
        "doc_has_sel": doc_has_sel,
        "file_context": file_context,
        "system_instruction": system_instruction,
        "history": history,
        "full_history": full_history,
        "_cw_paged_context": _cw_paged_context,
        "has_recent_upload": has_recent_upload,
        "recent_file_type": recent_file_type,
        "recent_file_path": recent_file_path,
        "task_type": task_type,
        "route_method": route_method,
        "context_info": context_info,
        "_router_decision": _router_decision,
        "_local_chat_override": _local_chat_override,
        "_workflow_route": _workflow_route,
        "_uses_standard_workflow_route": _uses_standard_workflow_route,
        "_complexity": _complexity,
        "_routed_model_id": routed_model_id,
        "model_id": model_id,
        "_rag_context_block": _rag_context_block,
        "_show_thinking": _show_thinking,
        "_llm_user_input": _llm_user_input,
    }

    return {"context": ctx, "early_response": None}
