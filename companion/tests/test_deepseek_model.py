"""Provider payload conformance, independent of model prose or file fixtures."""

import pytest

pytest.importorskip("langchain_deepseek")

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from companion.agent_lab.deepseek_model import KotoDeepSeek


def test_private_reasoning_is_preserved_for_tool_and_final_assistant_messages():
    model = KotoDeepSeek(
        model="deepseek-chat",
        api_key="test-only",
        extra_body={"thinking": {"type": "enabled"}},
        reasoning_effort="low",
    )
    messages = [
        HumanMessage("计算"),
        AIMessage(
            content="",
            additional_kwargs={"reasoning_content": "private-tool-state"},
            tool_calls=[
                {"id": "call-one", "name": "multiply", "args": {"a": 17, "b": 23}}
            ],
        ),
        ToolMessage(content="391", tool_call_id="call-one"),
        AIMessage(
            content="391",
            additional_kwargs={"reasoning_content": "private-final-state"},
        ),
        HumanMessage("继续"),
    ]
    payload = model._get_request_payload(messages)
    assert payload["messages"][1]["reasoning_content"] == "private-tool-state"
    assert payload["messages"][3]["reasoning_content"] == "private-final-state"
    assert payload["extra_body"]["thinking"]["type"] == "enabled"
    assert "reasoning_content" not in payload["messages"][2]
