from app.core.agent.file_task_contract import FileTaskRequest
from app.core.tasks.task_ledger import TaskLedger


def test_file_task_request_preserves_client_task_id_for_stream_recovery() -> None:
    request = FileTaskRequest.from_mapping(
        {
            "task": "生成一份摘要",
            "task_id": "task_reconnect_123",
            "run_id": "run_reconnect_123",
        }
    )

    assert request.task_id == "task_reconnect_123"
    assert request.run_id == "run_reconnect_123"


def test_task_ledger_accepts_the_client_task_id_used_by_recovery(tmp_path) -> None:
    ledger = TaskLedger(db_path=str(tmp_path / "tasks.db"))

    record = ledger.create(
        session_id="stream-recovery",
        user_input="生成一份摘要",
        task_id="task_reconnect_123",
    )

    assert record.task_id == "task_reconnect_123"
    assert ledger.get("task_reconnect_123") is not None


def test_retargeting_preserves_the_client_task_id() -> None:
    from app.core.agent.file_task_targeting import request_with_target_path

    request = FileTaskRequest(task="生成报告", task_id="task_reconnect_456")

    assert request_with_target_path(request, "report.docx").task_id == "task_reconnect_456"


def test_context_reader_ignores_instruction_prefixed_target_alias() -> None:
    from app.core.agent.file_task_context_read import _is_instruction_prefixed_target_alias
    from app.core.agent.file_task_contract import FileTaskFile

    request = FileTaskRequest(task="生成报告", target_path="report.docx")
    malformed = FileTaskFile(path="生成一份名为《report.docx", name="report.docx", type="docx")
    target = FileTaskFile(path="report.docx", name="report.docx", type="docx", target=True)

    assert _is_instruction_prefixed_target_alias(request, malformed) is True
    assert _is_instruction_prefixed_target_alias(request, target) is False


def test_workspace_task_runner_keeps_one_task_id_across_initial_and_recovery_streams() -> None:
    source = open("web/src/workspace/task-runner.ts", encoding="utf-8").read()

    assert "function createFileTaskId(): string" in source
    assert "payload.task_id = createFileTaskId();" in source
    assert "card.dataset.taskId = String(payload.task_id || payload.taskId || '').trim();" in source
    assert "function persistedTaskStreamEvent(event: Record<string, any>)" in source
    assert "events.map(persistedTaskStreamEvent)" in source
    assert "showTaskStreamReconnectNotice(card);" in source
    assert "const recovered = await resumePersistedFileTask({" in source


def test_workspace_dispatcher_prefers_a_clean_named_output_path() -> None:
    source = open("web/src/workspace/task-dispatcher.ts", encoding="utf-8").read()

    assert "const namedOutputPattern =" in source
    assert "score: 100" in source
    assert "namedMatch[0].lastIndexOf(rawPath)" in source


def test_recovery_stream_does_not_synthesize_a_successful_terminal_event() -> None:
    source = open("web/src/workspace/task-runner.ts", encoding="utf-8").read()

    stream_start = source.index("function streamTaskSse(")
    stream_end = source.index("function cancelFileTaskRun(", stream_start)
    stream_source = source[stream_start:stream_end]
    assert "if (!terminalSeen)" in stream_source
    assert "任务状态流已断开，正在保留后台任务状态。" in stream_source
    assert "type: 'run.finished', payload: { text: '流已结束。' }" not in stream_source
