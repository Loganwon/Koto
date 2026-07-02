from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from app.core.agent.doc_websocket_loop_executor import DocWebSocketLoopExecutor
from app.core.agent.legacy_loop_executor import (
    LegacyEditorLoopExecutor,
)
from app.core.agent.lifecycle import AgentEvent, AgentRequest
from app.core.agent.session_queue import SessionQueue
from app.core.llm.model_mode import normalize_model_mode


def iter_editor_agent_events(request: AgentRequest) -> Iterator[AgentEvent]:
    """Run the legacy editor AgentLoop behind a replaceable boundary."""
    yield from LegacyEditorLoopExecutor().iter_events(request)


def build_doc_agent_request(sid: str, data: Mapping[str, Any]) -> AgentRequest:
    """Build the legacy doc WebSocket AgentRequest without exposing AgentLoop."""
    return AgentRequest(
        prompt=str(data.get("prompt") or ""),
        session_id=sid or "",
        file_type=str(data.get("file_type") or "unknown"),
        file_name=str(data.get("file_name") or ""),
        context=str(data.get("context") or ""),
        selection=str(data.get("selection") or ""),
        has_selection=bool(data.get("has_selection", False)),
        history=data.get("history") if isinstance(data.get("history"), list) else [],
        output_mode=str(data.get("output_mode") or "inline"),
        model_mode=normalize_model_mode(data.get("model_mode"), default="auto"),
        language=str(data.get("language") or ""),
        csv_data=str(data.get("csv_data") or ""),
        action_type=str(data.get("_action_type") or ""),
        action_system_prompt=str(data.get("_action_system_prompt") or ""),
        live_doc=bool(data.get("live_doc", False)),
        live_mode=str(data.get("live_mode") or "replace"),
    )


def iter_doc_agent_events(
    sid: str,
    data: Mapping[str, Any],
    session_queue: SessionQueue,
) -> Iterator[AgentEvent]:
    """Run the legacy doc AgentLoop with its current hook and queue contract."""
    request = build_doc_agent_request(sid, data)
    yield from DocWebSocketLoopExecutor().iter_events(request, session_queue)
