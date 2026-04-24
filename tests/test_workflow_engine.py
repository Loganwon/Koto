"""
tests/test_workflow_engine.py
Tests for WorkflowExecutor base class and SSE event builders.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock

from app.core.workflow_engine import (
    sse_status,
    sse_progress,
    sse_step_start,
    sse_step_done,
    sse_output,
    sse_error,
    sse_done,
    call_llm,
    call_llm_json,
)


# ── SSE event builder unit tests ────────────────────────────────────────────

class TestSseBuilders:
    def test_sse_status(self):
        raw = sse_status("正在处理")
        assert raw.startswith("data: ")
        ev = json.loads(raw[6:])
        assert ev["type"] == "status"
        assert ev["text"] == "正在处理"

    def test_sse_progress(self):
        raw = sse_progress(3, 10, "处理第3个文件")
        ev = json.loads(raw[6:])
        assert ev["type"] == "progress"
        assert ev["current"] == 3
        assert ev["total"] == 10
        assert ev["detail"] == "处理第3个文件"

    def test_sse_step_start_done(self):
        start = sse_step_start("extract", "提取字段")
        done = sse_step_done("extract", "提取字段")
        ev_s = json.loads(start[6:])
        ev_d = json.loads(done[6:])
        assert ev_s["type"] == "step_start"
        assert ev_d["type"] == "step_done"
        assert ev_s["step"] == ev_d["step"] == "extract"

    def test_sse_output_xlsx(self):
        workbook = {"id": "wb1", "sheets": {}}
        raw = sse_output("xlsx_data", workbook, "提取结果")
        ev = json.loads(raw[6:])
        assert ev["type"] == "output"
        assert ev["output_type"] == "xlsx_data"
        assert ev["data"] == workbook
        assert ev["label"] == "提取结果"

    def test_sse_error(self):
        raw = sse_error("文件解析失败")
        ev = json.loads(raw[6:])
        assert ev["type"] == "error"
        assert ev["text"] == "文件解析失败"

    def test_sse_done(self):
        raw = sse_done("处理成功")
        ev = json.loads(raw[6:])
        assert ev["type"] == "done"
        assert ev["summary"] == "处理成功"

    def test_sse_events_end_with_double_newline(self):
        for fn, args in [
            (sse_status, ("test",)),
            (sse_progress, (1, 10)),
            (sse_step_start, ("s", "l")),
            (sse_step_done, ("s", "l")),
            (sse_output, ("markdown", "data")),
            (sse_error, ("err",)),
            (sse_done, ()),
        ]:
            result = fn(*args)
            assert result.endswith("\n\n"), f"{fn.__name__} should end with \\n\\n"


# ── call_llm tests ──────────────────────────────────────────────────────────

class TestCallLlm:
    @patch("app.core.llm.provider_factory.get_llm_provider")
    def test_call_llm_online_success(self, mock_factory):
        mock_provider = MagicMock()
        mock_provider.generate_content.return_value = "AI 回复"
        mock_factory.return_value = mock_provider

        result = call_llm("你好", model_mode="auto")
        assert result == "AI 回复"
        # auto → 不传参数，由 provider_factory 自动检测
        mock_factory.assert_called_once_with()

    @patch("app.core.llm.provider_factory.get_llm_provider")
    def test_call_llm_json_parses_raw_json(self, mock_factory):
        mock_provider = MagicMock()
        mock_provider.generate_content.return_value = '{"key": "value", "num": 42}'
        mock_factory.return_value = mock_provider

        result = call_llm_json('返回json')
        assert result == {"key": "value", "num": 42}

    @patch("app.core.llm.provider_factory.get_llm_provider")
    def test_call_llm_json_strips_markdown_fence(self, mock_factory):
        mock_provider = MagicMock()
        mock_provider.generate_content.return_value = "```json\n{\"a\": 1}\n```"
        mock_factory.return_value = mock_provider

        result = call_llm_json('返回json')
        assert result == {"a": 1}

    @patch("app.core.llm.provider_factory.get_llm_provider")
    def test_call_llm_json_returns_raw_on_invalid(self, mock_factory):
        mock_provider = MagicMock()
        mock_provider.generate_content.return_value = "这不是JSON"
        mock_factory.return_value = mock_provider

        result = call_llm_json('bad')
        # When JSON parsing fails, raw text is returned as fallback
        assert result == "这不是JSON"


# ── WorkflowExecutor lifecycle test ─────────────────────────────────────────

class TestWorkflowExecutorLifecycle:
    def test_run_yields_sse_events(self):
        from app.core.workflow_engine import WorkflowExecutor

        class DummyWorkflow(WorkflowExecutor):
            def execute(self, params, yield_event):
                yield sse_status("开始")

        wf = DummyWorkflow()
        events = list(wf.run({}))
        types = [json.loads(e[6:])["type"] for e in events]
        assert "status" in types
        assert "done" in types

    def test_run_emits_error_on_exception(self):
        from app.core.workflow_engine import WorkflowExecutor

        class BrokenWorkflow(WorkflowExecutor):
            def execute(self, params, yield_event):
                raise RuntimeError("模拟崩溃")
                yield  # make it a generator

        wf = BrokenWorkflow()
        events = list(wf.run({}))
        raw_types = [json.loads(e[6:])["type"] for e in events]
        assert "error" in raw_types
        assert "done" in raw_types
