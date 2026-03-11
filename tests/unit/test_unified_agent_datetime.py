"""Unit tests for datetime injection in UnifiedAgent.run().

Verifies that the current local time is prepended to system_instruction
on every call to run(), so cloud models always receive temporal context.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from app.core.agent.types import AgentStep, AgentStepType
from app.core.agent.unified_agent import UnifiedAgent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DATETIME_PATTERN = re.compile(
    r"当前本地时间：\d{4}年\d{2}月\d{2}日 \d{2}:\d{2}（周[一二三四五六日]）"
)

WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _make_agent(system_instruction: Optional[str] = None) -> UnifiedAgent:
    """Return a UnifiedAgent with a fake LLM provider and no tools."""
    fake_llm = MagicMock()
    # generate_content returns a minimal "ANSWER" response
    fake_llm.generate_content.return_value = {
        "content": "ok",
        "tool_calls": [],
    }
    agent = UnifiedAgent(
        llm_provider=fake_llm,
        system_instruction=system_instruction,
        use_tool_router=False,
        enable_pii_filter=False,
        enable_output_validation=False,
    )
    return agent


def _run_and_capture_instruction(agent: UnifiedAgent, message: str = "hello") -> str:
    """Run agent once and return the system_instruction passed to generate_content."""
    # Consume the generator to drive the loop
    for _ in agent.run(input_text=message):
        break
    call_kwargs = agent.llm.generate_content.call_args
    # system_instruction may be positional or keyword
    if call_kwargs.kwargs.get("system_instruction") is not None:
        return call_kwargs.kwargs["system_instruction"]
    # fallback: positional arg index varies; search all args
    for arg in call_kwargs.args:
        if isinstance(arg, str) and "当前本地时间" in arg:
            return arg
    return ""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDatetimeInjection:
    def test_instruction_contains_datetime_prefix(self):
        """System instruction sent to LLM must start with a datetime line."""
        agent = _make_agent()
        instruction = _run_and_capture_instruction(agent)
        assert _DATETIME_PATTERN.search(
            instruction
        ), f"Expected datetime prefix in instruction, got: {instruction[:200]!r}"

    def test_datetime_prefix_is_first_line(self):
        """The datetime prefix must appear at the very beginning of the instruction."""
        agent = _make_agent()
        instruction = _run_and_capture_instruction(agent)
        assert instruction.startswith(
            "当前本地时间："
        ), f"Instruction should start with datetime prefix, got: {instruction[:100]!r}"

    def test_original_instruction_preserved_after_prefix(self):
        """Custom system_instruction content must still be present after the prefix."""
        custom = "You are a specialized assistant for tests."
        agent = _make_agent(system_instruction=custom)
        instruction = _run_and_capture_instruction(agent)
        assert (
            custom in instruction
        ), "Original system instruction was lost after datetime injection."

    def test_weekday_label_is_correct(self):
        """The injected weekday label must match the frozen datetime's weekday."""
        fixed_dt = datetime(2026, 3, 11, 14, 0, 0)  # Wednesday → 周三
        expected_weekday = WEEKDAY_LABELS[fixed_dt.weekday()]

        agent = _make_agent()
        with patch("app.core.agent.unified_agent.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_dt
            instruction = _run_and_capture_instruction(agent)

        assert (
            expected_weekday in instruction
        ), f"Expected weekday '{expected_weekday}' in instruction, got: {instruction[:200]!r}"

    def test_date_and_time_values_are_correct(self):
        """The injected date/time string must match the frozen datetime."""
        fixed_dt = datetime(2026, 3, 11, 9, 5, 0)
        expected_str = "2026年03月11日 09:05"

        agent = _make_agent()
        with patch("app.core.agent.unified_agent.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_dt
            instruction = _run_and_capture_instruction(agent)

        assert (
            expected_str in instruction
        ), f"Expected '{expected_str}' in instruction, got: {instruction[:200]!r}"

    def test_datetime_refreshed_on_each_call(self):
        """Each call to run() must inject a fresh datetime, not a cached one."""
        dt1 = datetime(2026, 3, 11, 10, 0, 0)
        dt2 = datetime(2026, 3, 11, 11, 30, 0)

        agent = _make_agent()
        agent.llm.generate_content.return_value = {"content": "ok", "tool_calls": []}

        with patch("app.core.agent.unified_agent.datetime") as mock_dt:
            mock_dt.now.return_value = dt1
            for _ in agent.run(input_text="first call"):
                break
            instr1 = agent.llm.generate_content.call_args.kwargs.get(
                "system_instruction", ""
            )

        with patch("app.core.agent.unified_agent.datetime") as mock_dt:
            mock_dt.now.return_value = dt2
            for _ in agent.run(input_text="second call"):
                break
            instr2 = agent.llm.generate_content.call_args.kwargs.get(
                "system_instruction", ""
            )

        assert "10:00" in instr1, f"First call: expected 10:00 in {instr1[:100]!r}"
        assert "11:30" in instr2, f"Second call: expected 11:30 in {instr2[:100]!r}"
        assert instr1 != instr2, "Instructions for different times should differ"
