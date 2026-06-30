# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

import json

from app.core.agent.chat_pipeline import ChatPipeline
from app.core.agent.types import AgentStep, AgentStepType


def _payload(frame: str) -> dict:
    assert frame.startswith("data: ")
    return json.loads(frame.removeprefix("data: ").strip())


class _AnswerAgent:
    model_id = "gemini-test"

    def run(self, **_kwargs):
        yield AgentStep(AgentStepType.ANSWER, "ok")


class _ServiceUnavailableAgent:
    model_id = "gemini-test"

    def run(self, **_kwargs):
        yield AgentStep(AgentStepType.ERROR, "503 service unavailable")


def test_chat_pipeline_normal_answer_reaches_task_final():
    pipeline = ChatPipeline(
        agent=_AnswerAgent(),
        is_service_unavailable_fn=lambda text: "503" in text,
    )

    events = [_payload(frame) for frame in pipeline.run("hello", [])]

    assert [event["type"] for event in events] == ["agent_step", "task_final"]
    assert events[0]["data"]["content"] == "ok"
    assert events[1]["data"]["status"] == "success"
    assert events[1]["data"]["result"] == "ok"


def test_chat_pipeline_503_error_step_switches_to_local_fallback():
    pipeline = ChatPipeline(
        agent=_ServiceUnavailableAgent(),
        is_service_unavailable_fn=lambda text: "503" in text,
        local_fallback_fn=lambda _message, _history: ("local ok", "ollama-test"),
    )

    events = [_payload(frame) for frame in pipeline.run("hello", [])]

    assert [event["type"] for event in events] == [
        "agent_step",
        "agent_step",
        "task_final",
    ]
    assert events[1]["data"]["metadata"]["source"] == "local_fallback"
    assert events[2]["data"]["meta"]["local_fallback"] is True
    assert "local ok" in events[2]["data"]["result"]
