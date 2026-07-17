"""Regression coverage for the shared settings-to-file-task model contract."""

from __future__ import annotations


def test_file_task_ignores_stale_browser_cloud_choice(monkeypatch):
    import app.core.llm.local_model_runtime as local_runtime
    import app.core.llm.model_selection as model_selection
    from web.file_task_stream import _normalize_file_task_payload

    monkeypatch.setattr(local_runtime, "get_configured_model_mode", lambda: "cloud")
    monkeypatch.setattr(
        model_selection,
        "get_configured_cloud_model",
        lambda **_kwargs: "deepseek-chat",
    )

    normalized = _normalize_file_task_payload(
        {
            "task": "总结附件",
            "model_mode": "local",
            "model_id": "stale-local-model",
            "options": {"local_model": "stale-local-model"},
        }
    )

    assert normalized["model_mode"] == "cloud"
    assert normalized["model_id"] == "deepseek-chat"
    assert "local_model" not in normalized["options"]


def test_file_task_uses_current_local_selection_not_saved_task_payload(monkeypatch):
    import app.core.llm.local_model_runtime as local_runtime
    import web.runtime_context as runtime_context
    from web.file_task_stream import _normalize_file_task_payload

    monkeypatch.setattr(local_runtime, "get_configured_model_mode", lambda: "local")
    monkeypatch.setattr(runtime_context, "get_configured_local_model_id", lambda: "qwen3.5:9b")

    normalized = _normalize_file_task_payload(
        {
            "task": "总结附件",
            "model_mode": "cloud",
            "model_id": "deepseek-chat",
            "options": {"local_model": "old-model:latest"},
        }
    )

    assert normalized["model_mode"] == "local"
    assert normalized["model_id"] == ""
    assert normalized["options"]["local_model"] == "qwen3.5:9b"
