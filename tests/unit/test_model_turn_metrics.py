"""Actual model measurements must not leak content or invent billing usage."""

import json

import pytest

from app.core.agent.kernel import (
    AgentRequest,
    EventType,
    KernelRuntime,
    KernelRuntimeConfig,
    ModelResponse,
    ToolCatalog,
)
from app.core.agent.kernel.model_metrics import ModelTurnMetrics, reported_usage


def measurements(events):
    return [
        event.data
        for event in events
        if event.data.get("event_type") == "model.metrics"
    ]


def test_usage_only_reports_provider_numeric_facts_and_keeps_missing_unknown():
    usage = reported_usage(
        {
            "usage": {
                "prompt_tokens": 17,
                "completion_tokens": 6,
                "prompt_tokens_details": {"cached_tokens": 4},
                "secret": "not-an-allowed-field",
            }
        }
    )
    assert usage == {
        "provider_reported": True,
        "input_tokens": 17,
        "output_tokens": 6,
        "total_tokens": None,
        "cached_input_tokens": 4,
    }
    assert "secret" not in json.dumps(usage)
    assert reported_usage({})["input_tokens"] is None
    assert reported_usage({})["provider_reported"] is False


@pytest.mark.parametrize(
    "bad", [True, -1, 1.2, "99", float("nan"), float("inf"), 10**1000]
)
def test_malformed_usage_does_not_become_billing_or_break_the_task(bad):
    assert reported_usage({"usage": {"prompt_tokens": bad}})["input_tokens"] is None
    assert reported_usage("invalid-metadata")["provider_reported"] is False


def test_first_public_text_and_completion_are_measured_once_without_content():
    clock = iter([10.0, 10.25, 11.5])
    metrics = ModelTurnMetrics(
        run_id="run", message_id="message", clock=lambda: next(clock)
    )
    metrics.first_text()
    metrics.first_text()
    event = metrics.event(
        status="completed", response=ModelResponse(content="private material")
    )
    assert event.data["duration_ms"] == 1500
    assert event.data["first_text_ms"] == 250
    assert "private material" not in json.dumps(event.data)
    assert event.data["context_estimate"]["billing_usage"] is False


def test_call_clock_excludes_backpressure_before_gateway_invocation():
    clock = iter([0.0, 10.0, 10.25, 10.5])
    metrics = ModelTurnMetrics(
        run_id="run", message_id="message", clock=lambda: next(clock)
    )
    metrics.start_call()
    metrics.first_text()
    event = metrics.event(status="completed")
    assert event.data["duration_ms"] == 500
    assert event.data["first_text_ms"] == 250


def test_kernel_records_actual_stream_usage_and_keeps_budget_estimate_separate():
    class Gateway:
        def generate_stream(self, **kwargs):
            yield {"delta": "answer"}
            yield {
                "stream_final": True,
                "content": "answer",
                "model": "fixture",
                "usage": {
                    "prompt_tokens": 25,
                    "completion_tokens": 2,
                    "total_tokens": 27,
                },
            }

    events = list(
        KernelRuntime(gateway=Gateway(), catalog=ToolCatalog()).iter_events(
            AgentRequest(prompt="private prompt", extra={"run_id": "actual-run"})
        )
    )
    (data,) = measurements(events)
    assert data["status"] == "completed" and data["run_id"] == "actual-run"
    assert data["first_text_ms"] is not None
    assert data["usage"]["total_tokens"] == 27
    assert data["context_estimate"]["estimated_input_tokens"] > 0
    assert "private prompt" not in json.dumps(data)
    assert (
        next(e for e in events if e.type is EventType.TASK_COMPLETE).data["result"]
        == "answer"
    )


def test_nonstream_provider_does_not_invent_first_token_latency():
    class Gateway:
        def generate(self, **kwargs):
            return ModelResponse(content="answer")

    events = list(
        KernelRuntime(gateway=Gateway(), catalog=ToolCatalog()).iter_events(
            AgentRequest(prompt="task")
        )
    )
    (data,) = measurements(events)
    assert data["first_text_ms"] is None
    assert data["usage"]["provider_reported"] is False


def test_failed_stream_emits_safe_failure_measurement_and_real_failed_terminal():
    class Gateway:
        def generate_stream(self, **kwargs):
            yield {"delta": "partial"}
            raise RuntimeError("private server or document detail")

    events = list(
        KernelRuntime(gateway=Gateway(), catalog=ToolCatalog()).iter_events(
            AgentRequest(prompt="task")
        )
    )
    (data,) = measurements(events)
    assert data["status"] == "failed" and data["error_type"] == "RuntimeError"
    assert "private server" not in json.dumps(data)
    assert events[-1].data["state"] == "failed"


def test_cancel_closes_stream_without_reporting_fake_success():
    state = {"cancelled": False, "closed": False}

    class Gateway:
        def generate_stream(self, **kwargs):
            try:
                yield {"delta": "partial"}
                yield {"delta": "not-shown"}
            finally:
                state["closed"] = True

    stream = KernelRuntime(gateway=Gateway(), catalog=ToolCatalog()).iter_events(
        AgentRequest(prompt="task"), cancel_check=lambda: state["cancelled"]
    )
    next(e for e in stream if e.type is EventType.STREAM_CHUNK)
    state["cancelled"] = True
    tail = list(stream)
    (data,) = measurements(tail)
    assert data["status"] == "cancelled" and state["closed"]
    assert tail[-1].data["state"] == "cancelled"


def test_closing_consumer_never_yields_from_generator_exit():
    class Gateway:
        def generate_stream(self, **kwargs):
            yield {"delta": "first"}
            yield {"delta": "second"}

    stream = KernelRuntime(gateway=Gateway(), catalog=ToolCatalog()).iter_events(
        AgentRequest(prompt="task")
    )
    next(e for e in stream if e.type is EventType.STREAM_CHUNK)
    stream.close()


def test_completed_checkpoint_replay_has_no_new_model_call_or_measurement():
    class Gateway:
        def generate(self, **kwargs):
            pytest.fail("replay invoked a model")

    events = list(
        KernelRuntime(gateway=Gateway(), catalog=ToolCatalog()).iter_events(
            AgentRequest(prompt="task"),
            config=KernelRuntimeConfig(
                resume_state={"phase": "completed", "terminal_result": "saved"}
            ),
        )
    )
    assert measurements(events) == []
