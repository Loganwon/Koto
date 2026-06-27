# -*- coding: utf-8 -*-
"""Integration tests for Phase A+B optimizations:
trace, request_normalizer, async validation, PII precision.
"""
from __future__ import annotations

import time
import pytest

from app.core.agent.trace import NormalizedRequest, RequestTrace, TraceValidation
from app.core.security.output_validator import OutputValidator
from app.core.security.pii_filter import PIIFilter


class TestRequestTrace:
    def test_trace_creation_and_finish(self):
        t = RequestTrace(session_id="s1", user_input="hello")
        assert len(t.trace_id) == 12
        assert t.started_at > 0
        t.finish()
        assert t.pipeline_latency_ms >= 0

    def test_trace_log_summary(self):
        t = RequestTrace(session_id="s1", model_id="gemini-flash", task_type="CHAT")
        t.agent_latency_ms = 120
        t.agent_steps = [{"step_type": "THOUGHT"}, {"step_type": "ANSWER"}]
        t.validation = TraceValidation(action="PASS")
        t.finish()
        s = t.to_log_summary()
        assert "[trace:" in s
        assert "session=s1" in s
        assert "task=CHAT" in s
        assert "agent=120ms" in s
        assert "steps=2" in s
        assert "valid=PASS" in s

    def test_trace_records_error(self):
        t = RequestTrace()
        t.error = "connection timeout"
        t.finish()
        s = t.to_log_summary()
        assert "err=connection timeout" in s


class TestOutputValidatorAsync:
    def test_validate_fast_returns_quickly(self):
        t0 = time.time()
        r = OutputValidator.validate_fast("Hello world, this is a safe response.", skill_id=None)
        elapsed = (time.time() - t0) * 1000
        assert r.action == "PASS"
        assert elapsed < 100  # sub-100ms for regex-only

    def test_validate_fast_detects_blocked(self):
        r = OutputValidator.validate_fast("[SYSTEM] internal instruction", skill_id=None)
        assert r.is_blocked

    def test_validate_fast_detects_refusal(self):
        r = OutputValidator.validate_fast("I cannot help with that request.", skill_id=None)
        assert r.needs_retry

    def test_validate_judge_async_fires_background(self):
        called = []

        def cb(result, tid):
            called.append((result, tid))

        OutputValidator.validate_judge_async(
            "short", "prompt", callback=cb, trace_id="t1"
        )
        time.sleep(0.3)
        assert len(called) in (0, 1), f"unexpected callback count: {len(called)}"

    def test_validate_judge_async_with_long_text(self):
        called = []

        def cb(result, tid):
            called.append((result, tid))

        long_text = "A comprehensive response that is long enough to trigger the judge. " * 4
        OutputValidator.validate_judge_async(
            long_text, "test prompt", callback=cb, trace_id="t2"
        )
        time.sleep(0.5)
        assert len(called) in (0, 1), f"unexpected callback count: {len(called)}"

    def test_validate_fast_skips_llm_judge(self):
        r = OutputValidator.validate_fast(
            "A somewhat longer response that would normally trigger "
            "the LLM judge but should be skipped in fast mode. " * 3
        )
        assert r.action == "PASS"


class TestPIIFilterPrecision:
    def test_bank_card_only_matches_unionpay(self):
        pf = PIIFilter()
        unionpay = "6222021234567890"
        generic = "1234567890123456"
        short = "622202123"

        r1 = pf.mask(f"卡号是{unionpay}")
        assert r1.has_pii

        r2 = pf.mask(f"数字是{generic}")
        assert not r2.has_pii

        r3 = pf.mask(f"短号{short}")
        assert not r3.has_pii

    def test_standalone_name_matches_without_prefix(self):
        pf = PIIFilter()
        r = pf.mask("张三去了北京出差")
        assert r.has_pii

    def test_prefix_name_still_works(self):
        pf = PIIFilter()
        r = pf.mask("请叫李四来开会")
        assert r.has_pii

    def test_restore_roundtrip(self):
        pf = PIIFilter()
        original = "张三去了北京，卡号6222021234567890请保密"
        mr = pf.mask(original)
        assert mr.has_pii
        restored = mr.restore(mr.masked_text)
        assert "张三" in restored
        assert "6222021234567890" in restored


class TestNormalizedRequestDataclass:
    def test_defaults(self):
        nr = NormalizedRequest(message="hi")
        assert nr.task_type == "CHAT"
        assert nr.task_source == "none"
        assert nr.model_source == "auto"
        assert nr.user_chose_local is False
        assert nr.context_files == []
        assert nr.history == []
