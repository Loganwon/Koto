# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

import json
import logging

_logger = logging.getLogger(__name__)


def handle_langgraph_workflow(
    _workflow_route,
    session_name,
    user_input,
    session_manager,
    _app_logger,
    _safe_sse,
):
    """
    Handle LangGraph workflow routing for RESEARCH / FILE_GEN tasks.

    Returns a Flask Response if a LangGraph workflow was matched, otherwise None.
    """
    from flask import Response

    if _workflow_route not in ("langgraph_research_doc", "langgraph_multi_agent_ppt"):
        return None

    _wf_name = (
        "research_and_document"
        if _workflow_route == "langgraph_research_doc"
        else "multi_agent_ppt"
    )
    _wf_label = (
        "📚 研究+文档"
        if _workflow_route == "langgraph_research_doc"
        else "🎞️ 多Agent PPT"
    )

    def generate_langgraph_workflow():
        yield f"data: {json.dumps({'type': 'classification', 'task_type': 'LG_WORKFLOW', 'workflow': _wf_name, 'route_method': 'LangGraph', 'message': f'🎯 任务分类: {_wf_label} (LangGraph WorkflowEngine)'})}\n\n"
        try:
            from app.core.workflow.langgraph_workflow import WorkflowEngine

            _engine = WorkflowEngine()
            final_output = ""
            for event in _engine.stream(
                workflow=_wf_name,
                user_input=user_input,
                session_id=session_name,
            ):
                node = event.get("node", "")
                content = event.get("content", "")
                done = event.get("done", False)
                if node == "error":
                    yield _safe_sse({"type": "error", "message": content})
                    return
                if content:
                    yield f"data: {json.dumps({'type': 'status' if not done else 'token', 'message': f'[{node}] {content}' if not done else None, 'content': content if done else None}, ensure_ascii=False)}\n\n"
                if done:
                    final_output = content
            yield f"data: {json.dumps({'type': 'done', 'images': [], 'saved_files': []})}\n\n"
            try:
                session_manager.append_and_save(
                    f"{session_name}.json",
                    user_input,
                    final_output or f"[{_wf_label}工作流完成]",
                )
            except Exception:
                import logging; logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)
        except Exception as _wf_ex:
            import traceback

            _app_logger.error(
                f"[LG_WORKFLOW] ❌ 工作流失败:\n{traceback.format_exc()}"
            )
            yield _safe_sse({
                "type": "error",
                "message": f"工作流执行失败: {str(_wf_ex)}",
            })

    return Response(generate_langgraph_workflow(), mimetype="text/event-stream")
