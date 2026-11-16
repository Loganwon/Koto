"""A viewing connection must not own or cancel the Agent execution loop."""

from __future__ import annotations

import importlib
import json
import logging
import threading
import time
from types import SimpleNamespace

import pytest
from flask import Flask, Response, g, stream_with_context

# Import before replacing the canonical getter below.  Importing this module
# under a patched getter would permanently bind a test closure into its route
# globals and leak a closed test database to later integration tests.
from app.api import task_routes as task_api
from app.core.agent.kernel_agent import KernelAgent
from app.core.agent.tool_registry import ToolRegistry
from app.core.jobs.job_runner import JobRunner
from app.core.tasks.progress_bus import ProgressBus
from app.core.tasks.task_ledger import TaskLedger


def _event(frame):
    if isinstance(frame, bytes):
        frame = frame.decode("utf-8")
    return json.loads(
        next(line[6:] for line in frame.splitlines() if line.startswith("data: "))
    )


@pytest.mark.parametrize("cancel_after_close", [False, True])
def test_http_close_after_first_delta_continues_same_run_and_saves_once(
    tmp_path, monkeypatch, cancel_after_close
):
    from web.services.chat_stream.agent_handler import handle_agent_task

    ledger = TaskLedger(str(tmp_path / "tasks.sqlite"))
    bus = ProgressBus()
    runner = JobRunner(max_workers=1)
    monkeypatch.setattr(
        importlib.import_module("app.core.tasks.task_ledger"),
        "get_ledger",
        lambda: ledger,
    )
    monkeypatch.setattr(
        importlib.import_module("app.core.tasks.progress_bus"),
        "get_progress_bus",
        lambda: bus,
    )
    monkeypatch.setattr(
        importlib.import_module("app.core.jobs.job_runner"),
        "get_job_runner",
        lambda: runner,
    )
    model_gate = threading.Event()
    saved = threading.Event()
    saved_turns = []
    writes = []
    calls = []
    target = tmp_path / "result.txt"

    class Provider:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:

                def chunks():
                    yield {"delta": "开始处理", "content": "开始处理"}
                    assert model_gate.wait(2.0)
                    yield {
                        "delta": "",
                        "content": "开始处理",
                        "stream_final": True,
                        "tool_calls": [
                            {"id": "write-once", "name": "write_result", "args": {}}
                        ],
                    }

                return chunks()
            return iter(
                [{"delta": "已保存结果", "content": "已保存结果", "stream_final": True}]
            )

    def write_result():
        assert g.request_id == "trusted-request-id"
        writes.append("write")
        target.write_text("真实结果", encoding="utf-8")
        return {"saved": True}

    registry = ToolRegistry()
    registry.register_tool("write_result", write_result, read_only=False)
    agent = KernelAgent(
        llm_provider=Provider(),
        tool_registry=registry,
        enable_pii_filter=False,
        enable_output_validation=False,
        use_tool_router=False,
        allow_model_fallback=False,
    )
    monkeypatch.setattr(
        importlib.import_module("app.core.agent.kernel_agent_service"),
        "get_kernel_agent",
        lambda **kwargs: agent,
    )

    def save_turn(*args):
        saved_turns.append(args)
        saved.set()

    app = Flask(__name__)

    @app.before_request
    def trusted_request():
        g.request_id = "trusted-request-id"

    @app.post("/agent")
    def run_agent():
        return handle_agent_task(
            "AGENT",
            "session",
            "写入结果",
            [],
            None,
            "Kernel",
            {},
            SimpleNamespace(append_and_save=save_turn),
            logging.getLogger(__name__),
            lambda *args, **kwargs: None,
            lambda payload: f"data: {json.dumps(payload, ensure_ascii=False)}\n\n",
            system_context="必须保留本轮可信上下文",
            model_id="fake",
        )

    routes = task_api
    monkeypatch.setattr(routes, "get_ledger", lambda: ledger)
    monkeypatch.setattr(routes, "get_progress_bus", lambda: bus)
    app.register_blueprint(routes.task_bp, url_prefix="/api/tasks")

    try:
        response = app.test_client().post("/agent", buffered=False)
        first_delta = None
        for frame in response.response:
            current = _event(frame)
            if current["type"] == "message.delta":
                first_delta = current
                break
        assert first_delta is not None
        task_id, run_id = first_delta["task_id"], first_delta["run_id"]
        last_seq = first_delta["seq"]
        response.close()
        if cancel_after_close:
            ledger.cancel_task(task_id)
        model_gate.set()
        assert saved.wait(
            1.5
        ), "closing the HTTP viewer stopped the still-running Agent producer"
        for _ in range(50):
            latest = ledger.latest_run_event(task_id, run_id)
            if latest and latest["type"] == "run.finished":
                break
            time.sleep(0.01)
        assert writes == ([] if cancel_after_close else ["write"])
        if not cancel_after_close:
            assert target.read_text(encoding="utf-8") == "真实结果"
        assert len(calls) == (1 if cancel_after_close else 2)
        assert "必须保留本轮可信上下文" in calls[-1]["system_instruction"]
        assert len(saved_turns) == 1
        if cancel_after_close:
            assert "已取消" in saved_turns[0][-1]
        else:
            assert saved_turns[0][-1] == "已保存结果"
        assert ledger.get(task_id).status.value == (
            "cancelled" if cancel_after_close else "completed"
        )
        independent = app.test_client()
        replay = independent.get(
            f"/api/tasks/{task_id}/stream?run_id={run_id}&after_seq={last_seq}&timeout=0.1"
        )
        replay_items = [
            _event(frame)
            for frame in replay.data.decode().strip().split("\n\n")
            if "data: " in frame
        ]
        facts = [
            item["detail"]["event"]
            for item in replay_items
            if isinstance(item.get("detail"), dict)
            and isinstance(item["detail"].get("event"), dict)
        ]
        assert facts[-1]["type"] == "run.finished"
        assert not any(
            frame.startswith("event: timeout")
            for frame in replay.data.decode().split("\n\n")
        )
        assert (
            len(
                [
                    event
                    for event in ledger.list_run_events(task_id, run_id)
                    if event["type"] == "run.finished"
                ]
            )
            == 1
        )
    finally:
        model_gate.set()
        runner._executor.shutdown(wait=True)
        runner.stop()
        ledger._conn.close()


@pytest.mark.parametrize("cancel_before_close", [False, True])
def test_file_viewer_close_drains_same_producer_through_real_terminal(
    tmp_path, monkeypatch, cancel_before_close
):
    from app.core.agent.file_task_contract import FileTaskRequest
    from app.core.agent.file_task_runtime import FileTaskRuntime
    from app.core.services.file_task_stream import stream_file_task_request

    ledger = TaskLedger(str(tmp_path / "file-tasks.sqlite"))
    bus, runner = ProgressBus(), JobRunner(max_workers=1)
    monkeypatch.setattr(
        importlib.import_module("app.core.tasks.task_ledger"),
        "get_ledger",
        lambda: ledger,
    )
    monkeypatch.setattr(
        importlib.import_module("app.core.tasks.progress_bus"),
        "get_progress_bus",
        lambda: bus,
    )
    monkeypatch.setattr(
        importlib.import_module("app.core.jobs.job_runner"),
        "get_job_runner",
        lambda: runner,
    )
    gate = threading.Event()
    writes = []
    target = tmp_path / "report.txt"

    class FileClient:
        calls = 0

        def stream_call(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                yield {"delta": "准备写入", "content": "准备写入"}
                assert gate.wait(2.0)
                yield {
                    "delta": "",
                    "content": "准备写入",
                    "stream_final": True,
                    "tool_calls": [
                        {
                            "id": "file-write-once",
                            "name": "create_file",
                            "args": {"path": str(target), "content": "实际内容"},
                        }
                    ],
                }
            else:
                yield {"delta": "已保存", "content": "已保存", "stream_final": True}

    client = FileClient()

    def execute(name, args):
        if name == "create_file":
            assert g.request_id == "trusted-file-request"
            writes.append(name)
            target.write_text("实际内容", encoding="utf-8")
            return {
                "success": True,
                "path": str(target),
                "operation": name,
                "summary": "实际内容已保存",
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
                "completed": target.read_text(encoding="utf-8") == "实际内容",
                "confidence": 1.0,
                "summary": "已读回核验",
            }
        raise AssertionError(name)

    file_runtime = FileTaskRuntime(
        tool_executor=execute,
        model_client=client,
        workspace_root=str(tmp_path),
        max_rounds=3,
    )
    request = FileTaskRequest(
        task="创建 report.txt 并写入内容",
        task_id="file-task",
        run_id="file-run",
        session_id="session",
        target_path=str(target),
    )
    stream_module = importlib.import_module("app.core.services.file_task_stream")
    monkeypatch.setattr(
        stream_module, "_build_file_task_request_from_data", lambda payload: request
    )
    monkeypatch.setattr(
        stream_module, "_build_file_task_orchestrator", lambda **kwargs: file_runtime
    )
    app = Flask(__name__)

    @app.before_request
    def trusted_request():
        g.request_id = "trusted-file-request"

    @app.post("/file")
    def run_file():
        return Response(
            stream_with_context(stream_file_task_request({})),
            mimetype="text/event-stream",
        )

    routes = task_api
    monkeypatch.setattr(routes, "get_ledger", lambda: ledger)
    monkeypatch.setattr(routes, "get_progress_bus", lambda: bus)
    app.register_blueprint(routes.task_bp, url_prefix="/api/tasks")
    try:
        response = app.test_client().post("/file", buffered=False)
        for frame in response.response:
            current = _event(frame)
            if current["type"] == "message.delta":
                break
        assert current["type"] == "message.delta"
        if cancel_before_close:
            cancelled = app.test_client().post(
                "/api/tasks/file-task/cancel", json={"run_id": "file-run"}
            )
            assert cancelled.status_code == 200
        response.close()
        gate.set()
        expected = "cancelled" if cancel_before_close else "completed"
        for _ in range(150):
            if ledger.get("file-task").status.value == expected:
                break
            time.sleep(0.01)
        assert ledger.get("file-task").status.value == expected
        assert writes == ([] if cancel_before_close else ["create_file"])
        terminal = ledger.latest_run_event("file-task", "file-run")
        assert terminal["type"] in {"run.finished", "run.cancelled"}
        replay = app.test_client().get(
            f"/api/tasks/file-task/stream?run_id=file-run&after_seq={current['seq']}&timeout=0.1"
        )
        facts = [
            _event(frame)["detail"]["event"]
            for frame in replay.data.decode().strip().split("\n\n")
            if "data: " in frame
        ]
        assert facts[-1]["type"] in {"run.finished", "run.cancelled"}
    finally:
        gate.set()
        runner._executor.shutdown(wait=True)
        runner.stop()
        ledger._conn.close()


def test_pending_client_cancel_before_first_frame_survives_queued_handoff(
    tmp_path, monkeypatch
):
    from web.services.chat_stream.agent_handler import handle_agent_task

    ledger = TaskLedger(str(tmp_path / "pending.sqlite"))
    bus, runner = ProgressBus(), JobRunner(max_workers=1)
    monkeypatch.setattr(
        importlib.import_module("app.core.tasks.task_ledger"),
        "get_ledger",
        lambda: ledger,
    )
    monkeypatch.setattr(
        importlib.import_module("app.core.tasks.progress_bus"),
        "get_progress_bus",
        lambda: bus,
    )
    monkeypatch.setattr(
        importlib.import_module("app.core.jobs.job_runner"),
        "get_job_runner",
        lambda: runner,
    )
    blocker, saved = threading.Event(), threading.Event()
    calls = []
    runner.submit_continuation(lambda: blocker.wait(3.0))

    class Provider:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            raise AssertionError("cancelled before registration must not invoke model")

    agent = KernelAgent(
        llm_provider=Provider(),
        tool_registry=ToolRegistry(),
        enable_pii_filter=False,
        enable_output_validation=False,
        use_tool_router=False,
        allow_model_fallback=False,
    )
    monkeypatch.setattr(
        importlib.import_module("app.core.agent.kernel_agent_service"),
        "get_kernel_agent",
        lambda **kwargs: agent,
    )
    app = Flask(__name__)

    @app.post("/agent")
    def run_agent():
        return handle_agent_task(
            "AGENT",
            "pending-session",
            "尚未开始的任务",
            [],
            None,
            "Kernel",
            {},
            SimpleNamespace(append_and_save=lambda *args: saved.set()),
            logging.getLogger(__name__),
            lambda *args, **kwargs: None,
            lambda payload: f"data: {json.dumps(payload, ensure_ascii=False)}\n\n",
            model_id="fake",
            task_id="client-task",
            run_id="client-run",
        )

    routes = task_api
    monkeypatch.setattr(routes, "get_ledger", lambda: ledger)
    monkeypatch.setattr(routes, "get_progress_bus", lambda: bus)
    app.register_blueprint(routes.task_bp, url_prefix="/api/tasks")
    try:
        client = app.test_client()
        assert client.post("/api/tasks/no-run/cancel").status_code == 404
        pending = client.post(
            "/api/tasks/client-task/cancel",
            json={"run_id": "client-run", "session_id": "pending-session"},
        )
        assert pending.status_code == 202
        assert ledger.get("client-task") is None
        response = client.post("/agent", buffered=False)
        first = _event(next(iter(response.response)))
        assert first["type"] == "run.started"
        assert first["task_id"] == "client-task"
        response.close()
        assert not saved.is_set()
        blocker.set()
        assert saved.wait(1.5)
        for _ in range(50):
            latest = ledger.latest_run_event("client-task", "client-run")
            if latest and latest["type"] == "run.finished":
                break
            time.sleep(0.01)
        assert calls == []
        assert ledger.get("client-task").status.value == "cancelled"
        facts = ledger.list_run_events("client-task", "client-run")
        assert len([event for event in facts if event["type"] == "run.finished"]) == 1
        assert facts[-1]["payload"]["status"] == "cancelled"
        rebound = client.post(
            "/api/tasks/other-task/cancel",
            json={"run_id": "client-run", "session_id": "pending-session"},
        )
        assert rebound.status_code == 409
        assert not ledger.is_cancel_requested("other-task")
    finally:
        blocker.set()
        runner._executor.shutdown(wait=True)
        runner.stop()
        ledger._conn.close()
