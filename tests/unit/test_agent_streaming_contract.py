"""Offline regressions for incremental text and committed tool effects."""

import json
import threading
from types import SimpleNamespace as NS

import pytest

from app.core.agent.file_task_contract import (
    FileTaskToolStreamChunk,
    FileTaskToolStreamResult,
)
from app.core.agent.file_task_kernel_adapter import _FileTaskToolExecutor
from app.core.agent.file_task_tool_gateway import FileTaskToolGateway
from app.core.agent.kernel import (
    AgentRequest,
    EventType,
    KernelRuntime,
    KernelRuntimeConfig,
    ToolCatalog,
    ToolSpec,
    ValidationOutcome,
)
from app.core.agent.kernel.model import ModelResponse, ModelStreamChunk
from app.core.agent.provider_model_gateway import ProviderModelGateway
from app.core.llm.openai_provider import OpenAIProvider
from web.services.chat_stream.generate._provider_helpers import _stream_from_provider


class SdkStream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    def __iter__(self):
        return iter(self.chunks)

    def close(self):
        self.closed = True


def sdk_chunk(text="", calls=(), finish=None):
    return NS(
        usage=None,
        choices=[
            NS(
                delta=NS(content=text, tool_calls=calls),
                finish_reason=finish,
            )
        ],
    )


def call_piece(index, name=None, arguments=None, call_id=None):
    return NS(index=index, id=call_id, function=NS(name=name, arguments=arguments))


def test_openai_stream_assembles_interleaved_tool_calls_only_at_completion():
    provider = OpenAIProvider.__new__(OpenAIProvider)
    source = SdkStream(
        [
            sdk_chunk("你"),
            sdk_chunk("好"),
            sdk_chunk(calls=[call_piece(0, "read_", '{"path":', "call-a")]),
            sdk_chunk(calls=[call_piece(1, "get_time", "{}", "call-b")]),
            sdk_chunk(calls=[call_piece(0, "text", '"report.txt"}')]),
            sdk_chunk(finish="tool_calls"),
        ]
    )
    stream = provider._stream_generator(source, "fake")
    first = next(stream)
    assert first["delta"] == "你"
    assert first["tool_calls"] == []
    remaining = list(stream)
    assert "".join(x["delta"] for x in [first, *remaining]) == "你好"
    assert remaining[-1]["tool_calls"] == [
        {"id": "call-a", "name": "read_text", "args": {"path": "report.txt"}},
        {"id": "call-b", "name": "get_time", "args": {}},
    ]
    assert remaining[-1]["stream_final"] is True
    assert source.closed


@pytest.mark.parametrize(
    "arguments,finish", [('{"path":', "tool_calls"), ("{}", "length"), ("{}", None)]
)
def test_incomplete_tool_stream_fails_before_it_can_be_executed(arguments, finish):
    provider = OpenAIProvider.__new__(OpenAIProvider)
    stream = SdkStream(
        [
            sdk_chunk(calls=[call_piece(0, "write_file", arguments, "write-a")]),
            sdk_chunk(finish=finish),
        ]
    )
    with pytest.raises((ValueError, RuntimeError)):
        list(provider._stream_generator(stream, "fake"))
    assert stream.closed


def test_regular_chat_consumes_delta_instead_of_repeating_snapshot():
    class Provider:
        def generate_content(self, **kwargs):
            return iter(
                [
                    {"content": "你", "delta": "你"},
                    {"content": "你好", "delta": "好"},
                    {"content": "你好", "delta": "", "stream_final": True},
                ]
            )

    chunks = list(_stream_from_provider(Provider(), "fake", [], ""))
    assert "".join(chunk.text for chunk in chunks) == "你好"


def test_kernel_yields_text_before_model_finishes_or_tool_executes():
    state = {"finished": False, "calls": 0}

    class Provider:
        def generate_content(self, **kwargs):
            assert kwargs["stream"] is True
            if state["calls"]:
                return iter(
                    [{"delta": "done", "content": "done", "stream_final": True}]
                )

            def chunks():
                yield {"delta": "working", "content": "working"}
                state["finished"] = True
                yield {
                    "delta": "",
                    "content": "working",
                    "stream_final": True,
                    "tool_calls": [{"id": "a", "name": "read", "args": {}}],
                }

            return chunks()

    def read():
        assert state["finished"] is True
        state["calls"] += 1
        return "receipt"

    catalog = ToolCatalog()
    catalog.register(
        ToolSpec(
            name="read",
            description="read",
            input_schema={"type": "object"},
            handler=read,
            read_only=True,
        )
    )
    kernel = KernelRuntime(
        gateway=ProviderModelGateway(Provider(), allow_fallback=False), catalog=catalog
    )
    events = kernel.iter_events(AgentRequest(prompt="test"))
    first_text = next(event for event in events if event.type is EventType.STREAM_CHUNK)
    assert first_text.data["delta"] == "working"
    assert state == {"finished": False, "calls": 0}
    rest = list(events)
    assert state["calls"] == 1
    assert (
        next(event for event in rest if event.type is EventType.TASK_COMPLETE).data[
            "result"
        ]
        == "done"
    )


def test_streamed_validation_retry_uses_new_message_and_replaces_provisional_text():
    class Gateway:
        count = 0

        def generate_stream(self, **kwargs):
            self.count += 1
            text = "draft" if self.count == 1 else "accepted"
            yield ModelStreamChunk(delta=text)
            yield ModelStreamChunk(response=ModelResponse(content=text))

    class Validator:
        def validate(self, content, request):
            return (
                ValidationOutcome.retry(content, "repair")
                if content == "draft"
                else ValidationOutcome.accept(content)
            )

    events = list(
        KernelRuntime(
            gateway=Gateway(), catalog=ToolCatalog(), validator=Validator()
        ).iter_events(AgentRequest(prompt="test"))
    )
    finished = [
        event.data for event in events if event.type is EventType.MESSAGE_FINISHED
    ]
    assert [item["status"] for item in finished] == ["retrying", "completed"]
    assert finished[0]["message_id"] != finished[1]["message_id"]
    assert finished[-1]["text"] == "accepted"


def test_file_tool_progress_is_visible_before_tool_stream_finishes():
    state = {"finished": False}

    def chunks():
        yield FileTaskToolStreamChunk(
            kind="event", event_type="step_progress", payload={"detail": "first"}
        )
        state["finished"] = True
        yield FileTaskToolStreamChunk(kind="result", payload={"success": True})

    runtime = NS(
        _repair_tool_args_for_context=lambda name, args, *a, **kw: args,
        _protected_source_write_block_message=lambda *a: "",
    )
    executor = _FileTaskToolExecutor(
        NS(execute=lambda *a: FileTaskToolStreamResult(chunks())),
        runtime=runtime,
        request=NS(),
        context_files=[],
        generated_artifacts=[],
    )
    from app.core.agent.kernel import ToolCall, ToolResult

    stream = executor.iter_invoke(ToolCall(name="read", arguments={}, call_id="a"))
    first = next(stream)
    assert first.type is EventType.TOOL_PROGRESS
    assert state["finished"] is False
    result = list(stream)[-1]
    assert isinstance(result, ToolResult) and result.ok


def test_streamed_file_transaction_rolls_back_if_consumer_closes(tmp_path):
    path = tmp_path / "draft.docx"
    path.write_bytes(b"original")

    def executor(name, args):
        def chunks():
            path.write_bytes(b"partial")
            yield FileTaskToolStreamChunk(
                kind="event", event_type="step_progress", payload={}
            )
            path.write_bytes(b"complete")
            yield FileTaskToolStreamChunk(kind="result", payload={"success": True})

        return FileTaskToolStreamResult(chunks())

    gateway = FileTaskToolGateway(tool_executor=executor)
    result = gateway.execute(
        "write_docx_content", {"path": str(path), "paragraphs": "[]"}
    )
    assert path.read_bytes() == b"original"
    stream = iter(result.chunks)
    next(stream)
    assert path.read_bytes() == b"partial"
    stream.close()
    assert path.read_bytes() == b"original"


def test_cancellation_closes_model_stream_and_does_not_execute_pending_tool():
    state = {"cancel": False, "closed": False, "executed": False}
    checkpoints = []

    class Gateway:
        def generate_stream(self, **kwargs):
            try:
                yield ModelStreamChunk(delta="first")
                yield ModelStreamChunk(
                    response=ModelResponse.from_raw(
                        {
                            "tool_calls": [{"name": "write", "args": {}}],
                        }
                    )
                )
            finally:
                state["closed"] = True

    catalog = ToolCatalog()
    catalog.register(
        ToolSpec(
            name="write",
            description="write",
            input_schema={"type": "object"},
            handler=lambda: state.update(executed=True),
            read_only=False,
        )
    )
    stream = KernelRuntime(gateway=Gateway(), catalog=catalog).iter_events(
        AgentRequest(prompt="test"),
        cancel_check=lambda: state["cancel"],
        config=KernelRuntimeConfig(checkpoint_callback=checkpoints.append),
    )
    next(event for event in stream if event.type is EventType.STREAM_CHUNK)
    state["cancel"] = True
    rest = list(stream)
    assert state["closed"] and not state["executed"]
    assert rest[-1].data["state"] == "cancelled"
    assert checkpoints[-1]["phase"] == "cancelled"


def test_checkpoint_records_committed_receipt_before_publishing_tool_result():
    checkpoints = []
    executions = []

    class Gateway:
        calls = 0

        def generate(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"tool_calls": [{"id": "read-a", "name": "read", "args": {}}]}
            return {"content": "done"}

    def handler():
        assert checkpoints[-1]["phase"] == "tool_pending"
        executions.append("read")
        return "durable receipt"

    catalog = ToolCatalog()
    catalog.register(
        ToolSpec(
            name="read",
            description="read",
            input_schema={"type": "object"},
            handler=handler,
            read_only=True,
        )
    )
    kernel = KernelRuntime(gateway=Gateway(), catalog=catalog)
    events = kernel.iter_events(
        AgentRequest(prompt="test"),
        config=KernelRuntimeConfig(checkpoint_callback=checkpoints.append),
    )
    next(event for event in events if event.type is EventType.TOOL_RESULT)
    checkpoint = checkpoints[-1]
    assert checkpoint["phase"] == "tool_complete"
    assert checkpoint["messages"][-1]["role"] == "tool"
    assert checkpoint["pending_tool_calls"] == []
    events.close()
    resumed = list(
        KernelRuntime(
            gateway=NS(generate=lambda **kw: {"content": "resumed"}), catalog=catalog
        ).iter_events(
            AgentRequest(prompt="test"),
            config=KernelRuntimeConfig(resume_state=checkpoint),
        )
    )
    assert executions == ["read"]
    assert (
        next(event for event in resumed if event.type is EventType.TASK_COMPLETE).data[
            "result"
        ]
        == "resumed"
    )


def test_resume_rejects_unknown_write_outcome_without_touching_model_or_tool():
    gateway = NS(generate=lambda **kw: pytest.fail("must not call model"))
    events = list(
        KernelRuntime(gateway=gateway, catalog=ToolCatalog()).iter_events(
            AgentRequest(prompt="test"),
            config=KernelRuntimeConfig(
                resume_state={
                    "phase": "tool_pending",
                    "messages": [{"role": "user", "content": "test"}],
                    "pending_tool_calls": [
                        {
                            "id": "write-a",
                            "name": "write",
                            "args": {},
                            "read_only": False,
                        }
                    ],
                }
            ),
        )
    )
    assert events[-1].data["state"] == "failed"
    assert (
        "unknown write outcome"
        in next(
            event for event in events if event.type is EventType.TASK_COMPLETE
        ).data["error"]
    )


def test_agent_stream_persists_checkpoint_and_releases_execution_lease(
    tmp_path, monkeypatch
):
    from app.core.agent.kernel_agent import KernelAgent
    from app.core.tasks import task_ledger

    ledger = task_ledger.TaskLedger(db_path=str(tmp_path / "tasks.sqlite"))
    monkeypatch.setattr(task_ledger, "get_ledger", lambda: ledger)

    class Provider:
        def generate_content(self, **kwargs):
            return iter(
                [
                    {"delta": "你好", "content": "你好"},
                    {"delta": "", "content": "你好", "stream_final": True},
                ]
            )

    agent = KernelAgent(
        Provider(),
        enable_pii_filter=False,
        enable_output_validation=False,
        use_tool_router=False,
        allow_model_fallback=False,
    )
    steps = list(agent.run("test", stream_events=True))
    first = steps[0].metadata
    checkpoint = ledger.get_kernel_checkpoint(first["task_id"], first["run_id"])
    assert checkpoint["phase"] == "completed"
    assert checkpoint["state"]["terminal_result"] == "你好"
    assert not checkpoint["resumable"]
    assert checkpoint["owner_id"] is None
    assert steps[-1].step_type.value == "answer"


def test_native_openai_cancellation_closes_blocked_sdk_stream_before_terminal():
    state = {"cancel": False}

    class BlockingStream(SdkStream):
        def __init__(self):
            super().__init__([])
            self.close_event = threading.Event()

        def __iter__(self):
            yield sdk_chunk("first")
            assert self.close_event.wait(
                3
            ), "cancellation must close the real SDK response"
            raise RuntimeError("socket closed")

        def close(self):
            self.closed = True
            self.close_event.set()

    native = BlockingStream()
    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider.client = NS(
        base_url="https://example.invalid",
        chat=NS(completions=NS(create=lambda **kw: native)),
    )
    events = KernelRuntime(
        gateway=ProviderModelGateway(provider, allow_fallback=False),
        catalog=ToolCatalog(),
    ).iter_events(
        AgentRequest(prompt="test"),
        cancel_check=lambda: state["cancel"],
    )
    next(event for event in events if event.type is EventType.STREAM_CHUNK)
    state["cancel"] = True
    rest = list(events)
    assert native.closed
    assert rest[-1].data["state"] == "cancelled"


def test_sdk_timeout_is_honored_and_budget_options_never_reach_sdk():
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        raise TimeoutError("test network read timeout")

    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider.client = NS(
        base_url="https://example.invalid", chat=NS(completions=NS(create=create))
    )
    gateway = ProviderModelGateway(provider, allow_fallback=False)
    with pytest.raises(TimeoutError):
        list(
            gateway.generate_stream(
                messages=[],
                system="",
                tools=[],
                model_id="fake",
                options={
                    "call_timeout": 0.25,
                    "context_window_tokens": 8192,
                    "context_window": 8192,
                    "reserved_output_tokens": 512,
                },
            )
        )
    assert calls[0]["timeout"] == 0.25
    assert not (
        {"context_window", "context_window_tokens", "reserved_output_tokens"}
        & calls[0].keys()
    )


def test_ollama_pure_text_uses_native_incremental_stream(monkeypatch):
    from app.core.llm import ollama_llm_provider as module

    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            for piece in ("你", "好"):
                yield (
                    json.dumps({"message": {"content": piece}, "done": False}) + "\n"
                ).encode()
            yield b'{"done":true}\n'

        def close(self):
            pass

    def open_response(req, **kwargs):
        requests.append(json.loads(req.data))
        return Response()

    monkeypatch.setattr(
        module.urllib.request, "build_opener", lambda *args: NS(open=open_response)
    )
    provider = module.OllamaLLMProvider.__new__(module.OllamaLLMProvider)
    provider.base_url = "http://127.0.0.1:11434"
    provider._options = {}
    kernel = KernelRuntime(
        gateway=ProviderModelGateway(provider, allow_fallback=False),
        catalog=ToolCatalog(),
    )
    events = list(
        kernel.iter_events(
            AgentRequest(prompt="test"),
            config=KernelRuntimeConfig(
                model_id="qwen3",
                options={"num_ctx": 4096, "num_predict": 512},
            ),
        )
    )
    assert [
        event.data["delta"] for event in events if event.type is EventType.STREAM_CHUNK
    ] == ["你", "好"]
    assert (
        next(event for event in events if event.type is EventType.TASK_COMPLETE).data[
            "result"
        ]
        == "你好"
    )
    assert requests[0]["options"]["num_ctx"] == 4096


@pytest.mark.parametrize("override", ["call", "_call_native"])
def test_file_model_gateway_preserves_explicit_client_injection(monkeypatch, override):
    from app.core.agent.file_task_contract import FileTaskRequest
    from app.core.agent.file_task_model import FileTaskModelClient

    client = FileTaskModelClient()
    calls = []

    def injected(**kwargs):
        calls.append(kwargs)
        return {"content": "injected", "tool_calls": []}

    monkeypatch.setattr(client, override, injected)
    gateway = client.for_request(FileTaskRequest(task="test"))
    assert gateway.generate(messages=[], system="", tools=[]).content == "injected"
    chunks = list(gateway.generate_stream(messages=[], system="", tools=[]))
    assert chunks[-1].response.content == "injected"
    assert len(calls) == 2


@pytest.mark.parametrize("mode", ["blocked", "exhausted"])
def test_validation_rejection_never_completes_ledger_or_checkpoint(
    tmp_path, monkeypatch, mode
):
    from app.core.agent import kernel_agent as module
    from app.core.tasks import task_ledger

    ledger = task_ledger.TaskLedger(db_path=str(tmp_path / "validation.sqlite"))
    monkeypatch.setattr(task_ledger, "get_ledger", lambda: ledger)

    class Validator:
        def validate(self, content, request):
            if mode == "blocked":
                return ValidationOutcome.block(
                    "当前结果未通过校验。", reasons=("blocked evidence",)
                )
            return ValidationOutcome.retry(
                "当前结果未通过校验。", "请修正", reasons=("missing evidence",)
            )

    monkeypatch.setattr(module, "KotoOutputValidator", Validator)

    class Provider:
        def generate_content(self, **kwargs):
            return iter(
                [
                    {"delta": "draft", "content": "draft"},
                    {"delta": "", "content": "draft", "stream_final": True},
                ]
            )

    agent = module.KernelAgent(
        Provider(),
        enable_pii_filter=False,
        use_tool_router=False,
        allow_model_fallback=False,
    )
    steps = list(agent.run("test", stream_events=True))
    identity = steps[0].metadata
    task = ledger.get(identity["task_id"])
    checkpoint = ledger.get_kernel_checkpoint(identity["task_id"], identity["run_id"])
    assert task.status.value == "failed"
    assert checkpoint["phase"] == "failed" and not checkpoint["resumable"]
    expected = (
        "当前结果未通过校验。"
        if mode == "blocked"
        else "输出未通过验收，自动修正未能完成。请调整要求后重试。"
    )
    assert checkpoint["state"]["terminal_result"] == expected
    assert steps[-1].step_type.value == "error"
    assert not any(step.step_type.value == "answer" for step in steps)
    finished = [
        step.metadata
        for step in steps
        if step.metadata.get("event_type") == "message.finished"
    ]
    assert finished[-1]["status"] == ("blocked" if mode == "blocked" else "failed")
    from app.core.agent import kernel_agent_service

    monkeypatch.setattr(kernel_agent_service, "get_kernel_agent", lambda: agent)
    collected = kernel_agent_service.run_kernel_agent_collect("test", record_task=False)
    assert collected["status"] == "failed" and collected["error"]
    assert collected["answer"] == collected["result"] == expected
    restored = list(
        KernelRuntime(
            gateway=NS(
                generate=lambda **kw: pytest.fail(
                    "failed checkpoint cannot run a model"
                )
            ),
            catalog=ToolCatalog(),
        ).iter_events(
            AgentRequest(prompt="test"),
            config=KernelRuntimeConfig(resume_state=checkpoint["state"]),
        )
    )
    assert restored[-1].data["state"] == "failed"
    assert next(
        event for event in restored if event.type is EventType.TASK_COMPLETE
    ).data["error"]
