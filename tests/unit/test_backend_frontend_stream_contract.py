# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from flask import Flask


def _parse_compact_sse(frame: str) -> dict:
    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")
    return json.loads(frame[len("data: ") :].strip())


@pytest.mark.unit
def test_file_task_sse_uses_unified_compact_protocol():
    from web.file_task_stream import safe_editor_sse
    from web.sse.protocol import sse

    payload = {"type": "info", "text": "hello"}
    frame = safe_editor_sse(payload)

    assert frame == sse.chunk(payload)
    assert _parse_compact_sse(frame) == payload


@pytest.mark.unit
def test_task_stream_route_declares_non_buffered_sse(monkeypatch):
    import web.blueprints.editor_ai as editor_ai

    def fake_stream_file_task_request(data: dict):
        assert data["task"] == "整理文件"
        yield "data: {\"type\":\"run.started\"}\n\n"

    monkeypatch.setattr(
        editor_ai,
        "stream_file_task_request",
        fake_stream_file_task_request,
    )

    app = Flask(__name__)
    app.register_blueprint(editor_ai.editor_ai_bp)

    with app.test_client() as client:
        response = client.post("/api/editor/ai/task-stream", json={"task": "整理文件"})

    assert response.status_code == 200
    assert "text/event-stream" in response.content_type
    assert response.headers["Cache-Control"] == "no-cache"
    assert response.headers["X-Accel-Buffering"] == "no"
    assert _parse_compact_sse(response.get_data(as_text=True)) == {"type": "run.started"}


@pytest.mark.unit
def test_task_stream_route_rejects_missing_task():
    import web.blueprints.editor_ai as editor_ai

    app = Flask(__name__)
    app.register_blueprint(editor_ai.editor_ai_bp)

    with app.test_client() as client:
        response = client.post("/api/editor/ai/task-stream", json={"selection": "hello"})

    assert response.status_code == 400
    assert response.get_json()["error"] == "Missing 'task' parameter"


@pytest.mark.unit
def test_editor_stream_validation_errors_use_same_sse_headers():
    import web.blueprints.editor_ai as editor_ai

    app = Flask(__name__)
    app.register_blueprint(editor_ai.editor_ai_bp)

    with app.test_client() as client:
        response = client.post("/api/editor/ai/stream", json={"action": "polish"})

    assert response.status_code == 200
    assert "text/event-stream" in response.content_type
    assert response.headers["Cache-Control"] == "no-cache"
    assert response.headers["X-Accel-Buffering"] == "no"
    assert _parse_compact_sse(response.get_data(as_text=True))["type"] == "error"


@pytest.mark.unit
def test_chart_validation_errors_use_same_sse_headers():
    import web.blueprints.editor_ai as editor_ai

    app = Flask(__name__)
    app.register_blueprint(editor_ai.editor_ai_bp)

    with app.test_client() as client:
        response = client.post("/api/editor/ai/chart", json={"instruction": "生成图表"})

    assert response.status_code == 200
    assert "text/event-stream" in response.content_type
    assert response.headers["Cache-Control"] == "no-cache"
    assert response.headers["X-Accel-Buffering"] == "no"
    assert _parse_compact_sse(response.get_data(as_text=True))["type"] == "error"


@pytest.mark.unit
def test_frontend_task_runner_matches_backend_stream_contract():
    runner = Path("web/src/workspace/task-runner.ts").read_text(encoding="utf-8")
    bundle = Path("web/static/js/build/workspace-bundle.js").read_text(encoding="utf-8")

    assert "function parseSseEvents" in runner
    assert "WA.parseSseEvents = parseSseEvents" in runner
    assert "csrfFetch('/api/editor/ai/task-stream'" in runner
    assert "'Accept': 'text/event-stream'" in runner
    assert 'csrfFetch("/api/editor/ai/task-stream"' in bundle
    assert '"Accept": "text/event-stream"' in bundle
    assert re.search(r"WA(?:\$\d+)?\.parseSseEvents = parseSseEvents", bundle)


@pytest.mark.unit
def test_workspace_chat_stream_detaches_skills_by_request_contract():
    dispatcher = Path("web/src/workspace/task-dispatcher.ts").read_text(encoding="utf-8")
    bundle = Path("web/static/js/build/workspace-bundle.js").read_text(encoding="utf-8")
    orchestrator = Path("web/services/chat_stream/orchestrator.py").read_text(encoding="utf-8")

    assert "skills_enabled: false" in dispatcher
    assert "skills_enabled: false" in bundle
    assert "def _request_allows_skill_injection(data):" in orchestrator
    assert "system_instruction = _inject_skills_for_stream(" in orchestrator
    assert "SkillManager.inject_into_prompt(" in orchestrator
    assert "app_logger.debug(\"[STREAM] Skills injection disabled by request\")" in orchestrator


@pytest.mark.unit
def test_chat_stream_skill_injection_request_switch():
    from web.services.chat_stream.orchestrator import (
        _inject_skills_for_stream,
        _request_allows_skill_injection,
    )

    class _Logger:
        def __init__(self):
            self.messages: list[str] = []

        def debug(self, message, *args):
            self.messages.append(str(message))

        def warning(self, message, *args):
            raise AssertionError(f"unexpected warning: {message}")

    assert _request_allows_skill_injection({}) is True
    assert _request_allows_skill_injection({"skills_enabled": True}) is True
    assert _request_allows_skill_injection({"skills_enabled": "yes"}) is True
    assert _request_allows_skill_injection({"skills_enabled": False}) is False
    assert _request_allows_skill_injection({"skills_enabled": "false"}) is False
    assert _request_allows_skill_injection({"enable_skills": "off"}) is False
    assert _request_allows_skill_injection({"skill_mode": "detached"}) is False

    logger = _Logger()
    system = _inject_skills_for_stream(
        "base system",
        "CHAT",
        "hello",
        {"skills_enabled": False},
        logger,
    )

    assert system == "base system"
    assert "[STREAM] Skills injection disabled by request" in logger.messages
