from __future__ import annotations

import json
import logging
from importlib import import_module
from types import SimpleNamespace

import pytest
from flask import Flask

from app.core.agent.types import AgentStep, AgentStepType
from web.services.chat_stream.agent_handler import handle_agent_task


def _sse(payload):
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _events(body):
    return [
        json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")
    ]


def _stream_step(event_type, content="", **metadata):
    return AgentStep(
        SimpleNamespace(value="stream"),
        content,
        metadata={
            "event_type": event_type,
            "task_id": "task-a",
            "run_id": "run-a",
            **metadata,
        },
    )


def test_http_context_projection_keeps_only_agent_inputs():
    from web.services.chat_stream.agent_handler import agent_request_options

    options = agent_request_options(
        {
            "agent_system_context": "file/RAG/memory",
            "system_instruction": "stable persona",
            "model_id": "chosen-model",
            "file_context": {"file_id": "file-a"},
            "frontend_scope": {"frontend_session_id": "browser-a"},
            "unrelated_legacy_state": "not part of the Agent input",
        }
    )
    assert options["system_context"] == "file/RAG/memory"
    assert options["model_id"] == "chosen-model"
    assert "system_instruction" not in options
    assert "unrelated_legacy_state" not in options


@pytest.fixture
def transport(monkeypatch):
    observed = {"saved": [], "memory": [], "events": [], "published": []}

    class SessionManager:
        def append_and_save(self, *args):
            observed["saved"].append(args)

    class Ledger:
        def append_run_event(self, task_id, run_id, event_type, payload):
            if observed["events"] and observed["events"][-1]["type"] == "run.finished":
                raise AssertionError("cannot append after a durable terminal event")
            seq = len(observed["events"]) + 1
            event = {
                "version": 1,
                "task_id": task_id,
                "run_id": run_id,
                "seq": seq,
                "event_id": f"{run_id}:{seq}",
                "type": event_type,
                "payload": payload,
            }
            observed["events"].append(event)
            return event

    monkeypatch.setattr(
        import_module("app.core.tasks.task_ledger"), "get_ledger", lambda: Ledger()
    )
    monkeypatch.setattr(
        import_module("app.core.tasks.progress_bus"),
        "get_progress_bus",
        lambda: SimpleNamespace(publish=observed["published"].append),
    )
    app = Flask(__name__)

    def invoke(steps, **options):
        class FakeAgent:
            def run(self, **kwargs):
                observed["run"] = kwargs
                yield from steps

        def get_agent(**kwargs):
            observed["factory"] = kwargs
            return FakeAgent()

        monkeypatch.setattr(
            import_module("app.core.agent.kernel_agent_service"),
            "get_kernel_agent",
            get_agent,
        )
        with app.test_request_context("/api/chat/stream"):
            response = handle_agent_task(
                "AGENT",
                "chat-a",
                "处理当前选区",
                [{"role": "user", "content": "早期上下文"}],
                options.pop("locked_model", "cloud"),
                "Kernel Default",
                None,
                SessionManager(),
                logging.getLogger(__name__),
                lambda *args, **kwargs: observed["memory"].append((args, kwargs)),
                _sse,
                **options,
            )
            observed["response"] = response
            observed["body"] = response.get_data(as_text=True)
        return _events(observed["body"])

    return observed, invoke


def test_agent_http_passes_request_context_and_resolved_model(transport, monkeypatch):
    observed, invoke = transport
    monkeypatch.setattr(
        import_module("web.services.chat_stream.agent_handler"),
        "select_task_model",
        lambda *_args: pytest.fail("resolved request model must not be selected again"),
    )
    events = invoke(
        [AgentStep(AgentStepType.ANSWER, "完成")],
        system_context="当前文件 report.docx；选区 selected；RAG evidence；memory evidence",
        model_id="deepseek-reasoner",
    )
    assert observed["factory"]["model_id"] == "deepseek-reasoner"
    assert observed["run"]["system_context"].count("RAG evidence") == 1
    assert observed["run"]["history"][0]["content"] == "早期上下文"
    assert events[-2]["data"]["status"] == "success"
    assert observed["saved"][0][-1] == "完成"
    assert len(observed["memory"]) == 1


@pytest.mark.parametrize(
    "state,status", [("failed", "failed"), ("cancelled", "cancelled")]
)
def test_agent_http_error_never_becomes_success_or_memory(transport, state, status):
    observed, invoke = transport
    events = invoke(
        [
            AgentStep(AgentStepType.THOUGHT, "准备写入"),
            AgentStep(
                AgentStepType.ERROR, "实际执行没有完成", metadata={"state": state}
            ),
        ]
    )
    final = events[-2]["data"]
    assert final["status"] == status
    assert final["result"] == ""
    assert final["error"] == "实际执行没有完成"
    assert "任务完成" not in observed["saved"][0][-1]
    assert observed["memory"] == []
    assert events[-1] == {"type": "done", "status": status}


def test_agent_http_missing_answer_is_failure(transport):
    observed, invoke = transport
    events = invoke([AgentStep(AgentStepType.THOUGHT, "还在准备")])
    assert events[-2]["data"]["status"] == "failed"
    assert events[-2]["data"]["result"] == ""
    assert "未返回完成结果" in events[-2]["data"]["error"]
    assert observed["memory"] == []


def test_agent_http_blocked_answer_keeps_blocked_terminal(transport):
    observed, invoke = transport
    events = invoke(
        [
            _stream_step("run.started", state="running"),
            AgentStep(
                AgentStepType.ANSWER,
                "验收未通过",
                metadata={"validation": {"blocked": True}},
            ),
            _stream_step("run.finished", state="succeeded"),
        ]
    )
    finished = next(event for event in events if event["type"] == "run.finished")
    assert finished["state"] == "blocked"
    assert finished["runtime_state"] == "succeeded"
    assert events[-2]["data"]["status"] == "blocked"
    assert observed["memory"] == []


def test_agent_http_projects_stream_once_with_durable_identity(transport):
    observed, invoke = transport
    events = invoke(
        [
            _stream_step("run.started", state="running"),
            _stream_step(
                "message.started", message_id="message-a", attempt_id="attempt-a"
            ),
            _stream_step("message.delta", "你", message_id="message-a"),
            _stream_step("message.delta", "好", message_id="message-a"),
            _stream_step(
                "message.finished", "你好", message_id="message-a", status="completed"
            ),
            AgentStep(AgentStepType.ANSWER, "你好"),
            _stream_step("run.finished", state="succeeded"),
        ]
    )
    deltas = [event for event in events if event["type"] == "message.delta"]
    assert [event["content"] for event in deltas] == ["你", "好"]
    assert not any(
        event["type"] == "agent_step" and event["data"]["step_type"] == "stream"
        for event in events
    )
    final = events[-2]["data"]
    assert final["id"] == final["task_id"] == "task-a"
    assert final["run_id"] == "run-a"
    assert final["result"] == "你好"
    journal = observed["events"]
    assert [event["seq"] for event in journal] == list(range(1, len(journal) + 1))
    assert len(observed["published"]) == len(journal)
    assert journal[-1]["type"] == "run.finished"
    assert journal[-1]["payload"]["result"] == "你好"
    assert not any(event.get("persisted") is False for event in events)
    assert "id: run-a:1\n" in observed["body"]


def test_agent_http_binds_browser_scope_without_model_arguments(transport, monkeypatch):
    observed, invoke = transport
    context = object()

    def bind(base, scope, *, session_id):
        observed["scope"] = (base, scope, session_id)
        return context

    monkeypatch.setattr(
        import_module("app.core.agent.frontend_observability"),
        "bind_frontend_document_context",
        bind,
        raising=False,
    )
    invoke(
        [AgentStep(AgentStepType.ANSWER, "已读取")],
        file_context={"file_path": "workspace/report.docx", "file_id": "file-a"},
        frontend_session_id="browser-a",
    )
    assert observed["scope"][1] == {
        "frontend_session_id": "browser-a",
        "document_path": "workspace/report.docx",
        "file_id": "file-a",
    }
    assert observed["scope"][2] == "chat-a"
    assert observed["run"]["addon_invocation_context"] is context
    assert "frontend_scope" not in observed["run"]["addon_plan"]


def test_agent_http_stream_is_observable_before_generator_completes(monkeypatch):
    app = Flask(__name__)
    reached = []

    class FakeAgent:
        def run(self, **kwargs):
            yield _stream_step("message.delta", "第一段")
            reached.append("continued")
            yield AgentStep(AgentStepType.ANSWER, "第一段和第二段")

    monkeypatch.setattr(
        import_module("app.core.agent.kernel_agent_service"),
        "get_kernel_agent",
        lambda **kwargs: FakeAgent(),
    )
    monkeypatch.setattr(
        import_module("app.core.tasks.task_ledger"),
        "get_ledger",
        lambda: SimpleNamespace(
            append_run_event=lambda *_args: {"seq": 1, "event_id": "run-a:1"}
        ),
    )
    monkeypatch.setattr(
        import_module("app.core.tasks.progress_bus"),
        "get_progress_bus",
        lambda: SimpleNamespace(publish=lambda _event: None),
    )
    with app.test_request_context("/api/chat/stream"):
        response = handle_agent_task(
            "AGENT",
            "chat-a",
            "继续",
            [],
            "cloud",
            "Kernel",
            None,
            SimpleNamespace(append_and_save=lambda *_args: None),
            app.logger,
            lambda *_args, **_kwargs: None,
            _sse,
        )
        frames = iter(response.response)
        next(frames)  # classification
        delta = next(frames)
        assert "message.delta" in delta and "第一段" in delta
        assert reached == []
        list(frames)
        assert reached == ["continued"]


@pytest.mark.parametrize("explicit_id", [True, False])
def test_chat_interrupt_cancels_the_durable_kernel_task(monkeypatch, explicit_id):
    from web.blueprints import chat

    cancelled = []
    flags = {}
    task = SimpleNamespace(task_id="task-a", session_id="chat-a")
    monkeypatch.setattr(
        import_module("app.core.tasks.task_ledger"),
        "get_ledger",
        lambda: SimpleNamespace(
            get=lambda _task_id: task,
            list_tasks=lambda **kwargs: (
                [task] if kwargs["session_id"] == "chat-a" else []
            ),
            cancel_task=cancelled.append,
        ),
    )
    monkeypatch.setattr(
        chat,
        "service_registry",
        SimpleNamespace(
            interrupt_manager=SimpleNamespace(
                set_interrupt=lambda session: flags.update(session=session)
            ),
            interrupt_flags={},
        ),
    )
    app = Flask(__name__)
    app.register_blueprint(chat.chat_bp)
    payload = {"session": "chat-a"}
    if explicit_id:
        payload["task_id"] = "task-a"
    response = app.test_client().post("/api/chat/interrupt", json=payload)
    assert response.status_code == 200
    assert response.get_json()["task_id"] == "task-a"
    assert cancelled == ["task-a"]
    assert flags == {"session": "chat-a"}


def test_chat_interrupt_does_not_cancel_another_session(monkeypatch):
    from web.blueprints import chat

    cancelled = []
    monkeypatch.setattr(
        import_module("app.core.tasks.task_ledger"),
        "get_ledger",
        lambda: SimpleNamespace(
            get=lambda _task_id: SimpleNamespace(
                task_id="task-a", session_id="another-chat"
            ),
            cancel_task=cancelled.append,
        ),
    )
    app = Flask(__name__)
    app.register_blueprint(chat.chat_bp)
    response = app.test_client().post(
        "/api/chat/interrupt", json={"session": "chat-a", "task_id": "task-a"}
    )
    assert response.status_code == 404
    assert cancelled == []


@pytest.mark.parametrize(
    "blocked,error_code,finished_status",
    [
        (True, "validation_blocked", "blocked"),
        (False, "validation_exhausted", "failed"),
    ],
)
def test_real_kernel_validation_failure_agrees_across_http_ledger_checkpoint_and_journal(
    tmp_path,
    monkeypatch,
    blocked,
    error_code,
    finished_status,
):
    from app.core.agent.kernel import ValidationOutcome
    from app.core.agent.kernel_agent import KernelAgent
    from app.core.agent.tool_registry import ToolRegistry
    from app.core.tasks.task_ledger import TaskLedger, TaskStatus

    class Validator:
        def validate(self, content, request):
            if blocked:
                return ValidationOutcome.block(
                    "当前输出未通过验收。", reasons=("test_validation",)
                )
            return ValidationOutcome.retry(
                content, "请修正输出", reasons=("test_validation",)
            )

    class Provider:
        calls = 0

        def generate_content(self, **kwargs):
            self.calls += 1
            return iter(
                [
                    {
                        "delta": "待验收草稿",
                        "content": "待验收草稿",
                        "stream_final": True,
                        "tool_calls": [],
                    }
                ]
            )

    ledger = TaskLedger(db_path=str(tmp_path / "http-validation.db"))
    memory = []
    published = []
    monkeypatch.setattr(
        import_module("app.core.tasks.task_ledger"), "get_ledger", lambda: ledger
    )
    monkeypatch.setattr(
        import_module("app.core.tasks.progress_bus"),
        "get_progress_bus",
        lambda: SimpleNamespace(publish=published.append),
    )
    monkeypatch.setattr(
        import_module("app.core.agent.kernel_agent"), "KotoOutputValidator", Validator
    )
    provider = Provider()
    agent = KernelAgent(
        provider,
        ToolRegistry(),
        model_id="offline-validator",
        enable_pii_filter=False,
        enable_output_validation=True,
        use_tool_router=False,
        allow_model_fallback=False,
    )
    monkeypatch.setattr(
        import_module("app.core.agent.kernel_agent_service"),
        "get_kernel_agent",
        lambda **kwargs: agent,
    )
    app = Flask(__name__)
    with app.test_request_context("/api/chat/stream"):
        response = handle_agent_task(
            "AGENT",
            "validation-session",
            "回答问题",
            [],
            "cloud",
            "Kernel",
            None,
            SimpleNamespace(append_and_save=lambda *_args: None),
            app.logger,
            lambda *_args, **_kwargs: memory.append(True),
            _sse,
            model_id="offline-validator",
        )
        events = _events(response.get_data(as_text=True))
    final = next(event["data"] for event in events if event["type"] == "task_final")
    assert final["status"] == "failed"
    assert memory == []
    finished = [event for event in events if event["type"] == "message.finished"]
    assert finished[-1]["status"] == finished_status
    task = ledger.get(final["task_id"])
    assert task.status is TaskStatus.FAILED
    checkpoint = ledger.get_kernel_checkpoint(final["task_id"], final["run_id"])
    assert checkpoint["phase"] == "failed"
    assert checkpoint["state"]["error_code"] == error_code
    assert checkpoint["resumable"] is False
    journal = ledger.list_run_events(final["task_id"], final["run_id"])
    assert journal[-1]["type"] == "run.finished"
    assert journal[-1]["payload"]["status"] == "failed"
    assert not any(event.get("persisted") is False for event in events)
    assert provider.calls == (1 if blocked else 2)


def test_pending_cancel_before_first_frame_uses_the_same_client_identity(
    tmp_path, monkeypatch
):
    from app.core.agent.kernel_agent import KernelAgent
    from app.core.agent.tool_registry import ToolRegistry
    from app.core.tasks.task_ledger import TaskLedger, TaskStatus
    from web.blueprints import chat

    ledger = TaskLedger(db_path=str(tmp_path / "early-stop.db"))
    monkeypatch.setattr(
        import_module("app.core.tasks.task_ledger"), "get_ledger", lambda: ledger
    )
    monkeypatch.setattr(
        import_module("app.core.tasks.progress_bus"),
        "get_progress_bus",
        lambda: SimpleNamespace(publish=lambda _event: None),
    )
    legacy_flags = {}
    monkeypatch.setattr(
        chat,
        "service_registry",
        SimpleNamespace(
            interrupt_manager=SimpleNamespace(
                set_interrupt=lambda session: legacy_flags.update(session=session)
            ),
            interrupt_flags={},
        ),
    )
    provider = SimpleNamespace(
        generate_content=lambda **kwargs: pytest.fail(
            "an early stop must precede every model call"
        )
    )
    agent = KernelAgent(
        provider,
        ToolRegistry(),
        enable_pii_filter=False,
        enable_output_validation=False,
        use_tool_router=False,
        allow_model_fallback=False,
    )
    monkeypatch.setattr(
        import_module("app.core.agent.kernel_agent_service"),
        "get_kernel_agent",
        lambda **kwargs: agent,
    )
    app = Flask(__name__)
    app.register_blueprint(chat.chat_bp)
    stop = app.test_client().post(
        "/api/chat/interrupt",
        json={
            "session": "early-session",
            "task_id": "early-task",
            "run_id": "early-run",
        },
    )
    assert stop.status_code == 202
    assert stop.get_json()["status"] == "pending"
    assert legacy_flags == {"session": "early-session"}
    assert ledger.get("early-task") is None
    with app.test_request_context("/api/chat/stream"):
        response = handle_agent_task(
            "AGENT",
            "early-session",
            "写入结果",
            [],
            "cloud",
            "Kernel",
            None,
            SimpleNamespace(append_and_save=lambda *_args: None),
            app.logger,
            lambda *_args, **_kwargs: pytest.fail(
                "cancelled run must not extract success memory"
            ),
            _sse,
            task_id="early-task",
            run_id="early-run",
        )
        iterator = iter(response.response)
        first = _events(next(iterator))[0]
        assert first["type"] == "run.started"
        assert first["task_id"] == "early-task" and first["run_id"] == "early-run"
        assert ledger.get("early-task") is not None
        following = _events("".join(iterator))
    assert following[-2]["data"]["status"] == "cancelled"
    assert ledger.get("early-task").status is TaskStatus.CANCELLED
    assert (
        ledger.latest_run_event("early-task", "early-run")["payload"]["status"]
        == "cancelled"
    )
