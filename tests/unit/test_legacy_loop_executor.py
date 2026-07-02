from __future__ import annotations

from app.core.agent.lifecycle import AgentRequest, evt_task_complete


def test_legacy_editor_executor_delegates_text_requests_to_editor_executor(monkeypatch):
    from app.core.agent import legacy_loop_executor as executor

    captured = {}

    class FakeEditorExecutor:
        def iter_events(self, request):
            captured["request"] = request
            yield evt_task_complete(result=request.prompt)

    monkeypatch.setattr(executor, "EditorQuickActionExecutor", FakeEditorExecutor)

    request = AgentRequest(prompt="rewrite")
    events = list(executor.LegacyEditorLoopExecutor().iter_events(request))

    assert captured["request"] is request
    assert events[0].data["result"] == "rewrite"


def test_legacy_editor_executor_delegates_code_mode_to_code_executor(monkeypatch):
    from app.core.agent import legacy_loop_executor as executor

    captured = {}

    class FakeCodeExecutor:
        @staticmethod
        def supports(request):
            captured["supports_request"] = request
            return True

        def iter_events(self, request):
            captured["request"] = request
            yield evt_task_complete(result=f"code:{request.language}")

    monkeypatch.setattr(executor, "EditorCodeActionExecutor", FakeCodeExecutor)

    request = AgentRequest(prompt="chart", language="python")
    events = list(executor.LegacyEditorLoopExecutor().iter_events(request))

    assert captured["supports_request"] is request
    assert captured["request"] is request
    assert events[0].data["result"] == "code:python"
