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
def test_runtime_context_model_mode_uses_canonical_default_contract():
    from app.core.llm.model_mode import normalize_model_mode

    assert normalize_model_mode("local", default="deepseek") == "local"
    assert normalize_model_mode("auto", default="deepseek") == "deepseek"
    assert normalize_model_mode("gemini", default="deepseek") == "deepseek"


@pytest.mark.unit
def test_file_task_sse_uses_unified_compact_protocol():
    from app.core.services.file_task_event_safety import safe_editor_sse
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
        yield 'data: {"type":"run.started"}\n\n'

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
    assert _parse_compact_sse(response.get_data(as_text=True)) == {
        "type": "run.started"
    }


@pytest.mark.unit
def test_task_stream_route_rejects_missing_task():
    import web.blueprints.editor_ai as editor_ai

    app = Flask(__name__)
    app.register_blueprint(editor_ai.editor_ai_bp)

    with app.test_client() as client:
        response = client.post(
            "/api/editor/ai/task-stream", json={"selection": "hello"}
        )

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
def test_task_stream_quick_action_keeps_persisted_file_task_contract(monkeypatch):
    import web.blueprints.editor_ai as editor_ai

    received = {}

    def fake_file_task_stream(data: dict):
        received.update(data)
        yield 'data: {"type":"run.finished","payload":{"completed_task":true}}\n\n'

    monkeypatch.setattr(editor_ai, "stream_file_task_request", fake_file_task_stream)
    app = Flask(__name__)
    app.register_blueprint(editor_ai.editor_ai_bp)

    with app.test_client() as client:
        response = client.post(
            "/api/editor/ai/task-stream",
            json={
                "task": "润色所选文字",
                "selection": "  保留这段文字  ",
                "options": {"quick_action_mode": "simple"},
            },
        )

    assert response.status_code == 200
    assert received["task"] == "润色所选文字"
    assert received["selection"] == "  保留这段文字  "
    assert received["options"]["quick_action_mode"] == "simple"
    assert _parse_compact_sse(response.get_data(as_text=True))["type"] == "run.finished"


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
    transport = Path("web/src/workspace/task-stream-transport.ts").read_text(
        encoding="utf-8"
    )
    parser = Path("web/src/workspace/file-task-sse.ts").read_text(encoding="utf-8")
    dispatcher = Path("web/src/workspace/file-task-dispatch.ts").read_text(
        encoding="utf-8"
    )
    ui_state = Path("web/src/workspace/task-ui-state.ts").read_text(encoding="utf-8")
    presentation = Path("web/src/workspace/task-stage-presentation.ts").read_text(
        encoding="utf-8"
    )
    bundle = Path("web/static/js/build/workspace-bundle.js").read_text(encoding="utf-8")

    assert "from './task-stream-transport';" in runner
    assert "from './file-task-sse';" in transport
    assert "from './file-task-dispatch';" in runner
    assert "export function parseSseEvents" in parser
    assert "export interface SseParseResult" in parser
    assert "export function persistedTaskStreamEvent" in parser
    assert "export function isTaskStreamTerminalEvent" in parser
    assert "export function dispatchFileTaskEvent" in dispatcher
    assert "export function createFileTaskEventController" in dispatcher
    assert "event.event_seq || payload.seq || payload.event_seq" in dispatcher
    assert "state.processedEventKeys.has(eventKey)" in dispatcher
    assert (
        "noteStreamIssue?: (_card: Card, _key: string, _text: string) => void;"
        in dispatcher
    )
    assert (
        "afterDispatch?: (_card: Card, _event: Record<string, any>) => void;"
        in dispatcher
    )
    assert "createFileTaskEventController<TaskCardElement, FileTaskUiState>({" in runner
    assert "afterDispatch: scheduleCanonicalTaskStageState" in runner
    assert "const pendingStageEvents = new Map" in presentation
    assert "requestAnimationFrame(callback)" in presentation
    assert "function shouldDispatchStreamEvent(" not in runner
    assert "afterDispatch: notifyTaskWorkbenchForCard" not in runner
    assert "claimLiveTaskPresentation," in runner
    assert "function claimLiveTaskPresentation(card: TCard): void" in presentation
    assert "dataset.taskStreamIssueCount" in ui_state
    assert "noteStreamIssue: noteTaskStreamIssue" in runner
    assert "检测到任务进度事件缺失" not in runner
    assert "检测到任务进度事件顺序异常" not in runner
    assert "检测到重复进度事件" not in runner
    assert "registerFeatures({" in runner
    published = runner.split("registerFeatures({", 1)[1].split("});", 1)[0]
    assert "parseSseEvents" not in published
    assert "runtime.csrfFetch('/api/editor/ai/task-stream'" in transport
    assert "async function csrfFetch(" not in runner
    assert "'Accept': 'text/event-stream'" in transport
    # Production bundles are minified, so local identifier names and quote
    # styles are not stable. Keep only externally observable literals here.
    assert "/api/editor/ai/task-stream" in bundle
    assert "text/event-stream" in bundle
