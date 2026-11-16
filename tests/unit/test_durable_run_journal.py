from __future__ import annotations

import importlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from flask import Flask

from app.core.tasks.progress_bus import ProgressBus, ProgressEvent
from app.core.tasks.task_ledger import TaskLedger


@pytest.fixture
def ledger(tmp_path):
    value = TaskLedger(str(tmp_path / "runs.sqlite"))
    value.create("session", "完整请求", task_id="task", metadata={"run_id": "run"})
    yield value
    value._conn.close()


def _data(frame):
    return json.loads(
        next(line[6:] for line in frame.splitlines() if line.startswith("data: "))
    )


def test_journal_sequence_is_allocated_once_across_workers(ledger):
    second = TaskLedger(ledger._db_path)
    try:

        def append(worker):
            owner = ledger if worker % 2 else second
            return [
                owner.append_run_event(
                    "task", "run", "message.delta", {"delta": str(i)}
                )
                for i in range(50)
            ]

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(append, range(4)))
        events = second.list_run_events("task", "run", limit=1000)
        assert [event["seq"] for event in events] == list(range(1, 201))
        assert len({event["event_id"] for event in events}) == 200
    finally:
        second._conn.close()


def test_event_id_retry_is_idempotent_and_terminal_cannot_be_rewritten(ledger):
    first = ledger.append_run_event(
        "task", "run", "message.delta", {"delta": "你"}, event_id="stable-call"
    )
    assert (
        ledger.append_run_event(
            "task", "run", "message.delta", {"delta": "你"}, event_id="stable-call"
        )
        == first
    )
    final = ledger.append_run_event(
        "task", "run", "run.finished", {"status": "completed"}
    )
    with pytest.raises(ValueError, match="terminal"):
        ledger.append_run_event("task", "run", "message.delta", {"delta": "late"})
    assert ledger.latest_run_event("task") == final


def test_domain_waiting_event_is_not_a_terminal_and_can_continue(ledger):
    event = ledger.append_run_event(
        "task",
        "run",
        "run.finished",
        {
            "completed_task": False,
            "runtime": {"terminal_status": "awaiting_confirmation"},
        },
    )
    assert ProgressEvent.from_run_event(event).status == "waiting"
    next_event = ledger.append_run_event("task", "run", "run.started", {})
    assert next_event["seq"] == 2


def test_file_checkpoint_keeps_commit_hash_during_later_model_generation(tmp_path):
    from app.core.agent.file_task_checkpoint import (
        FileTaskCheckpointConflict,
        build_file_task_checkpoint,
        restore_file_task_receipts,
    )
    from app.core.agent.file_task_contract import FileTaskRequest

    target = tmp_path / "report.txt"
    target.write_text("original committed value", encoding="utf-8")
    request = FileTaskRequest(task="edit", run_id="run")
    first = build_file_task_checkpoint(
        {"phase": "tool_complete", "messages": []},
        request=request,
        workspace_root=str(tmp_path),
        runtime=SimpleNamespace(),
        receipts={"file_changes": [{"path": str(target), "operation": "write"}]},
    )
    target.write_text("manual edit during final model response", encoding="utf-8")
    final = build_file_task_checkpoint(
        {"phase": "completed", "messages": []},
        request=request,
        workspace_root=str(tmp_path),
        runtime=SimpleNamespace(),
        receipts={**first["adapter_receipts"], "file_versions": first["file_versions"]},
    )
    with pytest.raises(FileTaskCheckpointConflict):
        restore_file_task_receipts(final)


def test_replay_survives_bus_and_ledger_recreation_and_more_than_500_events(ledger):
    for index in range(505):
        ledger.append_run_event("task", "run", "message.delta", {"delta": f"{index},"})
    ledger.append_run_event("task", "run", "run.finished", {"status": "completed"})
    restarted = TaskLedger(ledger._db_path)
    try:
        frames = list(
            ProgressBus().stream_events(
                "task",
                run_id="run",
                after_seq=250,
                event_loader=restarted.list_run_events,
                timeout=0.1,
            )
        )
        events = [_data(frame)["detail"]["event"] for frame in frames]
        assert [event["seq"] for event in events] == list(range(251, 507))
        assert frames[0].startswith("id: run:251\n")
        assert events[-1]["type"] == "run.finished"
    finally:
        restarted._conn.close()


def test_replay_live_boundary_does_not_lose_or_duplicate_events(ledger):
    bus = ProgressBus()
    ledger.append_run_event("task", "run", "run.started", {})
    injected = False

    def loader(*args, **kwargs):
        nonlocal injected
        snapshot = ledger.list_run_events(*args, **kwargs)
        if not injected:
            injected = True
            event = ledger.append_run_event(
                "task", "run", "message.delta", {"delta": "你好"}
            )
            bus.publish(ProgressEvent.from_run_event(event))
            event = ledger.append_run_event(
                "task", "run", "run.finished", {"status": "completed"}
            )
            bus.publish(ProgressEvent.from_run_event(event))
        return snapshot

    events = [
        _data(frame)["detail"]["event"]
        for frame in bus.stream_events(
            "task",
            run_id="run",
            event_loader=loader,
            timeout=0.1,
        )
    ]
    assert [event["seq"] for event in events] == [1, 2, 3]


def test_checkpoint_preserves_full_observations_and_has_one_owner(ledger):
    state = {
        "phase": "tool_complete",
        "messages": [{"role": "tool", "content": "已提交版本7"}],
        "completed_tool_results": [{"call_id": "c1"}],
    }
    ledger.save_kernel_checkpoint("task", "run", state)
    assert ledger.claim_kernel_checkpoint("task", "worker-a", run_id="run")
    assert ledger.claim_kernel_checkpoint("task", "worker-b", run_id="run") is None
    assert ledger.renew_kernel_lease("task", "run", "worker-a")
    assert ledger.release_kernel_checkpoint("task", "run", "worker-b") is False
    assert ledger.release_kernel_checkpoint("task", "run", "worker-a")
    recovered = ledger.claim_kernel_checkpoint("task", "worker-b", run_id="run")
    assert recovered["state"]["messages"] == state["messages"]


def test_unconfirmed_write_and_cancelled_task_cannot_be_replayed(ledger):
    checkpoint = ledger.save_kernel_checkpoint(
        "task",
        "run",
        {
            "phase": "tool_pending",
            "messages": [],
            "pending_tool_calls": [
                {"id": "write-1", "name": "write_file", "read_only": False}
            ],
        },
    )
    assert not checkpoint["resumable"]
    assert ledger.claim_kernel_checkpoint("task", "worker", run_id="run") is None
    ledger.save_kernel_checkpoint(
        "task", "run", {"phase": "tool_complete", "messages": []}
    )
    ledger.cancel_task("run")
    assert ledger.claim_kernel_checkpoint("task", "worker", run_id="run") is None


def test_initial_owner_lease_prevents_resume_during_inflight_model(ledger):
    ledger.save_kernel_checkpoint(
        "task", "run", {"phase": "started", "messages": []}, owner_id="original"
    )
    assert ledger.claim_kernel_checkpoint("task", "duplicate", run_id="run") is None


def test_dead_process_checkpoint_can_resume_without_waiting_for_long_lease(ledger):
    script = (
        "import sys; from app.core.tasks.task_ledger import TaskLedger; "
        "ledger=TaskLedger(sys.argv[1]); "
        "ledger.save_kernel_checkpoint('task','run',{'phase':'tool_complete','messages':[]},owner_id='dead-worker')"
    )
    subprocess.run(
        [sys.executable, "-c", script, ledger._db_path], check=True, capture_output=True
    )
    assert (
        ledger.list_kernel_checkpoints(expired_only=True)[0]["owner_id"]
        == "dead-worker"
    )
    assert ledger.claim_kernel_checkpoint("task", "new-worker", run_id="run")


def test_file_adapter_cannot_be_mistaken_for_generic_kernel_resume(ledger):
    saved = ledger.save_kernel_checkpoint(
        "task",
        "run",
        {
            "phase": "tool_complete",
            "runtime_adapter": "file_task",
            "messages": [],
        },
    )
    assert not saved["resumable"]
    assert ledger.claim_kernel_checkpoint("task", "wrong-adapter", run_id="run") is None


@pytest.fixture
def client(ledger, monkeypatch):
    routes = importlib.import_module("app.api.task_routes")
    monkeypatch.setattr(routes, "get_ledger", lambda: ledger)
    monkeypatch.setattr(routes, "get_progress_bus", ProgressBus)
    app = Flask(__name__)
    app.register_blueprint(routes.task_bp, url_prefix="/api/tasks")
    return app.test_client()


def test_cancel_before_registration_persists_and_does_not_fake_stopped(client, ledger):
    response = client.post(
        "/api/tasks/not-yet-created/cancel", json={"run_id": "future-run"}
    )
    assert response.status_code == 202
    assert response.get_json()["data"]["status"] == "pending"
    assert ledger.is_cancel_requested("future-run")
    ledger.create("session", "later", task_id="not-yet-created")
    assert ledger.is_cancel_requested("not-yet-created")


def test_api_replays_from_last_event_id_and_returns_snapshot(client, ledger):
    ledger.append_run_event("task", "run", "message.delta", {"delta": "你"})
    ledger.append_run_event("task", "run", "message.delta", {"delta": "好"})
    ledger.append_run_event("task", "run", "run.finished", {"status": "completed"})
    response = client.get(
        "/api/tasks/task/stream?run_id=run&timeout=0.1",
        headers={"Last-Event-ID": "run:1"},
    )
    frames = response.data.decode().strip().split("\n\n")
    assert [_data(frame)["seq"] for frame in frames] == [2, 3]
    details = client.get("/api/tasks/task").get_json()["data"]
    assert details["last_event_seq"] == 3
    assert details["last_event"]["type"] == "run.finished"


def test_resume_requires_explicit_approval_for_human_waiting(client, ledger):
    ledger.mark_waiting("task", "human_in_loop")
    response = client.post("/api/tasks/task/resume", json={})
    assert response.status_code == 409
    assert ledger.get("task").status.value == "waiting"


def test_job_runner_continues_same_checkpoint_instead_of_reissuing_request(
    ledger, monkeypatch
):
    from app.core.jobs.job_runner import JobRunner

    ledger_module = importlib.import_module("app.core.tasks.task_ledger")
    bus_module = importlib.import_module("app.core.tasks.progress_bus")
    agent_module = importlib.import_module("app.core.agent.kernel_agent_service")
    monkeypatch.setattr(ledger_module, "get_ledger", lambda: ledger)
    monkeypatch.setattr(bus_module, "get_progress_bus", ProgressBus)
    observed = []

    class FakeAgent:
        def run(self, **kwargs):
            observed.append(kwargs)
            assert (
                kwargs["resume_state"]["messages"][-1]["content"] == "文件已写入，版本7"
            )
            kwargs["checkpoint_callback"](
                {"phase": "completed", "messages": kwargs["resume_state"]["messages"]}
            )
            ledger.mark_completed("task", "已从工具结果继续")
            yield SimpleNamespace(
                to_dict=lambda: {
                    "step_type": "ANSWER",
                    "content": "已从工具结果继续",
                    "metadata": {},
                }
            )

    monkeypatch.setattr(agent_module, "get_kernel_agent", lambda **kwargs: FakeAgent())
    ledger.save_kernel_checkpoint(
        "task",
        "run",
        {
            "phase": "tool_complete",
            "messages": [{"role": "tool", "content": "文件已写入，版本7"}],
        },
    )
    runner = JobRunner(max_workers=1)
    try:
        assert runner.resume_kernel("task", run_id="run") == "task"
        runner._executor.shutdown(wait=True)
        assert len(observed) == 1
        assert observed[0]["task_id"] == "task"
        assert observed[0]["run_id"] == "run"
        events = ledger.list_run_events("task", "run")
        assert events[-1]["type"] == "run.finished"
        assert events[-1]["payload"]["status"] == "completed"
    finally:
        runner.stop()


def test_real_kernel_resume_after_committed_tool_does_not_repeat_write(
    ledger, monkeypatch, tmp_path
):
    from app.core.agent.kernel_agent import KernelAgent
    from app.core.agent.tool_registry import ToolRegistry
    from app.core.jobs.job_runner import JobRunner

    ledger_module = importlib.import_module("app.core.tasks.task_ledger")
    agent_service = importlib.import_module("app.core.agent.kernel_agent_service")
    monkeypatch.setattr(ledger_module, "get_ledger", lambda: ledger)
    writes = []
    target = tmp_path / "result.txt"

    def write_result():
        writes.append("write")
        target.write_text("已提交", encoding="utf-8")
        return {"saved": True, "version": 7}

    registry = ToolRegistry()
    registry.register_tool(
        "write_result",
        write_result,
        read_only=False,
        parameters={"type": "object", "properties": {}},
    )

    class Provider:
        def __init__(self, responses):
            self.responses = list(responses)

        def generate_content(self, **kwargs):
            return self.responses.pop(0)

    def agent(responses):
        return KernelAgent(
            llm_provider=Provider(responses),
            tool_registry=registry,
            model_id="fake-test-model",
            enable_pii_filter=False,
            enable_output_validation=False,
            use_tool_router=False,
            allow_model_fallback=False,
        )

    first = agent(
        [
            {
                "content": "",
                "tool_calls": [
                    {"id": "write-once", "name": "write_result", "args": {}}
                ],
            }
        ]
    )

    def crash_after_commit(state):
        ledger.save_kernel_checkpoint("task", "run", state)
        if state["phase"] == "tool_complete":
            raise SystemExit("simulate process exit after actual commit")

    with pytest.raises(SystemExit):
        list(
            first.run(
                "写入结果并说明",
                task_id="task",
                run_id="run",
                checkpoint_callback=crash_after_commit,
            )
        )
    assert target.read_text(encoding="utf-8") == "已提交"
    assert writes == ["write"]
    saved = ledger.get_kernel_checkpoint("task", "run")
    assert saved["state"]["messages"][-1]["role"] == "tool"

    restarted_agent = agent([{"content": "文件已经保存", "tool_calls": []}])
    monkeypatch.setattr(
        agent_service, "get_kernel_agent", lambda **kwargs: restarted_agent
    )
    runner = JobRunner(max_workers=1)
    try:
        runner.resume_kernel("task", run_id="run")
        runner._executor.shutdown(wait=True)
        assert writes == ["write"]
        assert ledger.get("task").status.value == "completed"
        assert (
            ledger.latest_run_event("task", "run")["payload"]["status"] == "completed"
        )
    finally:
        runner.stop()


@pytest.mark.parametrize("tamper", [False, True])
def test_file_domain_resume_preserves_write_receipts_and_quality_gate(
    ledger, monkeypatch, tmp_path, tamper
):
    from app.core.agent.file_task_contract import FileTaskRequest
    from app.core.agent.file_task_runtime import FileTaskRuntime
    from app.core.jobs.job_runner import JobRunner

    ledger_module = importlib.import_module("app.core.tasks.task_ledger")
    stream_module = importlib.import_module("app.core.services.file_task_stream")
    monkeypatch.setattr(ledger_module, "get_ledger", lambda: ledger)
    target = tmp_path / "report.txt"
    writes = []

    def execute(name, args):
        if name == "create_file":
            writes.append(name)
            target.write_text("已核实的报告内容", encoding="utf-8")
            return {
                "success": True,
                "path": str(target),
                "operation": name,
                "summary": "报告已保存",
            }
        if name in {"parse_file_to_text", "read_file_content"}:
            return target.read_text(encoding="utf-8")
        if name == "get_file_info":
            return {
                "exists": target.exists(),
                "path": str(target),
                "size": target.stat().st_size,
            }
        if name == "verify_task_completion":
            return {
                "completed": target.read_text(encoding="utf-8") == "已核实的报告内容",
                "confidence": 1.0,
                "summary": "实际文件读回一致",
                "remaining": [],
            }
        raise AssertionError(f"unexpected tool: {name}")

    def first_model(**kwargs):
        return {
            "content": "写入报告",
            "tool_calls": [
                {
                    "id": "create-once",
                    "name": "create_file",
                    "args": {"path": str(target), "content": "已核实的报告内容"},
                }
            ],
        }

    def crash(state):
        if state["phase"] == "tool_complete":
            raise SystemExit("exit after file tool commit before adapter event")

    request = FileTaskRequest(
        task="创建 report.txt 并写入报告内容",
        task_id="task",
        run_id="run",
        session_id="session",
        target_path=str(target),
        options={"_checkpoint_callback": crash},
    )
    runtime = FileTaskRuntime(
        tool_executor=execute,
        model_client=first_model,
        workspace_root=str(tmp_path),
        max_rounds=3,
    )
    with pytest.raises(SystemExit):
        list(runtime.run(request))
    assert writes == ["create_file"]
    saved = ledger.get_kernel_checkpoint("task", "run")
    assert saved["state"]["runtime_adapter"] == "file_task"
    assert saved["state"]["adapter_receipts"]["file_changes"]
    assert saved["state"]["file_versions"][0]["fingerprint"]["exists"]
    ledger.release_kernel_checkpoint("task", "run", saved["owner_id"])
    if tamper:
        target.write_text("中断期间的人工修改", encoding="utf-8")
    second_runtime = FileTaskRuntime(
        tool_executor=execute,
        model_client=lambda **kwargs: {"content": "报告已保存并核验", "tool_calls": []},
        workspace_root=str(tmp_path),
        max_rounds=3,
    )
    monkeypatch.setattr(
        stream_module, "_build_file_task_orchestrator", lambda **kwargs: second_runtime
    )
    runner = JobRunner(max_workers=1)
    try:
        runner.resume_kernel("task", run_id="run")
        runner._executor.shutdown(wait=True)
        events = ledger.list_run_events("task", "run")
        assert writes == ["create_file"]
        if tamper:
            assert ledger.get("task").status.value == "waiting"
            assert events[-1]["type"] == "run.waiting"
            assert target.read_text(encoding="utf-8") == "中断期间的人工修改"
            return
        assert any(event["type"] == "check.finished" for event in events)
        assert events[-1]["type"] == "run.finished"
        assert events[-1]["payload"]["completed_task"] is True, json.dumps(
            {
                "summary": events[-1]["payload"].get("summary"),
                "checks": [
                    event["payload"]
                    for event in events
                    if event["type"] == "check.finished"
                ],
            },
            ensure_ascii=False,
        )
        assert ledger.get_kernel_checkpoint("task", "run")["resumable"] is False
    finally:
        runner.stop()


def test_file_stream_projection_reuses_persisted_sequence_and_legacy_frame(
    ledger, monkeypatch
):
    from app.core.services.file_task_progress_persistence import (
        persist_file_task_progress_event,
    )
    from app.core.services.file_task_stream import _iter_file_task_stream_events

    ledger_module = importlib.import_module("app.core.tasks.task_ledger")
    monkeypatch.setattr(ledger_module, "get_ledger", lambda: ledger)
    request = SimpleNamespace(
        task_id="task",
        run_id="run",
        session_id="session",
        task="show",
        target_path="",
        files=[],
        current_file=None,
        selection_source="",
    )
    source = [
        {"type": "run.started", "run_id": "run", "seq": 90, "payload": {}},
        {
            "type": "tool.progress",
            "run_id": "run",
            "seq": 200,
            "payload": {"message": "实际进度"},
        },
        {
            "type": "run.finished",
            "run_id": "run",
            "seq": 999,
            "payload": {"status": "completed", "completed_task": True},
        },
    ]
    frames = list(
        _iter_file_task_stream_events(
            request,
            source,
            save_task_summary_fn=lambda **kwargs: None,
            normalize_event_fn=lambda event: SimpleNamespace(
                to_payload=lambda: {"text": "展示投影"}
            ),
            persist_progress_fn=persist_file_task_progress_event,
        )
    )
    assert all(frame.startswith("data: ") for frame in frames)
    facts = [_data(frame) for frame in frames if _data(frame)["type"] != "ui.message"]
    projections = [
        _data(frame) for frame in frames if _data(frame)["type"] == "ui.message"
    ]
    persisted = ledger.list_run_events("task", "run")
    assert [item["seq"] for item in facts] == [1, 2, 3]
    assert [(item["seq"], item["event_id"]) for item in persisted] == [
        (item["seq"], item["event_id"]) for item in facts
    ]
    assert [item["seq"] for item in projections] == [1, 2]
    assert [item["projection_of"] for item in projections] == ["run:1", "run:2"]


def test_job_keeps_full_payload_for_restart_instead_of_truncated_user_input(
    ledger, monkeypatch
):
    from app.core.jobs.job_runner import JobRunner, JobSpec

    ledger_module = importlib.import_module("app.core.tasks.task_ledger")
    runner_module = importlib.import_module("app.core.jobs.job_runner")
    monkeypatch.setattr(ledger_module, "get_ledger", lambda: ledger)
    monkeypatch.setattr(runner_module.time, "sleep", lambda seconds: None)
    runner = JobRunner(max_workers=1)
    query = "完整任务材料" * 1500
    try:
        task_id = runner.submit(
            JobSpec(job_type="agent_query", payload={"query": query})
        )
        original = ledger.get(task_id)
        assert len(original.user_input) <= 1000
        assert json.loads(original.metadata)["job_payload"]["query"] == query
        runner._queue.get_nowait()
        runner._recover_stale_tasks()
        recovered = runner._queue.get_nowait()
        assert recovered[2] == task_id
        assert recovered[3].payload["query"] == query
    finally:
        runner.stop()


def test_agent_query_uses_same_ledger_and_honors_cancel_before_next_write(
    ledger, monkeypatch, tmp_path
):
    from app.core.agent.kernel_agent import KernelAgent
    from app.core.agent.tool_registry import ToolRegistry
    from app.core.jobs.job_runner import JobRunner, JobSpec, _handle_agent_query

    ledger_module = importlib.import_module("app.core.tasks.task_ledger")
    service_module = importlib.import_module("app.core.agent.kernel_agent_service")
    monkeypatch.setattr(ledger_module, "get_ledger", lambda: ledger)
    writes = []

    def first_write():
        writes.append("first")
        (tmp_path / "first.txt").write_text("committed", encoding="utf-8")
        ledger.cancel_task("task")
        return "已保存第一项"

    def second_write():
        writes.append("second")
        return "must not run"

    registry = ToolRegistry()
    registry.register_tool("first_write", first_write, read_only=False)
    registry.register_tool("second_write", second_write, read_only=False)

    class Provider:
        def generate_content(self, **kwargs):
            return {
                "content": "执行两项操作",
                "tool_calls": [
                    {"id": "first", "name": "first_write", "args": {}},
                    {"id": "second", "name": "second_write", "args": {}},
                ],
            }

    agent = KernelAgent(
        llm_provider=Provider(),
        tool_registry=registry,
        enable_pii_filter=False,
        enable_output_validation=False,
        use_tool_router=False,
        allow_model_fallback=False,
    )
    monkeypatch.setattr(service_module, "get_kernel_agent", lambda **kwargs: agent)
    runner = JobRunner(max_workers=1)
    runner.register_handler("agent_query", _handle_agent_query)
    try:
        runner._run_job(
            "task",
            JobSpec(
                job_type="agent_query",
                payload={"query": "依次执行两项操作"},
                session_id="session",
            ),
        )
        assert writes == ["first"]
        assert ledger.count() == 1
        assert ledger.get("task").status.value == "cancelled"
        events = ledger.list_run_events("task", "run")
        terminals = [event for event in events if event["type"] == "run.finished"]
        assert len(terminals) == 1
        assert terminals[0]["payload"]["status"] == "cancelled"
        assert ledger.get_kernel_checkpoint("task", "run")
    finally:
        runner.stop()


def test_job_startup_does_not_enqueue_original_request_beside_checkpoint(
    ledger, monkeypatch
):
    from app.core.jobs.job_runner import JobRunner, JobSpec

    ledger_module = importlib.import_module("app.core.tasks.task_ledger")
    runner_module = importlib.import_module("app.core.jobs.job_runner")
    monkeypatch.setattr(ledger_module, "get_ledger", lambda: ledger)
    monkeypatch.setattr(runner_module.time, "sleep", lambda seconds: None)
    runner = JobRunner(max_workers=1)
    try:
        task_id = runner.submit(
            JobSpec(job_type="agent_query", payload={"query": "saved request"})
        )
        runner._queue.get_nowait()
        run_id = json.loads(ledger.get(task_id).metadata)["run_id"]
        ledger.save_kernel_checkpoint(
            task_id, run_id, {"phase": "tool_complete", "messages": []}
        )
        claims = []
        monkeypatch.setattr(
            runner, "resume_kernel", lambda task_id, **kwargs: claims.append(task_id)
        )
        runner._recover_stale_tasks()
        assert claims == [task_id]
        assert runner._queue.empty()
    finally:
        runner.stop()


def test_explicit_job_retry_keeps_old_terminal_and_starts_new_run(ledger, monkeypatch):
    from app.core.jobs.job_runner import JobRunner, JobSpec

    ledger_module = importlib.import_module("app.core.tasks.task_ledger")
    monkeypatch.setattr(ledger_module, "get_ledger", lambda: ledger)
    runner = JobRunner(max_workers=1)
    try:
        task_id = runner.submit(
            JobSpec(job_type="agent_query", payload={"query": "完整重试参数" * 1000})
        )
        runner._queue.get_nowait()
        original_run = json.loads(ledger.get(task_id).metadata)["run_id"]
        ledger.append_run_event(
            task_id, original_run, "run.finished", {"status": "failed"}
        )
        ledger.save_kernel_checkpoint(
            task_id, original_run, {"phase": "failed", "messages": []}
        )
        ledger.cancel_task(task_id)
        ledger.mark_failed(task_id, "prior failure")
        runner.retry(task_id)
        task = ledger.get(task_id)
        retry_run = json.loads(task.metadata)["run_id"]
        assert retry_run != original_run
        assert ledger.is_cancel_requested(task_id) is False
        assert (
            ledger.latest_run_event(task_id, original_run)["payload"]["status"]
            == "failed"
        )
        assert ledger.list_kernel_checkpoints(expired_only=True) == []
        assert len(runner._queue.get_nowait()[3].payload["query"]) > 1000
    finally:
        runner.stop()
