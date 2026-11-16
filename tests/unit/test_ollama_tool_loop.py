"""Offline native Ollama requests must preserve the Kernel tool conversation."""

import json
from pathlib import Path

import pytest

from app.core.agent.kernel import (
    AgentRequest,
    EventType,
    KernelRuntime,
    ToolCatalog,
    ToolSpec,
)
from app.core.agent.provider_model_gateway import ProviderModelGateway
from app.core.llm import ollama_llm_provider as native


def test_kernel_native_second_request_contains_actual_tool_receipt(
    tmp_path, monkeypatch
):
    path = tmp_path / "report.txt"
    path.write_text("真实读取回执", encoding="utf-8")
    requests = []
    executions = []

    def post(url, payload, **kwargs):
        requests.append(payload)
        if len(requests) == 1:
            return {
                "message": {
                    "role": "assistant",
                    "content": "读取文件",
                    "tool_calls": [
                        {
                            "id": "native-read-1",
                            "type": "function",
                            "function": {
                                "name": "read_text",
                                "arguments": json.dumps({"path": str(path)}),
                            },
                        }
                    ],
                }
            }
        receipts = [
            message for message in payload["messages"] if message["role"] == "tool"
        ]
        assert len(receipts) == 1
        receipt = receipts[0]
        assert receipt["tool_call_id"] == "native-read-1"
        assert receipt["name"] == receipt["tool_name"] == "read_text"
        assert json.loads(receipt["content"])["value"] == {"text": "真实读取回执"}
        assistant = next(
            message for message in payload["messages"] if message.get("tool_calls")
        )
        assert assistant["tool_calls"][0]["function"] == {
            "name": "read_text",
            "arguments": {"path": str(path)},
        }
        return {"message": {"content": "已核对真实回执"}}

    monkeypatch.setattr(native, "_raw_post", post)

    def read_text(path):
        executions.append(path)
        return {"text": Path(path).read_text(encoding="utf-8")}

    catalog = ToolCatalog()
    catalog.register(
        ToolSpec(
            name="read_text",
            description="read",
            read_only=True,
            handler=read_text,
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        )
    )
    provider = native.OllamaLLMProvider(
        model="arbitrary", num_ctx=8192, num_predict=512
    )
    events = list(
        KernelRuntime(
            gateway=ProviderModelGateway(provider, allow_fallback=False),
            catalog=catalog,
        ).iter_events(
            AgentRequest(prompt="读取报告"),
        )
    )
    assert len(requests) == 2 and executions == [str(path)]
    assert (
        next(event for event in events if event.type is EventType.TASK_COMPLETE).data[
            "result"
        ]
        == "已核对真实回执"
    )
    assert events[-1].data["state"] == "succeeded"


def test_native_history_accepts_openai_function_shape_and_legacy_results():
    messages = native._to_ollama_messages(
        [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "search",
                            "arguments": '{"query":"报告"}',
                        },
                    }
                ],
            },
            {"role": "function", "name": "search", "content": "找到文件"},
        ],
        None,
    )
    assert messages[0]["tool_calls"][0]["function"] == {
        "name": "search",
        "arguments": {"query": "报告"},
    }
    assert messages[1] == {
        "role": "tool",
        "content": "找到文件",
        "tool_call_id": "call-1",
        "name": "search",
        "tool_name": "search",
    }


def test_native_tool_declarations_preserve_openai_nested_schema():
    declaration = {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Read one file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    }
    assert native._to_ollama_tools([declaration]) == [declaration]


@pytest.mark.parametrize("arguments", ['{"path":', "[]"])
def test_malformed_native_arguments_are_rejected_without_executing_tool(
    monkeypatch, arguments
):
    executions = []
    monkeypatch.setattr(
        native,
        "_raw_post",
        lambda *a, **kw: {
            "message": {
                "tool_calls": [
                    {
                        "function": {"name": "write", "arguments": arguments},
                    }
                ]
            }
        },
    )
    catalog = ToolCatalog()
    catalog.register(
        ToolSpec(
            name="write",
            description="write",
            read_only=False,
            handler=lambda **kwargs: executions.append(kwargs),
            input_schema={"type": "object"},
        )
    )
    provider = native.OllamaLLMProvider(model="arbitrary", num_predict=512)
    events = list(
        KernelRuntime(
            gateway=ProviderModelGateway(provider, allow_fallback=False),
            catalog=catalog,
        ).iter_events(AgentRequest(prompt="write"))
    )
    assert executions == []
    assert events[-1].data["state"] == "failed"


def test_native_tool_role_preserves_structured_content_and_identity():
    message = native._to_ollama_messages(
        [
            {
                "role": "tool",
                "name": "read",
                "tool_call_id": "a",
                "content": {"text": "原文"},
            }
        ],
        None,
    )[0]
    assert message["role"] == "tool" and message["tool_call_id"] == "a"
    assert message["name"] == message["tool_name"] == "read"
    assert json.loads(message["content"]) == {"text": "原文"}
