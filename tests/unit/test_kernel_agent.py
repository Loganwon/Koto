from __future__ import annotations

from app.core.agent.kernel_agent import KernelAgent
from app.core.agent.tool_registry import ToolRegistry
from app.core.agent.types import AgentStepType


class _RecordedProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def test_kernel_agent_preserves_agent_step_api_without_owning_another_loop() -> None:
    provider = _RecordedProvider(
        [
            {
                "content": "先读取。",
                "tool_calls": [
                    {"id": "call-1", "name": "read_text", "args": {"path": "a"}}
                ],
            },
            {"content": "内容是 hello", "tool_calls": []},
        ]
    )
    registry = ToolRegistry()
    registry.register_tool(
        "read_text",
        lambda path: "hello",
        description="Read text",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        read_only=True,
    )
    agent = KernelAgent(
        llm_provider=provider,
        tool_registry=registry,
        model_id="test-model",
        enable_pii_filter=False,
        enable_output_validation=False,
        use_tool_router=False,
        allow_model_fallback=False,
    )

    steps = list(agent.run("读取 a", record_task=False))

    assert [step.step_type for step in steps] == [
        AgentStepType.THOUGHT,
        AgentStepType.ACTION,
        AgentStepType.OBSERVATION,
        AgentStepType.ANSWER,
    ]
    assert steps[-1].content == "内容是 hello"
    assert steps[-1].metadata["runtime"] == "kernel"
    assert "写入后必须重新读取" in provider.calls[0]["system_instruction"]
    assert provider.calls[1]["prompt"][-1]["role"] == "tool"


def test_kernel_agent_record_task_false_does_not_touch_ledger(monkeypatch) -> None:
    provider = _RecordedProvider([{"content": "ok", "tool_calls": []}])
    agent = KernelAgent(
        llm_provider=provider,
        enable_pii_filter=False,
        enable_output_validation=False,
        use_tool_router=False,
        allow_model_fallback=False,
    )

    import app.core.tasks.task_ledger as ledger_module

    monkeypatch.setattr(
        ledger_module,
        "get_ledger",
        lambda: (_ for _ in ()).throw(AssertionError("ledger must not be used")),
    )

    steps = list(agent.run("hello", record_task=False))

    assert steps[-1].step_type is AgentStepType.ANSWER


def test_kernel_agent_merges_planned_addon_tools_into_router_selection() -> None:
    provider = _RecordedProvider([{"content": "ok", "tool_calls": []}])
    registry = ToolRegistry()
    registry.register_tool("core_tool", lambda: "core", read_only=True)
    registry.register_tool("legal_lookup", lambda: "legal", read_only=True)
    agent = KernelAgent(
        llm_provider=provider,
        tool_registry=registry,
        enable_pii_filter=False,
        enable_output_validation=False,
        use_tool_router=False,
        allow_model_fallback=False,
    )
    agent._tool_router = type(
        "OnlyCoreRouter",
        (),
        {"select": lambda self, definitions, user_input: [definitions[0]]},
    )()

    steps = list(
        agent.run(
            "核对合同",
            addon_tool_names=("legal_lookup",),
            addon_plan={
                "addon_ids": ["com.bank.legal"],
                "capabilities": ["legal.lookup"],
            },
            record_task=False,
        )
    )

    sent_tools = {item["name"] for item in provider.calls[0]["tools"]}
    assert sent_tools == {"core_tool", "legal_lookup"}
    assert "本轮 Add-on 能力边界" in provider.calls[0]["system_instruction"]
    assert steps[-1].step_type is AgentStepType.ANSWER
