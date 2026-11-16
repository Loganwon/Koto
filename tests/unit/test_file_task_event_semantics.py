from app.core.services.file_task_event_semantics import (
    file_task_message,
    file_task_step_type,
    file_task_terminal_status,
)


def test_file_task_event_semantics_separate_actions_from_observations() -> None:
    assert file_task_step_type("tool.started") == "ACTION"
    assert file_task_step_type("tool.finished") == "OBSERVATION"
    assert file_task_step_type("supervisor.step_verified") == "OBSERVATION"


def test_file_task_event_semantics_project_terminal_status_and_message() -> None:
    payload = {
        "completed_task": False,
        "failure": {"summary": "读取证据不足"},
        "runtime": {"terminal_status": "analysis_incomplete"},
    }

    assert file_task_terminal_status("run.finished", payload) == "failed"
    assert file_task_message("run.finished", payload) == "读取证据不足"
