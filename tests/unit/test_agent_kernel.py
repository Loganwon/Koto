from __future__ import annotations

import time

import pytest

from app.core.agent.kernel import (
    AgentEvent,
    AgentRequest,
    AgentRunLimits,
    EventType,
    KernelRuntime,
    KernelRuntimeConfig,
    ModelProtocolError,
    ModelResponse,
    RunGuard,
    RunLimitExceeded,
    RunState,
    ToolCall,
    ToolCatalog,
    ToolErrorCode,
    ToolExecutionPolicy,
    ToolExecutor,
    ToolRegistrationError,
    ToolSpec,
    ValidationOutcome,
    build_tool_usage_instruction,
    runtime_mermaid,
    runtime_topology,
)


def _spec(name: str, handler=lambda: "ok") -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"{name} description",
        input_schema={"type": "object", "properties": {}},
        handler=handler,
    )


def test_catalog_registration_is_atomic() -> None:
    catalog = ToolCatalog()
    catalog.register(_spec("existing"))

    with pytest.raises(ToolRegistrationError):
        catalog.register_many([_spec("new_tool"), _spec("existing")])

    assert catalog.names() == ["existing"]


def test_catalog_definitions_are_defensive_copies() -> None:
    catalog = ToolCatalog()
    catalog.register(_spec("reader"))

    first = catalog.definitions()
    first[0]["parameters"]["properties"]["injected"] = {"type": "string"}

    assert "injected" not in catalog.definitions()[0]["parameters"]["properties"]


def test_executor_returns_structured_success_and_failure() -> None:
    catalog = ToolCatalog()
    catalog.register(
        ToolSpec(
            name="double",
            description="Double a number",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
            },
            handler=lambda value: value * 2,
        )
    )
    executor = ToolExecutor(catalog)

    success = executor.invoke(
        ToolCall(name="double", arguments={"value": 3}, call_id="call-1")
    )
    missing = executor.invoke(ToolCall(name="missing", call_id="call-2"))

    assert success.ok is True
    assert success.value == 6
    assert success.to_payload()["call_id"] == "call-1"
    assert missing.ok is False
    assert missing.error_code is ToolErrorCode.NOT_FOUND


def test_executor_injects_trusted_context_outside_model_arguments() -> None:
    seen = []
    denials = []

    class TrustedContext:
        tenant_id = "tenant-a"
        principal_id = "employee-7"
        purpose_code = "customer_service"

        def require_identity(self):
            return None

    def governed(*, invocation_context, query):
        seen.append((invocation_context.tenant_id, query))
        return "ok"

    catalog = ToolCatalog()
    catalog.register(
        ToolSpec(
            name="governed_lookup",
            description="Governed lookup",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=governed,
            read_only=True,
            requires_invocation_context=True,
            policy_denied_handler=lambda reason, context: denials.append(reason),
        )
    )
    executor = ToolExecutor(catalog)

    missing = executor.invoke(ToolCall("governed_lookup", {"query": "customer"}))
    forged = executor.invoke(
        ToolCall(
            "governed_lookup",
            {
                "query": "customer",
                "invocation_context": {"tenant_id": "attacker"},
            },
        ),
        invocation_context=TrustedContext(),
    )
    allowed = executor.invoke(
        ToolCall("governed_lookup", {"query": "customer"}),
        invocation_context=TrustedContext(),
    )

    assert missing.error_code is ToolErrorCode.POLICY_DENIED
    assert forged.error_code is ToolErrorCode.POLICY_DENIED
    assert allowed.ok is True
    assert seen == [("tenant-a", "customer")]
    assert denials == ["trusted_context_missing", "model_context_injection"]


def test_tool_contract_reserves_invocation_context_from_model_schema() -> None:
    with pytest.raises(ValueError, match="reserved argument"):
        ToolSpec(
            name="unsafe_context_tool",
            description="Unsafe context tool",
            input_schema={
                "type": "object",
                "properties": {"invocation_context": {"type": "object"}},
            },
            handler=lambda invocation_context: None,
        )


def test_tool_contract_normalizes_legacy_schema_and_executor_validates_it() -> None:
    catalog = ToolCatalog()
    catalog.register(
        ToolSpec(
            name="typed_tool",
            description="Typed tool",
            input_schema={
                "type": "OBJECT",
                "properties": {"count": {"type": "INTEGER"}},
                "required": ["count"],
                "additionalProperties": False,
            },
            handler=lambda count: count,
        )
    )
    executor = ToolExecutor(catalog)

    missing = executor.invoke(ToolCall(name="typed_tool", arguments={}))
    wrong_type = executor.invoke(
        ToolCall(name="typed_tool", arguments={"count": "two"})
    )
    valid = executor.invoke(ToolCall(name="typed_tool", arguments={"count": 2}))

    assert catalog.require("typed_tool").input_schema["type"] == "object"
    assert missing.error_code is ToolErrorCode.INVALID_ARGUMENTS
    assert wrong_type.error_code is ToolErrorCode.INVALID_ARGUMENTS
    assert valid.ok is True
    assert valid.value == 2


def test_executor_enforces_timeout_as_structured_error() -> None:
    catalog = ToolCatalog()

    def slow() -> None:
        time.sleep(0.2)

    catalog.register(_spec("slow", slow))
    executor = ToolExecutor(catalog, ToolExecutionPolicy(default_timeout_seconds=0.01))

    result = executor.invoke(ToolCall(name="slow"))

    assert result.ok is False
    assert result.error_code is ToolErrorCode.TIMEOUT


def test_run_guard_blocks_repeated_batches_and_total_calls() -> None:
    guard = RunGuard(
        AgentRunLimits(
            max_steps=3,
            max_tool_calls=4,
            max_repeated_batches=0,
            max_seconds=10,
        )
    )
    call = ToolCall(name="reader", arguments={"path": "a.docx"})

    guard.begin_step()
    guard.accept_tool_batch([call])
    with pytest.raises(RunLimitExceeded, match="repeated"):
        guard.accept_tool_batch([call])


def test_fixed_tool_instruction_requires_read_write_verify_contract() -> None:
    instruction = build_tool_usage_instruction(
        [{"name": "read_docx"}, {"name": "write_docx"}]
    )

    assert "写入后必须重新读取" in instruction
    assert "tool_gap" in instruction
    assert "read_docx, write_docx" in instruction


def test_legacy_registry_exposes_structured_kernel_result() -> None:
    from app.core.agent.tool_registry import ToolRegistry

    registry = ToolRegistry()
    registry.register_tool("echo", lambda text: text, description="Echo text")

    result = registry.execute_result("echo", {"text": "hello"}, call_id="legacy-call")

    assert result.ok is True
    assert result.value == "hello"
    assert result.call_id == "legacy-call"


def test_kernel_runtime_topology_is_available_for_dev_visualization() -> None:
    topology = runtime_topology()
    mermaid = runtime_mermaid()

    assert {node["id"] for node in topology["nodes"]} >= {
        "model",
        "guard",
        "tools",
        "execute",
        "validate",
    }
    assert mermaid.startswith("flowchart LR")
    assert 'execute -->|"structured result"| model' in mermaid


def test_kernel_owns_transport_neutral_lifecycle_contract() -> None:
    request = AgentRequest(prompt="test", session_id="session")
    event = AgentEvent(EventType.THOUGHT, {"text": "working"})

    assert request.prompt == "test"
    assert event.type is EventType.THOUGHT


def test_model_response_normalizes_provider_tool_call_shapes() -> None:
    response = ModelResponse.from_raw(
        {
            "content": "working",
            "tool_calls": [
                {
                    "id": "call-1",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path": "report.docx"}',
                    },
                }
            ],
            "_raw_parts": [{"thought_signature": "sig"}],
            "provider_trace_id": "trace-1",
        }
    )

    assert response.content == "working"
    assert response.legacy_tool_calls() == [
        {
            "id": "call-1",
            "name": "read_file",
            "args": {"path": "report.docx"},
        }
    ]
    assert response.raw_parts == ({"thought_signature": "sig"},)
    assert response.metadata["provider_trace_id"] == "trace-1"


def test_model_response_rejects_malformed_tool_arguments_in_strict_mode() -> None:
    with pytest.raises(ModelProtocolError, match="valid JSON"):
        ModelResponse.from_raw(
            {"tool_calls": [{"name": "read_file", "arguments": "{not-json}"}]}
        )


class _RecordedGateway:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def test_kernel_runtime_runs_one_fixed_tool_loop_and_emits_canonical_events() -> None:
    gateway = _RecordedGateway(
        [
            {
                "content": "先读取文件。",
                "tool_calls": [{"name": "read_file", "args": {"path": "report.txt"}}],
            },
            {"content": "文件内容是：hello"},
        ]
    )
    catalog = ToolCatalog()
    catalog.register(
        ToolSpec(
            name="read_file",
            description="Read a text file",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            handler=lambda path: "hello",
        )
    )
    catalog.register(_spec("hidden_tool"))
    runtime = KernelRuntime(gateway=gateway, catalog=catalog)

    events = list(
        runtime.iter_events(
            AgentRequest(prompt="读取报告", session_id="session-1"),
            config=KernelRuntimeConfig(
                system_instruction="You are helpful.",
                tool_allowlist=("read_file",),
            ),
        )
    )

    measurements = [
        event for event in events if event.data.get("event_type") == "model.metrics"
    ]
    assert len(measurements) == len(gateway.calls) == 2
    assert all(event.data["status"] == "completed" for event in measurements)
    assert all(
        event.data["usage"]["provider_reported"] is False for event in measurements
    )
    assert [
        event.type
        for event in events
        if event.data.get("event_type") != "model.metrics"
    ] == [
        EventType.LIFECYCLE_START,
        EventType.STREAM_BLOCK,
        EventType.TOOL_CALL,
        EventType.TOOL_RESULT,
        EventType.STREAM_BLOCK,
        EventType.TASK_COMPLETE,
        EventType.LIFECYCLE_END,
    ]
    assert [tool["name"] for tool in gateway.calls[0]["tools"]] == ["read_file"]
    assert "写入后必须重新读取" in gateway.calls[0]["system"]
    tool_message = gateway.calls[1]["messages"][-1]
    assert tool_message["role"] == "tool"
    assert '"ok":true' in tool_message["content"]
    assert events[-1].data["state"] == RunState.SUCCEEDED.value


def test_kernel_runtime_stops_repeated_identical_tool_batches() -> None:
    repeated = {"tool_calls": [{"name": "reader", "args": {"path": "a"}}]}
    gateway = _RecordedGateway([repeated, repeated])
    catalog = ToolCatalog()
    executions = []
    catalog.register(_spec("reader", lambda path: executions.append(path) or "ok"))
    runtime = KernelRuntime(
        gateway=gateway,
        catalog=catalog,
        limits=AgentRunLimits(
            max_steps=3,
            max_tool_calls=3,
            max_repeated_batches=0,
            max_seconds=10,
        ),
    )

    events = list(runtime.iter_events(AgentRequest(prompt="loop")))

    assert executions == ["a"]
    assert any(
        event.type is EventType.LIFECYCLE_ERROR
        and "repeated identical tool batch" in event.data["error"]
        for event in events
    )


def test_kernel_runtime_rejects_unknown_allowlisted_tools_before_model_call() -> None:
    gateway = _RecordedGateway([{"content": "unused"}])
    runtime = KernelRuntime(gateway=gateway, catalog=ToolCatalog())

    events = list(
        runtime.iter_events(
            AgentRequest(prompt="test"),
            config=KernelRuntimeConfig(tool_allowlist=("missing",)),
        )
    )

    assert gateway.calls == []
    assert events[1].type is EventType.LIFECYCLE_ERROR
    assert "unknown tools: missing" in events[1].data["error"]
    assert events[-1].data["state"] == RunState.FAILED.value


def test_kernel_runtime_never_executes_a_model_call_outside_run_allowlist() -> None:
    gateway = _RecordedGateway(
        [
            {"tool_calls": [{"name": "hidden_tool", "args": {}}]},
            {"content": "已改用允许的能力。"},
        ]
    )
    executions = []
    catalog = ToolCatalog()
    catalog.register(_spec("visible_tool"))
    catalog.register(
        _spec("hidden_tool", lambda: executions.append("hidden") or "unsafe")
    )
    runtime = KernelRuntime(gateway=gateway, catalog=catalog)

    events = list(
        runtime.iter_events(
            AgentRequest(prompt="test"),
            config=KernelRuntimeConfig(tool_allowlist=("visible_tool",)),
        )
    )

    assert executions == []
    denied = next(event for event in events if event.type is EventType.TOOL_RESULT)
    assert denied.data["result"]["ok"] is False
    assert denied.data["result"]["error"]["code"] == "policy_denied"


def test_kernel_runtime_honors_cancellation_before_model_or_tool_work() -> None:
    gateway = _RecordedGateway([{"content": "unused"}])
    runtime = KernelRuntime(gateway=gateway, catalog=ToolCatalog())

    events = list(
        runtime.iter_events(
            AgentRequest(prompt="cancel"),
            cancel_check=lambda: True,
        )
    )

    assert gateway.calls == []
    assert [event.type for event in events] == [
        EventType.LIFECYCLE_START,
        EventType.TASK_COMPLETE,
        EventType.LIFECYCLE_END,
    ]
    assert events[-1].data["state"] == RunState.CANCELLED.value


class _RetryOnceValidator:
    def __init__(self):
        self.calls = 0

    def validate(self, content, request):
        self.calls += 1
        if self.calls == 1:
            return ValidationOutcome.retry(
                content,
                "请补充最终结论。",
                reasons=("missing conclusion",),
            )
        return ValidationOutcome.accept(content)


def test_kernel_runtime_owns_validation_repair_loop() -> None:
    gateway = _RecordedGateway(
        [
            {"content": "分析过程"},
            {"content": "最终结论"},
        ]
    )
    validator = _RetryOnceValidator()
    runtime = KernelRuntime(
        gateway=gateway,
        catalog=ToolCatalog(),
        validator=validator,
    )

    events = list(runtime.iter_events(AgentRequest(prompt="分析")))

    assert validator.calls == 2
    assert gateway.calls[1]["messages"][-1] == {
        "role": "user",
        "content": "请补充最终结论。",
    }
    assert any(
        event.type is EventType.VALIDATION and event.data["retrying"]
        for event in events
    )
    assert (
        next(
            event.data["result"]
            for event in events
            if event.type is EventType.TASK_COMPLETE
        )
        == "最终结论"
    )


def test_kernel_runtime_emits_complete_parallel_tool_batch_in_call_order() -> None:
    gateway = _RecordedGateway(
        [
            {
                "tool_calls": [
                    {"id": "a", "name": "first", "args": {}},
                    {"id": "b", "name": "second", "args": {}},
                ]
            },
            {"content": "done"},
        ]
    )
    catalog = ToolCatalog()
    catalog.register(_spec("first", lambda: "one"))
    catalog.register(_spec("second", lambda: "two"))
    runtime = KernelRuntime(gateway=gateway, catalog=catalog)

    events = list(runtime.iter_events(AgentRequest(prompt="run both")))
    batch_events = [
        event
        for event in events
        if event.type in {EventType.TOOL_CALL, EventType.TOOL_RESULT}
    ]

    assert [event.type for event in batch_events] == [
        EventType.TOOL_CALL,
        EventType.TOOL_CALL,
        EventType.TOOL_RESULT,
        EventType.TOOL_RESULT,
    ]
    assert [
        event.data.get("tool_call", {}).get("name") or event.data.get("tool_name")
        for event in batch_events
    ] == ["first", "second", "first", "second"]


def test_executor_parallelizes_only_explicitly_read_only_tools() -> None:
    catalog = ToolCatalog()
    active = 0
    overlapped = False

    def _read() -> str:
        nonlocal active, overlapped
        active += 1
        try:
            if active > 1:
                overlapped = True
            time.sleep(0.03)
            return "ok"
        finally:
            active -= 1

    for name in ("read_a", "read_b"):
        catalog.register(
            ToolSpec(
                name=name,
                description="read",
                input_schema={"type": "object", "properties": {}},
                handler=_read,
                read_only=True,
            )
        )

    ToolExecutor(catalog).invoke_many(
        [ToolCall(name="read_a"), ToolCall(name="read_b")],
        max_workers=2,
    )

    assert overlapped is True


def test_executor_serializes_batches_containing_a_mutating_tool() -> None:
    catalog = ToolCatalog()
    execution_order = []

    def _handler(name: str) -> str:
        execution_order.append(f"{name}:start")
        time.sleep(0.01)
        execution_order.append(f"{name}:end")
        return name

    catalog.register(
        ToolSpec(
            name="read_data",
            description="read",
            input_schema={"type": "object", "properties": {}},
            handler=lambda: _handler("read"),
            read_only=True,
        )
    )
    catalog.register(
        ToolSpec(
            name="write_data",
            description="write",
            input_schema={"type": "object", "properties": {}},
            handler=lambda: _handler("write"),
            read_only=False,
        )
    )

    ToolExecutor(catalog).invoke_many(
        [ToolCall(name="read_data"), ToolCall(name="write_data")],
        max_workers=2,
    )

    assert execution_order == [
        "read:start",
        "read:end",
        "write:start",
        "write:end",
    ]
