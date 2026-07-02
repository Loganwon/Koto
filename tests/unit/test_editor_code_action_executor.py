from __future__ import annotations

from app.core.agent.editor_code_action_executor import EditorCodeActionExecutor
from app.core.agent.lifecycle import AgentRequest


def _events_for(request: AgentRequest):
    return list(EditorCodeActionExecutor().iter_events(request))


def test_editor_code_action_executor_generates_and_runs_python(monkeypatch):
    from app.core.agent import llm_provider_helpers
    from app.core import sandbox

    captured = {}

    def fake_call_llm_sync(prompt, use_local_only=False):
        captured["prompt"] = prompt
        captured["use_local_only"] = use_local_only
        return "```python\nprint('chart')\n```"

    def fake_run_python(code):
        captured["code"] = code
        return {"stdout": "chart", "stderr": "", "files": {"chart.png": "ZmFrZQ=="}, "error": ""}

    monkeypatch.setattr(llm_provider_helpers, "call_llm_sync", fake_call_llm_sync)
    monkeypatch.setattr(sandbox, "run_python", fake_run_python)

    events = _events_for(
        AgentRequest(
            prompt="生成图表",
            language="python",
            csv_data="类别,值\nA,10",
            model_mode="cloud",
        )
    )

    assert captured["use_local_only"] is False
    assert "表格数据（CSV 格式）" in captured["prompt"]
    assert captured["code"] == "print('chart')"
    code_results = [event for event in events if event.type.value == "code_result"]
    assert code_results[-1].data["files"] == {"chart.png": "ZmFrZQ=="}
    assert events[-1].type.value == "lifecycle_end"


def test_editor_code_action_executor_honors_local_only_generation(monkeypatch):
    from app.core.agent import llm_provider_helpers
    from app.core import sandbox

    captured = {}

    def fake_call_llm_sync(prompt, use_local_only=False):
        captured["use_local_only"] = use_local_only
        return "print('local')"

    monkeypatch.setattr(llm_provider_helpers, "call_llm_sync", fake_call_llm_sync)
    monkeypatch.setattr(
        sandbox,
        "run_python",
        lambda code: {"stdout": "local", "stderr": "", "files": {}, "error": ""},
    )

    events = _events_for(AgentRequest(prompt="生成图表", language="python", model_mode="local"))

    assert captured["use_local_only"] is True
    assert [event for event in events if event.type.value == "code_result"]


def test_editor_code_action_executor_returns_code_result_on_generation_failure(monkeypatch):
    from app.core.agent import llm_provider_helpers

    monkeypatch.setattr(llm_provider_helpers, "call_llm_sync", lambda *args, **kwargs: "")

    events = _events_for(AgentRequest(prompt="生成图表", language="python"))

    code_result = [event for event in events if event.type.value == "code_result"][-1]
    assert "AI 代码生成失败" in code_result.data["error"]
    assert events[-1].type.value == "lifecycle_end"


def test_editor_code_action_executor_supports_only_code_languages() -> None:
    assert EditorCodeActionExecutor.supports(AgentRequest(prompt="x", language="python")) is True
    assert EditorCodeActionExecutor.supports(AgentRequest(prompt="x", language="r")) is True
    assert EditorCodeActionExecutor.supports(AgentRequest(prompt="x")) is False
