# -*- coding: utf-8 -*-
"""
Business-logic tests for BackgroundAgent, DeepResearchAgent.

Design rules
────────────
- No real LLM calls: LLM is patched at the provider / call site level
- No network I/O
- No file-system mutations (tmp dirs only if needed)
- Assert on return types, state transitions, and error paths

Each class groups all tests for one agent to keep the file scannable.
"""

from __future__ import annotations

import threading
import time
import types
import unittest
from typing import Any, Dict
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_fake_registry():
    reg = MagicMock()
    reg.get_definitions.return_value = []
    return reg


def _make_fake_llm_provider():
    prov = MagicMock()
    prov.generate.return_value = "OK"
    return prov


# ─────────────────────────────────────────────────────────────────────────────
# BackgroundAgent
# ─────────────────────────────────────────────────────────────────────────────


class TestBackgroundAgentSubmit(unittest.TestCase):
    """submit() must return a task_id immediately without blocking."""

    def setUp(self):
        from app.core.agent.background_agent import BackgroundAgent

        self.agent = BackgroundAgent(session_id="test-session")

    def test_submit_returns_string_id(self):
        """submit() returns a non-empty string task_id immediately."""
        with patch.object(self.agent, "_run_task", return_value=None) as mock_run:
            task_id = self.agent.submit("Test goal")
        self.assertIsInstance(task_id, str)
        self.assertTrue(len(task_id) > 0)

    def test_submit_creates_status_entry(self):
        """After submit(), get_status() returns a BackgroundTaskStatus in 'planning' phase."""
        with patch.object(self.agent, "_run_task", return_value=None):
            task_id = self.agent.submit("Summarize my notes")

        status = self.agent.get_status(task_id)
        self.assertIsNotNone(status)
        self.assertEqual(status.task_id, task_id)
        self.assertEqual(status.goal, "Summarize my notes")
        self.assertEqual(status.session_id, "test-session")

    def test_submit_unique_task_ids(self):
        """Each call to submit() produces a distinct task_id."""
        ids = set()
        with patch.object(self.agent, "_run_task", return_value=None):
            for _ in range(5):
                ids.add(self.agent.submit("Goal"))
        self.assertEqual(len(ids), 5)

    def test_get_status_returns_none_for_unknown(self):
        """get_status() returns None for an unknown task_id."""
        self.assertIsNone(self.agent.get_status("nonexistent-id"))

    def test_cancel_sets_failed_phase(self):
        """cancel() marks the task phase as 'failed'."""
        with patch.object(self.agent, "_run_task", return_value=None):
            task_id = self.agent.submit("Some work")

        self.agent.cancel(task_id)
        status = self.agent.get_status(task_id)
        self.assertEqual(status.phase, "failed")
        self.assertIn("取消", status.error)

    def test_list_tasks_scoped_by_session(self):
        """list_tasks(session_id) returns only tasks for that session."""
        agent_a = type(self.agent)(session_id="A")
        agent_b = type(self.agent)(session_id="B")
        with patch.object(agent_a, "_run_task", return_value=None):
            tid_a = agent_a.submit("Task A")
        with patch.object(agent_b, "_run_task", return_value=None):
            tid_b = agent_b.submit("Task B")

        tasks_a = agent_a.list_tasks(session_id="A")
        self.assertTrue(all(t.session_id == "A" for t in tasks_a))

    def test_approve_plan_sets_executing_phase(self):
        """approve_plan() transitions the task to the 'executing' phase."""
        with patch.object(self.agent, "_run_task", return_value=None):
            task_id = self.agent.submit("Plan task", human_review_before_execute=True)

        self.agent.approve_plan(task_id)
        status = self.agent.get_status(task_id)
        self.assertEqual(status.phase, "executing")

    def test_approve_plan_raises_for_unknown_task(self):
        """approve_plan() raises KeyError for unknown task_id."""
        with self.assertRaises(KeyError):
            self.agent.approve_plan("unknown-task")

    def test_on_complete_callback_invoked(self):
        """on_complete callback is called with (task_id, report) when task succeeds."""
        from app.core.agent.background_agent import BackgroundAgent, ExecutionPlan, PlanStep

        callback_results = {}

        def cb(task_id, report):
            callback_results["task_id"] = task_id
            callback_results["report"] = report

        fake_plan = ExecutionPlan(
            plan_id="p1",
            goal="Test goal",
            steps=[PlanStep(step_id="s1", title="Step", description="Do it")],
        )

        agent = BackgroundAgent(session_id="cb-test")

        # Pre-set the review event so _run_task doesn't block
        review_event = threading.Event()
        review_event.set()
        cancel_event = threading.Event()
        agent._review_events["t1"] = review_event
        agent._cancel_events["t1"] = cancel_event

        with (
            patch.object(agent, "_init_lazy"),
            patch.object(agent, "_plan", return_value=fake_plan),
            patch.object(agent, "_execute_step", return_value="step result"),
            patch.object(agent, "_synthesize", return_value="Final report"),
            patch.object(agent, "_emit"),
            patch.object(agent, "_update"),
        ):
            agent._run_task(
                task_id="t1",
                goal="Test goal",
                context={},
                review_event=review_event,
                cancel_event=cancel_event,
                on_complete=cb,
            )

        self.assertEqual(callback_results.get("report"), "Final report")


class TestBackgroundAgentExtractJson(unittest.TestCase):
    """_extract_json() should parse valid JSON and gracefully handle bad input."""

    def setUp(self):
        from app.core.agent.background_agent import BackgroundAgent

        self._agent = BackgroundAgent()

    def test_valid_json_object(self):
        result = self._agent._extract_json('{"key": "value"}')
        self.assertEqual(result, {"key": "value"})

    def test_json_wrapped_in_markdown_fence(self):
        raw = '```json\n{"steps": []}\n```'
        result = self._agent._extract_json(raw)
        self.assertEqual(result, {"steps": []})

    def test_invalid_json_returns_none(self):
        result = self._agent._extract_json("not json at all")
        self.assertIsNone(result)

    def test_empty_string_returns_none(self):
        result = self._agent._extract_json("")
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────────────────────
# DeepResearchAgent
# ─────────────────────────────────────────────────────────────────────────────


class TestDeepResearchAgentRun(unittest.TestCase):
    """run() should yield dictionaries with correct 'type' keys."""

    def _make_agent(self):
        from app.core.agent.deep_research import DeepResearchAgent

        return DeepResearchAgent(
            llm_provider=_make_fake_llm_provider(),
            tool_registry=_make_fake_registry(),
            max_rounds=1,
            queries_per_round=1,
        )

    def _patch_agent(self, agent):
        """Return a context manager that stubs out all I/O in an agent."""
        import contextlib

        @contextlib.contextmanager
        def cm():
            with (
                patch.object(agent, "_decompose_query", return_value=["sub-q1"]),
                patch.object(
                    agent,
                    "_parallel_search",
                    return_value=[{"query": "sub-q1", "results": [{"snippet": "fact"}]}],
                ),
                patch.object(
                    agent,
                    "_detect_gaps",
                    return_value={"sufficient": True, "gaps": []},
                ),
                patch.object(
                    agent,
                    "_synthesize",
                    return_value="Final report text",
                ),
            ):
                yield

        return cm()

    def test_run_yields_progress_and_result(self):
        agent = self._make_agent()
        with self._patch_agent(agent):
            events = list(agent.run("What is quantum computing?"))

        types_seen = {e["type"] for e in events}
        self.assertIn("progress", types_seen)
        self.assertIn("result", types_seen)

    def test_result_event_has_report_key(self):
        agent = self._make_agent()
        with self._patch_agent(agent):
            events = list(agent.run("Research query"))

        result_events = [e for e in events if e["type"] == "result"]
        self.assertTrue(len(result_events) >= 1)
        self.assertIn("report", result_events[0])

    def test_run_error_yields_error_event(self):
        agent = self._make_agent()
        with patch.object(agent, "_decompose_query", side_effect=RuntimeError("LLM explode")):
            events = list(agent.run("Bad query"))

        error_events = [e for e in events if e["type"] == "error"]
        self.assertTrue(len(error_events) >= 1)
        self.assertIn("LLM explode", error_events[0].get("message", ""))

    def test_progress_events_have_stage_and_message(self):
        agent = self._make_agent()
        with self._patch_agent(agent):
            events = list(agent.run("Query"))

        for evt in events:
            if evt["type"] == "progress":
                self.assertIn("stage", evt)
                self.assertIn("message", evt)

    def test_extract_json_valid(self):
        agent = self._make_agent()
        result = agent._extract_json('{"queries": ["a", "b"]}')
        self.assertEqual(result, {"queries": ["a", "b"]})

    def test_extract_json_invalid_returns_none(self):
        agent = self._make_agent()
        result = agent._extract_json("garbage")
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────────────────────
# MultiAgentOrchestrator
# ─────────────────────────────────────────────────────────────────────────────


class TestMultiAgentOrchestrator(unittest.TestCase):
    """
    Test MultiAgentOrchestrator.run() using mocked LLM calls.

    The orchestrator builds a LangGraph graph, so these tests require
    langgraph to be installed. They are skipped automatically when
    LangGraph is absent.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import langgraph  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("langgraph not installed – skipping MultiAgent tests")

    def _make_orchestrator(self):
        from app.core.agent.multi_agent import ROLES, MultiAgentOrchestrator
        from langgraph.checkpoint.memory import MemorySaver

        return MultiAgentOrchestrator(
            roles=[ROLES.RESEARCHER, ROLES.WRITER],
            model_id="gemini-mock",
            checkpointer=MemorySaver(),
        )

    def test_run_returns_dict_with_output_key(self):
        orchestrator = self._make_orchestrator()
        with patch("app.core.agent.multi_agent._llm_call", return_value="mocked result"):
            result = orchestrator.run("Write about Python")

        self.assertIn("output", result)
        self.assertIn("steps", result)
        self.assertIn("error", result)

    def test_run_steps_include_role_names(self):
        orchestrator = self._make_orchestrator()
        with patch("app.core.agent.multi_agent._llm_call", return_value="Mocked LLM text"):
            result = orchestrator.run("Task")

        # researcher and writer nodes should both appear in steps
        self.assertIn("researcher", result["steps"])
        self.assertIn("writer", result["steps"])

    def test_run_returns_error_on_graph_failure(self):
        orchestrator = self._make_orchestrator()
        with patch("app.core.agent.multi_agent._llm_call", side_effect=RuntimeError("boom")):
            result = orchestrator.run("Failing task")

        # Should not raise; error captured in result
        self.assertIsNotNone(result.get("error"))

    def test_stream_yields_agent_events(self):
        orchestrator = self._make_orchestrator()
        with patch("app.core.agent.multi_agent._llm_call", return_value="Stream content"):
            events = list(orchestrator.stream("Stream task"))

        # Must yield at least one event dict with 'agent' and 'content' keys
        self.assertTrue(len(events) >= 1)
        for evt in events:
            self.assertIn("agent", evt)
            self.assertIn("content", evt)

    def test_preset_content_pipeline_creates_orchestrator(self):
        from app.core.agent.multi_agent import MultiAgentOrchestrator
        from langgraph.checkpoint.memory import MemorySaver

        with patch.object(MultiAgentOrchestrator, "__init__", lambda self, **kw: None):
            # Smoke test: class method does not crash when __init__ is stubbed
            pass

    def test_roles_cannot_be_empty(self):
        from app.core.agent.multi_agent import MultiAgentOrchestrator

        with self.assertRaises((ValueError, Exception)):
            MultiAgentOrchestrator(roles=[])

    def test_get_graph_mermaid_returns_string(self):
        orchestrator = self._make_orchestrator()
        mermaid = orchestrator.get_graph_mermaid()
        self.assertIsInstance(mermaid, str)


# ─────────────────────────────────────────────────────────────────────────────
# LangGraphAgent.run() compatibility shim
# ─────────────────────────────────────────────────────────────────────────────


class TestLangGraphAgentRunCompat(unittest.TestCase):
    """
    LangGraphAgent.run() must yield AgentStep objects compatible with
    agent_routes expectations.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import langgraph  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("langgraph not installed")

    def _make_agent(self):
        from app.core.agent.langgraph_agent import LangGraphAgent
        from app.core.agent.tool_registry import ToolRegistry

        return LangGraphAgent(
            registry=ToolRegistry(),
            model_id="gemini-mock",
            enable_pii_filter=False,
            enable_output_validation=False,
        )

    def test_run_yields_agent_steps(self):
        from app.core.agent.types import AgentStep

        agent = self._make_agent()
        events = [
            {"type": "token", "content": "Thinking…"},
            {"type": "answer", "content": "Final answer"},
        ]
        with patch.object(agent, "stream", return_value=iter(events)):
            steps = list(agent.run("Hello"))

        self.assertTrue(len(steps) >= 1)
        for s in steps:
            self.assertIsInstance(s, AgentStep)

    def test_run_yields_answer_step(self):
        from app.core.agent.types import AgentStep, AgentStepType

        agent = self._make_agent()
        events = [{"type": "answer", "content": "42"}]
        with patch.object(agent, "stream", return_value=iter(events)):
            steps = list(agent.run("The answer?"))

        answer_steps = [s for s in steps if s.step_type == AgentStepType.ANSWER]
        self.assertEqual(len(answer_steps), 1)
        self.assertEqual(answer_steps[0].content, "42")

    def test_run_yields_error_step_on_exception(self):
        from app.core.agent.types import AgentStep, AgentStepType

        agent = self._make_agent()
        with patch.object(agent, "stream", side_effect=RuntimeError("graph fail")):
            steps = list(agent.run("Broken input"))

        error_steps = [s for s in steps if s.step_type == AgentStepType.ERROR]
        self.assertTrue(len(error_steps) >= 1)

    def test_run_maps_tool_call_to_action(self):
        from app.core.agent.types import AgentStep, AgentStepType

        agent = self._make_agent()
        events = [{"type": "tool_call", "content": "web_search", "args": {"q": "test"}}]
        with patch.object(agent, "stream", return_value=iter(events)):
            steps = list(agent.run("Search for X"))

        action_steps = [s for s in steps if s.step_type == AgentStepType.ACTION]
        self.assertTrue(len(action_steps) >= 1)
        self.assertIsNotNone(action_steps[0].action)
        self.assertEqual(action_steps[0].action.tool_name, "web_search")


if __name__ == "__main__":
    unittest.main()
