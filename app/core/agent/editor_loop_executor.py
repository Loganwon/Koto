from __future__ import annotations

from collections.abc import Iterator

from app.core.agent.editor_code_action_executor import EditorCodeActionExecutor
from app.core.agent.editor_quick_action_executor import EditorQuickActionExecutor
from app.core.agent.lifecycle import AgentEvent, AgentRequest


class EditorLoopExecutor:
    """Editor SSE executor behind the compatibility facade."""

    def iter_events(self, request: AgentRequest) -> Iterator[AgentEvent]:
        if EditorCodeActionExecutor.supports(request):
            yield from EditorCodeActionExecutor().iter_events(request)
            return
        yield from EditorQuickActionExecutor().iter_events(request)
