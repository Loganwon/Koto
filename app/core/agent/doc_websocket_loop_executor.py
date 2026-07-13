from __future__ import annotations

from collections.abc import Iterator

from app.core.agent.doc_websocket_agent_executor import DocWebSocketAgentExecutor
from app.core.agent.lifecycle import AgentEvent, AgentRequest
from app.core.agent.session_queue import SessionQueue


class DocWebSocketLoopExecutor:
    """Doc WebSocket executor with the existing session queue contract."""

    def iter_events(
        self,
        request: AgentRequest,
        session_queue: SessionQueue,
    ) -> Iterator[AgentEvent]:
        with session_queue.acquire(request.session_id):
            yield from DocWebSocketAgentExecutor().iter_events(request)
