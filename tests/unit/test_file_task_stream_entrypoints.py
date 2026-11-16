# -*- coding: utf-8 -*-
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_file_task_stream_has_single_request_entrypoint():
    stream_source = (
        ROOT / "app" / "core" / "services" / "file_task_stream.py"
    ).read_text(encoding="utf-8")
    app_source = (ROOT / "web" / "app.py").read_text(encoding="utf-8")

    assert "def stream_file_task_request(" in stream_source
    assert "def stream_file_task_chat_request(" not in stream_source
    assert "stream_file_task_chat_request" not in app_source
    assert "stream_legacy_file_task" not in stream_source
    assert "stream_legacy_file_task" not in app_source
    assert not (ROOT / "web" / "file_task_stream.py").exists()


def test_file_task_stream_uses_core_workspace_owner_by_default(monkeypatch, tmp_path):
    from app.core.config import workspace_runtime
    from app.core.services.file_task_stream import _build_file_task_orchestrator

    monkeypatch.setattr(workspace_runtime, "get_workspace_root", lambda: str(tmp_path))

    runtime = _build_file_task_orchestrator(workspace_root=None)

    assert runtime._workspace_root == str(tmp_path)
    assert not hasattr(runtime, "_gemini_client")
