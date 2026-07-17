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

    assert (
        request_with_target_path(request, "report.docx").task_id == "task_reconnect_456"
    )


def test_context_reader_ignores_instruction_prefixed_target_alias() -> None:
    from app.core.agent.file_task_context_read import (
        _is_instruction_prefixed_target_alias,
    )
    from app.core.agent.file_task_contract import FileTaskFile

    request = FileTaskRequest(task="生成报告", target_path="report.docx")
    malformed = FileTaskFile(
        path="生成一份名为《report.docx", name="report.docx", type="docx"
    )
    target = FileTaskFile(
        path="report.docx", name="report.docx", type="docx", target=True
    )

    assert _is_instruction_prefixed_target_alias(request, malformed) is True
    assert _is_instruction_prefixed_target_alias(request, target) is False


def test_workspace_task_runner_keeps_one_task_id_across_initial_and_recovery_streams() -> (
    None
):
    runner = open("web/src/workspace/task-runner.ts", encoding="utf-8").read()
    transport = open(
        "web/src/workspace/task-stream-transport.ts", encoding="utf-8"
    ).read()
    sse = open("web/src/workspace/file-task-sse.ts", encoding="utf-8").read()
    lifecycle = open(
        "web/src/workspace/task-stream-lifecycle.ts", encoding="utf-8"
    ).read()

    assert "from './task-stream-transport';" in runner
    assert "export function createFileTaskId(): string" in transport
    assert "payload.task_id = createFileTaskId();" in transport
    assert "card.dataset.taskId = String(" in transport
    assert "payload.task_id || payload.taskId || ''" in transport
    assert "function persistedTaskStreamEvent(event: Record<string, any>)" in sse
    assert "function persistedTaskStreamEvent(event: Record<string, any>)" not in runner
    assert "transformEvent: persistedTaskStreamEvent" in transport
    assert "export async function consumeTaskEventStream(" in lifecycle
    assert "runtime.showReconnectNotice(card, 'recovering');" in transport
    assert "const recovered = await resumePersistedTask({" in transport
    assert "setResumePersistedTask(resumePersistedFileTask);" in runner


def test_workspace_target_inference_prefers_a_clean_named_output_path() -> None:
    source = open(
        "web/src/workspace/task-target-inference.ts", encoding="utf-8"
    ).read()

    assert "const namedOutputPattern =" in source
    assert "score: 100" in source
    assert "namedMatch[0].lastIndexOf(rawPath)" in source


def test_recovery_stream_does_not_synthesize_a_successful_terminal_event() -> None:
    transport = open(
        "web/src/workspace/task-stream-transport.ts", encoding="utf-8"
    ).read()
    lifecycle = open(
        "web/src/workspace/task-stream-lifecycle.ts", encoding="utf-8"
    ).read()

    stream_start = transport.index("  function streamTaskSse(")
    stream_end = transport.index("  async function streamTaskFlow(", stream_start)
    stream_source = transport[stream_start:stream_end]
    assert "if (!terminalSeen)" in stream_source
    assert "任务状态流已断开，正在保留后台任务状态。" in stream_source
    assert "type: 'run.finished', payload: { text: '流已结束。' }" not in stream_source
    assert "const trailing = parseSseEvents(buffer, true);" in lifecycle


def test_short_stream_cancel_handler_is_cleaned_after_settlement() -> None:
    transport = open(
        "web/src/workspace/task-stream-transport.ts", encoding="utf-8"
    ).read()
    lifecycle = open(
        "web/src/workspace/task-stream-lifecycle.ts", encoding="utf-8"
    ).read()

    assert "const cleanupCancellation = installTaskCancelHandler(" in transport
    assert "cleanupCancellation();" in transport
    assert "if (card._cancelHandler === handler) delete card._cancelHandler;" in lifecycle
