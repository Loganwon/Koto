# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

import logging

from app.core.llm.model_selection import select_task_model

_logger = logging.getLogger(__name__)


def agent_request_options(context):
    """Project prepared HTTP context onto the Agent transport's narrow input."""
    return {
        "system_context": context.get("agent_system_context", ""),
        "model_id": context.get("model_id"),
        "file_context": context.get("file_context"),
        "frontend_session_id": context.get("frontend_session_id", ""),
        "frontend_scope": context.get("frontend_scope"),
        "task_id": context.get("task_id"),
        "run_id": context.get("run_id"),
    }


def handle_agent_task(
    task_type,
    session_name,
    user_input,
    history,
    locked_model,
    route_method,
    addon_runtime_plan,
    session_manager,
    _app_logger,
    _start_memory_extraction,
    _safe_sse,
    *,
    system_context="",
    model_id=None,
    file_context=None,
    frontend_session_id="",
    frontend_scope=None,
    task_id=None,
    run_id=None,
):
    """
    Handle AGENT task execution through Koto's deterministic production Agent.

    Returns a Flask Response if task_type is AGENT, otherwise None.
    """
    from flask import Response, copy_current_request_context, g, stream_with_context

    if task_type != "AGENT":
        return None

    _app_logger.debug("[STREAM] 🤖 执行 Koto production Agent")
    # Addon routing owns executable extension capabilities.
    _addon_plan = dict(addon_runtime_plan or {})
    _addon_tool_names = tuple(_addon_plan.get("tool_names") or ())
    requested_task_id = str(task_id or "").strip()
    requested_run_id = str(run_id or "").strip()

    def generate_agent():
        task_id = ""
        run_id = ""
        final_answer = ""
        collected_steps = []
        terminal_status = "failed"
        error_message = ""
        answer_seen = False
        terminal_metadata = {}
        active_system_context = system_context
        classification_pending = True
        classification_payload = {
            "task_type": "AGENT", "route_method": route_method,
            "model_id": model_id or "", "message": "🎯 任务分类: 🤖 Koto Agent",
        }

        def emit(event_type, payload, *, journal=True):
            """Persist once, then project the same event to the chat transport."""
            event = {"type": event_type, **payload}
            if task_id:
                event.setdefault("task_id", task_id)
            if run_id:
                event.setdefault("run_id", run_id)
            if journal and task_id and run_id:
                try:
                    from app.core.tasks.task_ledger import get_ledger

                    canonical = get_ledger().append_run_event(
                        task_id, run_id, event_type, payload
                    )
                    event = {**canonical, **event}
                except Exception as exc:
                    _app_logger.warning("[STREAM] Agent event persistence failed: %s", exc)
                    event["persisted"] = False
                else:
                    try:
                        from app.core.tasks.progress_bus import (
                            ProgressEvent, get_progress_bus,
                        )

                        get_progress_bus().publish(ProgressEvent.from_run_event(
                            canonical, session_id=session_name,
                        ))
                    except Exception as exc:
                        _app_logger.warning("[STREAM] Agent event broadcast failed: %s", exc)
            encoded = _safe_sse(event)
            event_id = str(event.get("event_id") or "")
            return f"id: {event_id}\n{encoded}" if event_id else encoded

        if locked_model == "local":
            from app.core.shared.llm_helpers import (
                is_ollama_alive as _is_ollama_alive,
            )

            if not _is_ollama_alive():
                error_message = "本地模式已启用，但 Ollama 未运行。请执行 ollama serve。"
                yield emit("error", {"message": error_message})
                yield emit("task_final", {"data": {
                    "id": "", "status": "failed", "error": error_message,
                    "result": "", "steps": [], "engine": "kernel",
                }})
                yield emit("done", {"status": "failed"})
                return

        try:
            from app.core.agent.kernel_agent_service import get_kernel_agent
            from app.core.agent.kernel_step_events import project_agent_step
            from app.core.agent.types import AgentStepType

            if requested_task_id or requested_run_id:
                from app.core.tasks.task_ledger import get_ledger

                if not requested_task_id or not requested_run_id:
                    raise ValueError("task_id 和 run_id 必须同时提供")
                task_ledger = get_ledger()
                task_ledger.bind_run_identity(requested_task_id, requested_run_id, session_id=session_name)
                if task_ledger.get(requested_task_id) is not None:
                    raise ValueError("该任务已经登记，请连接已有任务的进度流，不能重复执行")

            agent = get_kernel_agent(
                local=locked_model == "local",
                model_id=model_id or (
                    None if locked_model == "local" else select_task_model("AGENT")
                ),
                tool_profile="core",
                addon_tool_names=_addon_tool_names,
            )
            _addon_invocation_context = None
            if _addon_tool_names:
                from flask import g

                from app.core.agent.plugin_protocol import (
                    AddonInvocationContext,
                    DataClassification,
                )
                from web.blueprints.auth import resolve_addon_identity

                _tenant_id, _principal_id = resolve_addon_identity()
                if _tenant_id and _principal_id:
                    _addon_invocation_context = AddonInvocationContext(
                        request_id=str(getattr(g, "request_id", "") or ""),
                        session_id=str(session_name or ""),
                        tenant_id=_tenant_id,
                        principal_id=_principal_id,
                        purpose_code="interactive_agent_task",
                        data_classification=DataClassification(
                            str(_addon_plan.get("data_classification") or "internal")
                        ),
                        correlation_id=str(
                            getattr(g, "request_id", "") or session_name or ""
                        ),
                    )
            scope = dict(frontend_scope or {})
            if frontend_session_id:
                scope.setdefault("frontend_session_id", frontend_session_id)
            if isinstance(file_context, dict):
                scope.setdefault("document_path", file_context.get("file_path") or "")
                scope.setdefault("file_id", file_context.get("file_id") or "")
            if scope.get("frontend_session_id"):
                from app.core.agent.frontend_observability import (
                    bind_frontend_document_context,
                )

                _addon_invocation_context = bind_frontend_document_context(
                    _addon_invocation_context, scope, session_id=session_name
                )
                if getattr(_addon_invocation_context, "frontend_document_scope", None):
                    active_system_context += (
                        "\n\n当前文档已由宿主验证连接。可调用 ui_read_context 读取编辑器实际内容和 revision。"
                        "用户授权编辑时，用 ui_apply_edit 并提供读取到的 expected_revision；"
                        "只有 ui_save 的成功回执代表已保存。预览、已编辑和已保存分别说明，"
                        "分析或只读请求不要写入文档。"
                    )
            for step in agent.run(
                input_text=user_input,
                history=history,
                session_id=session_name,
                task_type="AGENT",
                system_context=active_system_context,
                stream_events=True,
                task_id=requested_task_id or None,
                run_id=requested_run_id or None,
                addon_tool_names=_addon_tool_names,
                addon_plan=_addon_plan,
                addon_invocation_context=_addon_invocation_context,
            ):
                step_data = step.to_dict()
                metadata = dict(step_data.get("metadata") or {})
                task_id = str(metadata.get("task_id") or task_id)
                run_id = str(metadata.get("run_id") or run_id)
                is_run_start = step_data.get("step_type") == "stream" and metadata.get("event_type") == "run.started"
                if classification_pending and not is_run_start:
                    yield emit("classification", classification_payload)
                    classification_pending = False
                if step_data.get("step_type") == "stream":
                    event_type, payload = project_agent_step(step_data)
                    if event_type == "run.finished":
                        # The HTTP owner publishes one terminal fact after the
                        # final answer and session save, never two terminals.
                        terminal_metadata = payload
                        continue
                    yield emit(event_type, payload)
                    if classification_pending:
                        yield emit("classification", classification_payload)
                        classification_pending = False
                    continue
                collected_steps.append(step_data)
                if step.step_type == AgentStepType.ANSWER:
                    final_answer = step.content or ""
                    answer_seen = True
                    terminal_status = (
                        "blocked" if (metadata.get("validation") or {}).get("blocked")
                        else "success"
                    )
                elif step.step_type == AgentStepType.ERROR:
                    error_message = step.content or "Agent 执行失败。"
                    terminal_status = (
                        "cancelled" if metadata.get("state") == "cancelled" else "failed"
                    )
                    answer_seen = False
                yield emit("agent_step", {"data": step_data})
            if not answer_seen and not error_message:
                error_message = "Agent 未返回完成结果，任务未完成。"
                terminal_status = "failed"
                yield emit("error", {"message": error_message})
        except Exception as exc:
            _app_logger.exception("[AGENT] production Agent failed")
            terminal_status = "failed"
            error_message = f"Agent 执行失败: {exc}"
            yield emit("error", {"message": error_message})

        task_payload = {
            "id": task_id,
            "task_id": task_id,
            "run_id": run_id,
            "status": terminal_status,
            "result": final_answer,
            "steps": collected_steps,
            "engine": "kernel",
        }
        if error_message:
            task_payload["error"] = error_message

        try:
            saved_answer = final_answer if answer_seen else (
                f"[Agent 任务{'已取消' if terminal_status == 'cancelled' else '未完成'}] "
                + error_message
            )
            session_manager.append_and_save(
                f"{session_name}.json",
                user_input,
                saved_answer,
            )
        except Exception as _se:
            _app_logger.warning("[STREAM] Agent 会话保存失败: %s", _se)
        if terminal_status == "success":
            try:
                _start_memory_extraction(
                    user_input, final_answer, [], task_type="AGENT",
                    session_name=session_name,
                )
            except Exception as _me:
                _app_logger.debug("[STREAM] Agent 记忆提取跳过: %s", _me)
        terminal_payload = {
            **terminal_metadata, "status": terminal_status,
            "state": {"success": "succeeded"}.get(terminal_status, terminal_status),
            "result": final_answer,
        }
        if terminal_status == "blocked" and terminal_metadata.get("state"):
            terminal_payload["runtime_state"] = terminal_metadata["state"]
        if error_message:
            terminal_payload["error"] = error_message
        yield emit("run.finished", terminal_payload)
        # Legacy transport views of the terminal fact do not create journal
        # entries after first-terminal-wins has closed the durable run.
        yield emit("task_final", {"data": task_payload}, journal=False)
        yield emit("done", {"status": terminal_status}, journal=False)

    producer = generate_agent()
    request_globals = dict(g._get_current_object().__dict__)

    @copy_current_request_context
    def finish_producer():
        # Flask copies the request/session context, but creates a fresh g in
        # another worker. Preserve the host-authenticated identity and trace
        # values rather than resolving a different identity after disconnect.
        g.__dict__.update(request_globals)
        try:
            for _frame in producer:
                pass
        except Exception:
            _app_logger.exception("[STREAM] Detached Agent continuation failed")
            raise

    def transport():
        try:
            for frame in producer:
                yield frame
        except GeneratorExit:
            # The viewer does not own execution. Continue this exact generator
            # on the existing JobRunner pool; resubmitting agent.run would
            # execute tools and save the same conversation a second time.
            request_globals.update(g._get_current_object().__dict__)
            try:
                from app.core.jobs.job_runner import get_job_runner

                get_job_runner().submit_continuation(finish_producer)
            except Exception:
                _app_logger.exception("[STREAM] Could not hand off the Agent producer")
                producer.close()
            raise

    return Response(
        stream_with_context(transport()), mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
