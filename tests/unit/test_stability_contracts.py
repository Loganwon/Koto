from __future__ import annotations

import json
import multiprocessing
import time
from pathlib import Path

import pytest

from app.core.agent.addons.audit import AddonAuditStore
from app.core.agent.file_task_tool_gateway import (
    CallableFileTaskToolProvider,
    FileTaskToolContext,
    FileTaskToolGateway,
)
from app.core.agent.kernel import (
    AgentRunLimits,
    RunGuard,
    RunLimitExceeded,
    ToolCall,
    ToolCatalog,
    ToolExecutionPolicy,
    ToolExecutor,
    ToolSpec,
)
from app.core.config.atomic_json_store import (
    AtomicJsonStoreError,
    load_json_document,
    update_json_document,
)
from app.core.tasks.task_ledger import TaskLedger, TaskStatus
from app.core.tasks.task_planner import Plan, PlanStep, StepStatus, TaskPlanner


def _increment_json_counter(path: str, iterations: int) -> None:
    for _ in range(iterations):
        update_json_document(
            path,
            lambda current: {"count": int(current.get("count", 0)) + 1},
            default={"count": 0},
        )


def _patch_task_plan(db_path: str, key: str, value: str) -> None:
    TaskLedger(db_path).upsert_task_plan("shared-run", {key: value})


@pytest.fixture
def source_import_path_for_spawn(monkeypatch):
    """Give spawned interpreters the tested source tree, not prior import state.

    Windows spawn copies sys.path and imports this test module in a fresh
    interpreter.  An already-cached parent package must not hide a shadowing
    test/packaging path from that child.  Restore the caller's path afterward.
    """
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]))


def test_chat_readonly_timeout_observes_wall_clock_deadline() -> None:
    from web.services.chat_stream.generate.regular_handler import run_with_timeout

    started = time.monotonic()
    result, error, timed_out = run_with_timeout(lambda: time.sleep(0.25), 0.02)

    assert time.monotonic() - started < 0.15
    assert (result, error, timed_out) == (None, None, True)


def test_mutating_kernel_tool_never_reports_timeout_while_still_running() -> None:
    catalog = ToolCatalog()
    catalog.register(
        ToolSpec(
            name="write_once",
            description="A representative in-process mutating operation.",
            input_schema={"type": "object", "properties": {}},
            handler=lambda: (time.sleep(0.04), "committed")[1],
            read_only=False,
        )
    )
    executor = ToolExecutor(catalog, ToolExecutionPolicy(default_timeout_seconds=0.01))

    result = executor.invoke(ToolCall(name="write_once"))

    assert result.ok is True
    assert result.value == "committed"
    assert result.duration_ms >= 30


def test_task_plan_patch_preserves_recovery_fields(tmp_path) -> None:
    ledger = TaskLedger(str(tmp_path / "ledger.sqlite"))
    before = ledger.upsert_task_plan(
        "run-1",
        {
            "status": "in_progress",
            "task": "analyze",
            "recipe_id": "pdf_report",
            "target_path": "out.docx",
            "total_steps": 5,
            "completed_steps": 3,
            "extra": {"checkpoint": "p3"},
        },
    )
    after = ledger.upsert_task_plan("run-1", {"status": "completed"})

    assert before["created_at"] == after["created_at"]
    assert after["task"] == "analyze"
    assert after["recipe_id"] == "pdf_report"
    assert after["target_path"] == "out.docx"
    assert after["completed_steps"] == 3
    assert after["extra"] == {"checkpoint": "p3"}
    assert after["status"] == "completed"


def test_task_plan_patches_are_serialized_across_processes(
    tmp_path, source_import_path_for_spawn
) -> None:
    db_path = str(tmp_path / "ledger.sqlite")
    TaskLedger(db_path).upsert_task_plan("shared-run", {"status": "in_progress"})
    processes = [
        multiprocessing.Process(
            target=_patch_task_plan,
            args=(db_path, f"field_{index}", f"value_{index}"),
        )
        for index in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    plan = TaskLedger(db_path).get_task_plan("shared-run")
    assert plan is not None
    for index in range(4):
        assert plan[f"field_{index}"] == f"value_{index}"


def test_cancellation_is_visible_across_ledger_instances(tmp_path) -> None:
    db_path = str(tmp_path / "ledger.sqlite")
    first = TaskLedger(db_path)
    second = TaskLedger(db_path)

    assert first.cancel_task("run-before-registration") is True
    assert second.is_cancel_requested("run-before-registration") is True
    assert second.cancel_task("run-before-registration") is False


def test_first_terminal_task_state_wins(tmp_path) -> None:
    ledger = TaskLedger(str(tmp_path / "ledger.sqlite"))
    task = ledger.create("session", "request")

    assert ledger.mark_completed(task.task_id, "done") is True
    assert ledger.mark_failed(task.task_id, "late failure") is False
    assert ledger.mark_running(task.task_id) is False
    assert ledger.mark_waiting(task.task_id) is False
    assert ledger.get(task.task_id).status is TaskStatus.COMPLETED


def test_missing_approval_handler_fails_closed() -> None:
    plan = Plan(
        task_id="approval-plan",
        original_request="commit",
        steps=[
            PlanStep(
                name="commit",
                description="Commit external state",
                require_approval=True,
            )
        ],
    )
    calls = 0

    def execute(_step, _context):
        nonlocal calls
        calls += 1

    events = list(TaskPlanner().execute_plan(plan, execute))

    assert calls == 0
    assert plan.status == "waiting"
    assert plan.steps[0].status is StepStatus.WAITING
    assert any(
        event.get("reason") == "approval_handler_unavailable" for event in events
    )


def test_non_idempotent_step_is_not_retried_automatically() -> None:
    step = PlanStep(
        name="send",
        description="Send once",
        max_retries=3,
        idempotent=False,
    )
    plan = Plan(task_id="retry-plan", original_request="send", steps=[step])
    calls = 0

    def execute(_step, _context):
        nonlocal calls
        calls += 1
        raise RuntimeError("uncertain external result")

    list(TaskPlanner().execute_plan(plan, execute))

    assert calls == 1
    assert step.status is StepStatus.FAILED


def test_identical_mutating_kernel_call_cannot_repeat() -> None:
    guard = RunGuard(AgentRunLimits(max_repeated_batches=5))
    call = ToolCall(name="commit_record", arguments={"id": "record-1"})

    guard.accept_tool_batch([call], nonrepeatable_names={"commit_record"})
    with pytest.raises(RunLimitExceeded, match="mutating tool call"):
        guard.accept_tool_batch([call], nonrepeatable_names={"commit_record"})


def test_atomic_json_updates_survive_multiple_processes(
    tmp_path, source_import_path_for_spawn
) -> None:
    path = str(tmp_path / "state.json")
    processes = [
        multiprocessing.Process(target=_increment_json_counter, args=(path, 12))
        for _ in range(3)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    assert load_json_document(path, default={}) == {"count": 36}


def test_corrupt_json_never_silently_becomes_empty_state(tmp_path) -> None:
    path = Path(tmp_path / "state.json")
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(AtomicJsonStoreError):
        load_json_document(path, default={})

    assert not path.exists()
    assert list(tmp_path.glob("state.json.corrupt-*"))


def test_addon_audit_events_are_durable_across_store_instances(tmp_path) -> None:
    path = tmp_path / "addon-audit.sqlite"
    first = AddonAuditStore(path)
    event_id = first.append(
        {
            "event": "plugin.tool.started",
            "plugin_id": "com.test.audit",
            "correlation_id": "corr-1",
        }
    )

    events = AddonAuditStore(path).list_events()

    assert events[0]["event_id"] == event_id
    assert events[0]["plugin_id"] == "com.test.audit"


def test_file_tool_error_rolls_back_partial_target_mutation(tmp_path) -> None:
    target = tmp_path / "report.md"
    target.write_text("original", encoding="utf-8")

    def failing_provider(_name, arguments):
        Path(arguments["path"]).write_text("partial", encoding="utf-8")
        return json.dumps({"error": "write failed after touching target"})

    provider = CallableFileTaskToolProvider(
        failing_provider,
        definitions=[
            {
                "name": "create_file",
                "description": "Mutation rollback fixture.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                "read_only": False,
                "file_types": ["md"],
            }
        ],
    )
    gateway = FileTaskToolGateway(
        context=FileTaskToolContext(
            request_context={"run_id": "rollback-test", "target_path": str(target)}
        ),
        providers=[provider],
    )

    result = gateway.execute("create_file", {"path": str(target)})

    assert json.loads(result)["error"]
    assert target.read_text(encoding="utf-8") == "original"
    assert not list(tmp_path.glob("*.koto-rollback*"))
