from pathlib import Path


def test_koto_agent_loop_retires_legacy_ai_task_mode():
    source = Path("app/core/agent/agent_loop.py").read_text(encoding="utf-8")

    assert "_run_task_mode" not in source
    assert "_build_task_registry" not in source
    assert "_call_task_llm" not in source
    assert 'action_type == "ai_task"' not in source
    assert "旧版 ai_task" not in source