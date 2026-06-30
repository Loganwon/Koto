# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch


def test_background_artifact_result_extracts_files_and_changes():
    from app.core.agent.background_agent import PlanStep, StepStatus
    from app.core.artifacts import build_background_artifact_result

    step = PlanStep(
        step_id="s1",
        title="生成报告",
        description="写入 workspace/reports/summary.docx",
        tool_hint="write_file",
        result="已保存到 workspace/reports/summary.docx",
        status=StepStatus.DONE,
    )

    result = build_background_artifact_result(
        task_id="task-1",
        goal="整理材料",
        phase="done",
        final_report="报告已完成：workspace/reports/summary.docx",
        steps=[step],
    )

    data = result.to_dict()
    assert data["status"] == "completed"
    assert data["artifacts"][0]["path"] == "workspace/reports/summary.docx"
    assert data["artifacts"][0]["type"] == "docx"
    assert data["changes"][0]["kind"] == "update"
    assert "open" in data["actions"]


def test_file_task_artifact_result_maps_changes_and_sources():
    from app.core.artifacts import build_file_task_artifact_result

    result = build_file_task_artifact_result(
        task_id="task-file-1",
        task="给合同添加审阅批注",
        run_id="run-1",
        status="completed",
        summary="已完成合同审阅。",
        file_changes=[
            {
                "path": "workspace/contracts/reviewed.docx",
                "operation": "annotate_file",
                "summary": "已添加 3 条审阅批注。",
                "annotations_added": 3,
                "source_path": "workspace/contracts/source.pdf",
            }
        ],
        source_files=[
            {
                "path": "workspace/contracts/source.pdf",
                "name": "source.pdf",
                "type": "pdf",
            }
        ],
    )

    data = result.to_dict()
    assert data["status"] == "completed"
    assert data["artifacts"][0]["path"] == "workspace/contracts/reviewed.docx"
    assert data["artifacts"][0]["source_path"] == "workspace/contracts/source.pdf"
    assert data["changes"][0]["kind"] == "comment"
    assert data["changes"][0]["status"] == "applied"
    assert data["sources"][0]["file"] == "workspace/contracts/source.pdf"


def test_file_task_stream_attaches_artifact_result_to_finished_event():
    from app.core.agent.file_task_contract import FileTaskEvent
    from web.file_task_stream import _iter_file_task_stream_events

    request_payload = SimpleNamespace(
        task="把总结写入当前文件",
        run_id="run-stream-1",
        task_id="task-stream-1",
        session_id="session-1",
        target_path="report.docx",
        files=[
            {
                "path": "report.docx",
                "name": "report.docx",
                "type": "docx",
                "target": True,
            }
        ],
        current_file=None,
        selection_source="",
    )
    changes = [
        {
            "path": "report.docx",
            "operation": "write_docx_content",
            "summary": "已写入报告摘要。",
            "paragraphs_written": 4,
        }
    ]
    events = [
        FileTaskEvent(
            type="file.changed",
            run_id="run-stream-1",
            seq=1,
            step_id="execute",
            payload=changes[0],
        ),
        FileTaskEvent(
            type="run.finished",
            run_id="run-stream-1",
            seq=2,
            payload={
                "summary": "已完成文件任务。",
                "completed_task": True,
                "file_changes": changes,
            },
        ),
    ]

    chunks = list(
        _iter_file_task_stream_events(
            request_payload,
            events,
            save_task_summary_fn=lambda **_: None,
            normalize_event_fn=lambda _: None,
            persist_progress_fn=lambda *_: None,
        )
    )
    parsed = [
        json.loads(chunk.strip()[6:])
        for chunk in chunks
        if chunk.strip().startswith("data: ")
    ]

    assert parsed[0]["type"] == "file.changed"
    assert parsed[0]["payload"]["artifact_result"]["status"] == "running"
    assert parsed[-1]["type"] == "run.finished"
    result = parsed[-1]["payload"]["artifact_result"]
    assert result["task_id"] == "task-stream-1"
    assert result["status"] == "completed"
    assert result["artifacts"][0]["path"] == "report.docx"
    assert result["changes"][0]["summary"] == "已写入报告摘要。"


def test_task_route_serializer_extracts_artifact_result_from_metadata():
    from app.api.task_routes import _serialize_task
    from app.core.tasks.task_ledger import TaskRecord, TaskStatus

    artifact_result = {
        "task_id": "task-route-1",
        "title": "文件任务结果",
        "status": "completed",
        "summary": "已完成。",
        "artifacts": [],
        "changes": [],
        "sources": [],
        "logs": [],
        "actions": [],
    }
    task = TaskRecord(
        task_id="task-route-1",
        session_id="session-1",
        user_input="处理文件",
        status=TaskStatus.COMPLETED,
        metadata=json.dumps(
            {
                "terminal_event": {
                    "type": "run.finished",
                    "payload": {"artifact_result": artifact_result},
                }
            },
            ensure_ascii=False,
        ),
    )

    data = _serialize_task(task)
    assert data["artifact_result"]["task_id"] == "task-route-1"
    assert data["artifact_result"]["status"] == "completed"


def test_background_agent_status_always_has_artifact_result():
    from app.core.agent.background_agent import BackgroundAgent

    agent = BackgroundAgent(session_id="artifact-test")
    with patch.object(agent, "_run_task", return_value=None):
        task_id = agent.submit("处理 workspace/input.pdf 并输出摘要")

    status = agent.get_status(task_id)
    assert status.artifact_result is not None
    data = status.artifact_result.to_dict()
    assert data["task_id"] == task_id
    assert data["status"] == "running"


def test_bg_agent_status_serializer_includes_artifact_result():
    from app.api.bg_agent_routes import _serialize_status
    from app.core.agent.background_agent import BackgroundAgent

    agent = BackgroundAgent(session_id="serializer-test")
    with patch.object(agent, "_run_task", return_value=None):
        task_id = agent.submit("生成 workspace/output.md")

    serialized = _serialize_status(agent.get_status(task_id))
    assert serialized["artifact_result"]["task_id"] == task_id
    assert (
        serialized["artifact_result"]["artifacts"][0]["path"] == "workspace/output.md"
    )


def test_approve_plan_updates_artifact_result_status():
    from app.core.agent.background_agent import BackgroundAgent, ExecutionPlan, PlanStep

    agent = BackgroundAgent(session_id="approve-artifact-test")
    with patch.object(agent, "_run_task", return_value=None):
        task_id = agent.submit("处理文档", human_review_before_execute=True)

    status = agent.get_status(task_id)
    status.plan = ExecutionPlan(
        plan_id="plan-1",
        goal="处理文档",
        steps=[PlanStep(step_id="s1", title="读取", description="读取文档")],
    )
    agent.approve_plan(task_id)

    data = agent.get_status(task_id).artifact_result.to_dict()
    assert data["status"] == "running"
    assert data["metadata"]["phase"] == "executing"
