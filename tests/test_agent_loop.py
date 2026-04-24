#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests for the unified KotoAgentLoop and supporting modules.

Validates:
1. lifecycle.py — Event types, RunMetadata, RunState
2. hooks.py — Hook registry, ordering, abort
3. session_queue.py — Per-session serialization
4. agent_loop.py — Full loop with mocked LLM
5. pipeline_hooks.py — EditorAIPipeline hook adapter
"""

import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# ── Ensure project root is importable ──
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ══════════════════════════════════════════════════════════════
# 1. lifecycle.py tests
# ══════════════════════════════════════════════════════════════

class TestLifecycle:
    def test_run_state_terminal(self):
        from app.core.agent.lifecycle import RunState
        assert RunState.SUCCEEDED.is_terminal
        assert RunState.FAILED.is_terminal
        assert RunState.CANCELLED.is_terminal
        assert RunState.TIMED_OUT.is_terminal
        assert not RunState.RUNNING.is_terminal
        assert not RunState.QUEUED.is_terminal

    def test_agent_event_repr(self):
        from app.core.agent.lifecycle import AgentEvent, EventType
        e = AgentEvent(EventType.STREAM_CHUNK, {"chunk": "hello"})
        assert "stream_chunk" in repr(e)
        assert "chunk" in repr(e)

    def test_run_metadata_lifecycle(self):
        from app.core.agent.lifecycle import RunMetadata, RunState
        meta = RunMetadata(session_id="s1")
        assert meta.state == RunState.QUEUED
        assert meta.elapsed == 0.0

        meta.start()
        assert meta.state == RunState.RUNNING
        assert meta.started_at > 0
        assert meta.elapsed >= 0

        meta.finish(RunState.SUCCEEDED)
        assert meta.state == RunState.SUCCEEDED
        assert meta.ended_at > 0
        assert meta.elapsed >= 0

    def test_event_constructors(self):
        from app.core.agent.lifecycle import (
            EventType, evt_lifecycle_start, evt_plan, evt_step_done,
            evt_step_start, evt_stream_chunk, evt_task_complete, evt_error,
        )
        e = evt_lifecycle_start("run1", "sess1")
        assert e.type == EventType.LIFECYCLE_START
        assert e.data["run_id"] == "run1"

        plan = evt_plan([{"id": "understand", "description": "理解需求"}])
        assert plan.type == EventType.PLAN
        assert plan.data["steps"][0]["id"] == "understand"

        step = evt_step_start("understand", "理解需求")
        assert step.type == EventType.STEP_START
        assert step.data["step_id"] == "understand"

        e2 = evt_stream_chunk("hello")
        assert e2.data["chunk"] == "hello"

        step_done = evt_step_done("understand", "理解完成")
        assert step_done.type == EventType.STEP_DONE
        assert step_done.data["text"] == "理解完成"

        e3 = evt_task_complete(result="done", has_proposals=True)
        assert e3.data["has_proposals"] is True

        e4 = evt_error("oops")
        assert e4.data["text"] == "oops"

    def test_agent_request_defaults(self):
        from app.core.agent.lifecycle import AgentRequest
        req = AgentRequest(prompt="test")
        assert req.session_id == ""
        assert req.model_mode == "auto"
        assert req.output_mode == "inline"
        assert req.history == []


# ══════════════════════════════════════════════════════════════
# 2. hooks.py tests
# ══════════════════════════════════════════════════════════════

class TestHooks:
    def test_register_and_fire(self):
        from app.core.agent.hooks import HookContext, HookPoint, HookRegistry

        registry = HookRegistry()
        call_log = []

        def hook_a(ctx):
            call_log.append("a")
            ctx.metadata["touched_by"] = "a"

        def hook_b(ctx):
            call_log.append("b")

        registry.register("hook_a", HookPoint.BEFORE_PROMPT_BUILD, hook_a)
        registry.register("hook_b", HookPoint.BEFORE_PROMPT_BUILD, hook_b)

        ctx = HookContext(messages=[])
        registry.fire(HookPoint.BEFORE_PROMPT_BUILD, ctx)
        assert call_log == ["a", "b"]
        assert ctx.metadata["touched_by"] == "a"

    def test_priority_ordering(self):
        from app.core.agent.hooks import HookContext, HookPoint, HookRegistry

        registry = HookRegistry()
        order = []

        registry.register("low", HookPoint.BEFORE_REPLY, lambda c: order.append("low"), priority=200)
        registry.register("high", HookPoint.BEFORE_REPLY, lambda c: order.append("high"), priority=10)
        registry.register("mid", HookPoint.BEFORE_REPLY, lambda c: order.append("mid"), priority=100)

        registry.fire(HookPoint.BEFORE_REPLY, HookContext())
        assert order == ["high", "mid", "low"]

    def test_abort_stops_chain(self):
        from app.core.agent.hooks import HookContext, HookPoint, HookRegistry

        registry = HookRegistry()
        call_log = []

        def aborter(ctx):
            call_log.append("abort")
            ctx.abort_reason = "dangerous content"

        def second(ctx):
            call_log.append("second")

        registry.register("aborter", HookPoint.BEFORE_PROMPT_BUILD, aborter, priority=10)
        registry.register("second", HookPoint.BEFORE_PROMPT_BUILD, second, priority=20)

        ctx = HookContext()
        registry.fire(HookPoint.BEFORE_PROMPT_BUILD, ctx)
        assert call_log == ["abort"]
        assert ctx.abort_reason == "dangerous content"

    def test_unregister(self):
        from app.core.agent.hooks import HookContext, HookPoint, HookRegistry

        registry = HookRegistry()
        call_log = []
        registry.register("x", HookPoint.AGENT_END, lambda c: call_log.append("x"))
        registry.unregister("x")
        registry.fire(HookPoint.AGENT_END, HookContext())
        assert call_log == []

    def test_hook_exception_does_not_crash(self):
        from app.core.agent.hooks import HookContext, HookPoint, HookRegistry

        registry = HookRegistry()
        call_log = []

        def bad_hook(ctx):
            raise ValueError("boom")

        def good_hook(ctx):
            call_log.append("good")

        registry.register("bad", HookPoint.BEFORE_REPLY, bad_hook, priority=10)
        registry.register("good", HookPoint.BEFORE_REPLY, good_hook, priority=20)

        ctx = HookContext()
        registry.fire(HookPoint.BEFORE_REPLY, ctx)
        # Good hook still runs despite bad hook raising
        assert call_log == ["good"]

    def test_list_hooks(self):
        from app.core.agent.hooks import HookPoint, HookRegistry

        registry = HookRegistry()
        registry.register("a", HookPoint.BEFORE_TOOL_CALL, lambda c: None, priority=50)
        hooks = registry.list_hooks(HookPoint.BEFORE_TOOL_CALL)
        assert len(hooks) == 1
        assert hooks[0]["name"] == "a"
        assert hooks[0]["priority"] == 50


# ══════════════════════════════════════════════════════════════
# 3. session_queue.py tests
# ══════════════════════════════════════════════════════════════

class TestSessionQueue:
    def test_basic_serialization(self):
        from app.core.agent.session_queue import SessionQueue

        sq = SessionQueue()
        results = []

        def work(session_id, value, delay=0.01):
            with sq.acquire(session_id):
                time.sleep(delay)
                results.append(value)

        # Same session: should serialize
        t1 = threading.Thread(target=work, args=("s1", "A", 0.02))
        t2 = threading.Thread(target=work, args=("s1", "B", 0.01))
        t1.start()
        time.sleep(0.005)  # ensure t1 gets lock first
        t2.start()
        t1.join()
        t2.join()

        assert results == ["A", "B"]  # A finishes before B starts

    def test_different_sessions_parallel(self):
        from app.core.agent.session_queue import SessionQueue

        sq = SessionQueue()
        results = []
        lock = threading.Lock()

        def work(session_id, value, delay=0.02):
            with sq.acquire(session_id):
                time.sleep(delay)
                with lock:
                    results.append((value, time.time()))

        t1 = threading.Thread(target=work, args=("s1", "A"))
        t2 = threading.Thread(target=work, args=("s2", "B"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Both should finish roughly at the same time (parallel)
        assert len(results) == 2

    def test_queue_depth(self):
        from app.core.agent.session_queue import SessionQueue

        sq = SessionQueue()
        assert sq.queue_depth("nonexistent") == 0

    def test_global_concurrency(self):
        from app.core.agent.session_queue import SessionQueue

        sq = SessionQueue(global_concurrency=1)
        results = []

        def work(session_id, value):
            with sq.acquire(session_id):
                time.sleep(0.02)
                results.append(value)

        t1 = threading.Thread(target=work, args=("s1", "A"))
        t2 = threading.Thread(target=work, args=("s2", "B"))
        t1.start()
        time.sleep(0.005)
        t2.start()
        t1.join()
        t2.join()

        # Even different sessions are serialized with concurrency=1
        assert results == ["A", "B"]


# ══════════════════════════════════════════════════════════════
# 4. agent_loop.py tests (with mocked LLM)
# ══════════════════════════════════════════════════════════════

class TestAgentLoop:
    """Tests for KotoAgentLoop with mocked LLM providers."""

    def _make_fake_provider(self, responses: List[str]):
        """Create a fake LLM provider that yields predetermined chunks."""
        provider = MagicMock()
        idx = [0]

        def fake_generate(prompt=None, model=None, system_instruction=None, stream=False, **kw):
            text = responses[min(idx[0], len(responses) - 1)]
            idx[0] += 1
            if stream:
                # Yield chunks
                for word in text.split():
                    yield {"content": word + " "}
            else:
                return {"content": text}

        provider.generate_content = MagicMock(side_effect=fake_generate)
        return provider

    def test_build_proposals_omits_duplicate_rationale_text(self):
        from app.core.agent.agent_loop import KotoAgentLoop
        from app.core.agent.hooks import HookRegistry

        loop = KotoAgentLoop(hook_registry=HookRegistry())
        original = "未来每一款产品的销量预计有多少。"
        revised = "我们需要明确各款产品的销量预期。"
        proposals = loop._build_proposals(
            original,
            [{"type": "set_html", "value": revised}],
            revised,
        )

        assert len(proposals) == 1
        assert proposals[0]["proposed_text"] == revised
        assert proposals[0]["rationale"] == ""

    def test_build_proposals_preserves_distinct_rationale_text(self):
        from app.core.agent.agent_loop import KotoAgentLoop
        from app.core.agent.hooks import HookRegistry

        loop = KotoAgentLoop(hook_registry=HookRegistry())
        proposals = loop._build_proposals(
            "原文",
            [{"type": "set_html", "value": "修改后内容"}],
            "调整语气，使表述更正式并补齐问题导向。",
        )

        assert proposals[0]["rationale"] == "调整语气，使表述更正式并补齐问题导向。"

    @patch("app.core.agent.agent_loop._get_provider")
    @patch("app.core.agent.agent_loop._pick_online_model", return_value="test-model")
    def test_basic_text_response(self, mock_model, mock_provider):
        from app.core.agent.agent_loop import KotoAgentLoop
        from app.core.agent.hooks import HookRegistry
        from app.core.agent.lifecycle import AgentRequest, EventType

        provider = self._make_fake_provider(["你好世界 这是AI回复"])
        mock_provider.return_value = provider

        loop = KotoAgentLoop(hook_registry=HookRegistry())
        request = AgentRequest(
            prompt="你好",
            file_type="docx",
            output_mode="chat",
        )

        events = list(loop.run(request))
        types = [e.type for e in events]

        assert EventType.LIFECYCLE_START in types
        assert EventType.STREAM_CHUNK in types
        assert EventType.TASK_COMPLETE in types
        assert EventType.LIFECYCLE_END in types

    @patch("app.core.agent.agent_loop._get_provider")
    @patch("app.core.agent.agent_loop._pick_online_model", return_value="test-model")
    def test_plan_and_step_events_emitted_for_text_request(self, mock_model, mock_provider):
        from app.core.agent.agent_loop import KotoAgentLoop
        from app.core.agent.hooks import HookRegistry
        from app.core.agent.lifecycle import AgentRequest, EventType

        provider = self._make_fake_provider(["统一主链返回结果"])
        mock_provider.return_value = provider

        loop = KotoAgentLoop(hook_registry=HookRegistry())
        request = AgentRequest(
            prompt="请整理这段文字",
            file_type="docx",
            output_mode="chat",
            action_type="polish",
        )

        with patch.object(
            KotoAgentLoop,
            "_resolve_phases",
            return_value=[
                {"id": "understand", "label": "理解需求"},
                {"id": "generate", "label": "生成回复"},
            ],
        ):
            events = list(loop.run(request))
        types = [e.type for e in events]

        assert EventType.PLAN in types
        assert EventType.STEP_START in types
        assert EventType.STEP_PROGRESS in types
        assert EventType.STEP_DONE in types

        plan_events = [e for e in events if e.type == EventType.PLAN]
        assert plan_events[0].data["steps"]

        step_start_ids = [e.data["step_id"] for e in events if e.type == EventType.STEP_START]
        assert any(step_id in step_start_ids for step_id in ("understand", "generate"))

    @patch("app.core.agent.agent_loop._get_provider")
    @patch("app.core.agent.agent_loop._pick_online_model", return_value="test-model")
    def test_tool_call_parsing(self, mock_model, mock_provider):
        from app.core.agent.agent_loop import KotoAgentLoop
        from app.core.agent.hooks import HookRegistry
        from app.core.agent.lifecycle import AgentRequest, EventType

        response = '已修改。<TOOL>{"type":"set_html","value":"<p>新内容</p>"}</TOOL>'
        provider = self._make_fake_provider([response])
        mock_provider.return_value = provider

        loop = KotoAgentLoop(hook_registry=HookRegistry())
        request = AgentRequest(
            prompt="写一段文字",
            file_type="docx",
            output_mode="inline",
        )

        events = list(loop.run(request))
        types = [e.type for e in events]

        assert EventType.DOC_TOOL_CALL in types
        tc_events = [e for e in events if e.type == EventType.DOC_TOOL_CALL]
        assert tc_events[0].data["type"] == "set_html"
        assert "新内容" in tc_events[0].data["value"]

    @patch("app.core.agent.agent_loop._get_provider")
    @patch("app.core.agent.agent_loop._pick_online_model", return_value="test-model")
    def test_proposal_with_selection(self, mock_model, mock_provider):
        from app.core.agent.agent_loop import KotoAgentLoop
        from app.core.agent.hooks import HookRegistry
        from app.core.agent.lifecycle import AgentRequest, EventType

        response = '已润色。<TOOL>{"type":"set_html","value":"<p>润色后的文字</p>"}</TOOL>'
        provider = self._make_fake_provider([response])
        mock_provider.return_value = provider

        loop = KotoAgentLoop(hook_registry=HookRegistry())
        request = AgentRequest(
            prompt="润色这段文字",
            file_type="docx",
            selection="原始文字",
            has_selection=True,
            output_mode="inline",
        )

        events = list(loop.run(request))
        types = [e.type for e in events]

        assert EventType.PROPOSAL in types
        prop_events = [e for e in events if e.type == EventType.PROPOSAL]
        proposals = prop_events[0].data["proposals"]
        assert len(proposals) == 1
        assert proposals[0]["original_text"] == "原始文字"

    def test_empty_prompt_error(self):
        from app.core.agent.agent_loop import KotoAgentLoop
        from app.core.agent.hooks import HookRegistry
        from app.core.agent.lifecycle import AgentRequest, EventType

        loop = KotoAgentLoop(hook_registry=HookRegistry())
        request = AgentRequest(prompt="")

        events = list(loop.run(request))
        types = [e.type for e in events]
        assert EventType.ERROR in types

    def test_hooks_modify_prompt(self):
        from app.core.agent.agent_loop import KotoAgentLoop
        from app.core.agent.hooks import HookContext, HookPoint, HookRegistry
        from app.core.agent.lifecycle import AgentRequest, EventType

        registry = HookRegistry()
        hook_called = [False]

        def my_hook(ctx):
            hook_called[0] = True
            ctx.metadata["system_instruction"] = "Modified system instruction"

        registry.register("test_hook", HookPoint.BEFORE_PROMPT_BUILD, my_hook)

        with patch("app.core.agent.agent_loop._get_provider") as mock_prov, \
             patch("app.core.agent.agent_loop._pick_online_model", return_value="m"):
            provider = MagicMock()
            provider.generate_content = MagicMock(side_effect=lambda **kw: iter([{"content": "OK "}]))
            mock_prov.return_value = provider

            loop = KotoAgentLoop(hook_registry=registry)
            request = AgentRequest(prompt="test", file_type="txt", output_mode="chat")
            events = list(loop.run(request))

        assert hook_called[0]

    def test_hook_abort(self):
        from app.core.agent.agent_loop import KotoAgentLoop
        from app.core.agent.hooks import HookPoint, HookRegistry
        from app.core.agent.lifecycle import AgentRequest, EventType

        registry = HookRegistry()

        def abort_hook(ctx):
            ctx.abort_reason = "Content policy violation"

        registry.register("abort", HookPoint.BEFORE_PROMPT_BUILD, abort_hook)

        loop = KotoAgentLoop(hook_registry=registry)
        request = AgentRequest(prompt="bad content", file_type="txt")
        events = list(loop.run(request))
        types = [e.type for e in events]

        assert EventType.ERROR in types
        error_events = [e for e in events if e.type == EventType.ERROR]
        assert "Content policy" in error_events[0].data["text"]


# ══════════════════════════════════════════════════════════════
# 5. _parse_tool_calls tests
# ══════════════════════════════════════════════════════════════

class TestParseToolCalls:
    def test_tool_tag_parsing(self):
        from app.core.agent.agent_loop import _parse_tool_calls

        text = '已修改。<TOOL>{"type":"set_html","value":"<p>hi</p>"}</TOOL>'
        clean, calls = _parse_tool_calls(text)
        assert clean == "已修改。"
        assert len(calls) == 1
        assert calls[0]["type"] == "set_html"

    def test_multiple_tool_calls(self):
        from app.core.agent.agent_loop import _parse_tool_calls

        text = (
            '已更新。<TOOL>{"type":"set_cell","r":0,"c":0,"value":"Name"}</TOOL>\n'
            '<TOOL>{"type":"set_cell","r":0,"c":1,"value":"Sales"}</TOOL>'
        )
        clean, calls = _parse_tool_calls(text)
        assert len(calls) == 2
        assert calls[0]["value"] == "Name"
        assert calls[1]["value"] == "Sales"

    def test_code_fenced_json(self):
        from app.core.agent.agent_loop import _parse_tool_calls

        text = '说明。\n```json\n{"type":"set_html","value":"<p>test</p>"}\n```'
        clean, calls = _parse_tool_calls(text)
        assert len(calls) == 1

    def test_no_tool_calls(self):
        from app.core.agent.agent_loop import _parse_tool_calls

        text = "这是一段普通回复，没有任何工具调用。"
        clean, calls = _parse_tool_calls(text)
        assert clean == text
        assert calls == []

    def test_unknown_type_ignored(self):
        from app.core.agent.agent_loop import _parse_tool_calls

        text = '<TOOL>{"type":"unknown_op","value":"x"}</TOOL>'
        clean, calls = _parse_tool_calls(text)
        assert calls == []


class TestOnlineFailureDetection:
    def test_model_not_found_treated_as_online_failure(self):
        from app.core.agent.agent_loop import _is_online_failure

        exc = RuntimeError("404 model not found: gemini-2.5-flash")
        assert _is_online_failure(exc) is True

    def test_permission_denied_treated_as_online_failure(self):
        from app.core.agent.agent_loop import _is_online_failure

        exc = RuntimeError("Permission denied: Project does not have access to model")
        assert _is_online_failure(exc) is True
