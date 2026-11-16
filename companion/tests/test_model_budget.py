"""Auxiliary API attempts share the execution budget and cancellation boundary."""

import httpx
import pytest

from companion.agent_lab.model_budget import activate, reset, charge
from companion.agent_lab.planning_model import PlanningModel
from companion.model import ModelConfig
from companion.contracts import CompanionError
from companion.tests.test_agent_lab import make_lab


def test_execution_and_planning_attempts_share_one_budget(tmp_path):
    _, _, broker, _ = make_lab(tmp_path)
    turn = broker.turn
    turn.max_model_requests = 2
    calls, events = [], []

    def handle(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]},
        )

    client = PlanningModel(
        ModelConfig("https://example.test/v1", "test", "test-key"),
        transport=httpx.MockTransport(handle),
    )
    token = activate(turn, events.append)
    try:
        charge(turn, "agent", events.append)
        client._request({"model": "test", "messages": []}, turn.cancelled)
        with pytest.raises(CompanionError, match="总预算"):
            client._request({"model": "test", "messages": []}, turn.cancelled)
        assert len(calls) == 1
        assert turn.model_requests_total == 2 and turn.auxiliary_model_calls == 1
        assert [e["kind"] for e in events] == ["agent", "planning", "planning_result"]
        assert turn.blocked_error
    finally:
        reset(token)


def test_empty_review_retry_cannot_escape_shared_budget(tmp_path):
    _, _, broker, _ = make_lab(tmp_path)
    turn = broker.turn
    turn.max_model_requests = 1
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
        )

    client = PlanningModel(
        ModelConfig("https://api.deepseek.com", "test", "test-key"),
        transport=httpx.MockTransport(respond),
    )
    token = activate(turn, lambda event: None)
    try:
        with pytest.raises(CompanionError, match="总预算"):
            client.request_review(
                {"model": "test", "messages": [], "max_tokens": 6000}, turn.cancelled
            )
        assert len(calls) == 1
        assert turn.model_requests_total == 1
    finally:
        reset(token)
