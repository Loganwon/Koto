from __future__ import annotations


class _FakeLocalExecutor:
    @staticmethod
    def is_system_command(text: str) -> bool:
        return text == "打开微信"


def test_workspace_route_intent_maps_system_actions_to_direct_response(monkeypatch):
    from web.blueprints import editor_ai

    monkeypatch.setattr(editor_ai, "get_local_executor", lambda: _FakeLocalExecutor)

    decision = editor_ai._deterministic_workspace_route({"text": "打开微信"})

    assert decision is not None
    assert decision["route_kind"] == "direct_response"
    assert decision["route"] == "system_action"
    assert decision["task_type"] == "SYSTEM"
    assert decision["route_source"] == "deterministic:system"


def test_workspace_route_intent_trusts_explicit_file_context_without_adjudication():
    from web.blueprints import editor_ai

    decision = editor_ai._deterministic_workspace_route(
        {
            "text": "总结这个文件",
            "files": [{"path": "workspace/report.docx", "type": "docx"}],
        }
    )

    assert decision is not None
    assert decision["route_kind"] == "complex_task"
    assert decision["route"] == "file_task"
    assert decision["task_type"] == "FILE_TASK"
    assert decision["route_source"] == "deterministic:file_context"
    assert decision["skip_ai_intent_adjudicator"] is True


def test_workspace_route_intent_normalizes_system_task_type():
    from web.blueprints import editor_ai

    decision = editor_ai._normalize_workspace_route(
        {
            "route_kind": "complex_task",
            "route": "file_task",
            "task_type": "SYSTEM",
            "confidence": 0.8,
        },
        source="test",
    )

    assert decision is not None
    assert decision["route_kind"] == "direct_response"
    assert decision["route"] == "system_action"
    assert decision["task_type"] == "SYSTEM"
