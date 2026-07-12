from __future__ import annotations

import json
from types import SimpleNamespace


def _event(event_type: str, payload: dict):
    from app.core.agent.file_task_contract import FileTaskEvent

    return FileTaskEvent(
        type=event_type,
        run_id="compact-run",
        seq=1,
        step_id="plan",
        payload=payload,
    )


def test_file_task_stream_compacts_repeated_internal_workflow_state():
    from web.file_task_stream import _iter_file_task_stream_events

    request = SimpleNamespace(
        task="分析工作簿",
        run_id="compact-run",
        task_id="compact-task",
        session_id="session-1",
        target_path="",
        files=[],
        current_file=None,
        selection_source="",
    )
    event = _event(
        "supervisor.status",
        {
            "stage": "planned",
            "summary": "正在读取文件。",
            "mainline_locked": True,
            "completion": {"required_completed": 0, "required_total": 3},
            "supervisor_audit": {"status": "clear"},
            "workflow_state": {"large": ["internal-only"] * 100},
            "task_plan": {"steps": [{"id": "read_context"}]},
        },
    )

    chunks = list(
        _iter_file_task_stream_events(
            request,
            [event],
            save_task_summary_fn=lambda **_: None,
            normalize_event_fn=lambda _: None,
            persist_progress_fn=lambda *_: None,
        )
    )
    parsed = [json.loads(chunk.strip()[6:]) for chunk in chunks if chunk.strip().startswith("data: ")]

    payload = parsed[0]["payload"]
    assert payload["stream_payload_version"] == "compact_v1"
    assert payload["completion"]["required_total"] == 3
    assert payload["supervisor_audit"]["status"] == "clear"
    assert "workflow_state" not in payload
    assert "task_plan" not in payload


def test_file_task_stream_emits_frontend_progress_events_for_known_stages():
    from web.file_task_stream import _iter_file_task_stream_events

    request = SimpleNamespace(
        task="分析工作簿",
        run_id="progress-run",
        task_id="progress-task",
        session_id="session-1",
        target_path="",
        files=[],
        current_file=None,
        selection_source="",
    )
    event = _event("plan.checked", {"passed": True, "summary": "规划检查通过。"})

    chunks = list(
        _iter_file_task_stream_events(
            request,
            [event],
            save_task_summary_fn=lambda **_: None,
            normalize_event_fn=lambda _: None,
            persist_progress_fn=lambda *_: None,
        )
    )
    parsed = [json.loads(chunk.strip()[6:]) for chunk in chunks if chunk.strip().startswith("data: ")]

    assert parsed[0]["type"] == "plan.checked"
    assert parsed[0]["ui_state"]["progress"] == 20
    progress = next(item for item in parsed if item["type"] == "progress")
    assert progress["payload"]["progress"] == 20
    assert progress["payload"]["label"] == "规划检查"
    assert progress["payload"]["source_event"] == "plan.checked"
