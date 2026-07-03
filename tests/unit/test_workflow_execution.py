from __future__ import annotations

import pytest

from app.core.workflows import execution
from app.core.workflows.execution import (
    WorkflowExecutionError,
    iter_workflow_events,
    prepare_workflow_execution,
)


def test_prepare_workflow_execution_rejects_missing_workflow_id():
    with pytest.raises(WorkflowExecutionError) as exc:
        prepare_workflow_execution("")

    assert exc.value.status_code == 400
    assert "缺少 workflow_id" in str(exc.value)


def test_prepare_workflow_execution_rejects_unknown_workflow():
    with pytest.raises(WorkflowExecutionError) as exc:
        prepare_workflow_execution("missing_workflow")

    assert exc.value.status_code == 404


def test_prepare_workflow_execution_rejects_chat_workflow():
    with pytest.raises(WorkflowExecutionError) as exc:
        prepare_workflow_execution("source_grounded_qa")

    assert exc.value.status_code == 400
    assert "对话模式" in str(exc.value)


def test_prepare_workflow_execution_returns_executor_plan():
    plan = prepare_workflow_execution("comm_digest")

    assert plan.workflow_id == "comm_digest"
    assert plan.executor.WORKFLOW_ID == "comm_digest"


def test_prepare_workflow_execution_reports_executor_load_failure(monkeypatch):
    monkeypatch.setattr(execution, "get_workflow_executor", lambda _workflow_id: None)

    with pytest.raises(WorkflowExecutionError) as exc:
        prepare_workflow_execution("comm_digest")

    assert exc.value.status_code == 500


def test_iter_workflow_events_delegates_to_executor_run():
    class FakeExecutor:
        def run(self, params):
            yield {"type": "seen", "params": params}

    plan = execution.WorkflowExecutionPlan("fake", FakeExecutor())

    assert list(iter_workflow_events(plan, {"x": 1})) == [
        {"type": "seen", "params": {"x": 1}}
    ]
