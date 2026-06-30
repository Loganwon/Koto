# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

import json
import logging
import time

_logger = logging.getLogger(__name__)


def handle_agent_task(
    task_type,
    session_name,
    user_input,
    history,
    locked_model,
    route_method,
    _router_decision,
    SmartDispatcher,
    session_manager,
    _app_logger,
    _start_memory_extraction,
    _safe_sse,
):
    """
    Handle AGENT task execution (LangGraphAgent ReAct, fallback to UnifiedAgent).

    Returns a Flask Response if task_type is AGENT, otherwise None.
    """
    from flask import Response

    if task_type != "AGENT":
        return None

    _app_logger.debug(f"[STREAM] 🤖 执行 Agent 任务 (LangGraphAgent ReAct)")
    _agent_skill_id = _router_decision.skill_id if _router_decision else None

    def generate_agent():
        if locked_model == "local":
            from app.core.socket_handler import _is_ollama_alive, _get_local_provider
            if not _is_ollama_alive():
                yield _safe_sse({
                    "type": "error",
                    "message": "本地模式已启用，但 Ollama 未运行。请执行 ollama serve。",
                })
                return
            yield f"data: {json.dumps({'type': 'classification', 'task_type': 'AGENT', 'route_method': 'ollama_local', 'message': '🦙 本地模式，使用 Ollama 回答…'})}\n\n"
            try:
                _lp = _get_local_provider()
                _local_answer = ""
                for _ck in _lp.generate_content(prompt=user_input, stream=True):
                    _t = _ck.get("content", "") if isinstance(_ck, dict) else str(_ck)
                    if _t:
                        _local_answer += _t
                        yield f"data: {json.dumps({'type': 'token', 'content': _t}, ensure_ascii=False)}\n\n"
                _lp_payload = {"id": f"task_{int(time.time() * 1000)}", "status": "success",
                               "result": _local_answer, "steps": [], "engine": "ollama"}
                yield f"data: {json.dumps({'type': 'task_final', 'data': _lp_payload}, ensure_ascii=False)}\n\n"
                try:
                    session_manager.append_and_save(f"{session_name}.json", user_input, _local_answer)
                except Exception as _save_exc:
                    _app_logger.debug("[STREAM] 保存本地模式对话失败: %s", _save_exc)
            except Exception as _ole:
                yield _safe_sse({
                    "type": "error",
                    "message": f"本地模型失败: {_ole}",
                })
            return

        yield f"data: {json.dumps({'type': 'classification', 'task_type': 'AGENT', 'route_method': route_method, 'message': '🎯 任务分类: 🤖 智能助手 (LangGraph ReAct)'})}\n\n"

        final_answer = ""
        collected_steps = []

        _lg_ok = False
        try:
            from app.core.agent.factory import create_langgraph_agent

            _lg_agent = create_langgraph_agent(
                model_id=SmartDispatcher.get_model_for_task("AGENT"),
            )
            _lg_ok = True
            for chunk in _lg_agent.stream(
                input_text=user_input,
                history=history,
                session_id=session_name,
                skill_id=_agent_skill_id,
                task_type="AGENT",
            ):
                ctype = chunk.get("type", "token")
                content = chunk.get("content", "")
                if ctype == "answer":
                    final_answer = content
                    step_data = {
                        "step_type": "ANSWER",
                        "content": content,
                        "tool": None,
                    }
                elif ctype == "tool_call":
                    step_data = {
                        "step_type": "TOOL_CALL",
                        "content": f"调用工具: {content}",
                        "tool": content,
                        "args": chunk.get("args", {}),
                    }
                elif ctype == "tool_result":
                    step_data = {
                        "step_type": "TOOL_RESULT",
                        "content": content,
                        "tool": None,
                    }
                elif ctype == "token":
                    step_data = {
                        "step_type": "THINKING",
                        "content": content,
                        "tool": None,
                    }
                elif ctype == "error":
                    raise RuntimeError(content)
                else:
                    continue
                collected_steps.append(step_data)
                yield f"data: {json.dumps({'type': 'agent_step', 'data': step_data}, ensure_ascii=False)}\n\n"

        except Exception as _lg_err:
            _app_logger.debug(
                f"[AGENT] LangGraphAgent 失败 ({_lg_err})，降级到 UnifiedAgent..."
            )
            _lg_ok = False

        if not _lg_ok:
            try:
                from app.core.agent.factory import create_agent
                from app.core.agent.types import AgentStepType

                _ua = create_agent(
                    model_id=SmartDispatcher.get_model_for_task("AGENT")
                )
                collected_steps = []
                final_answer = ""
                for step in _ua.run(
                    input_text=user_input,
                    history=history,
                    session_id=session_name,
                    skill_id=_agent_skill_id,
                    task_type="AGENT",
                ):
                    step_data = step.to_dict()
                    collected_steps.append(step_data)
                    if step.step_type == AgentStepType.ANSWER:
                        final_answer = step.content or ""
                    yield f"data: {json.dumps({'type': 'agent_step', 'data': step_data}, ensure_ascii=False)}\n\n"
                if not final_answer and collected_steps:
                    final_answer = collected_steps[-1].get("content", "")
            except Exception as e:
                import traceback

                _app_logger.error(
                    f"[AGENT] ❌ UnifiedAgent 也失败:\n{traceback.format_exc()}"
                )
                yield _safe_sse({
                    "type": "error",
                    "message": f"Agent 执行失败: {str(e)}",
                })
                return

        task_payload = {
            "id": f"task_{int(time.time() * 1000)}",
            "status": "success",
            "result": final_answer,
            "steps": collected_steps,
            "engine": "langgraph" if _lg_ok else "unified",
        }
        yield f"data: {json.dumps({'type': 'task_final', 'data': task_payload}, ensure_ascii=False)}\n\n"

        try:
            session_manager.append_and_save(
                f"{session_name}.json",
                user_input,
                final_answer or "[Agent 任务完成]",
            )
        except Exception as _se:
            _app_logger.warning("[STREAM] Agent 会话保存失败: %s", _se)
        try:
            _start_memory_extraction(
                user_input,
                final_answer or "",
                [],
                task_type="AGENT",
                session_name=session_name,
            )
        except Exception as _me:
            _app_logger.debug("[STREAM] Agent 记忆提取跳过: %s", _me)

    return Response(generate_agent(), mimetype="text/event-stream")
