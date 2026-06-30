# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

import json
import time
import os
import re

from web.sse.sanitizer import safe_sse as _safe_sse


def handle_regular(
    yield_thinking,
    task_type,
    user_input,
    session_name,
    start_time,
    client,
    _app_logger,
    session_manager,
    settings_manager,
    request,
    _safe_sse,
    MODEL_MAP,
    locked_model,
    use_instruction,
    history,
    context_info,
    _interrupt_manager,
    _rag_context_block,
    SmartDispatcher,
    _LMRv2,
):
    from google.genai import types
    from web.runtime_context import get_utils
    from web.utils.threading_utils import stream_with_keepalive

    Utils = get_utils()
    try:
        from web.context_analyzer import ContextAnalyzer
    except Exception:
        class ContextAnalyzer:
            @staticmethod
            def filter_history(_query, history):
                return history

    def interrupted():
        return _interrupt_manager.is_interrupted(session_name)

    model_id = MODEL_MAP.get(task_type, MODEL_MAP.get("CHAT", "gemini-2.5-flash"))
    full_history = history
    _local_chat_override = (context_info or {}).get("local_chat_override", False)
    _memory_manager = get_memory_manager()

    try:

        if full_history and len(full_history) > 20:

            def _summarize():
                return _memory_manager.get_or_update_summary(
                    session_name, full_history
                )

            _, err, timed_out = run_with_timeout(_summarize, 6)
            if timed_out:
                _app_logger.debug("[MEMORY] 摘要更新超时, 已跳过")
            elif err:
                _app_logger.debug(f"[MEMORY] 摘要更新失败: {err}")

        memory_context = _memory_manager.get_context_string(
            user_input, session_name=session_name, history=full_history
        )
        if memory_context:
            use_instruction += f"\n\n{memory_context}"
            _app_logger.debug(
                f"[MEMORY] 注入了 {len(memory_context)} 字符的记忆上下文"
            )
            t = yield_thinking(
                f"从长期记忆中检索到 {len(memory_context)} 字符的相关上下文并注入",
                "context",
                "local",
            )
            if t:
                yield t

        if task_type == "CODER":
            used_model = model_id
            t = yield_thinking(
                f"进入代码生成模式, 使用 {model_id} 进行代码分析与生成",
                "generating",
                "cloud",
            )
            if t:
                yield t
            yield _safe_sse({'type': 'progress', 'message': '💻 正在分析代码需求...', 'detail': f'使用 {model_id}'})

            if any(
                k in user_input.lower()
                for k in ["游戏", "app", "五子棋", "pygame", "install", "安装"]
            ):
                use_instruction += "\n\n[Important] If suggesting to install packages (like pygame), assume the user knows how to use pip. Just output `pip install package_name` in a code block. Do NOT write long tutorials about installation. Focus on the Python Code."

        elif task_type == "CHAT":
            used_model = model_id
            t = yield_thinking(
                f"进入对话模式, 使用 {model_id} 生成回复", "generating", "cloud"
            )
            if t:
                yield t
            yield _safe_sse({'type': 'progress', 'message': '💬 Koto 正在思考...', 'detail': '请稍候'})

            from app.core.routing import LocalModelRouter

            if locked_model != "local" and (
                _local_chat_override or LocalModelRouter.is_simple_query(
                    user_input, task_type, history
                )
            ):
                local_stream = LocalModelRouter.generate_stream(
                    user_input,
                    history=history,
                    system_instruction=use_instruction,
                )
                if local_stream is not None:
                    _app_logger.debug(
                        f"[CHAT] ⚡ 使用本地模型快速响应: {LocalModelRouter._response_model}"
                    )
                    t = yield_thinking(
                        f"检测到简单查询, 切换到本地模型 {LocalModelRouter._response_model} 快速响应",
                        "model",
                        "local",
                    )
                    if t:
                        yield t
                    yield _safe_sse({'type': 'classification', 'task_type': task_type, 'task_display': '💬 对话', 'model': f'🏠 {LocalModelRouter._response_model} (本地)', 'message': f'🎯 任务分类: 💬 对话 (方法: 🏠 {LocalModelRouter._response_model} 本地快速通道)'})
                    local_full_text = ""
                    local_ok = False
                    try:
                        for chunk in local_stream:
                            local_full_text += chunk
                            yield _safe_sse({'type': 'token', 'content': chunk})
                        local_ok = bool(local_full_text.strip())
                    except Exception as local_err:
                        _app_logger.debug(f"[CHAT] 本地模型生成失败: {local_err}")

                    if local_ok:
                        session_manager.append_and_save(
                            f"{session_name}.json",
                            user_input,
                            local_full_text,
                            task=task_type,
                            model_name=f"ollama/{LocalModelRouter._response_model}",
                        )
                        _reflect_types_local = {
                            "CHAT",
                            "RESEARCH",
                            "CODER",
                            "FILE_GEN",
                            "AGENT",
                        }
                        if task_type in _reflect_types_local:
                            _start_memory_extraction(
                                user_input,
                                local_full_text,
                                history,
                                task_type=task_type,
                                session_name=session_name,
                            )
                        total_time = time.time() - start_time
                        _app_logger.debug(
                            f"[CHAT] ⚡ 本地模型响应完成 ({total_time:.2f}s)"
                        )
                        yield _safe_sse({'type': 'done', 'images': [], 'saved_files': [], 'total_time': total_time})
                        return
                    else:
                        _app_logger.debug(f"[CHAT] 本地模型输出为空, 降级到云模型")
                        t = yield_thinking(
                            f"本地模型输出为空, 降级到云端模型 {model_id}",
                            "model",
                            "hybrid",
                        )
                        if t:
                            yield t
                        yield _safe_sse({'type': 'progress', 'message': '☁️ 切换到云端模型...', 'detail': model_id})
        elif task_type == "RESEARCH":
            yield _safe_sse({'type': 'progress', 'message': '🔬 正在进行深度分析...', 'detail': f'使用 {model_id}'})
        else:
            yield _safe_sse({'type': 'progress', 'message': '💭 Koto 正在思考...', 'detail': '请稍候'})

        _task_skill = (context_info or {}).get("skill_prompt")
        if _task_skill:
            use_instruction += f"\n\n[响应要求] {_task_skill}"

        if context_info and context_info.get("is_continuation"):
            history_for_model = history
            t = yield_thinking(
                f"检测到上下文延续, 保留全部 {len(history)} 轮对话历史",
                "context",
                "hybrid",
            )
            if t:
                yield t
        else:
            history_for_model = ContextAnalyzer.filter_history(user_input, history)
            if len(history_for_model) != len(history):
                t = yield_thinking(
                    f"过滤对话历史: {len(history)} 轮 → {len(history_for_model)} 轮相关记录",
                    "context",
                    "hybrid",
                )
                if t:
                    yield t

        formatted_history = []
        for turn in history_for_model:
            formatted_history.append(
                types.Content(
                    role=turn["role"],
                    parts=[types.Part.from_text(text=p) for p in turn["parts"]],
                )
            )

        t = yield_thinking(
            f"准备调用 {model_id} API, 发送 {len(formatted_history)+1} 条消息",
            "generating",
        )
        if t:
            yield t

        import concurrent.futures as _cf

        _plan_future = None
        try:
            from app.core.routing import LocalModelRouter as _LMR_plan

            if _LMR_plan.is_ollama_available() and _LMR_plan._initialized:
                _plan_exec = _cf.ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="koto_plan"
                )
                _plan_future = _plan_exec.submit(
                    _LMR_plan.generate_plan, user_input, task_type
                )
                _plan_exec.shutdown(wait=False)
        except Exception:
            _plan_future = None

        effective_input = user_input
        if _rag_context_block:
            _rag_augmented_input = (
                f"[📚 知识库参考内容（请以此为事实依据）]\n"
                f"{_rag_context_block}"
                f"────────────────────────────────────────────\n"
                f"[用户问题]\n{effective_input}"
            )
        else:
            _rag_augmented_input = effective_input

        if locked_model == "local":
            from app.core.routing import LocalModelRouter as _LMR_all
            _lmr_name = _LMR_all._response_model or "本地模型"
            yield _safe_sse({'type': 'classification', 'task_type': task_type, 'task_display': task_type, 'model': f'🏠 {_lmr_name} (本地)', 'message': f'🏠 本地模型处理 {task_type} 任务'})
            _local_all_stream = _LMR_all.generate_stream(
                _rag_augmented_input,
                history=history,
                system_instruction=use_instruction,
            )
            if _local_all_stream is None:
                _err_msg = "❌ 本地模型 (Ollama) 未响应.\n\n请检查:\n1. Ollama 是否正常运行（`ollama serve`）\n2. 所选模型是否已下载（`ollama list`）\n3. 或在设置中切换到云端模式"
                yield _safe_sse({'type': 'token', 'content': _err_msg})
                total_time = time.time() - start_time
                yield _safe_sse({'type': 'done', 'images': [], 'saved_files': [], 'total_time': total_time})
                return
            _local_all_text = ""
            _local_all_ok = False
            try:
                for _chunk in _local_all_stream:
                    _local_all_text += _chunk
                    yield _safe_sse({'type': 'token', 'content': _chunk})
                _local_all_ok = bool(_local_all_text.strip())
            except Exception as _le:
                _app_logger.debug(f"[LOCAL] 本地模型流式失败 ({task_type}): {_le}")
            if _local_all_ok:
                session_manager.append_and_save(
                    f"{session_name}.json",
                    user_input,
                    _local_all_text,
                    task=task_type,
                    model_name=f"ollama/{_LMR_all._response_model}",
                )
                _start_memory_extraction(
                    user_input,
                    _local_all_text,
                    history,
                    task_type=task_type,
                    session_name=session_name,
                )
                total_time = time.time() - start_time
                yield _safe_sse({'type': 'done', 'images': [], 'saved_files': [], 'total_time': total_time})
            else:
                _err_msg = "❌ 本地模型 (Ollama) 响应失败, 输出为空.\n\n请检查:\n1. Ollama 是否正常运行\n2. 所选模型是否已下载\n3. 或切换到云端模式"
                yield _safe_sse({'type': 'token', 'content': _err_msg})
                total_time = time.time() - start_time
                yield _safe_sse({'type': 'done', 'images': [], 'saved_files': [], 'total_time': total_time})
            return

        from app.core.llm.model_fallback import get_fallback_executor
        executor = get_fallback_executor()
        candidates = executor._build_candidate_list(model_id, task_type)

        stream_error = None
        response = None
        for candidate_model in candidates:
            if not executor.is_available(candidate_model):
                continue
            try:
                response = client.models.generate_content_stream(
                    model=candidate_model,
                    contents=formatted_history
                    + [
                        types.Content(
                            role="user",
                            parts=[types.Part.from_text(text=_rag_augmented_input)],
                        )
                    ],
                    config=types.GenerateContentConfig(system_instruction=use_instruction),
                )
                used_model = candidate_model
                if candidate_model != model_id:
                    _app_logger.warning(
                        f"[STREAM] 模型 {model_id} 不可用, 降级到 {candidate_model}"
                    )
                    yield _safe_sse({'type': 'progress', 'message': f'⚠️ {model_id} 不可用, 已切换到 {candidate_model}', 'detail': ''})
                    model_id = candidate_model
                stream_error = None
                break
            except Exception as e:
                _app_logger.warning(f"[STREAM] 模型 {candidate_model} 不可用: {str(e)[:100]}")
                executor.mark_unavailable(candidate_model)
                stream_error = e
                continue

        if response is None:
            if stream_error:
                raise stream_error
            raise RuntimeError(f"[STREAM] 所有候选模型均失败: {task_type}")

        full_text = ""
        chunk_count = 0
        heartbeat_interval = 5
        first_chunk_received = False
        _plan_flushed = False

        try:
            max_wait = 60 if task_type == "CODER" else 120
            for item_type, item_data in stream_with_keepalive(
                response,
                start_time,
                keepalive_interval=heartbeat_interval,
                max_wait_first_token=max_wait,
            ):
                if _interrupt_manager.is_interrupted(session_name):
                    _app_logger.debug(
                        f"[INTERRUPT] User interrupted at chunk {chunk_count}"
                    )
                    interrupt_msg = "\n\n⏸️ 用户已中断"
                    yield _safe_sse({'type': 'token', 'content': interrupt_msg})
                    break

                if not _plan_flushed and _plan_future is not None:
                    try:
                        _steps = _plan_future.result(timeout=0.05)
                        if _steps:
                            for _s in _steps:
                                _pt = yield_thinking(
                                    f"📋 {_s}", "planning", "local"
                                )
                                if _pt:
                                    yield _pt
                        _plan_flushed = True
                        _plan_future = None
                    except _cf.TimeoutError:
                        pass
                    except Exception:
                        _plan_flushed = True
                        _plan_future = None

                if item_type == "heartbeat":
                    elapsed = item_data
                    if first_chunk_received:
                        char_count = len(full_text)
                        if task_type == "CODER":
                            hb_msg = f"💻 代码生成中... 已输出 {char_count} 字符"
                        elif task_type == "RESEARCH":
                            hb_msg = f"🔬 深度分析中... 已输出 {char_count} 字符"
                        else:
                            hb_msg = "💭 正在生成..."
                        yield _safe_sse({'type': 'progress', 'message': hb_msg, 'detail': f'{elapsed}s', 'stage': 'generating'})
                    else:
                        if task_type == "CODER":
                            hb_msg = "💻 代码分析中, 请稍候..."
                        elif task_type == "RESEARCH":
                            hb_msg = "🔬 深度思考中, 请耐心等待..."
                        else:
                            hb_msg = "🧠 模型思考中..."
                        yield _safe_sse({'type': 'progress', 'message': hb_msg, 'detail': f'已等待 {elapsed}s', 'stage': 'api_calling'})

                elif item_type == "timeout":
                    if task_type == "CODER" and not full_text:
                        yield _safe_sse({'type': 'progress', 'message': '⚠️ 首包超时, 切换到快速模型...', 'detail': ''})
                        try:
                            fallback_resp = client.models.generate_content(
                                model="gemini-2.5-flash",
                                contents=formatted_history
                                + [
                                    types.Content(
                                        role="user",
                                        parts=[
                                            types.Part.from_text(
                                                text=_rag_augmented_input
                                            )
                                        ],
                                    )
                                ],
                                config=types.GenerateContentConfig(
                                    system_instruction=use_instruction,
                                    temperature=0.4,
                                    max_output_tokens=4000,
                                ),
                            )
                            fallback_text = fallback_resp.text or ""
                            if fallback_text:
                                full_text = fallback_text
                                yield _safe_sse({'type': 'token', 'content': fallback_text})
                        except Exception:
                            yield _safe_sse({'type': 'token', 'content': f'⚠️ {item_data}, 请稍后重试'})
                    else:
                        yield _safe_sse({'type': 'token', 'content': f'⚠️ {item_data}, 请稍后重试'})
                    break

                elif item_type == "chunk":
                    chunk = item_data
                    if chunk.text:
                        if not first_chunk_received:
                            first_chunk_received = True
                            _app_logger.debug(
                                f"[CHAT] 收到第一个响应, 耗时 {time.time() - start_time:.1f}s"
                            )
                            if not _plan_flushed and _plan_future is not None:
                                try:
                                    _steps = _plan_future.result(timeout=0.5)
                                    if _steps:
                                        for _s in _steps:
                                            _pt = yield_thinking(
                                                f"📋 {_s}", "planning", "local"
                                            )
                                            if _pt:
                                                yield _pt
                                except Exception:
                                    import logging; logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)
                                _plan_flushed = True
                                _plan_future = None

                        full_text += chunk.text
                        chunk_count += 1
                        yield _safe_sse({'type': 'token', 'content': chunk.text})

        except Exception as stream_error:
            error_str = str(stream_error)
            _app_logger.debug(f"[CHAT] Stream error: {error_str}")

            from app.core.socket_handler import _is_online_failure as _iof, _is_ollama_alive as _ioav
            from app.core.routing import LocalModelRouter as _LMR_fb
            _OLLAMA_TEXT_TASKS = {"CHAT", "CODER", "RESEARCH", "FILE_GEN", "MULTI_STEP", "AGENT"}

            if _iof(stream_error) and not full_text and task_type in _OLLAMA_TEXT_TASKS and _ioav():
                _app_logger.warning(f"[CHAT] cloud unavailable ({error_str[:60]}), falling back to Ollama")
                yield _safe_sse({'type': 'progress', 'message': '⚠️ 云端 AI 不可用, 已切换到本地模型 (Ollama)...', 'detail': ''})
                try:
                    _fb_stream = _LMR_fb.generate_stream(
                        user_input, history=history,
                        system_instruction=use_instruction,
                    )
                    if _fb_stream:
                        for _fc in _fb_stream:
                            if _fc:
                                full_text += _fc
                                yield _safe_sse({'type': 'token', 'content': _fc})
                    else:
                        raise RuntimeError("本地模型流不可用")
                except Exception as _fb_err:
                    _app_logger.error(f"[CHAT] Ollama fallback failed: {_fb_err}")
                    raise stream_error
            elif full_text:
                error_msg = error_str[:50]
                warn_text = f"\n\n⚠️ (传输中断: {error_msg}...)"
                yield _safe_sse({'type': 'token', 'content': warn_text})
            else:
                raise stream_error

        if Utils.is_failure_output(full_text):
            yield _safe_sse({'type': 'progress', 'message': '⚠️ 初次生成失败, 正在修正...', 'detail': ''})
            fix_prompt = Utils.build_fix_prompt(task_type, user_input, full_text)
            fix_resp = client.models.generate_content(
                model=model_id,
                contents=fix_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=use_instruction,
                    temperature=0.4,
                    max_output_tokens=4000,
                ),
            )
            corrected_text = fix_resp.text or full_text
            if corrected_text and corrected_text != full_text:
                corrected_msg = f"\n\n🔁 修正版本:\n{corrected_text}"
                yield _safe_sse({'type': 'token', 'content': corrected_msg})
                full_text = corrected_text
        else:
            is_complex_task = (
                task_type in ["RESEARCH", "FILE_GEN", "CODER"]
                or (context_info and context_info.get("complexity") == "complex")
                or len(user_input) > 200
            )
            if is_complex_task:
                check = Utils.quick_self_check(task_type, user_input, full_text)
                if not check.get("pass") and check.get("fix_prompt"):
                    status_msg = "🩺 自检未通过, 正在修正..."
                    yield _safe_sse({'type': 'progress', 'message': status_msg, 'detail': '快速模型自检'})
                    fix_resp = client.models.generate_content(
                        model=model_id,
                        contents=check["fix_prompt"],
                        config=types.GenerateContentConfig(
                            system_instruction=use_instruction,
                            temperature=0.4,
                            max_output_tokens=4000,
                        ),
                    )
                    corrected_text = fix_resp.text or full_text
                    if corrected_text and corrected_text != full_text:
                        corrected_msg = f"\n\n🔁 修正版本:\n{corrected_text}"
                        yield _safe_sse({'type': 'token', 'content': corrected_msg})
                        full_text = corrected_text

        if settings_manager.get("ai", "auto_save_files") is not False:
            saved_files = Utils.auto_save_files(full_text)
        else:
            saved_files = []

        if task_type == "CODER":
            pkgs = Utils.detect_required_packages(full_text)
            if pkgs:
                yield _safe_sse({'type': 'progress', 'message': '📦 检测到依赖, 正在检查/安装...', 'detail': ', '.join(pkgs)})
                install_result = Utils.auto_install_packages(pkgs)
                installed = install_result.get("installed", [])
                failed = install_result.get("failed", [])
                skipped = install_result.get("skipped", [])
                msg_parts = []
                if installed:
                    msg_parts.append(f"✅ 已安装: {', '.join(installed)}")
                if skipped:
                    msg_parts.append(f"ℹ️ 已存在: {', '.join(skipped)}")
                if failed:
                    msg_parts.append(f"⚠️ 安装失败: {', '.join(failed)}")
                if msg_parts:
                    msg_content = "\n\n" + "\n".join(msg_parts)
                    yield _safe_sse({'type': 'token', 'content': msg_content})

        if saved_files:
            files_list = ", ".join(saved_files)
            save_hint = (
                f"\n\n📁 文件已保存: **{files_list}**\n📂 位置: `{settings_manager.get('workspace', 'dir', fallback='.')}`"
            )
            yield _safe_sse({'type': 'token', 'content': save_hint})

        session_manager.append_and_save(
            f"{session_name}.json",
            user_input,
            full_text,
            task=task_type,
            model_name=model_id,
            saved_files=saved_files,
        )
        _reflect_types = {"CHAT", "RESEARCH", "CODER", "FILE_GEN", "AGENT"}
        if task_type in _reflect_types:
            _start_memory_extraction(
                user_input,
                full_text,
                history_for_model,
                task_type=task_type,
                session_name=session_name,
            )

        try:
            from app.core.learning.rating_store import RatingStore as _RS

            _done_msg_id = _RS.make_msg_id(session_name, user_input)
        except Exception:
            _done_msg_id = ""

        total_time = time.time() - start_time
        yield _safe_sse({'type': 'done', 'images': [], 'saved_files': saved_files, 'total_time': total_time, 'msg_id': _done_msg_id})

    except Exception as e:
        error_str = str(e)
        _app_logger.debug(f"[CHAT] Exception: {error_str}")

        from app.core.socket_handler import _is_online_failure as _iof2, _is_ollama_alive as _ioav2
        from app.core.routing import LocalModelRouter as _LMR_fb2
        _OLLAMA_TEXT_TASKS2 = {"CHAT", "CODER", "RESEARCH", "FILE_GEN", "MULTI_STEP", "AGENT"}

        if _iof2(e) and task_type in _OLLAMA_TEXT_TASKS2 and _ioav2():
            _app_logger.warning(f"[CHAT] outer: cloud failure ({error_str[:60]}), trying Ollama")
            yield _safe_sse({'type': 'progress', 'message': '⚠️ 云端 AI 不可用, 已切换到本地模型 (Ollama)...', 'detail': ''})
            _ollama_ok = False
            try:
                _fb2_stream = _LMR_fb2.generate_stream(
                    user_input, history=history,
                    system_instruction=use_instruction,
                )
                if _fb2_stream:
                    _fb2_full = ""
                    for _fc2 in _fb2_stream:
                        if _fc2:
                            _fb2_full += _fc2
                            yield _safe_sse({'type': 'token', 'content': _fc2})
                    if _fb2_full:
                        _ollama_ok = True
                        session_manager.append_and_save(
                            f"{session_name}.json", user_input, _fb2_full,
                            task=task_type, model_name=f"ollama/local",
                        )
                        total_time = time.time() - start_time
                        yield _safe_sse({'type': 'done', 'images': [], 'saved_files': [], 'total_time': total_time})
                        return
            except Exception as _fb2_err:
                _app_logger.error(f"[CHAT] outer Ollama fallback failed: {_fb2_err}")

            if not _ollama_ok:
                error_response = f"❌ 云端 AI 不可用, 本地模型也响应失败.\n\n原始错误: {error_str[:150]}"
                session_manager.append_and_save(
                    f"{session_name}.json", user_input, error_response,
                    task=task_type, model_name=model_id,
                )
                yield _safe_sse({'type': 'token', 'content': error_response})
                total_time = time.time() - start_time
                yield _safe_sse({'type': 'done', 'images': [], 'saved_files': [], 'total_time': total_time})
                return

        if (
            "location is not supported" in error_str.lower()
            or "failed_precondition" in error_str.lower()
        ):
            error_response = "❌ 地区限制\n\n您所在的地区不支持 Gemini API.\n\n💡 解决方案:\n1. 在 `config/gemini_config.env` 配置中转服务 `GEMINI_API_BASE`\n2. 或使用支持的代理服务\n3. 或启动本地 Ollama 模型作为备用"
        elif "API key not valid" in error_str or (
            "INVALID_ARGUMENT" in error_str and "api key" in error_str.lower()
        ):
            error_response = (
                "❌ **API 密钥无效**\n\n"
                "请检查您的 Gemini API 密钥:\n"
                "1. 前往 [aistudio.google.com/apikey](https://aistudio.google.com/apikey) 获取有效密钥\n"
                "2. 在 Koto 设置页面更新 API 密钥（设置 → API 配置）\n"
                "3. 确保密钥所在 Google 项目已启用 Generative Language API\n\n"
                f"原始错误: `{error_str[:150]}`"
            )
        elif (
            "server disconnected" in error_str.lower()
            or "disconnected without" in error_str.lower()
            or "connection reset" in error_str.lower()
            or "connection aborted" in error_str.lower()
        ):
            try:
                from app.core.llm.model_fallback import get_fallback_executor
                get_fallback_executor().mark_unavailable(model_id, ttl=120)
                _app_logger.warning(
                    f"[CHAT] 连接中断, 已将 {model_id} 标记不可用 120s, 下次自动降级"
                )
            except Exception:
                import logging; logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)
            error_response = (
                "❌ **服务器连接中断**\n\n"
                "与 Gemini API 的连接被意外断开, 这通常是临时性问题.\n\n"
                "💡 建议:\n"
                "1. 稍等片刻后重新发送消息\n"
                "2. 检查您的网络连接稳定性\n"
                "3. 如果使用代理, 请确认代理连接正常\n"
                "4. 如问题持续, 可尝试切换到其他模型"
            )
        elif (
            "resource_exhausted" in error_str.lower()
            or "quota" in error_str.lower()
            or "rate limit" in error_str.lower()
            or "429" in error_str
        ):
            error_response = (
                "❌ **API 配额超限**\n\n"
                "当前 API 密钥的请求频率或配额已达上限.\n\n"
                "💡 建议:\n"
                "1. 稍等 1-2 分钟后重试\n"
                "2. 在设置中切换到其他 API 密钥\n"
                "3. 或升级您的 Google AI Studio 计划"
            )
        elif (
            "unavailable" in error_str.lower()
            or "503" in error_str
            or "service unavailable" in error_str.lower()
        ):
            error_response = (
                "❌ **Gemini 服务暂时不可用**\n\n"
                "Gemini API 服务器当前无法响应, 可能正在维护中.\n\n"
                "💡 建议: 稍等片刻后重试, 或访问 [status.google.com](https://status.google.com) 查看服务状态"
            )
        elif (
            "deadline_exceeded" in error_str.lower()
            or "timed out" in error_str.lower()
        ):
            error_response = (
                "❌ **请求超时**\n\n"
                "模型响应时间过长, 请求已超时.\n\n"
                "💡 建议:\n"
                "1. 尝试缩短您的问题或分步骤提问\n"
                "2. 切换到响应更快的模型（如 gemini-2.5-flash）\n"
                "3. 检查网络连接质量"
            )
        else:
            error_response = f"❌ 发生错误: {error_str[:200]}"

        session_manager.append_and_save(
            f"{session_name}.json",
            user_input,
            error_response,
            task=task_type,
            model_name=model_id,
        )

        yield _safe_sse({'type': 'token', 'content': error_response})
        total_time = time.time() - start_time
        yield _safe_sse({'type': 'done', 'images': [], 'saved_files': [], 'total_time': total_time})


def _start_memory_extraction(*args, **kwargs):
    pass


def get_memory_manager():
    try:
        from web.runtime_context import get_memory_manager as _get_runtime_memory_manager

        manager = _get_runtime_memory_manager()
        if manager is not None:
            return manager
    except Exception:
        pass
    try:
        from web.enhanced_memory_manager import EnhancedMemoryManager

        return EnhancedMemoryManager()
    except Exception:
        from web.memory_manager import MemoryManager

        class _CompatMemoryManager:
            def __init__(self):
                self._base = MemoryManager()

            def get_or_update_summary(self, *args, **kwargs):
                return ""

            def get_context_string(self, user_input, *args, **kwargs):
                return self._base.get_context_string(user_input)

        return _CompatMemoryManager()


def run_with_timeout(func, timeout):
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func)
        try:
            result = future.result(timeout=timeout)
            return result, None, False
        except concurrent.futures.TimeoutError:
            return None, None, True
        except Exception as e:
            return None, str(e), False
