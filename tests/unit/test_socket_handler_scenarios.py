# -*- coding: utf-8 -*-
"""
Unit tests for socket_handler.py — end-to-end scenario coverage.

Scenarios covered:
  1. _parse_tool_calls — all formats and edge cases
     a. canonical <TOOL>...</TOOL>
     b. space-in-closing-tag  </ TOOL>  (model bug, fixed)
     c. lowercase </tool>
     d. orphaned closing tag left after partial match
     e. code-fenced JSON  ```json {...} ```
     f. bare JSON line (no wrapper)
     g. unknown "type" is ignored
     h. invalid JSON is ignored
     i. multi-line value inside TOOL tag
     j. multiple tool calls in one response
     k. clean_text has no leftover JSON / tag noise

  2. _is_online_failure — classifies exceptions correctly
     a. API key expired (400 INVALID_ARGUMENT)
     b. 503 / unavailable
     c. timeout / timed out
     d. resource exhausted / 429
     e. unrelated error → False

  3. _get_local_provider — model selection heuristic
     a. picks the 7b/8b model when multiple models available
     b. falls back to first model when none match size heuristic
     c. falls back to OllamaLLMProvider(model=None) on network error

  4. Insert-at-cursor fallback logic (isolated unit)
     a. synthesises set_html from last assistant turn when no tool call
     b. skips fallback if AI already returned a tool call
     c. skips fallback for non-docx/pptx file types
     d. skips fallback if history has no usable assistant turn
     e. strips existing TOOL tags when extracting history content

  5. Selection context — prompt construction
     a. selection text is prepended to full_prompt in [用户选中的文字] block
     b. no selection → plain prompt with history
"""

from __future__ import annotations

import importlib
import json
import sys
import types
from unittest.mock import MagicMock, patch

# ─── helpers ──────────────────────────────────────────────────────────────────


def _import_parse_tool_calls():
    """Import _parse_tool_calls without requiring the full Flask/SocketIO stack."""
    # Stub heavy deps so the module can be imported in a bare test environment
    stub_names = (
        "flask_socketio",
        "flask",
        "flask.request",
        "app.core.llm.provider_factory",
        "app.core.llm.ollama_llm_provider",
        "app.core.sandbox",
        "web.settings",
        "web.app",
    )
    missing = object()
    originals = {name: sys.modules.get(name, missing) for name in stub_names}

    try:
        for mod_name in stub_names:
            if mod_name not in sys.modules:
                sys.modules[mod_name] = MagicMock()

        # flask_socketio.SocketIO must be importable
        fsi = sys.modules.setdefault("flask_socketio", MagicMock())
        fsi.SocketIO = MagicMock

        import importlib as _il

        spec = _il.util.spec_from_file_location(
            "socket_handler_test",
            "app/core/socket_handler.py",
        )
        mod = _il.util.module_from_spec(spec)
        # Provide a dummy socketio attribute so module-level code doesn't crash
        mod.socketio = MagicMock()
        spec.loader.exec_module(mod)
        return mod
    finally:
        for name, original in originals.items():
            if original is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


_sh = None


def _get_sh():
    global _sh
    if _sh is None:
        _sh = _import_parse_tool_calls()
    return _sh


# ─── 1. _parse_tool_calls ─────────────────────────────────────────────────────


class TestParseToolCalls:

    def _parse(self, text):
        return _get_sh()._parse_tool_calls(text)

    # 1a — canonical format
    def test_canonical_tool_tag(self):
        text = 'Done.<TOOL>{"type":"set_html","value":"<p>hi</p>"}</TOOL>'
        clean, calls = self._parse(text)
        assert len(calls) == 1
        assert calls[0] == {"type": "set_html", "value": "<p>hi</p>"}
        assert "<TOOL>" not in clean
        assert "set_html" not in clean

    # 1b — space in closing tag  </ TOOL>  (qwen2.5 model bug)
    def test_space_in_closing_tag(self):
        text = 'Sure.<TOOL>{"type":"set_html","value":"<p>你好</p>"}</ TOOL>'
        clean, calls = self._parse(text)
        assert len(calls) == 1
        assert calls[0]["type"] == "set_html"
        assert calls[0]["value"] == "<p>你好</p>"
        # No TOOL noise in clean text
        assert "TOOL" not in clean
        assert "set_html" not in clean

    # 1c — lowercase closing tag
    def test_lowercase_closing_tag(self):
        text = '<TOOL>{"type":"set_html","value":"<p>x</p>"}</tool>'
        clean, calls = self._parse(text)
        assert len(calls) == 1
        assert "TOOL" not in clean.upper()

    # 1d — orphaned closing tag (no opening match)
    def test_orphaned_closing_tag_stripped(self):
        text = '{"type":"set_html","value":"<p>x</p>"}</ TOOL>'
        clean, calls = self._parse(text)
        # The JSON is caught by pass-3 bare-JSON, the orphaned tag is stripped
        assert "TOOL" not in clean
        # The bare-JSON pass should have caught the set_html
        assert any(c.get("type") == "set_html" for c in calls)

    # 1e — code-fenced JSON
    def test_code_fenced_json(self):
        text = 'Here:\n```json\n{"type":"set_html","value":"<p>v</p>"}\n```\ndone'
        clean, calls = self._parse(text)
        assert len(calls) == 1
        assert calls[0]["type"] == "set_html"
        assert "```" not in clean

    # 1f — bare JSON on its own line
    def test_bare_json_line(self):
        text = 'Response:\n{"type":"set_html","value":"<p>bare</p>"}\nEnd'
        clean, calls = self._parse(text)
        assert len(calls) == 1
        assert calls[0]["value"] == "<p>bare</p>"
        assert "set_html" not in clean

    # 1g — unknown type is ignored (not added to tool_calls)
    def test_unknown_type_ignored(self):
        text = '<TOOL>{"type":"unknown_action","value":"x"}</TOOL>'
        clean, calls = self._parse(text)
        assert calls == []

    # 1h — invalid JSON is ignored
    def test_invalid_json_ignored(self):
        text = "<TOOL>not json at all</TOOL>"
        clean, calls = self._parse(text)
        assert calls == []
        assert clean == ""  # tag body stripped regardless

    # 1i — multi-line value inside TOOL tag
    def test_multiline_value(self):
        payload = {"type": "set_html", "value": "<p>line1</p><p>line2</p>"}
        text = f"<TOOL>{json.dumps(payload)}</TOOL>"
        clean, calls = self._parse(text)
        assert len(calls) == 1
        assert calls[0]["value"] == "<p>line1</p><p>line2</p>"

    # 1j — multiple tool calls
    def test_multiple_tool_calls(self):
        tc1 = json.dumps({"type": "set_html", "value": "<p>a</p>"})
        tc2 = json.dumps({"type": "set_cell", "r": 0, "c": 0, "value": "v"})
        text = f"<TOOL>{tc1}</TOOL> then <TOOL>{tc2}</TOOL>"
        clean, calls = self._parse(text)
        assert len(calls) == 2
        assert calls[0]["type"] == "set_html"
        assert calls[1]["type"] == "set_cell"

    # 1k — clean text contains no JSON / tag noise
    def test_clean_text_has_no_noise(self):
        text = '已翻译。<TOOL>{"type":"set_html","value":"<p>hello</p>"}</TOOL>如有需要请告知。'
        clean, _ = self._parse(text)
        assert "type" not in clean
        assert "set_html" not in clean
        assert "TOOL" not in clean
        assert "已翻译" in clean
        assert "如有需要请告知" in clean


# ─── 2. _is_online_failure ────────────────────────────────────────────────────


class TestIsOnlineFailure:

    def _check(self, msg):
        return _get_sh()._is_online_failure(Exception(msg))

    def test_api_key_expired(self):
        assert self._check("400 INVALID_ARGUMENT. API key expired.")

    def test_invalid_argument_lower(self):
        assert self._check("invalid_argument something")

    def test_api_key_lower(self):
        assert self._check("api key not valid")

    def test_503_unavailable(self):
        assert self._check("503 service unavailable")

    def test_timed_out(self):
        assert self._check("request timed out after 30s")

    def test_resource_exhausted(self):
        assert self._check("ResourceExhausted: quota exceeded")

    def test_429_too_many(self):
        assert self._check("429 too many requests")

    def test_overloaded(self):
        assert self._check("model overloaded, retry later")

    def test_stream_stalled(self):
        assert self._check("stream stalled")

    def test_400_in_string(self):
        assert self._check("HTTP 400 error")

    def test_unrelated_valueerror(self):
        assert not self._check("list index out of range")

    def test_unrelated_key_error(self):
        assert not self._check("KeyError: 'model'")

    def test_import_error(self):
        assert not self._check("No module named 'mammoth'")


# ─── 3. _get_local_provider ───────────────────────────────────────────────────


class TestGetLocalProvider:

    def _run(self, models_list):
        """Call _get_local_provider with a faked /api/tags response."""
        sh = _get_sh()
        fake_response_body = json.dumps(
            {"models": [{"name": m} for m in models_list]}
        ).encode()

        class FakeResponse:
            def read(self):
                return fake_response_body

            def close(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        mock_provider = MagicMock(name="OllamaLLMProvider_instance")
        mock_cls = MagicMock(return_value=mock_provider)
        mock_opener = MagicMock()
        mock_opener.open.return_value = FakeResponse()

        with patch.dict(
            sys.modules,
            {"app.core.llm.ollama_llm_provider": MagicMock(OllamaLLMProvider=mock_cls)},
        ):
            with patch("urllib.request.build_opener", return_value=mock_opener):
                result = sh._get_local_provider()

        return result, mock_cls

    def test_picks_7b_model(self):
        _, cls = self._run(["llama3:latest", "qwen2.5:7b", "mistral:7b"])
        # called with one of the 7b models
        args = cls.call_args[1] if cls.call_args[1] else {"model": cls.call_args[0][0]}
        assert "7b" in args.get("model", "")

    def test_picks_8b_over_smaller(self):
        _, cls = self._run(["phi3:mini", "llama3.1:8b"])
        args = cls.call_args[1] if cls.call_args[1] else {"model": cls.call_args[0][0]}
        assert "8b" in args.get("model", "")

    def test_falls_back_to_first_model_when_no_size_match(self):
        _, cls = self._run(["phi3:mini", "tinyllama:latest"])
        args = cls.call_args[1] if cls.call_args[1] else {"model": cls.call_args[0][0]}
        assert args.get("model") == "phi3:mini"

    def test_falls_back_to_none_on_network_error(self):
        sh = _get_sh()
        mock_cls = MagicMock()
        with patch.dict(
            sys.modules,
            {"app.core.llm.ollama_llm_provider": MagicMock(OllamaLLMProvider=mock_cls)},
        ):
            mock_opener = MagicMock()
            mock_opener.open.side_effect = OSError("connection refused")
            with patch("urllib.request.build_opener", return_value=mock_opener):
                sh._get_local_provider()
        mock_cls.assert_called_once_with(model=None)


# ─── 4. Insert-at-cursor fallback logic ───────────────────────────────────────


class TestInsertAtCursorFallback:
    """
    Tests the synthesise-set_html-from-history logic in _task().
    We isolate it by calling the logic directly (extracted helper).
    """

    def _run_fallback(self, prompt, file_type, tool_calls, history):
        """
        Reproduce the fallback block from socket_handler._task() in isolation.
        Returns (tool_calls_after_fallback, synthesised).
        """
        import html as _html
        import re

        _INSERT_TRIGGERS = (
            "在光标处插入",
            "插入文档",
            "插入到文档",
            "请插入",
            "插入内容",
        )
        synthesised = False

        if (
            not tool_calls
            and file_type in ("docx", "pptx")
            and any(t in prompt for t in _INSERT_TRIGGERS)
        ):
            last_ai_content = ""
            for turn in reversed(history or []):
                if turn.get("role") == "assistant":
                    c = turn.get("content", "").strip()
                    c_clean = re.sub(
                        r"<TOOL>.*?</TOOL>", "", c, flags=re.DOTALL
                    ).strip()
                    if len(c_clean) > 10:
                        last_ai_content = c_clean
                        break
            if last_ai_content:
                paragraphs = [
                    p.strip() for p in last_ai_content.split("\n") if p.strip()
                ]
                html_val = "".join(f"<p>{_html.escape(p)}</p>" for p in paragraphs)
                tool_calls = [{"type": "set_html", "value": html_val}]
                synthesised = True

        return tool_calls, synthesised

    # 4a — synthesises tool call from last assistant turn
    def test_synthesises_from_last_assistant_turn(self):
        history = [
            {"role": "user", "content": "写个冷笑话"},
            {"role": "assistant", "content": "为什么电脑经常生病？因为它窗户太多！"},
        ]
        calls, syn = self._run_fallback("请在光标处插入", "docx", [], history)
        assert syn is True
        assert len(calls) == 1
        assert calls[0]["type"] == "set_html"
        assert "为什么电脑经常生病" in calls[0]["value"]

    # 4b — skips when AI already returned a tool call
    def test_skips_when_tool_call_exists(self):
        history = [{"role": "assistant", "content": "做好了"}]
        existing = [{"type": "set_html", "value": "<p>content</p>"}]
        calls, syn = self._run_fallback("请在光标处插入", "docx", existing, history)
        assert syn is False
        assert calls == existing  # unchanged

    # 4c — skips for non-docx/pptx types (e.g. xlsx)
    def test_skips_non_docx_type(self):
        history = [{"role": "assistant", "content": "这是一段很长的内容啊啊啊啊啊啊"}]
        calls, syn = self._run_fallback("请在光标处插入", "xlsx", [], history)
        assert syn is False
        assert calls == []

    # 4d — skips when history has no usable assistant turn
    def test_skips_empty_history(self):
        calls, syn = self._run_fallback("请在光标处插入", "docx", [], [])
        assert syn is False
        assert calls == []

    # 4e — strips TOOL tags from history content before using it
    def test_strips_tool_tags_from_history(self):
        raw = '已完成。<TOOL>{"type":"set_html","value":"<p>x</p>"}</TOOL>'
        history = [{"role": "assistant", "content": raw}]
        # After stripping TOOL, remaining text is "已完成。" — only 4 chars → too short
        calls, syn = self._run_fallback("请在光标处插入", "docx", [], history)
        assert syn is False  # "已完成。" is 4 chars < 10 threshold

    def test_strips_tool_tags_keeps_long_prefix(self):
        # Longer prefix text survives the strip and becomes the inserted content
        raw = '这是一段经过AI生成的内容，内容很丰富。<TOOL>{"type":"set_html","value":"<p>x</p>"}</TOOL>'
        history = [{"role": "assistant", "content": raw}]
        calls, syn = self._run_fallback("请在光标处插入", "docx", [], history)
        assert syn is True
        assert "这是一段经过AI生成的内容" in calls[0]["value"]

    # 4f — trigger keywords all work
    def test_various_trigger_keywords(self):
        history = [
            {
                "role": "assistant",
                "content": "写好了，内容如下：Hello World！！！！！！",
            }
        ]
        for trigger in ("在光标处插入", "插入文档", "插入到文档", "请插入", "插入内容"):
            calls, syn = self._run_fallback(trigger, "docx", [], history)
            assert syn is True, f"trigger '{trigger}' should fire fallback"

    # 4g — HTML-escapes special chars in content
    def test_html_escapes_content(self):
        history = [
            {"role": "assistant", "content": "1 < 2 & 3 > 0 — this is a long sentence"}
        ]
        calls, syn = self._run_fallback("请在光标处插入", "docx", [], history)
        assert syn is True
        assert "&lt;" in calls[0]["value"]
        assert "&amp;" in calls[0]["value"]
        assert "&gt;" in calls[0]["value"]


# ─── 5. Selection context — prompt construction ───────────────────────────────


class TestSelectionContext:
    """
    Tests that pinned selection text is correctly prepended to the LLM prompt.
    Mirrors the logic in _task() around the `selection` variable.
    """

    def _build_prompt(self, selection: str, user_prompt: str, history=None):
        """Reproduce the prompt-building block from _task()."""
        MAX_HISTORY_TURNS = 10
        recent_history = (history or [])[-MAX_HISTORY_TURNS * 2 :]
        history_text = ""
        if recent_history:
            parts = []
            for turn in recent_history:
                role = turn.get("role", "")
                content = turn.get("content", "")
                if role == "user":
                    parts.append(f"用户：{content}")
                elif role == "assistant":
                    parts.append(f"Koto AI：{content}")
            history_text = "\n".join(parts) + "\n\n"

        if selection:
            full_prompt = (
                f'[用户选中的文字]\n"{selection}"\n\n'
                f"{history_text}用户：{user_prompt}"
            )
        else:
            full_prompt = f"{history_text}用户：{user_prompt}"
        return full_prompt

    def test_selection_prepended(self):
        prompt = self._build_prompt("Hello world", "翻译成中文")
        assert prompt.startswith("[用户选中的文字]")
        assert '"Hello world"' in prompt
        assert "翻译成中文" in prompt

    def test_no_selection_plain_prompt(self):
        prompt = self._build_prompt("", "写个冷笑话")
        assert "[用户选中的文字]" not in prompt
        assert "用户：写个冷笑话" in prompt

    def test_selection_appears_before_history(self):
        history = [
            {"role": "user", "content": "上一条"},
            {"role": "assistant", "content": "好的"},
        ]
        prompt = self._build_prompt("选中文字", "分析", history)
        sel_pos = prompt.index("[用户选中的文字]")
        hist_pos = prompt.index("Koto AI：好的")
        assert sel_pos < hist_pos

    def test_history_included_with_selection(self):
        history = [
            {"role": "user", "content": "问题一"},
            {"role": "assistant", "content": "回答一"},
        ]
        prompt = self._build_prompt("some selected text", "继续", history)
        assert "用户：问题一" in prompt
        assert "Koto AI：回答一" in prompt
        assert "[用户选中的文字]" in prompt

    def test_empty_selection_not_injected(self):
        prompt = self._build_prompt("", "just chat")
        assert (
            '"' not in prompt.split("用户：")[0]
        )  # no quoted block before first user turn
