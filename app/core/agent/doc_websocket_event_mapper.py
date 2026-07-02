from __future__ import annotations

from app.core.agent.lifecycle import EventType
from app.core.security.output_validator import sanitize_user_visible_text


def _safe_user_error_text(text, fallback: str) -> str:
    return sanitize_user_visible_text(text, fallback=fallback, treat_as_error=True)


def _safe_user_preview_text(text, fallback: str) -> str:
    return sanitize_user_visible_text(text, fallback=fallback)


def emit_agent_event(socketio, sid, event, namespace: str = "/doc") -> None:
    """Map a single AgentEvent to one or more doc WebSocket emit calls."""
    etype = event.type
    data = event.data

    if etype == EventType.STREAM_CHUNK:
        chunk = data.get("chunk", "")
        socketio.emit("agent_stream_chunk", {"chunk": chunk}, namespace=namespace, to=sid)
        if data.get("live_doc"):
            socketio.emit(
                "doc_live_chunk",
                {
                    "chunk": chunk,
                    "mode": data.get("live_mode", "replace"),
                    "request_id": data.get("request_id", ""),
                },
                namespace=namespace,
                to=sid,
            )

    elif etype == EventType.LIVE_DOC_COMMIT:
        socketio.emit(
            "doc_live_commit",
            {
                "full_text": data.get("full_text", ""),
                "mode": data.get("live_mode", "replace"),
                "original_selection": data.get("original_selection", ""),
                "request_id": data.get("request_id", ""),
            },
            namespace=namespace,
            to=sid,
        )

    elif etype == EventType.TASK_COMPLETE:
        socketio.emit(
            "agent_task_complete",
            {
                "result": data.get("result", ""),
                "has_proposals": data.get("has_proposals", False),
                "error": data.get("error", ""),
            },
            namespace=namespace,
            to=sid,
        )

    elif etype == EventType.PHASE:
        socketio.emit(
            "agent_phase",
            {
                "phases": data.get("phases", []),
                "current": data.get("current", ""),
                "status": data.get("status", ""),
            },
            namespace=namespace,
            to=sid,
        )

    elif etype == EventType.THOUGHT:
        socketio.emit(
            "agent_event",
            {"type": "thought", "text": data.get("text", "")},
            namespace=namespace,
            to=sid,
        )

    elif etype == EventType.PLAN:
        socketio.emit(
            "agent_event",
            {"type": "plan", "steps": data.get("steps", [])},
            namespace=namespace,
            to=sid,
        )

    elif etype == EventType.STEP_START:
        socketio.emit(
            "agent_event",
            {
                "type": "step_start",
                "step_id": data.get("step_id", ""),
                "text": data.get("text", ""),
            },
            namespace=namespace,
            to=sid,
        )

    elif etype == EventType.STEP_PROGRESS:
        socketio.emit(
            "agent_event",
            {
                "type": "step_progress",
                "step_id": data.get("step_id", ""),
                "detail": data.get("detail", ""),
            },
            namespace=namespace,
            to=sid,
        )

    elif etype == EventType.STEP_DONE:
        socketio.emit(
            "agent_event",
            {
                "type": "step_done",
                "step_id": data.get("step_id", ""),
                "text": data.get("text", ""),
            },
            namespace=namespace,
            to=sid,
        )

    elif etype == EventType.STEP_ERROR:
        socketio.emit(
            "agent_event",
            {
                "type": "step_error",
                "step_id": data.get("step_id", ""),
                "error": _safe_user_error_text(
                    data.get("error", ""),
                    "处理失败，请稍后重试。",
                ),
            },
            namespace=namespace,
            to=sid,
        )

    elif etype == EventType.TOOL_CALL:
        tool_call = data.get("tool_call", {}) or {}
        socketio.emit(
            "agent_event",
            {
                "type": "tool_call",
                "tool_name": tool_call.get("name", ""),
                "tool_args": tool_call.get("args", {}),
            },
            namespace=namespace,
            to=sid,
        )

    elif etype == EventType.TOOL_RESULT:
        socketio.emit(
            "agent_event",
            {
                "type": "tool_result",
                "tool_name": data.get("tool_name", ""),
                "result_preview": _safe_user_preview_text(
                    data.get("result_preview", ""),
                    "工具已执行。",
                ),
            },
            namespace=namespace,
            to=sid,
        )

    elif etype == EventType.STATUS_MESSAGE:
        text = data.get("text", "")
        is_error = data.get("is_error", False)
        if is_error:
            socketio.emit(
                "agent_execute_command",
                {
                    "action": "show_message",
                    "text": _safe_user_error_text(text, "AI 调用失败，请稍后重试。"),
                    "is_error": True,
                },
                namespace=namespace,
                to=sid,
            )
        else:
            socketio.emit(
                "agent_progress",
                {
                    "step": "status",
                    "detail": _safe_user_preview_text(text, "处理中…"),
                },
                namespace=namespace,
                to=sid,
            )

    elif etype == EventType.PROPOSAL:
        socketio.emit(
            "agent_proposals",
            {
                "proposals": data.get("proposals", []),
                "summary": data.get("summary", ""),
            },
            namespace=namespace,
            to=sid,
        )

    elif etype == EventType.DOC_TOOL_CALL:
        socketio.emit("doc_tool_call", data, namespace=namespace, to=sid)

    elif etype == EventType.SKILL_SUGGESTIONS:
        socketio.emit(
            "skill_suggestions",
            {"suggestions": data.get("suggestions", [])},
            namespace=namespace,
            to=sid,
        )

    elif etype == EventType.RAG_INFO:
        socketio.emit("rag_info", data, namespace=namespace, to=sid)
        socketio.emit(
            "agent_event",
            {"type": "rag_info", **data},
            namespace=namespace,
            to=sid,
        )

    elif etype == EventType.CODE_RESULT:
        socketio.emit("code_result", data, namespace=namespace, to=sid)

    elif etype == EventType.ERROR:
        socketio.emit(
            "agent_task_complete",
            {"full_text": "", "error": data.get("text", "未知错误")},
            namespace=namespace,
            to=sid,
        )

    elif etype in (EventType.LIFECYCLE_START, EventType.LIFECYCLE_END):
        socketio.emit(
            "agent_lifecycle",
            {"type": etype.value, **data},
            namespace=namespace,
            to=sid,
        )
