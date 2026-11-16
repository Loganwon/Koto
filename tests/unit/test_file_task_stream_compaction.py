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
    from app.core.services.file_task_stream import _iter_file_task_stream_events

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
    parsed = [
        json.loads(chunk.strip()[6:])
        for chunk in chunks
        if chunk.strip().startswith("data: ")
    ]

    payload = parsed[0]["payload"]
    assert payload["stream_payload_version"] == "compact_v1"
    assert payload["completion"]["required_total"] == 3
    assert payload["supervisor_audit"]["status"] == "clear"
    assert "workflow_state" not in payload
    assert "task_plan" not in payload


def test_file_task_record_metadata_counts_the_current_file() -> None:
    from app.core.agent.file_task_contract import FileTaskFile
    from app.core.services.file_task_stream import _file_task_record_metadata

    current = FileTaskFile(
        path="financial_model.xlsx",
        name="financial_model.xlsx",
        type="xlsx",
    )
    request = SimpleNamespace(
        run_id="metadata-run",
        target_path="",
        model_mode="deepseek",
        model_id="",
        selection_source="",
        selection="",
        files=[],
        current_file=current,
        task_context=None,
    )

    metadata = _file_task_record_metadata(request)

    assert metadata["file_count"] == 1
    assert metadata["files"] == [current.public_dict()]
    assert metadata["current_file"] == current.public_dict()


def test_only_tool_started_is_counted_as_a_tool_action() -> None:
    from app.core.services.file_task_stream import _file_task_step_type

    assert _file_task_step_type("tool.started") == "ACTION"
    assert _file_task_step_type("tool.finished") == "OBSERVATION"
    assert _file_task_step_type("supervisor.step_verified") == "OBSERVATION"


def test_progress_persistence_counts_one_real_tool_call(tmp_path, monkeypatch) -> None:
    import importlib

    from app.core.services.file_task_stream import _persist_file_task_progress_event
    from app.core.tasks.task_ledger import TaskLedger

    ledger = TaskLedger(db_path=str(tmp_path / "tasks.db"))
    ledger.create(
        session_id="telemetry-session",
        user_input="分析工作簿",
        task_id="telemetry-task",
    )
    try:
        task_ledger_module = importlib.import_module("app.core.tasks.task_ledger")
        progress_bus_module = importlib.import_module("app.core.tasks.progress_bus")
        monkeypatch.setattr(task_ledger_module, "get_ledger", lambda: ledger)
        monkeypatch.setattr(
            progress_bus_module,
            "get_progress_bus",
            lambda: SimpleNamespace(publish=lambda _event: None),
        )
        request = SimpleNamespace(
            task_id="telemetry-task",
            run_id="compact-run",
            session_id="telemetry-session",
        )

        _persist_file_task_progress_event(
            request,
            _event(
                "tool.finished",
                {
                    "tool_name": "kernel_evidence_guard",
                    "success": False,
                },
            ),
        )
        _persist_file_task_progress_event(
            request,
            _event("tool.started", {"tool_name": "read_sheet_data"}),
        )
        _persist_file_task_progress_event(
            request,
            _event(
                "tool.finished",
                {"tool_name": "read_sheet_data", "success": True},
            ),
        )

        record = ledger.get("telemetry-task", include_steps=True)
        assert record is not None
        assert record.tool_calls == 1
        assert [step.step_type for step in record.steps] == [
            "OBSERVATION",
            "ACTION",
            "OBSERVATION",
        ]
    finally:
        ledger._conn.close()


def test_file_task_stream_embeds_canonical_ui_state_without_progress_duplicate():
    from app.core.services.file_task_stream import _iter_file_task_stream_events

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
    parsed = [
        json.loads(chunk.strip()[6:])
        for chunk in chunks
        if chunk.strip().startswith("data: ")
    ]

    assert [item["type"] for item in parsed] == ["plan.checked"]
    assert parsed[0]["ui_state"] == {
        "schema": "koto.file_task_ui_state.v1",
        "phase": "plan",
        "title": "执行边界检查通过",
        "status": "running",
        "progress": 24,
        "terminal": False,
        "progress_explicit": False,
        "detail_mode": "fallback",
        "allow_regression": False,
    }


def test_file_task_ui_state_uses_five_user_facing_stages():
    from app.core.agent.file_task_ui_stream import normalize_ui_state

    cases = [
        ("run.started", {}, "route", "正在建立任务上下文", 5),
        ("task.classified", {}, "route", "已识别任务目标", 16),
        ("plan.created", {}, "plan", "已生成执行方案", 32),
        (
            "tool.started",
            {"tool_name": "write_docx_content"},
            "execute",
            "正在写入任务结果",
            58,
        ),
        ("check.started", {}, "check", "正在核验结果与文件变更", 86),
        (
            "run.finished",
            {"completed_task": True, "runtime": {"terminal_status": "verified"}},
            "deliver",
            "结果与产物已整理完成",
            100,
        ),
    ]

    states = [
        normalize_ui_state(_event(event_type, payload))
        for event_type, payload, *_ in cases
    ]
    assert all(state is not None for state in states)
    for state, (_, _, phase, title, progress) in zip(states, cases):
        assert state.phase == phase
        assert state.title == title
        assert state.progress == progress
    assert [state.progress for state in states] == sorted(
        state.progress for state in states
    )


def test_file_task_ui_state_marks_completed_step_result_as_succeeded():
    from app.core.agent.file_task_ui_stream import normalize_ui_state

    state = normalize_ui_state(
        _event(
            "step.result",
            {"title": "正在处理", "status": "completed", "success": True},
        )
    )

    assert state is not None
    assert state.phase == "execute"
    assert state.status == "succeeded"


def test_file_task_ui_state_keeps_plan_summary_visible():
    from app.core.agent.file_task_ui_stream import normalize_ui_state

    state = normalize_ui_state(
        {
            "type": "plan.created",
            "payload": {"summary": "先读取文件，再整理关键结论。"},
        }
    )

    assert state is not None
    assert state.phase == "plan"
    assert state.title == "先读取文件，再整理关键结论。"


def test_file_task_ui_state_owns_readable_file_activity_titles():
    from app.core.agent.file_task_ui_stream import normalize_ui_state

    read_state = normalize_ui_state(
        {
            "type": "read.changed",
            "payload": {"file_path": r"C:\workspace\季度报告.docx"},
        }
    )
    write_state = normalize_ui_state(
        {
            "type": "file.changed",
            "payload": {
                "path": "/workspace/汇总结果.xlsx",
                "change_type": "created",
            },
        }
    )

    assert read_state is not None
    assert read_state.title == "正在读取 季度报告.docx"
    assert write_state is not None
    assert write_state.title == "已创建 汇总结果.xlsx"


def test_file_task_ui_state_serializes_repair_transition_contract():
    from app.core.agent.file_task_ui_stream import normalize_ui_state

    state = normalize_ui_state(
        {"type": "supervisor.status", "payload": {"stage": "repairing"}}
    )

    assert state is not None
    assert state.to_payload()["schema"] == "koto.file_task_ui_state.v1"
    assert state.to_payload()["allow_regression"] is True
    assert state.to_payload()["detail_mode"] == "replace"


def test_file_task_ui_state_marks_confirmation_tools_as_waiting():
    from app.core.agent.file_task_ui_stream import normalize_ui_state

    state = normalize_ui_state(
        {
            "type": "tool.finished",
            "payload": {
                "tool_name": "ask_user",
                "blocked": True,
                "success": False,
            },
        }
    )

    assert state is not None
    assert state.phase == "execute"
    assert state.status == "waiting"
    assert state.title == "等待你确认后继续"


def test_file_task_ui_state_returns_from_check_to_visible_repair():
    from app.core.agent.file_task_ui_stream import normalize_ui_state

    state = normalize_ui_state(
        {
            "type": "supervisor.status",
            "payload": {"stage": "repairing"},
        }
    )

    assert state is not None
    assert state.phase == "execute"
    assert state.status == "warning"
    assert state.progress == 90
    assert state.title == "核验发现问题，正在修复结果"


def test_file_task_terminal_progress_uses_quality_gate_failure_ui_state():
    from app.core.services.file_task_stream import _iter_file_task_stream_events

    request = SimpleNamespace(
        task="读取不存在的文件",
        run_id="terminal-progress-run",
        task_id="terminal-progress-task",
        session_id="session-1",
        target_path="",
        files=[],
        current_file=None,
        selection_source="",
    )
    event = _event(
        "run.finished",
        {
            "completed_task": False,
            "runtime": {"terminal_status": "quality_gate_failed"},
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
    parsed = [
        json.loads(chunk.strip()[6:])
        for chunk in chunks
        if chunk.strip().startswith("data: ")
    ]

    assert [item["type"] for item in parsed] == ["run.finished"]
    assert parsed[0]["ui_state"]["phase"] == "deliver"
    assert parsed[0]["ui_state"]["title"] == "任务未完成，已保留诊断信息"
    assert parsed[0]["ui_state"]["status"] == "failed"


def test_file_task_stream_stops_after_first_terminal_event():
    from app.core.services.file_task_stream import _iter_file_task_stream_events

    request = SimpleNamespace(
        task="生成报告",
        run_id="terminal-once-run",
        task_id="terminal-once-task",
        session_id="session-1",
        target_path="report.docx",
        files=[],
        current_file=None,
        selection_source="",
    )
    source_state = {"late_event_requested": False}
    summaries = []

    def events():
        yield _event(
            "run.finished",
            {
                "completed_task": True,
                "summary": "报告已生成。",
                "target_path": "report.docx",
                "runtime": {"terminal_status": "verified"},
            },
        )
        source_state["late_event_requested"] = True
        yield _event("file.changed", {"path": "late.docx"})
        yield _event(
            "run.finished",
            {"completed_task": False, "summary": "重复终态不应到达。"},
        )

    chunks = list(
        _iter_file_task_stream_events(
            request,
            events(),
            save_task_summary_fn=lambda **payload: summaries.append(payload),
            normalize_event_fn=lambda _: None,
            persist_progress_fn=lambda *_: None,
        )
    )
    parsed = [
        json.loads(chunk.strip()[6:])
        for chunk in chunks
        if chunk.strip().startswith("data: ")
    ]

    assert [item["type"] for item in parsed].count("run.finished") == 1
    assert parsed[-1]["type"] == "run.finished"
    assert source_state["late_event_requested"] is False
    assert len(summaries) == 1


def test_file_task_stream_converts_producer_exception_into_one_terminal_failure():
    from app.core.services.file_task_stream import _iter_file_task_stream_events

    request = SimpleNamespace(
        task="生成复杂报告",
        run_id="producer-failure-run",
        task_id="producer-failure-task",
        session_id="session-1",
        target_path="report.docx",
        files=[],
        current_file=None,
        selection_source="",
    )
    persisted = []

    def events():
        yield _event("run.started", {"task": request.task})
        raise RuntimeError("producer exploded")

    chunks = list(
        _iter_file_task_stream_events(
            request,
            events(),
            save_task_summary_fn=lambda **_: None,
            normalize_event_fn=lambda _: None,
            persist_progress_fn=lambda _, event: persisted.append(event),
        )
    )
    parsed = [
        json.loads(chunk.strip()[6:])
        for chunk in chunks
        if chunk.strip().startswith("data: ")
    ]
    terminals = [item for item in parsed if item["type"] == "run.finished"]

    assert len(terminals) == 1
    assert terminals[0]["payload"]["completed_task"] is False
    assert terminals[0]["payload"]["failure"]["code"] == "FILE_TASK_STREAM_FAILED"
    assert terminals[0]["payload"]["runtime"]["terminal_status"] == "failed"
    assert parsed[-1]["type"] == "run.finished"
    assert [item["seq"] for item in parsed] == list(range(1, len(parsed) + 1))
    assert [item["type"] for item in persisted].count("run.finished") == 1
