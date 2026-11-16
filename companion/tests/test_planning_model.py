"""JSON reasoning has output budget; unrelated providers/tool loops stay explicit."""

import json
import threading
import httpx
import pytest

from companion.model import ModelConfig
from companion.agent_lab.planning_model import PlanningModel


@pytest.mark.parametrize(
    "base,tools,enabled",
    [
        ("https://api.deepseek.com", False, True),
        ("https://example.test", False, False),
        ("https://api.deepseek.com", True, False),
    ],
)
def test_json_reasoning_policy_is_scoped_and_does_not_exhaust_tiny_output_budget(
    base, tools, enabled
):
    seen = []

    def respond(request):
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]},
        )

    client = PlanningModel(
        ModelConfig(base, "chosen-model", "test-only-key"),
        transport=httpx.MockTransport(respond),
    )
    payload = {
        "model": "chosen-model",
        "messages": [{"role": "user", "content": "Return JSON"}],
        "max_tokens": 350,
        "stream": False,
    }
    if tools:
        payload["tools"] = [{"type": "function", "function": {"name": "test"}}]
    client._request(payload, threading.Event())
    assert (seen[0].get("thinking", {}).get("type") == "enabled") is enabled
    assert seen[0]["max_tokens"] == (4096 if enabled else 350)
    assert "thinking" not in payload


def test_reasoning_stream_is_collected_as_complete_json_without_exposing_private_text():
    packets = [
        {
            "choices": [
                {"index": 0, "delta": {"reasoning_content": "private reasoning"}}
            ]
        },
        {"choices": [{"index": 0, "delta": {"content": '{"allowed":'}}]},
        {
            "choices": [
                {"index": 0, "delta": {"content": "true}"}, "finish_reason": "stop"}
            ]
        },
    ]

    def respond(request):
        assert json.loads(request.content)["stream"] is True
        body = (
            "".join("data: " + json.dumps(p) + "\n\n" for p in packets)
            + "data: [DONE]\n\n"
        )
        return httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"}
        )

    client = PlanningModel(
        ModelConfig("https://api.deepseek.com", "chosen-model", "test-only-key"),
        transport=httpx.MockTransport(respond),
    )
    result = client._request(
        {"model": "chosen-model", "messages": [], "stream": False}, threading.Event()
    )
    assert result["choices"][0]["message"]["content"] == '{"allowed":true}'
    assert "private reasoning" not in str(result)


def test_framing_and_private_reasoning_do_not_consume_the_visible_output_limit():
    packet = {
        "choices": [{"index": 0, "delta": {"reasoning_content": "private " * 150}}]
    }
    body = ("data: " + json.dumps(packet) + "\n\n") * 2000
    body += (
        "data: "
        + json.dumps(
            {
                "choices": [
                    {"index": 0, "delta": {"content": "{}"}, "finish_reason": "stop"}
                ]
            }
        )
        + "\n\ndata: [DONE]\n\n"
    )

    def respond(request):
        return httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"}
        )

    client = PlanningModel(
        ModelConfig("https://api.deepseek.com", "chosen-model", "test-only-key"),
        transport=httpx.MockTransport(respond),
    )
    assert (
        client._request({"model": "chosen-model", "messages": []}, threading.Event())[
            "choices"
        ][0]["message"]["content"]
        == "{}"
    )


def test_empty_review_truncation_uses_one_nonreasoning_retry_with_same_obligations():
    seen = []

    def respond(request):
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
        )

    client = PlanningModel(
        ModelConfig("https://api.deepseek.com", "test", "test-key"),
        transport=httpx.MockTransport(respond),
    )
    result = client.request_review(
        {"model": "test", "messages": [], "max_tokens": 6000}, threading.Event()
    )
    assert result["choices"][0]["finish_reason"] == "length"
    assert len(seen) == 2 and seen[0]["max_tokens"] == 8048
    assert seen[1]["thinking"] == {"type": "disabled"}
    assert seen[1]["max_tokens"] == 6000
    assert seen[1]["messages"] == seen[0]["messages"]


@pytest.mark.parametrize(
    "base,disabled",
    [("https://api.deepseek.com", True), ("https://example.test", False)],
)
def test_short_validation_has_separate_budget_preserving_provider_profile(
    base, disabled
):
    seen = []

    def respond(request):
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"allowed":false}'},
                    }
                ]
            },
        )

    client = PlanningModel(
        ModelConfig(base, "test", "synthetic-only"),
        transport=httpx.MockTransport(respond),
    )
    original = {"model": "test", "messages": [], "max_tokens": 350}
    result = client.request_validation(original, threading.Event())
    assert result["choices"][0]["message"]["content"] == '{"allowed":false}'
    assert (seen[0].get("thinking") == {"type": "disabled"}) is disabled
    assert seen[0]["max_tokens"] == 350
    assert "thinking" not in original


@pytest.mark.parametrize(
    "base,content",
    [("https://example.test", ""), ("https://api.deepseek.com", '{"checks":[')],
)
def test_review_fallback_does_not_replay_other_providers_or_partial_json(base, content):
    seen = []

    def respond(request):
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "length", "message": {"content": content}}
                ]
            },
        )

    client = PlanningModel(
        ModelConfig(base, "test", "test-key"), transport=httpx.MockTransport(respond)
    )
    client.request_review(
        {"model": "test", "messages": [], "max_tokens": 6000}, threading.Event()
    )
    assert len(seen) == 1


def test_stream_usage_and_resolved_model_survive_without_private_reasoning():
    packets = [
        {
            "model": "deepseek-flash",
            "choices": [{"delta": {"reasoning_content": "private"}}],
        },
        {
            "model": "deepseek-flash",
            "choices": [{"delta": {"content": "{}"}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 30,
                "completion_tokens": 20,
                "completion_tokens_details": {
                    "reasoning_tokens": 15,
                    "private": "do not retain",
                },
            },
        },
    ]

    def respond(request):
        body = (
            "".join("data: " + json.dumps(p) + "\n\n" for p in packets)
            + "data: [DONE]\n\n"
        )
        return httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"}
        )

    client = PlanningModel(
        ModelConfig("https://api.deepseek.com", "test", "test-key"),
        transport=httpx.MockTransport(respond),
    )
    result = client._request({"model": "test", "messages": []}, threading.Event())
    assert result["model"] == "deepseek-flash"
    assert result["usage"]["completion_tokens_details"] == {"reasoning_tokens": 15}
    assert "private" not in str(result)
