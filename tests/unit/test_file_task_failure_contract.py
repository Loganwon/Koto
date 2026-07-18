from pathlib import Path

from app.core.agent.file_task_contract import FileTaskRequest
from app.core.agent.file_task_runtime import FileTaskRuntime

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_active_file_task_flow_has_one_terminal_protocol_and_one_ui_projection_owner():
    backend_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "app/core/agent").glob("file_task_*.py")
    )
    stream_source = _read("web/file_task_stream.py")
    ui_projection_source = _read("app/core/agent/file_task_ui_stream.py")
    artifact_model_source = _read("app/core/artifacts/models.py")
    runner_source = _read("web/src/workspace/task-runner.ts")
    dispatcher_source = _read("web/src/workspace/task-dispatcher.ts")
    status_source = _read("web/src/workspace/file-task-status.ts")

    assert '"run.error"' not in backend_sources
    assert '"run.error"' not in stream_source
    assert "'run.error':" not in runner_source
    assert "needs_attention" not in backend_sources
    assert "needs_attention" not in runner_source
    assert "needs_attention" not in status_source
    assert "needs_attention" not in artifact_model_source
    assert "stages = {" not in stream_source
    assert 'if raw_type == "run.finished":' in ui_projection_source
    assert "legacyRoute" not in dispatcher_source
    assert "'open_file', 'system_action'" not in dispatcher_source
    assert "multi_target." not in stream_source
    assert "multi_target." not in ui_projection_source


def test_write_task_model_timeout_has_one_precise_terminal_result(tmp_path):
    target_path = tmp_path / "timeout-report.docx"

    def timeout_model(**_kwargs):
        raise TimeoutError("provider timed out after 45 seconds")

    events = list(
        FileTaskRuntime(
            model_client=timeout_model,
            workspace_root=str(tmp_path),
            max_rounds=1,
        ).run(
            FileTaskRequest(
                task="创建一个新的 docx，写入项目风险摘要",
                run_id="model_timeout_contract",
                target_path=str(target_path),
            )
        )
    )

    event_types = [event.type for event in events]
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]

    assert "run.error" not in event_types
    assert event_types.count("run.finished") == 1
    assert check_finished.payload["status"] == "model_timeout"
    assert check_finished.payload["failure"]["code"] == "MODEL_CALL_TIMEOUT"
    assert run_finished.type == "run.finished"
    assert run_finished.payload["completed_task"] is False
    assert run_finished.payload["runtime"]["terminal_status"] == "model_timeout"
    assert run_finished.payload["failure"]["status"] == "model_timeout"
    assert "no_file_change" not in str([event.to_dict() for event in events])


def test_successful_model_without_write_tool_is_not_reported_as_model_failure(tmp_path):
    events = list(
        FileTaskRuntime(
            model_client=lambda **_kwargs: {
                "content": "已整理风险摘要。",
                "tool_calls": [],
            },
            workspace_root=str(tmp_path),
            max_rounds=1,
        ).run(
            FileTaskRequest(
                task="创建一个新的 docx，写入项目风险摘要",
                run_id="write_not_performed_contract",
                target_path=str(tmp_path / "no-write-report.docx"),
            )
        )
    )

    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = events[-1]

    assert check_finished.payload["status"] == "write_not_performed"
    assert "failure" not in check_finished.payload
    assert run_finished.payload["runtime"]["terminal_status"] == "write_not_performed"
    assert "failure" not in run_finished.payload
