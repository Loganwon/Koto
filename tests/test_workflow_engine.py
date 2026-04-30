# -*- coding: utf-8 -*-
"""
Tests for app.core.workflow_engine — PR #78.

Covers:
  - SSE event builder functions (_sse, sse_status, sse_progress, sse_step_start,
    sse_step_done, sse_output, sse_error, sse_done)
  - _resolve_provider_arg — model_mode → provider kwargs mapping
  - _extract_text — flexible result-to-string extraction
  - call_llm_json — JSON response parsing and markdown-fence stripping
  - WorkflowExecutor base class — run(), execute() contract, helper statics
"""

import json
import sys
import unittest
from unittest.mock import MagicMock, patch

# ── Stub optional heavy imports ───────────────────────────────────────────────

def _stub(name):
    if name not in sys.modules:
        sys.modules[name] = MagicMock()
    return sys.modules[name]


for _m in [
    "google",
    "google.genai",
    "google.genai.types",
    "sentence_transformers",
    "cv2",
    "pdfplumber",
    "docx",
    "PIL",
    "PIL.Image",
    "vosk",
    "pynput",
    "pynput.keyboard",
    "pynput.mouse",
    "scipy",
    "scipy.io",
    "pyaudio",
    "sounddevice",
]:
    _stub(_m)


# ══════════════════════════════════════════════════════════════════════════════
# 1. SSE event builder functions
# ══════════════════════════════════════════════════════════════════════════════


class TestSseBuilders(unittest.TestCase):
    """All SSE builder functions emit correctly formatted 'data: ...\n\n' lines."""

    def _parse(self, sse_str: str) -> dict:
        """Extract the JSON payload from a single SSE data line."""
        self.assertTrue(sse_str.startswith("data: "), f"Missing 'data: ' prefix: {sse_str!r}")
        self.assertTrue(sse_str.endswith("\n\n"), f"Missing trailing '\\n\\n': {sse_str!r}")
        return json.loads(sse_str[len("data: "):].strip())

    def setUp(self):
        from app.core.workflow_engine import (
            sse_status,
            sse_progress,
            sse_step_start,
            sse_step_done,
            sse_output,
            sse_error,
            sse_done,
        )
        self.sse_status = sse_status
        self.sse_progress = sse_progress
        self.sse_step_start = sse_step_start
        self.sse_step_done = sse_step_done
        self.sse_output = sse_output
        self.sse_error = sse_error
        self.sse_done = sse_done

    # ── sse_status
    def test_sse_status_type(self):
        payload = self._parse(self.sse_status("Processing…"))
        self.assertEqual(payload["type"], "status")

    def test_sse_status_text(self):
        payload = self._parse(self.sse_status("Processing…"))
        self.assertEqual(payload["text"], "Processing…")

    def test_sse_status_chinese(self):
        payload = self._parse(self.sse_status("正在处理"))
        self.assertEqual(payload["text"], "正在处理")

    # ── sse_progress
    def test_sse_progress_type(self):
        payload = self._parse(self.sse_progress(3, 10))
        self.assertEqual(payload["type"], "progress")

    def test_sse_progress_values(self):
        payload = self._parse(self.sse_progress(3, 10, "step 3"))
        self.assertEqual(payload["current"], 3)
        self.assertEqual(payload["total"], 10)
        self.assertEqual(payload["detail"], "step 3")

    def test_sse_progress_default_detail_empty(self):
        payload = self._parse(self.sse_progress(1, 5))
        self.assertEqual(payload["detail"], "")

    # ── sse_step_start
    def test_sse_step_start_type(self):
        payload = self._parse(self.sse_step_start("extract", "提取数据"))
        self.assertEqual(payload["type"], "step_start")

    def test_sse_step_start_fields(self):
        payload = self._parse(self.sse_step_start("s1", "Step 1"))
        self.assertEqual(payload["step"], "s1")
        self.assertEqual(payload["label"], "Step 1")

    # ── sse_step_done
    def test_sse_step_done_type(self):
        payload = self._parse(self.sse_step_done("s1", "Step 1 done"))
        self.assertEqual(payload["type"], "step_done")

    def test_sse_step_done_fields(self):
        payload = self._parse(self.sse_step_done("extract", "提取完成"))
        self.assertEqual(payload["step"], "extract")
        self.assertEqual(payload["label"], "提取完成")

    # ── sse_output
    def test_sse_output_type(self):
        payload = self._parse(self.sse_output("markdown", "# Title"))
        self.assertEqual(payload["type"], "output")

    def test_sse_output_fields(self):
        payload = self._parse(self.sse_output("xlsx_data", {"rows": []}, "Sheet1"))
        self.assertEqual(payload["output_type"], "xlsx_data")
        self.assertEqual(payload["data"], {"rows": []})
        self.assertEqual(payload["label"], "Sheet1")

    def test_sse_output_default_label_empty(self):
        payload = self._parse(self.sse_output("text", "hello"))
        self.assertEqual(payload["label"], "")

    # ── sse_error
    def test_sse_error_type(self):
        payload = self._parse(self.sse_error("Something went wrong"))
        self.assertEqual(payload["type"], "error")

    def test_sse_error_text(self):
        payload = self._parse(self.sse_error("LLM unavailable"))
        self.assertEqual(payload["text"], "LLM unavailable")

    # ── sse_done
    def test_sse_done_type(self):
        payload = self._parse(self.sse_done())
        self.assertEqual(payload["type"], "done")

    def test_sse_done_default_summary_empty(self):
        payload = self._parse(self.sse_done())
        self.assertEqual(payload["summary"], "")

    def test_sse_done_with_summary(self):
        payload = self._parse(self.sse_done("Completed in 1.5s"))
        self.assertEqual(payload["summary"], "Completed in 1.5s")

    # ── UTF-8 / non-ASCII characters preserved
    def test_chinese_characters_not_escaped(self):
        raw = self.sse_status("你好世界")
        # ensure_ascii=False means Chinese chars appear literally, not as \\uXXXX
        self.assertIn("你好世界", raw)


# ══════════════════════════════════════════════════════════════════════════════
# 2. _resolve_provider_arg
# ══════════════════════════════════════════════════════════════════════════════


class TestResolveProviderArg(unittest.TestCase):
    """_resolve_provider_arg maps model_mode to provider kwargs dict."""

    def setUp(self):
        from app.core.workflow_engine import _resolve_provider_arg
        self.resolve = _resolve_provider_arg

    def test_local_maps_to_ollama(self):
        result = self.resolve("local")
        self.assertEqual(result, {"provider": "ollama"})

    def test_cloud_maps_to_gemini(self):
        result = self.resolve("cloud")
        self.assertEqual(result, {"provider": "gemini"})

    def test_gemini_passthrough_to_empty(self):
        # normalize_model_mode maps unknown values (e.g. "gemini") to "auto",
        # so _resolve_provider_arg returns {} and lets provider_factory auto-detect.
        result = self.resolve("gemini")
        self.assertEqual(result, {})

    def test_ollama_passthrough_to_empty(self):
        # Same as above: "ollama" is not a recognized model_mode, maps to "auto".
        result = self.resolve("ollama")
        self.assertEqual(result, {})

    def test_auto_returns_empty(self):
        result = self.resolve("auto")
        self.assertEqual(result, {})

    def test_unknown_returns_empty(self):
        result = self.resolve("unknown")
        self.assertEqual(result, {})


# ══════════════════════════════════════════════════════════════════════════════
# 3. _extract_text
# ══════════════════════════════════════════════════════════════════════════════


class TestExtractText(unittest.TestCase):
    """_extract_text pulls plain text from varied result types."""

    def setUp(self):
        from app.core.workflow_engine import _extract_text
        self.extract = _extract_text

    def test_string_passthrough(self):
        self.assertEqual(self.extract("hello"), "hello")

    def test_dict_with_text_key(self):
        self.assertEqual(self.extract({"text": "result"}), "result")

    def test_dict_with_content_key(self):
        self.assertEqual(self.extract({"content": "body"}), "body")

    def test_dict_text_preferred_over_content(self):
        # "text" key takes priority
        self.assertEqual(self.extract({"text": "t", "content": "c"}), "t")

    def test_dict_fallback_to_str(self):
        d = {"other": "value"}
        result = self.extract(d)
        self.assertIsInstance(result, str)

    def test_integer_converted_to_str(self):
        result = self.extract(42)
        self.assertEqual(result, "42")

    def test_none_converted_to_str(self):
        result = self.extract(None)
        self.assertEqual(result, "None")


# ══════════════════════════════════════════════════════════════════════════════
# 4. call_llm_json — JSON parsing and fence stripping
# ══════════════════════════════════════════════════════════════════════════════


class TestCallLlmJson(unittest.TestCase):
    """call_llm_json strips markdown fences and parses JSON from LLM responses."""

    def _make_call_llm_json(self, fake_response: str):
        """Return call_llm_json with call_llm patched to return fake_response."""
        from app.core.workflow_engine import call_llm_json

        def _fake_call_llm(prompt, system="", model_mode="auto",
                           max_tokens=8192, call_timeout=None):
            return fake_response

        return call_llm_json, _fake_call_llm

    def test_plain_json_object_parsed(self):
        from app.core.workflow_engine import call_llm_json
        with patch("app.core.workflow_engine.call_llm", return_value='{"key": "value"}'):
            result = call_llm_json("prompt")
        self.assertEqual(result, {"key": "value"})

    def test_plain_json_array_parsed(self):
        from app.core.workflow_engine import call_llm_json
        with patch("app.core.workflow_engine.call_llm", return_value='[1, 2, 3]'):
            result = call_llm_json("prompt")
        self.assertEqual(result, [1, 2, 3])

    def test_json_fence_stripped(self):
        from app.core.workflow_engine import call_llm_json
        fenced = '```json\n{"a": 1}\n```'
        with patch("app.core.workflow_engine.call_llm", return_value=fenced):
            result = call_llm_json("prompt")
        self.assertEqual(result, {"a": 1})

    def test_plain_fence_stripped(self):
        from app.core.workflow_engine import call_llm_json
        fenced = '```\n{"b": 2}\n```'
        with patch("app.core.workflow_engine.call_llm", return_value=fenced):
            result = call_llm_json("prompt")
        self.assertEqual(result, {"b": 2})

    def test_json_embedded_in_prose_extracted(self):
        from app.core.workflow_engine import call_llm_json
        prose = 'Here is the result: {"score": 5} end'
        with patch("app.core.workflow_engine.call_llm", return_value=prose):
            result = call_llm_json("prompt")
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("score"), 5)

    def test_invalid_json_returns_raw_string(self):
        from app.core.workflow_engine import call_llm_json
        with patch("app.core.workflow_engine.call_llm", return_value="not json at all"):
            result = call_llm_json("prompt")
        self.assertIsInstance(result, str)

    def test_system_prompt_json_reminder_appended(self):
        from app.core.workflow_engine import call_llm_json
        captured = {}
        def _capture_call_llm(prompt, system="", **kwargs):
            captured["system"] = system
            return '{"ok": true}'
        with patch("app.core.workflow_engine.call_llm", side_effect=_capture_call_llm):
            call_llm_json("prompt", system="Be concise.")
        # The JSON reminder should be appended when "json" is not already in system
        self.assertIn("JSON", captured["system"])

    def test_system_prompt_with_json_not_double_appended(self):
        from app.core.workflow_engine import call_llm_json
        captured = {}
        def _capture_call_llm(prompt, system="", **kwargs):
            captured["system"] = system
            return '{"ok": true}'
        with patch("app.core.workflow_engine.call_llm", side_effect=_capture_call_llm):
            call_llm_json("prompt", system="Output as json only.")
        # "json" is already in system prompt → no duplication
        self.assertEqual(captured["system"], "Output as json only.")


# ══════════════════════════════════════════════════════════════════════════════
# 5. WorkflowExecutor base class
# ══════════════════════════════════════════════════════════════════════════════


class TestWorkflowExecutorBase(unittest.TestCase):
    """WorkflowExecutor.run() wraps execution with status / done events."""

    def _collect(self, executor, params):
        """Collect all SSE strings produced by executor.run(params)."""
        return list(executor.run(params))

    def test_run_yields_status_first(self):
        from app.core.workflow_engine import WorkflowExecutor

        class NopExecutor(WorkflowExecutor):
            WORKFLOW_ID = "nop"
            WORKFLOW_NAME = "Nop"
            def execute(self, params, yield_event):
                return
                yield  # make it a generator

        events = self._collect(NopExecutor(), {})
        first = json.loads(events[0][len("data: "):].strip())
        self.assertEqual(first["type"], "status")

    def test_run_yields_done_last(self):
        from app.core.workflow_engine import WorkflowExecutor

        class NopExecutor(WorkflowExecutor):
            WORKFLOW_ID = "nop"
            WORKFLOW_NAME = "Nop"
            def execute(self, params, yield_event):
                return
                yield

        events = self._collect(NopExecutor(), {})
        last = json.loads(events[-1][len("data: "):].strip())
        self.assertEqual(last["type"], "done")

    def test_run_yields_error_on_exception(self):
        from app.core.workflow_engine import WorkflowExecutor

        class BrokenExecutor(WorkflowExecutor):
            WORKFLOW_ID = "broken"
            WORKFLOW_NAME = "Broken"
            def execute(self, params, yield_event):
                raise RuntimeError("intentional failure")
                yield

        events = self._collect(BrokenExecutor(), {})
        types = [json.loads(e[len("data: "):].strip())["type"] for e in events]
        self.assertIn("error", types)
        self.assertIn("done", types)

    def test_execute_not_implemented_raises(self):
        from app.core.workflow_engine import WorkflowExecutor

        ex = WorkflowExecutor()
        with self.assertRaises(NotImplementedError):
            list(ex.execute({}, lambda x: None))

    def test_run_passes_through_yielded_events(self):
        from app.core.workflow_engine import WorkflowExecutor, sse_step_start, sse_step_done

        class SimpleExecutor(WorkflowExecutor):
            WORKFLOW_ID = "simple"
            WORKFLOW_NAME = "Simple"
            def execute(self, params, yield_event):
                yield sse_step_start("s1", "Step 1")
                yield sse_step_done("s1", "Step 1 done")

        events = self._collect(SimpleExecutor(), {})
        types = [json.loads(e[len("data: "):].strip())["type"] for e in events]
        self.assertIn("step_start", types)
        self.assertIn("step_done", types)

    def test_workflow_id_and_name_defaults(self):
        from app.core.workflow_engine import WorkflowExecutor
        ex = WorkflowExecutor()
        self.assertEqual(ex.WORKFLOW_ID, "base")
        self.assertEqual(ex.WORKFLOW_NAME, "基础工作流")


class TestWorkflowExecutorSaveOutputFile(unittest.TestCase):
    """WorkflowExecutor.save_output_file creates a path with the correct suffix."""

    def test_docx_suffix(self):
        from app.core.workflow_engine import WorkflowExecutor
        path = WorkflowExecutor.save_output_file(".docx")
        self.assertTrue(str(path).endswith(".docx"))

    def test_xlsx_suffix(self):
        from app.core.workflow_engine import WorkflowExecutor
        path = WorkflowExecutor.save_output_file(".xlsx")
        self.assertTrue(str(path).endswith(".xlsx"))

    def test_unique_filenames(self):
        from app.core.workflow_engine import WorkflowExecutor
        p1 = WorkflowExecutor.save_output_file(".docx")
        p2 = WorkflowExecutor.save_output_file(".docx")
        self.assertNotEqual(p1, p2)

    def test_parent_directory_exists(self):
        from app.core.workflow_engine import WorkflowExecutor
        path = WorkflowExecutor.save_output_file(".txt")
        self.assertTrue(path.parent.exists())


if __name__ == "__main__":
    unittest.main()
