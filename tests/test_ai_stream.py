#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests for the File Assistant AI stream endpoint.

Validates:
1. SSE streaming response format
2. All action types (polish, translate, find_replace, find_reference, etc.)
3. Full-text context injection
4. Chart rerun endpoint
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Ensure project root is importable ──
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── Helper ──

def parse_sse_events(response_data: bytes) -> list:
    """Parse SSE response bytes into list of event dicts."""
    events = []
    for chunk in response_data.decode("utf-8", errors="replace").split("\n\n"):
        chunk = chunk.strip()
        if chunk.startswith("data: "):
            try:
                events.append(json.loads(chunk[6:]))
            except json.JSONDecodeError:
                pass
    return events


# ── Mock LLM fixture ──

class FakeChunk:
    def __init__(self, text):
        self.text = text


def _make_fake_stream(prompt_keyword_responses: dict):
    """Create a fake generate_content_stream that returns deterministic output."""
    def fake_stream(model, contents, config=None):
        for keyword, response in prompt_keyword_responses.items():
            if keyword in str(contents):
                yield FakeChunk(response)
                return
        yield FakeChunk("默认 AI 回复。")
    return fake_stream


@pytest.fixture
def app_client():
    """Create a Flask test client with mocked LLM."""
    # Mock the Gemini client before importing app
    mock_client = MagicMock()
    mock_client.models.generate_content_stream = _make_fake_stream({
        "润色": "这是一段经过精心润色的优雅文本。",
        "翻译": "This is the translated text.",
        "总结": "本文主要讨论了三个核心观点。",
        "替换": '{"replacements": [{"from": "你好", "to": "您好"}, {"from": "世界", "to": "地球"}], "summary": "共替换 2 处"}',
        "引用": "1. 【论文】Smith et al. (2024) — AI辅助写作综述\n   链接：待核实",
        "检查": "1. 【第2行】你好 → 您好（更正式）",
        "改写": "这是用全新措辞表达的内容。",
        "续写": "接下来，我们将探讨更深层次的问题。",
    })

    with patch.dict("sys.modules", {}):
        # We need to patch the client object in web.app
        try:
            from web.app import app
            app.config["TESTING"] = True
            # Patch the client and types (to avoid google.genai circular import under test)
            import web.app as web_app_module
            original_client = getattr(web_app_module, "client", None)
            original_api_key = getattr(web_app_module, "API_KEY", None)
            original_types = getattr(web_app_module, "types", None)
            mock_types = MagicMock()
            mock_types.GenerateContentConfig.return_value = MagicMock()
            web_app_module.client = mock_client
            web_app_module.API_KEY = "test-key-mock"
            web_app_module.types = mock_types
            yield app.test_client()
            # Restore
            web_app_module.client = original_client
            web_app_module.API_KEY = original_api_key
            web_app_module.types = original_types
        except ImportError as e:
            pytest.skip(f"Cannot import web.app: {e}")


# ══════════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════════

class TestEditorAIStream:
    """Tests for POST /api/editor/ai/stream"""

    def test_polish_returns_sse(self, app_client):
        """润色请求应返回 SSE 流，包含 token 和 done 事件"""
        resp = app_client.post("/api/editor/ai/stream", json={
            "action": "polish",
            "selection": "这段文字需要被润色一下。",
        })
        assert resp.status_code == 200
        assert "text/event-stream" in resp.content_type
        events = parse_sse_events(resp.data)
        assert len(events) >= 1
        types = {e["type"] for e in events}
        assert "token" in types or "done" in types

    def test_polish_with_full_text_context(self, app_client):
        """润色请求带 full_text 应正常工作"""
        resp = app_client.post("/api/editor/ai/stream", json={
            "action": "polish",
            "selection": "这段文字需要润色。",
            "full_text": "第一段落。这段文字需要润色。第三段落结尾。",
        })
        assert resp.status_code == 200
        events = parse_sse_events(resp.data)
        assert any(e.get("type") == "token" for e in events)

    def test_translate_action(self, app_client):
        """翻译请求应返回翻译结果"""
        resp = app_client.post("/api/editor/ai/stream", json={
            "action": "translate",
            "selection": "你好世界",
        })
        assert resp.status_code == 200
        events = parse_sse_events(resp.data)
        assert len(events) >= 1

    def test_find_replace_action(self, app_client):
        """查找替换请求应返回 JSON 格式替换列表"""
        resp = app_client.post("/api/editor/ai/stream", json={
            "action": "find_replace",
            "instruction": "把所有你好替换成您好",
            "full_text": "你好世界，你好中国，你好大家。",
        })
        assert resp.status_code == 200
        events = parse_sse_events(resp.data)
        assert len(events) >= 1

    def test_find_reference_action(self, app_client):
        """引用查找请求应返回引用列表"""
        resp = app_client.post("/api/editor/ai/stream", json={
            "action": "find_reference",
            "selection": "人工智能在教育中的应用越来越广泛。",
            "full_text": "本文探讨人工智能在教育中的应用。",
        })
        assert resp.status_code == 200
        events = parse_sse_events(resp.data)
        assert len(events) >= 1

    def test_empty_selection_returns_error(self, app_client):
        """空选区应返回错误"""
        resp = app_client.post("/api/editor/ai/stream", json={
            "action": "polish",
            "selection": "",
            "instruction": "",
        })
        assert resp.status_code == 200
        events = parse_sse_events(resp.data)
        assert any(e.get("type") == "error" for e in events)

    def test_custom_instruction_with_context(self, app_client):
        """自定义指令应带上选区和全文上下文"""
        resp = app_client.post("/api/editor/ai/stream", json={
            "action": "custom_instruction",
            "selection": "AI技术",
            "instruction": "用更学术的方式描述",
            "full_text": "本篇论文探讨AI技术的发展趋势。",
        })
        assert resp.status_code == 200
        events = parse_sse_events(resp.data)
        assert len(events) >= 1


class TestChartRerun:
    """Tests for POST /api/editor/ai/chart-rerun"""

    def test_empty_code_returns_error(self, app_client):
        """空代码应返回错误"""
        resp = app_client.post("/api/editor/ai/chart-rerun", json={
            "code": "",
            "lang": "python",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["error"]

    def test_simple_python_code(self, app_client):
        """简单 Python 代码应成功执行"""
        resp = app_client.post("/api/editor/ai/chart-rerun", json={
            "code": "print('hello')",
            "lang": "python",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert "hello" in (data.get("stdout") or "")

    def test_chart_generation_code(self, app_client):
        """图表生成代码应产出图片文件"""
        code = (
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            "plt.plot([1, 2, 3], [1, 4, 9])\n"
            "plt.savefig('chart.png', dpi=72)\n"
            "plt.close()\n"
        )
        resp = app_client.post("/api/editor/ai/chart-rerun", json={
            "code": code,
            "lang": "python",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("error") is None or data["error"] == ""
        assert "chart.png" in (data.get("files") or {})


class TestBuildEditorPrompt:
    """Tests for _build_editor_prompt function"""

    def test_polish_includes_full_text(self):
        """润色 prompt 应包含全文上下文"""
        try:
            from web.app import _build_editor_prompt
        except ImportError:
            pytest.skip("Cannot import _build_editor_prompt")

        prompt = _build_editor_prompt(
            "polish",
            "需要润色的内容",
            "",
            "全文开头。需要润色的内容。全文结尾。",
        )
        assert "需要润色的内容" in prompt
        assert "全文" in prompt or "文档" in prompt

    def test_find_replace_prompt_structure(self):
        """查找替换 prompt 应包含 JSON 格式要求"""
        try:
            from web.app import _build_editor_prompt
        except ImportError:
            pytest.skip("Cannot import _build_editor_prompt")

        prompt = _build_editor_prompt(
            "find_replace",
            "",
            "把你好替换成您好",
            "你好世界，你好中国。",
        )
        assert "replacements" in prompt
        assert "JSON" in prompt

    def test_find_reference_prompt(self):
        """引用查找 prompt 应包含来源格式要求"""
        try:
            from web.app import _build_editor_prompt
        except ImportError:
            pytest.skip("Cannot import _build_editor_prompt")

        prompt = _build_editor_prompt(
            "find_reference",
            "AI 在教育中的应用",
            "",
            "文档全文内容",
        )
        assert "参考" in prompt or "引用" in prompt or "来源" in prompt


class TestPromptContextTruncation:
    """Test that full_text context is properly truncated."""

    def test_long_full_text_truncated(self):
        """超长全文应被截断以控制 token"""
        try:
            from web.app import _build_editor_prompt
        except ImportError:
            pytest.skip("Cannot import _build_editor_prompt")

        long_text = "A" * 20000
        prompt = _build_editor_prompt("polish", "选中内容", "", long_text)
        # Prompt should not contain the entire 20K text
        assert len(prompt) < 15000


class TestLocalModelMode:
    """Tests that model_mode='local' properly routes to Ollama (not cloud) in editor_ai_stream."""

    def test_local_mode_uses_ollama_when_alive(self, app_client):
        """model_mode=local + Ollama alive → response comes from Ollama, not cloud."""
        from unittest.mock import patch, MagicMock

        # Mock Ollama provider to return a known response
        mock_provider = MagicMock()
        mock_provider.generate_content.return_value = iter([
            {"content": "本地", "tool_calls": [], "usage": {}},
            {"content": "Ollama", "tool_calls": [], "usage": {}},
            {"content": "响应", "tool_calls": [], "usage": {}},
        ])

        with patch("app.core.socket_handler._is_ollama_alive", return_value=True), \
             patch("app.core.socket_handler._get_local_provider", return_value=mock_provider):
            resp = app_client.post("/api/editor/ai/stream", json={
                "action": "polish",
                "selection": "需要润色的文字",
                "model_mode": "local",
            })

        assert resp.status_code == 200
        events = parse_sse_events(resp.data)
        token_texts = "".join(e.get("text", "") for e in events if e.get("type") == "token")
        assert "Ollama" in token_texts or "本地" in token_texts

    def test_local_mode_ollama_not_running_returns_error(self, app_client):
        """model_mode=local + Ollama not running → returns error event."""
        from unittest.mock import patch

        with patch("app.core.socket_handler._is_ollama_alive", return_value=False):
            resp = app_client.post("/api/editor/ai/stream", json={
                "action": "polish",
                "selection": "需要润色的文字",
                "model_mode": "local",
            })

        assert resp.status_code == 200
        events = parse_sse_events(resp.data)
        error_events = [e for e in events if e.get("type") == "error"]
        assert len(error_events) > 0, "Expected an error event when Ollama is not running"

    def test_find_replace_sends_model_mode(self):
        """Verify _sendViaFindReplace in AIPanel.js passes model_mode."""
        # Read the built source to verify model_mode is included
        import pathlib
        src = pathlib.Path("web/univer-editor/src/AIPanel.js").read_text(encoding="utf-8")
        # Check that _sendViaFindReplace sends model_mode
        find_replace_section = src[src.find("_sendViaFindReplace"):]
        fetch_call = find_replace_section[:find_replace_section.find("}\n  }")]
        assert "model_mode" in fetch_call, "_sendViaFindReplace should include model_mode"