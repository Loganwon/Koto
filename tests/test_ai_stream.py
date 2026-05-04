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
import io
import re
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
        assert len(events) >= 1

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

    def test_ai_task_action_uses_task_agent(self, app_client):
        """ai_task 应始终走 TaskAgent 的 ReAct 主通路。"""
        captured = {}

        class FakeTaskAgent:
            def __init__(self, socketio=None, model_id="", api_key=None):
                captured["init_model_id"] = model_id

            def execute(self, task, files=None, options=None):
                captured["task"] = task
                captured["files"] = list(files or [])
                captured["options"] = options or {}
                yield 'data: {"type":"plan_summary","text":"正在分析任务..."}\n\n'
                yield 'data: {"type":"step_start","step_id":"s1","text":"读取文件"}\n\n'
                yield 'data: {"type":"verification","status":"completed","summary":"已完成"}\n\n'
                yield 'data: {"type":"done","summary":"task agent done"}\n\n'

        with patch("app.core.agent.task_agent.TaskAgent", FakeTaskAgent), \
             patch.dict("web.app.MODEL_MAP", {"CHAT": "gemini-chat-default", "FILE_TASK": "gemini-file-task-default"}, clear=False):
            resp = app_client.post(
                "/api/editor/ai/stream",
                json={
                    "action": "ai_task",
                    "instruction": "整理当前文件",
                    "full_text": "第一段\n第二段",
                    "file_type": "docx",
                    "file_name": "demo.docx",
                    "model_mode": "LOCAL",
                    "model_id": "local",
                },
            )
            payload = resp.get_data()

        assert resp.status_code == 200
        assert "text/event-stream" in resp.content_type
        assert captured["task"] == "整理当前文件"
        assert captured["options"]["model_mode"] == "local"
        assert captured["options"]["model_id"] == ""
        assert captured["options"]["current_file"] == "demo.docx"
        assert captured["options"]["current_file_name"] == "demo.docx"
        assert captured["files"] and captured["files"][0]["type"] == "docx"
        events = parse_sse_events(payload)
        assert any(e.get("type") == "phase" and e.get("current") == "analysis" for e in events)
        assert any(e.get("type") == "step_start" for e in events)
        assert any(e.get("type") == "verification" for e in events)
        assert any(e.get("type") == "done" for e in events)

    def test_ai_task_runtime_always_uses_task_agent(self, app_client):
        """ai_task 无论文件类型，均走 TaskAgent，不再有 DocAgent 回退。"""
        captured = {}

        class FakeTaskAgent:
            def __init__(self, socketio=None, model_id="", api_key=None):
                captured["task_agent_model_id"] = model_id

            def execute(self, task, files=None, options=None):
                captured["task"] = task
                captured["options"] = options or {}
                yield 'data: {"type":"done","summary":"task agent done"}\n\n'

        with patch("app.core.agent.task_agent.TaskAgent", FakeTaskAgent):
            resp = app_client.post(
                "/api/editor/ai/stream",
                json={
                    "action": "ai_task",
                    "instruction": "整理当前文件",
                    "file_name": "demo.docx",
                    "file_type": "docx",
                },
            )
            payload = resp.get_data()

        assert resp.status_code == 200
        assert captured["task"] == "整理当前文件"
        events = parse_sse_events(payload)
        assert any(e.get("type") == "done" and e.get("summary") == "task agent done" for e in events)

    def test_ai_task_any_file_type_uses_task_agent(self, app_client):
        """无论是 docx、xlsx 还是长文本，ai_task 均使用 TaskAgent。"""
        captured = {}

        class FakeTaskAgent:
            def __init__(self, socketio=None, model_id="", api_key=None):
                captured["init_model_id"] = model_id

            def execute(self, task, files=None, options=None):
                captured["task"] = task
                captured["files"] = list(files or [])
                captured["options"] = options or {}
                yield 'data: {"type":"done","summary":"done"}\n\n'

        long_text = ("第一段需要润色。\n\n" * 500).strip()

        with patch("app.core.agent.task_agent.TaskAgent", FakeTaskAgent):
            resp = app_client.post(
                "/api/editor/ai/stream",
                json={
                    "action": "ai_task",
                    "instruction": "润色当前文件",
                    "full_text": long_text,
                    "file_type": "docx",
                    "file_name": "demo.docx",
                    "model_mode": "auto",
                },
            )
            payload = resp.get_data()

        assert resp.status_code == 200
        assert captured["task"] == "润色当前文件"
        assert captured["options"]["current_file_text"] == long_text
        events = parse_sse_events(payload)
        assert any(e.get("type") == "phase" for e in events)
        assert any(e.get("type") == "done" for e in events)

    def test_ai_task_passes_incoming_history_into_runtime_options(self, app_client):
        captured = {}

        class FakeTaskAgent:
            def __init__(self, socketio=None, model_id="", api_key=None):
                captured["init_model_id"] = model_id

            def execute(self, task, files=None, options=None):
                captured["task"] = task
                captured["history"] = list(options.get("history") or [])
                captured["options"] = options or {}
                yield 'data: {"type":"done","summary":"ok"}\n\n'

        history = [
            {"role": "user", "content": "先看一下这个文件"},
            {"role": "assistant", "content": "我已经初步看过了"},
        ]

        with patch("app.core.agent.task_agent.TaskAgent", FakeTaskAgent):
            resp = app_client.post(
                "/api/editor/ai/stream",
                json={
                    "action": "ai_task",
                    "instruction": "继续整理当前文件",
                    "file_name": "demo.docx",
                    "file_type": "docx",
                    "history": history,
                },
            )
            _ = resp.get_data()

        assert resp.status_code == 200
        assert captured["task"] == "继续整理当前文件"
        assert captured["history"] == [
            {"role": "user", "content": "先看一下这个文件"},
            {"role": "model", "content": "我已经初步看过了"},
        ]

    def test_ai_task_loads_persisted_history_when_frontend_omits_history(self, app_client):
        captured = {}

        class FakeTaskAgent:
            def __init__(self, socketio=None, model_id="", api_key=None):
                captured["model_id"] = model_id

            def execute(self, task, files=None, options=None):
                captured["history"] = list(options.get("history") or [])
                captured["options"] = options or {}
                yield 'data: {"type":"done","summary":"ok"}\n\n'

        stored_history = [
            {"role": "user", "parts": ["第一轮任务"]},
            {"role": "model", "parts": ["第一轮结果"]},
        ]

        with patch("app.core.agent.task_agent.TaskAgent", FakeTaskAgent), \
             patch("web.app.session_manager.load", return_value=stored_history):
            resp = app_client.post(
                "/api/editor/ai/stream",
                json={
                    "action": "ai_task",
                    "instruction": "继续处理",
                    "session_id": "editor_demo",
                    "file_name": "demo.docx",
                    "file_type": "docx",
                },
            )
            _ = resp.get_data()

        assert resp.status_code == 200
        assert captured["history"] == [
            {"role": "user", "content": "第一轮任务"},
            {"role": "model", "content": "第一轮结果"},
        ]

    def test_ai_task_persists_runtime_turns_via_session_manager(self, app_client):

        class FakeTaskAgent:
            def __init__(self, socketio=None, model_id="", api_key=None):
                pass

            def execute(self, task, files=None, options=None):
                yield 'data: {"type":"result","output_type":"markdown","data":"已整理内容","summary":"已整理内容"}\n\n'
                yield 'data: {"type":"done","summary":"已整理内容"}\n\n'

        with patch("app.core.agent.task_agent.TaskAgent", FakeTaskAgent), \
             patch("web.app.session_manager.append_user_early") as append_user_early, \
             patch("web.app.session_manager.update_last_model_response") as update_last_model_response:
            resp = app_client.post(
                "/api/editor/ai/stream",
                json={
                    "action": "ai_task",
                    "instruction": "整理当前文件",
                    "session_id": "editor_demo",
                    "file_name": "demo.docx",
                    "file_type": "docx",
                },
            )
            _ = resp.get_data()

        assert resp.status_code == 200
        append_user_early.assert_called_once_with("editor_demo.json", "整理当前文件")
        update_last_model_response.assert_called_once()
        call_args = update_last_model_response.call_args
        assert call_args.args[0] == "editor_demo.json"
        assert call_args.args[1] == "已整理内容"
        assert call_args.kwargs["task"] == "FILE_TASK"
        assert call_args.kwargs["model_name"] == "koto-task-agent"

    def test_workspace_open_file_returns_temp_path(self, app_client):
        resp = app_client.post(
            "/api/v1/workspace/open_file",
            data={"file": (io.BytesIO("hello world".encode("utf-8")), "notes.txt")},
            content_type="multipart/form-data",
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["temp_path"].startswith("tmp/")
        assert data["temp_path"].endswith(".txt")

    def test_main_stream_forwards_plan_and_step_events(self, app_client):
        """主 editor_ai_stream 应转发 KotoAgentLoop 的 plan/step 事件。"""
        from app.core.agent.lifecycle import evt_plan, evt_step_done, evt_step_progress, evt_step_start, evt_task_complete

        def fake_run(self, request):
            yield evt_plan([{"id": "understand", "description": "理解需求"}])
            yield evt_step_start("understand", "理解需求")
            yield evt_step_progress("understand", "正在分析上下文…")
            yield evt_step_done("understand", "理解需求完成")
            yield evt_task_complete(result="处理完成")

        with patch("app.core.agent.agent_loop.KotoAgentLoop.run", fake_run):
            resp = app_client.post(
                "/api/editor/ai/stream",
                json={
                    "action": "polish",
                    "selection": "这段文字需要润色。",
                },
            )
            payload = resp.get_data()

        assert resp.status_code == 200
        events = parse_sse_events(payload)
        assert any(e.get("type") == "plan" for e in events)
        assert any(e.get("type") == "step_start" for e in events)
        assert any(e.get("type") == "step_progress" for e in events)
        assert any(e.get("type") == "step_done" for e in events)
        done_events = [e for e in events if e.get("type") == "done"]
        assert done_events and done_events[0].get("result") == "处理完成"


class TestEditorAIAgent:
    """Tests for POST /api/editor/ai/agent structured progress events."""

    def test_agent_route_emits_structured_step_events(self, app_client):
        from app.core.agent.types import AgentAction, AgentStep, AgentStepType

        class FakeAgent:
            def run(self, input_text, session_id=None, system_context=None):
                yield AgentStep(step_type=AgentStepType.THOUGHT, content="先理解文档问题")
                yield AgentStep(
                    step_type=AgentStepType.ACTION,
                    content="执行搜索",
                    action=AgentAction(tool_name="web_search", tool_args={"query": "AI"}),
                )
                yield AgentStep(
                    step_type=AgentStepType.OBSERVATION,
                    content="找到结果",
                    observation="找到 3 条相关结果",
                )
                yield AgentStep(step_type=AgentStepType.ANSWER, content="最终答案")

        with patch("app.api.agent_routes.get_agent", return_value=FakeAgent()):
            resp = app_client.post(
                "/api/editor/ai/agent",
                json={"query": "帮我分析这份文档", "full_text": "文档内容"},
            )
            payload = resp.get_data()

        assert resp.status_code == 200
        events = parse_sse_events(payload)
        types = [e.get("type") for e in events]
        assert "thought" in types
        assert "step_start" in types
        assert "tool_call" in types
        assert "tool_result" in types
        assert "step_done" in types
        assert "token" in types
        assert "done" in types


class TestChartStream:
    """Tests for POST /api/editor/ai/chart streaming progress."""

    def test_chart_stream_emits_step_events(self, app_client):
        fake_result = {
            "stdout": "",
            "stderr": "",
            "files": {"chart.png": "ZmFrZQ=="},
            "error": "",
        }

        with patch("app.core.sandbox.run_python", return_value=fake_result):
            resp = app_client.post(
                "/api/editor/ai/chart",
                json={"data_context": "类别,值\nA,10", "instruction": "画一个简单图表", "lang": "python"},
            )
            payload = resp.get_data()

        assert resp.status_code == 200
        events = parse_sse_events(payload)
        types = [e.get("type") for e in events]
        assert "step_start" in types
        assert "step_done" in types
        assert "code" in types
        assert "image" in types
        assert "done" in types


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
             patch("app.core.socket_handler._get_local_provider", return_value=mock_provider), \
             patch("app.core.agent.agent_loop._is_ollama_alive", return_value=True), \
             patch("app.core.agent.agent_loop._get_local_provider", return_value=mock_provider):
            resp = app_client.post("/api/editor/ai/stream", json={
                "action": "polish",
                "selection": "需要润色的文字",
                "model_mode": "local",
            })
            # Force stream consumption while patches are active.
            resp_data = resp.get_data()

        assert resp.status_code == 200
        events = parse_sse_events(resp_data)
        token_texts = "".join(e.get("text", "") for e in events if e.get("type") == "token")
        assert "Ollama" in token_texts or "本地" in token_texts

    def test_local_mode_ollama_not_running_returns_error(self, app_client):
        """model_mode=local + Ollama not running → returns error event."""
        from unittest.mock import patch

        with patch("app.core.socket_handler._is_ollama_alive", return_value=False), \
             patch("app.core.agent.agent_loop._is_ollama_alive", return_value=False):
            resp = app_client.post("/api/editor/ai/stream", json={
                "action": "polish",
                "selection": "需要润色的文字",
                "model_mode": "local",
            })
            # Force stream consumption while patches are active.
            resp_data = resp.get_data()

        assert resp.status_code == 200
        events = parse_sse_events(resp_data)
        error_events = [e for e in events if e.get("type") == "error"]
        assert len(error_events) > 0, "Expected an error event when Ollama is not running"

    def test_explicit_cloud_mode_is_not_overridden_by_legacy_local_only_setting(self, app_client):
        """model_mode=cloud must keep using cloud first even if legacy local-only is enabled."""
        class FakeCloudProvider:
            def generate_content(self, prompt=None, model=None, system_instruction=None, stream=False, **kwargs):
                assert stream is True
                return iter([
                    {"content": "云端", "tool_calls": [], "usage": {}},
                    {"content": "Gemini", "tool_calls": [], "usage": {}},
                ])

        class FakeLocalProvider:
            def generate_content(self, prompt=None, model=None, system_instruction=None, stream=False, **kwargs):
                assert stream is True
                return iter([
                    {"content": "本地", "tool_calls": [], "usage": {}},
                    {"content": "Ollama", "tool_calls": [], "usage": {}},
                ])

        with patch("web.settings.SettingsManager.get", return_value=True), \
             patch("app.core.agent.agent_loop._get_provider", return_value=FakeCloudProvider()), \
             patch("app.core.agent.agent_loop._get_local_provider", return_value=FakeLocalProvider()), \
             patch("app.core.agent.agent_loop._is_ollama_alive", return_value=True):
            resp = app_client.post("/api/editor/ai/stream", json={
                "action": "polish",
                "selection": "需要润色的文字",
                "model_mode": "cloud",
            })
            resp_data = resp.get_data()

        assert resp.status_code == 200
        events = parse_sse_events(resp_data)
        token_texts = "".join(e.get("text", "") for e in events if e.get("type") == "token")
        assert "云端" in token_texts
        assert "Gemini" in token_texts
        assert "Ollama" not in token_texts

    def test_workspace_quick_actions_use_editor_ai_stream_with_model_mode(self):
        """Workspace quick actions should use the canonical editor SSE endpoint."""
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        helper_start = src.find("async function _sendViaEditorActionSSE(payload)")
        assert helper_start != -1
        helper_section = src[helper_start:]
        stream_idx = helper_section.find("/api/editor/ai/stream")
        assert stream_idx != -1
        stream_fetch = helper_section[: stream_idx + 900]
        assert "model_mode" in stream_fetch
        assert "model_id" in stream_fetch
        assert "output_mode" in stream_fetch

    def test_workspace_local_toggle_syncs_editor_ai_task_model_keys(self):
        """Workspace local/cloud toggle must also update the editor ai_task model keys."""
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        toggle_start = src.find("function _syncEditorModelPreference(")
        toggle_end = src.find("window.WA.setLockedModel = (val) => {", toggle_start)
        assert toggle_start != -1 and toggle_end != -1
        toggle_section = src[toggle_start:toggle_end]
        assert "const editorMode = mode === 'local' ? 'local' : 'cloud';" in toggle_section
        assert "localStorage.setItem('editor_model_mode', editorMode);" in toggle_section
        assert "localStorage.setItem('editor_locked_model', editorLockedModel);" in toggle_section
        assert "localStorage.removeItem('editor_locked_model');" in toggle_section
        assert "window.__koto?.aiPanel?.notifyModelChange?.(" in toggle_section
        assert "_syncEditorModelPreference(newModel, newModel);" in toggle_section

    def test_workspace_model_selector_fetches_dynamic_catalog(self):
        """Workspace assistant should fetch the dynamic model catalog instead of relying on hardcoded options."""
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        assert "function _refreshModelCatalog(force = false)" in src
        assert "fetch('/api/v1/models', { cache: 'no-store' })" in src
        assert "_syncModelStatusUi();" in src

    def test_workspace_stream_handlers_consume_classification_events(self):
        """Workspace assistant streams should surface backend classification/model routing events."""
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        assert src.count("if (evt.type === 'classification') {") >= 3
        assert "_applyRouteEvent(evt);" in src

    def test_workspace_send_quick_action_routes_text_and_chart_via_unified_paths(self):
        """sendQuickAction should call editor/chart SSE helpers instead of legacy JSON quick-action."""
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        fn_start = src.find("window.WA.sendQuickAction = (action) => {")
        fn_end = src.find("window.WA.sendSelectionToAI = () => {", fn_start)
        assert fn_start != -1 and fn_end != -1
        send_quick = src[fn_start:fn_end]
        assert "_sendViaEditorActionSSE({" in send_quick
        assert "_sendViaSSEChart({" in send_quick
        assert "/api/v1/workspace/quick-action" not in send_quick

    def test_workspace_quick_action_keyword_list_includes_check(self):
        """The workspace assistant quick-action keyword routing must recognize 检查."""
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        quick_start = src.find("window.WA.quickAction = (text) => {")
        quick_end = src.find("window.WA.pptxSync = (ta) => {", quick_start)
        assert quick_start != -1 and quick_end != -1
        quick_section = src[quick_start:quick_end]
        assert "'检查'" in quick_section
        assert "WA.sendQuickAction(matchedAction);" in quick_section

    def test_pdf_ai_annotate_is_explicitly_disabled_during_migration(self):
        """PDF AI annotate should not call the legacy quick-action path while the feature is offline."""
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        fn_start = src.find("async aiAnnotate() {")
        fn_end = src.find("// ─── AI Watermark removal", fn_start)
        assert fn_start != -1 and fn_end != -1
        ai_annotate = src[fn_start:fn_end]
        assert "/api/v1/workspace/quick-action" not in ai_annotate
        assert "ai_annotate" not in ai_annotate
        assert "AI 标注功能正在迁移到新的 AI 流程" in ai_annotate

    def test_pdf_ai_annotate_button_title_marks_temporary_unavailability(self):
        """The PDF toolbar button should advertise that AI annotate is temporarily unavailable."""
        html = Path("web/templates/workspace_assistant.html").read_text(encoding="utf-8")
        assert 'title="AI 标注迁移中，暂不可用"' in html

    def test_workspace_templates_use_shared_model_controls_partial(self):
        """Workspace templates should share the same local/cloud model controls without exposing a redundant model picker."""
        standalone_html = Path("web/templates/workspace_assistant.html").read_text(encoding="utf-8")
        index_html = Path("web/templates/index.html").read_text(encoding="utf-8")
        partial_html = Path("web/templates/_workspace_model_controls.html").read_text(encoding="utf-8")
        assert "{% include '_workspace_model_controls.html' %}" in standalone_html
        assert "{% include '_workspace_model_controls.html' %}" in index_html
        assert 'data-local-mode="off"' in partial_html
        assert 'data-local-mode="on"' in partial_html
        assert 'AI 模型' not in partial_html
        assert 'id="wa-model-select"' not in partial_html
        assert 'Gemini Flash' not in partial_html
        assert 'Gemini Pro 3.1（代码）' not in partial_html

    def test_workspace_cloud_selection_maps_request_model_mode_to_cloud(self):
        js = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        assert "lockedModel: localStorage.getItem('wa_locked_model') === 'local' ? 'local' : 'auto'" in js
        assert "const storedLockedModel = localStorage.getItem('wa_locked_model');" in js
        assert "return state.lockedModel === 'local' ? 'local' : 'cloud';" in js
        assert "model_mode: lockedModel === 'local' ? 'local' : 'cloud'," in js
        assert "window.WA.setLockedModel = (val) => {\n    window.WA.setUseLocalModel(val === 'local');\n  };" in js


class TestAIPanelRegression:
    """Regression checks for recent AIPanel request-plumbing fixes."""

    def test_check_action_defines_selection_before_use(self):
        """check action should compute selection/hasSelection before branch logic."""
        src = Path("web/univer-editor/src/AIPanel.js").read_text(encoding="utf-8")
        pattern = re.compile(
            r"const\s+selection\s*=\s*this\._doc\.getSelection\(\);[\s\S]*?"
            r"const\s+hasSelection\s*=\s*!!\(selection\s*&&\s*selection\.text\s*&&\s*selection\.text\.trim\(\)\);[\s\S]*?"
            r"if\s*\(actionType\s*===\s*'check'\)",
            re.MULTILINE,
        )
        assert pattern.search(src), "check branch must derive selection/hasSelection before use"

    def test_main_ai_stream_payload_includes_file_metadata(self):
        """Main AI stream body should include file_type and file_name."""
        src = Path("web/univer-editor/src/AIPanel.js").read_text(encoding="utf-8")
        send_via_main = src[src.find("async _sendViaMainAI("):]
        stream_fetch = send_via_main[: send_via_main.find("/api/editor/ai/stream") + 1000]
        assert "file_type" in stream_fetch
        assert "file_name" in stream_fetch

    def test_task_stream_payload_uses_unified_stream_endpoint_and_model_fields(self):
        """Task flow should go through editor_ai_stream and send model settings explicitly."""
        src = Path("web/univer-editor/src/AIPanel.js").read_text(encoding="utf-8")
        send_via_task = src[src.find("async _sendViaTask("):]
        task_fetch = send_via_task[: send_via_task.find("/api/editor/ai/stream") + 1200]
        assert "/api/editor/ai/stream" in task_fetch
        assert "/api/editor/ai/task-execute" not in task_fetch
        assert "action: 'ai_task'" in task_fetch
        assert "model_mode" in task_fetch
        assert "editor_model_mode" in task_fetch
        assert "model_id" in task_fetch
        assert "editor_locked_model" in task_fetch

    def test_floating_toolbar_routes_standard_actions_via_main_ai(self):
        """FloatingToolbar 普通文本动作应通过面板 SSE，而不是 sendAction。"""
        src = Path("web/univer-editor/src/FloatingToolbar.js").read_text(encoding="utf-8")
        assert "_sendViaMainAI('custom_instruction', this._selectedText, selData, instruction)" in src
        assert "_sendViaMainAI(action, this._selectedText, selData, '')" in src

    def test_main_ai_uses_shared_progress_consumer_for_phase_and_steps(self):
        """Main SSE handler should route phase/plan/step progress through the shared consumer."""
        src = Path("web/univer-editor/src/AIPanel.js").read_text(encoding="utf-8")
        send_via_main = src[src.find("async _sendViaMainAI("):]
        assert "_consumeTaskProgressEvent(progressState, this._chatFlow, parsed)" in send_via_main

    def test_task_progress_consumer_handles_phase_events(self):
        """Shared task progress consumer should understand canonical phase events."""
        src = Path("web/univer-editor/src/AIPanel.js").read_text(encoding="utf-8")
        consume_section = src[src.find("_consumeTaskProgressEvent("): src.find("handleAgentEvent(")]
        assert "case 'phase':" in consume_section
        assert "_computeTaskProgressPercent(phaseIndex, meta.totalPhases" in consume_section

    def test_agent_mode_uses_structured_progress_consumer(self):
        """Agent analysis mode should feed canonical step events into the shared progress consumer."""
        src = Path("web/univer-editor/src/AIPanel.js").read_text(encoding="utf-8")
        send_via_agent = src[src.find("async _sendViaAgent("): src.find("async _sendViaTask(")]
        assert "_consumeTaskProgressEvent(progressState, this._chatFlow, parsed)" in send_via_agent

    def test_task_mode_uses_structured_progress_consumer(self):
        """Task mode should share the same canonical progress renderer."""
        src = Path("web/univer-editor/src/AIPanel.js").read_text(encoding="utf-8")
        send_via_task = src[src.find("async _sendViaTask("): src.find("async _sendViaMainAI(")]
        assert "_consumeTaskProgressEvent(progressState, this._chatFlow, ev)" in send_via_task

    def test_task_mode_applies_file_change_preview_updates(self):
        """Task mode should apply file_change previews into the active document view."""
        src = Path("web/univer-editor/src/AIPanel.js").read_text(encoding="utf-8")
        send_via_task = src[src.find("async _sendViaTask("): src.find("async _sendViaMainAI(")]
        assert "case 'file_change':" in send_via_task
        assert "this._applyTaskFilePreview(ev);" in send_via_task
        assert "_applyTaskFilePreview(ev)" in src
        assert "docxViewer.setLiveText(preview" in src

    def test_skill_exec_handles_plan_tool_and_step_progress(self):
        """Skill execution panel should preserve plan/tool/step progress via the shared consumer."""
        src = Path("web/univer-editor/src/AIPanel.js").read_text(encoding="utf-8")
        execute_skill = src[src.find("async _executeSkill("): src.find("_renderSkillOutput(")]
        assert "_consumeTaskProgressEvent(progressState, body, ev" in execute_skill
        assert "wrapperClass: 'skill-exec-progress task-progress'" in execute_skill


class TestSocketBridgeRegression:
    """Regression checks for structured WebSocket progress plumbing."""

    def test_socket_bridge_listens_for_agent_event(self):
        src = Path("web/univer-editor/src/SocketBridge.js").read_text(encoding="utf-8")
        assert "this._socket.on('agent_event'" in src
        assert "this._panel.handleAgentEvent?.(payload);" in src


class TestMainChatProgressRegression:
    """Regression checks for canonical step-event support in the main chat UI."""

    def test_main_chat_normalizes_canonical_step_events(self):
        src = Path("web/static/js/app.js").read_text(encoding="utf-8")
        assert "evt.type === 'plan'" in src
        assert "evt.type === 'phase'" in src
        assert "evt.type === 'step_start'" in src
        assert "evt.type === 'tool_call'" in src
        assert "const canonicalProgressPercent =" in src


class TestSkillExecuteRoute:
    """Tests for POST /api/editor/ai/skill-execute structured forwarding."""

    def test_skill_execute_forwards_structured_progress_events(self, app_client):
        class FakeRuntime:
            def __init__(self, socketio=None, model_id="", api_key=None, session_store=None):
                pass

            def execute(self, request):
                yield 'data: {"type":"phase","phase_id":"decision","status":"running"}\n\n'
                yield 'data: {"type":"plan","steps":[{"id":"read","description":"读取文件"}]}\n\n'
                yield 'data: {"type":"thought","text":"先理解任务"}\n\n'
                yield 'data: {"type":"step_start","step_id":"read","text":"读取文件"}\n\n'
                yield 'data: {"type":"tool_call","step_id":"read","tool_name":"read_docx_content","tool_args":{"path":"demo.docx"}}\n\n'
                yield 'data: {"type":"tool_result","step_id":"read","tool_name":"read_docx_content","result_preview":"读取成功"}\n\n'
                yield 'data: {"type":"step_progress","step_id":"read","detail":"已读取 1/1 份文件"}\n\n'
                yield 'data: {"type":"step_done","step_id":"read","text":"读取完成"}\n\n'
                yield 'data: {"type":"done","summary":"ok"}\n\n'

        class FakeSkillManager:
            def get_all_skills(self):
                return [{"id": "comm_digest", "name": "沟通纪要"}]

        with patch("app.core.agent.openclaw_task_runtime.OpenClawTaskRuntime", FakeRuntime), \
             patch("app.core.skills.skill_manager.SkillManager", FakeSkillManager):
            resp = app_client.post(
                "/api/editor/ai/skill-execute",
                json={"skill_id": "comm_digest", "params": {}},
            )
            payload = resp.get_data()

        assert resp.status_code == 200
        events = parse_sse_events(payload)
        types = [e.get("type") for e in events]
        assert "phase" in types
        assert "plan" in types
        assert "thought" in types
        assert "step_start" in types
        assert "tool_call" in types
        assert "tool_result" in types
        assert "step_progress" in types
        assert "step_done" in types
        assert "done" in types


class TestTaskExecuteRoute:
    """Tests for POST /api/editor/ai/task-execute option normalization."""

    def test_missing_task_returns_400(self, app_client):
        resp = app_client.post("/api/editor/ai/task-execute", json={})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data and "error" in data

    def test_normalizes_pseudo_model_id_and_defaults_from_file_task_map(self, app_client):
        captured = {}

        class FakeRuntime:
            def __init__(self, socketio=None, model_id="", api_key=None, session_store=None):
                captured["init_model_id"] = model_id

            def execute(self, request):
                captured["task"] = request.task
                captured["files"] = request.files or []
                captured["options"] = request.options or {}
                yield 'data: {"type":"done","summary":"ok"}\n\n'

        with patch("app.core.agent.openclaw_task_runtime.OpenClawTaskRuntime", FakeRuntime), \
             patch.dict("web.app.MODEL_MAP", {"CHAT": "gemini-chat-default", "FILE_TASK": "gemini-file-task-default"}, clear=False):
            resp = app_client.post(
                "/api/editor/ai/task-execute",
                json={
                    "task": "整理当前文件",
                    "files": [{"path": "workspace/a.docx", "name": "a.docx", "type": "docx"}],
                    "options": {"model_mode": "LOCAL", "model_id": "local"},
                },
            )
            payload = resp.get_data()

        assert resp.status_code == 200
        assert "text/event-stream" in resp.content_type
        assert captured["init_model_id"] == ""
        assert captured["options"]["model_mode"] == "local"
        assert captured["options"]["model_id"] == ""
        assert captured["task"] == "整理当前文件"
        assert captured["files"] and captured["files"][0]["type"] == "docx"
        events = parse_sse_events(payload)
        assert any(e.get("type") == "done" for e in events)

    def test_skill_execute_defaults_to_file_task_model(self, app_client):
        captured = {}

        class FakeRuntime:
            def __init__(self, socketio=None, model_id="", api_key=None, session_store=None):
                captured["init_model_id"] = model_id

            def execute(self, request):
                captured["options"] = request.options or {}
                yield 'data: {"type":"done","summary":"ok"}\n\n'

        class FakeSkillManager:
            def get_all_skills(self):
                return [{"id": "comm_digest", "name": "沟通纪要"}]

        with patch("app.core.agent.openclaw_task_runtime.OpenClawTaskRuntime", FakeRuntime), \
             patch("app.core.skills.skill_manager.SkillManager", FakeSkillManager), \
             patch.dict("web.app.MODEL_MAP", {"CHAT": "gemini-chat-default", "FILE_TASK": "gemini-file-task-default"}, clear=False):
            resp = app_client.post(
                "/api/editor/ai/skill-execute",
                json={"skill_id": "comm_digest", "params": {}},
            )
            _ = resp.get_data()

        assert resp.status_code == 200
        assert captured["init_model_id"] == "gemini-file-task-default"
        assert captured["options"]["model_id"] == "gemini-file-task-default"

    def test_preserves_explicit_model_id(self, app_client):
        captured = {}

        class FakeRuntime:
            def __init__(self, socketio=None, model_id="", api_key=None, session_store=None):
                captured["init_model_id"] = model_id

            def execute(self, request):
                captured["options"] = request.options or {}
                yield 'data: {"type":"done","summary":"ok"}\n\n'

        with patch("app.core.agent.openclaw_task_runtime.OpenClawTaskRuntime", FakeRuntime):
            resp = app_client.post(
                "/api/editor/ai/task-execute",
                json={
                    "task": "处理任务",
                    "options": {"model_mode": "cloud", "model_id": "gemini-2.5-pro"},
                },
            )
            _ = resp.get_data()

        assert resp.status_code == 200
        assert captured["init_model_id"] == "gemini-2.5-pro"
        assert captured["options"]["model_mode"] == "cloud"
        assert captured["options"]["model_id"] == "gemini-2.5-pro"


class TestEditorEntrypointRegression:
    """Regression checks for the file assistant runtime entrypoint."""

    def test_editor_entrypoint_no_longer_loads_runtime_patch(self):
        src_index = Path("web/univer-editor/index.html").read_text(encoding="utf-8")
        dist_index = Path("web/static/univer-dist/index.html").read_text(encoding="utf-8")
        assert "/editor/assets/koto-patch.js" not in src_index
        assert "/editor/assets/koto-patch.js" not in dist_index

    def test_file_manager_owns_new_and_export_shortcuts(self):
        src = Path("web/univer-editor/src/FileManager.js").read_text(encoding="utf-8")
        assert "key === 'n'" in src
        assert "key === 'e'" in src
        assert "exportCurrentAsText()" in src

    def test_floating_toolbar_owns_ai_shortcuts(self):
        src = Path("web/univer-editor/src/FloatingToolbar.js").read_text(encoding="utf-8")
        assert "static SHORTCUT_ACTIONS" in src
        assert "this._triggerShortcutAction(action);" in src
        assert "this._panel._sendViaMainAI(action, fullText, selData, '');" in src


class TestTaskAgentDocumentEdits:
    """Regression checks for real file-edit tool execution in TaskAgent."""

    def test_task_agent_runs_stage_verification_after_file_change(self, monkeypatch):
        from app.core.agent.task_agent import TaskAgent

        class FakeRegistry:
            def __init__(self):
                self.executions = []

            def get_definitions(self):
                return [
                    {"name": "insert_excel_as_docx_table"},
                    {"name": "verify_task_completion"},
                ]

            def execute(self, tool_name, tool_args):
                self.executions.append((tool_name, dict(tool_args)))
                if tool_name == "insert_excel_as_docx_table":
                    return json.dumps({
                        "success": True,
                        "summary": "已将工作表“汇总表”的 200 行数据写入 Word 表格",
                        "path": "target.docx",
                        "file_type": "docx",
                        "change_type": "modify",
                        "operation": tool_name,
                        "preview": "表格已写入目标文档",
                    }, ensure_ascii=False)
                if tool_name == "verify_task_completion":
                    assert tool_args["model_mode"] == "local"
                    payload = json.loads(tool_args["file_states"])
                    assert payload and payload[0]["path"] == "target.docx"
                    return json.dumps({
                        "completed": True,
                        "confidence": 0.96,
                        "summary": "结果符合要求，目标文档已经完成更新",
                        "remaining_steps": [],
                    }, ensure_ascii=False)
                raise AssertionError(f"Unexpected tool call: {tool_name}")

        registry = FakeRegistry()
        llm_call_count = {"count": 0}

        def fake_call_llm(self, provider, messages, system, tool_defs, options=None):
            llm_call_count["count"] += 1
            return {
                "content": "先执行插表，再检查结果。",
                "tool_calls": [{
                    "id": "call_1",
                    "name": "insert_excel_as_docx_table",
                    "args": {
                        "source_path": "sales.xlsx",
                        "target_path": "target.docx",
                        "sheet_name": "汇总表",
                    },
                }],
            }

        monkeypatch.setattr(TaskAgent, "_get_provider", lambda self, options=None: object())
        monkeypatch.setattr(TaskAgent, "_build_registry", lambda self, files=None: registry)
        monkeypatch.setattr(TaskAgent, "_call_llm", fake_call_llm)

        agent = TaskAgent(model_id="test-model")
        payload = "".join(agent.execute(
            task="将 xls 表格加入 docx，并确认结果符合要求",
            files=[],
            options={"model_mode": "local"},
        ))

        assert llm_call_count["count"] == 1
        assert [name for name, _ in registry.executions] == [
            "insert_excel_as_docx_table",
            "verify_task_completion",
        ]
        events = parse_sse_events(payload.encode("utf-8"))
        assert any(
            e.get("type") == "step_progress" and "检查当前结果是否符合任务要求" in str(e.get("detail", ""))
            for e in events
        )
        assert any(
            e.get("type") == "step_done" and "结果符合要求" in str(e.get("text", ""))
            for e in events
        )
        assert any(
            e.get("type") == "done" and "结果符合要求" in str(e.get("summary", ""))
            for e in events
        )

    def test_task_agent_reinjects_stage_verification_feedback_when_incomplete(self, monkeypatch):
        from app.core.agent.task_agent import TaskAgent

        class FakeRegistry:
            def get_definitions(self):
                return [
                    {"name": "write_docx_content"},
                    {"name": "verify_task_completion"},
                ]

            def execute(self, tool_name, tool_args):
                if tool_name == "write_docx_content":
                    return json.dumps({
                        "success": True,
                        "summary": "已写入 2 个段落到 Word 文档",
                        "path": "draft.docx",
                        "file_type": "docx",
                        "change_type": "modify",
                        "operation": tool_name,
                        "preview": "第一段\n第二段",
                    }, ensure_ascii=False)
                if tool_name == "verify_task_completion":
                    return json.dumps({
                        "completed": False,
                        "confidence": 0.41,
                        "summary": "当前文档还缺少结论段",
                        "remaining_steps": ["补充结论段"],
                    }, ensure_ascii=False)
                raise AssertionError(f"Unexpected tool call: {tool_name}")

        seen_message_batches = []
        responses = iter([
            {
                "content": "先写入主体内容。",
                "tool_calls": [{
                    "id": "call_1",
                    "name": "write_docx_content",
                    "args": {"path": "draft.docx", "paragraphs": []},
                }],
            },
            {
                "content": "继续补充结论段。",
                "tool_calls": [],
            },
        ])

        monkeypatch.setattr(TaskAgent, "_get_provider", lambda self, options=None: object())
        monkeypatch.setattr(TaskAgent, "_build_registry", lambda self, files=None: FakeRegistry())

        def fake_call_llm(self, provider, messages, system, tool_defs, options=None):
            seen_message_batches.append(messages)
            return next(responses)

        monkeypatch.setattr(TaskAgent, "_call_llm", fake_call_llm)

        agent = TaskAgent(model_id="test-model")
        _ = "".join(agent.execute(task="补全文档并保证结构完整", files=[], options={}))

        assert len(seen_message_batches) == 2
        verify_messages = [m for m in seen_message_batches[1] if m.get("name") == "verify_task_completion"]
        assert verify_messages
        assert "缺少结论段" in verify_messages[-1]["content"]

    def test_task_agent_skips_duplicate_tool_calls_within_single_batch(self, monkeypatch):
        from app.core.agent.task_agent import TaskAgent

        class FakeRegistry:
            def __init__(self):
                self.executions = []

            def get_definitions(self):
                return [{"name": "insert_excel_as_docx_table"}]

            def execute(self, tool_name, tool_args):
                self.executions.append((tool_name, dict(tool_args)))
                return json.dumps({
                    "success": True,
                    "summary": "已将工作表“汇总表”的 200 行数据写入 Word 表格",
                    "path": "target.docx",
                    "file_type": "docx",
                    "change_type": "modify",
                    "operation": tool_name,
                }, ensure_ascii=False)

        registry = FakeRegistry()
        duplicate_args = {
            "source_path": "sales.xlsx",
            "target_path": "target.docx",
            "sheet_name": "汇总表",
            "table_title": "汇总表",
        }
        responses = iter([
            {
                "content": "先把 Excel 插入 Word 表格。",
                "tool_calls": [
                    {"id": "call_1", "name": "insert_excel_as_docx_table", "args": duplicate_args},
                    {"id": "call_2", "name": "insert_excel_as_docx_table", "args": dict(duplicate_args)},
                ],
            },
            {
                "content": "目标文档已经更新完成。",
                "tool_calls": [],
            },
        ])

        monkeypatch.setattr(TaskAgent, "_get_provider", lambda self, options=None: object())
        monkeypatch.setattr(TaskAgent, "_build_registry", lambda self, files=None: registry)
        monkeypatch.setattr(
            TaskAgent,
            "_call_llm",
            lambda self, provider, messages, system, tool_defs, options=None: next(responses),
        )

        agent = TaskAgent(model_id="test-model")
        payload = "".join(agent.execute(task="将 xls 表格插入 docx", files=[], options={}))

        assert registry.executions == [("insert_excel_as_docx_table", duplicate_args)]
        events = parse_sse_events(payload.encode("utf-8"))
        assert any(
            e.get("type") == "thought" and "重复工具调用" in str(e.get("text", ""))
            for e in events
        )
        assert any(
            e.get("type") == "tool_result" and "已跳过重复工具调用" in str(e.get("result_preview", ""))
            for e in events
        )

    def test_task_agent_stops_before_repeating_identical_successful_tool_batch(self, monkeypatch):
        from app.core.agent.task_agent import TaskAgent

        class FakeRegistry:
            def __init__(self):
                self.executions = []

            def get_definitions(self):
                return [{"name": "parse_file_to_text"}]

            def execute(self, tool_name, tool_args):
                self.executions.append((tool_name, dict(tool_args)))
                return "第一轮读取成功"

        registry = FakeRegistry()
        repeated_call = {
            "id": "call_1",
            "name": "parse_file_to_text",
            "args": {"path": "demo.txt", "max_chars": 12000},
        }
        responses = iter([
            {
                "content": "先读取当前文件。",
                "tool_calls": [repeated_call],
            },
            {
                "content": "继续读取当前文件。",
                "tool_calls": [{
                    "id": "call_2",
                    "name": "parse_file_to_text",
                    "args": {"path": "demo.txt", "max_chars": 12000},
                }],
            },
        ])

        monkeypatch.setattr(TaskAgent, "_get_provider", lambda self, options=None: object())
        monkeypatch.setattr(TaskAgent, "_build_registry", lambda self, files=None: registry)
        monkeypatch.setattr(
            TaskAgent,
            "_call_llm",
            lambda self, provider, messages, system, tool_defs, options=None: next(responses),
        )

        agent = TaskAgent(model_id="test-model")
        payload = "".join(agent.execute(task="总结当前文件", files=[], options={}))

        assert registry.executions == [("parse_file_to_text", {"path": "demo.txt", "max_chars": 12000})]
        events = parse_sse_events(payload.encode("utf-8"))
        assert any(
            e.get("type") == "thought" and "重复请求同一组工具" in str(e.get("text", ""))
            for e in events
        )
        assert any(
            e.get("type") == "done" and "检测到重复步骤" in str(e.get("summary", ""))
            for e in events
        )

    def test_file_task_cloud_default_model_prefers_gemini31_pro(self):
        from web.app import MODEL_MAP, _get_file_task_default_model

        assert MODEL_MAP["FILE_TASK"] == "gemini-3.1-pro-preview"
        assert _get_file_task_default_model() == "gemini-3.1-pro-preview"

    def test_resolve_requested_model_id_falls_back_when_unavailable(self, monkeypatch):
        import web.app as webapp

        class _DummyManager:
            _cached_caps = {}

            def get_available_models(self):
                return [{"id": "gemini-2.5-flash"}]

            def get_model_for_task(self, task):
                return "gemini-2.5-flash"

        monkeypatch.setattr(webapp, "_model_manager", _DummyManager())

        assert (
            webapp._resolve_requested_model_id(
                "gemini-2.5-pro",
                fallback_model="gemini-3.1-pro-preview",
            )
            == "gemini-2.5-flash"
        )

    def test_normalize_file_task_model_id_rejects_unavailable_locked_model(self, monkeypatch):
        import web.app as webapp

        class _DummyManager:
            _cached_caps = {}

            def get_available_models(self):
                return [{"id": "gemini-2.5-flash"}]

            def get_model_for_task(self, task):
                return "gemini-2.5-flash"

        monkeypatch.setattr(webapp, "_model_manager", _DummyManager())
        monkeypatch.setitem(webapp.MODEL_MAP, "FILE_TASK", "gemini-3.1-pro-preview")

        assert (
            webapp._normalize_file_task_model_id("auto", "gemini-2.5-pro")
            == "gemini-2.5-flash"
        )

    def test_normalize_file_task_model_id_keeps_supported_preview_ids(self, monkeypatch):
        import web.app as webapp

        monkeypatch.setattr(webapp, "_model_manager", None)

        assert (
            webapp._normalize_file_task_model_id("auto", "gemini-3.1-pro-preview")
            == "gemini-3.1-pro-preview"
        )

    def test_resolve_requested_model_id_rejects_image_model_for_chat(self, monkeypatch):
        import web.app as webapp

        class _DummyManager:
            _cached_caps = {
                "gemini-3.1-flash-image-preview": {
                    "image_gen": True,
                    "multimodal": True,
                    "grounding": False,
                    "function_calling": False,
                    "tier": 7,
                }
            }

            def get_available_models(self):
                return [
                    {"id": "gemini-3.1-flash-image-preview"},
                    {"id": "gemini-2.5-flash"},
                ]

        monkeypatch.setattr(webapp, "_model_manager", _DummyManager())

        assert (
            webapp._resolve_requested_model_id(
                "gemini-3.1-flash-image-preview",
                fallback_model="gemini-2.5-flash",
                task_type="CHAT",
            )
            == "gemini-2.5-flash"
        )

    def test_resolve_requested_model_id_rejects_model_without_required_task_capability(self, monkeypatch):
        import web.app as webapp

        class _DummyManager:
            _cached_caps = {
                "gemini-2.5-flash": {
                    "speed": 10,
                    "quality": 8,
                    "reasoning": 8,
                    "context": 8,
                    "multimodal": True,
                    "grounding": False,
                    "function_calling": True,
                    "image_gen": False,
                    "tier": 8,
                }
            }

            def get_available_models(self):
                return [
                    {"id": "gemini-2.5-flash"},
                    {"id": "gemini-2.5-pro"},
                ]

        monkeypatch.setattr(webapp, "_model_manager", _DummyManager())

        assert (
            webapp._resolve_requested_model_id(
                "gemini-2.5-flash",
                fallback_model="gemini-2.5-pro",
                task_type="WEB_SEARCH",
            )
            == "gemini-2.5-pro"
        )

    def test_parse_file_to_text_accepts_larger_custom_windows(self, tmp_path):
        from app.core.agent.task_tools import parse_file_to_text

        source_path = tmp_path / "long_notes.txt"
        source_path.write_text("A" * 20_000, encoding="utf-8")

        parsed = parse_file_to_text(str(source_path), max_chars=18_000)

        assert len(parsed) == 18_000
        assert len(parsed) > 12_000

    def test_task_agent_keeps_long_tool_results_in_followup_context(self, monkeypatch):
        from app.core.agent.task_agent import TaskAgent

        class FakeRegistry:
            def get_definitions(self):
                return [{"name": "parse_file_to_text"}]

            def execute(self, tool_name, tool_args):
                return "B" * 12_000

        seen_message_batches = []
        responses = iter([
            {
                "content": "先读取文件全文。",
                "tool_calls": [{
                    "id": "call_1",
                    "name": "parse_file_to_text",
                    "args": {"path": "demo.txt", "max_chars": 12000},
                }],
            },
            {
                "content": "已完成。",
                "tool_calls": [],
            },
        ])

        monkeypatch.setattr(TaskAgent, "_get_provider", lambda self, options=None: object())
        monkeypatch.setattr(TaskAgent, "_build_registry", lambda self, files=None: FakeRegistry())

        def fake_call_llm(self, provider, messages, system, tool_defs, options=None):
            seen_message_batches.append(messages)
            return next(responses)

        monkeypatch.setattr(TaskAgent, "_call_llm", fake_call_llm)

        agent = TaskAgent(model_id="test-model")
        _ = "".join(agent.execute(task="读取大文件", files=[], options={}))

        assert len(seen_message_batches) == 2
        function_messages = [m for m in seen_message_batches[1] if m.get("role") == "function"]
        assert function_messages
        assert len(function_messages[-1]["content"]) > 4000

    def test_task_agent_run_python_code_can_open_attached_file_by_basename(self, tmp_path, monkeypatch):
        openpyxl = pytest.importorskip("openpyxl")

        source_path = tmp_path / "销售台账.xlsx"

        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = "销售数据"
        worksheet.append(["姓名", "地区", "销售额"])
        worksheet.append(["张三", "华东", 120])
        workbook.save(source_path)
        workbook.close()

        from app.core.agent.task_agent import TaskAgent

        responses = iter([
            {
                "content": "先用 Python 读取附件中的 Excel。",
                "tool_calls": [{
                    "id": "call_1",
                    "name": "run_python_code",
                    "args": {
                        "code": (
                            "import openpyxl\n"
                            "wb = openpyxl.load_workbook('销售台账.xlsx', read_only=True, data_only=True)\n"
                            "ws = wb.active\n"
                            "print(ws['A2'].value)\n"
                            "wb.close()\n"
                        )
                    },
                }],
            },
            {
                "content": "已成功读取附件文件。",
                "tool_calls": [],
            },
        ])

        monkeypatch.setattr(TaskAgent, "_get_provider", lambda self, options=None: object())
        monkeypatch.setattr(
            TaskAgent,
            "_call_llm",
            lambda self, provider, messages, system, tool_defs, options=None: next(responses),
        )

        agent = TaskAgent(model_id="test-model")
        payload = "".join(agent.execute(
            task="读取附件里的 Excel 并打印第一行数据",
            files=[
                {"path": str(source_path), "name": source_path.name, "type": "xlsx"},
            ],
            options={},
        ))

        events = parse_sse_events(payload.encode("utf-8"))
        assert any(
            e.get("type") == "tool_result" and "张三" in str(e.get("result_preview", ""))
            for e in events
        )
        assert any(e.get("type") == "done" for e in events)

    def test_run_python_in_sandbox_syncs_modified_attached_file_when_cleanup_fails(self, tmp_path, monkeypatch):
        from app.core.agent import task_tools

        source_path = tmp_path / "任务说明.txt"
        source_path.write_text("before", encoding="utf-8")

        cleanup_calls = {"count": 0}
        original_rmtree = task_tools.shutil.rmtree

        def flaky_rmtree(path, *args, **kwargs):
            cleanup_calls["count"] += 1
            if cleanup_calls["count"] == 1:
                raise PermissionError(32, "locked", path)
            return original_rmtree(path, *args, **kwargs)

        monkeypatch.setattr(task_tools.shutil, "rmtree", flaky_rmtree)

        result = task_tools.run_python_in_sandbox(
            (
                "from pathlib import Path\n"
                f"p = Path(TASK_SANDBOX_FILE_PATHS[{source_path.name!r}])\n"
                "p.write_text('after', encoding='utf-8')\n"
                f"print('KOTO_MODIFIED:' + TASK_FILE_PATHS[{source_path.name!r}])\n"
            ),
            timeout=10,
            task_files=[{"path": str(source_path), "name": source_path.name}],
        )

        assert "Sandbox error:" not in result
        assert "__koto_modified__" in result
        assert source_path.read_text(encoding="utf-8") == "after"
        assert cleanup_calls["count"] == 1

    def test_task_agent_run_python_code_syncs_modified_attached_file_and_emits_file_change(self, tmp_path, monkeypatch):
        source_path = tmp_path / "任务说明.txt"
        source_path.write_text("before", encoding="utf-8")

        from app.core.agent.task_agent import TaskAgent

        responses = iter([
            {
                "content": "先用 Python 修改附件内容。",
                "tool_calls": [{
                    "id": "call_1",
                    "name": "run_python_code",
                    "args": {
                        "code": (
                            "from pathlib import Path\n"
                            f"p = Path(TASK_SANDBOX_FILE_PATHS[{source_path.name!r}])\n"
                            "p.write_text('after', encoding='utf-8')\n"
                            f"print('KOTO_MODIFIED:' + TASK_FILE_PATHS[{source_path.name!r}])\n"
                        )
                    },
                }],
            },
            {
                "content": "已完成附件修改。",
                "tool_calls": [],
            },
        ])

        monkeypatch.setattr(TaskAgent, "_get_provider", lambda self, options=None: object())
        monkeypatch.setattr(
            TaskAgent,
            "_call_llm",
            lambda self, provider, messages, system, tool_defs, options=None: next(responses),
        )

        agent = TaskAgent(model_id="test-model")
        payload = "".join(agent.execute(
            task="把附件内容改成 after",
            files=[
                {"path": str(source_path), "name": source_path.name, "type": "txt"},
            ],
            options={"model_mode": "local"},
        ))

        events = parse_sse_events(payload.encode("utf-8"))
        assert source_path.read_text(encoding="utf-8") == "after"
        assert any(
            e.get("type") == "file_change"
            and e.get("path") == str(source_path)
            and e.get("change_type") == "modify"
            for e in events
        )
        assert any(e.get("type") == "done" for e in events)

    def test_task_agent_run_python_code_detects_direct_source_file_modification(self, tmp_path, monkeypatch):
        source_path = tmp_path / "任务说明.txt"
        source_path.write_text("before", encoding="utf-8")

        from app.core.agent.task_agent import TaskAgent

        responses = iter([
            {
                "content": "直接修改原始附件路径。",
                "tool_calls": [{
                    "id": "call_1",
                    "name": "run_python_code",
                    "args": {
                        "code": (
                            "from pathlib import Path\n"
                            f"p = Path(TASK_FILE_PATHS[{source_path.name!r}])\n"
                            "p.write_text('after-direct', encoding='utf-8')\n"
                            "print('done')\n"
                        )
                    },
                }],
            },
            {
                "content": "已完成原文件修改。",
                "tool_calls": [],
            },
        ])

        monkeypatch.setattr(TaskAgent, "_get_provider", lambda self, options=None: object())
        monkeypatch.setattr(
            TaskAgent,
            "_call_llm",
            lambda self, provider, messages, system, tool_defs, options=None: next(responses),
        )

        agent = TaskAgent(model_id="test-model")
        payload = "".join(agent.execute(
            task="把原始附件内容改成 after-direct",
            files=[
                {"path": str(source_path), "name": source_path.name, "type": "txt"},
            ],
            options={"model_mode": "local"},
        ))

        events = parse_sse_events(payload.encode("utf-8"))
        assert source_path.read_text(encoding="utf-8") == "after-direct"
        assert any(
            e.get("type") == "file_change"
            and e.get("path") == str(source_path)
            and e.get("change_type") == "modify"
            for e in events
        )
        assert any(e.get("type") == "done" for e in events)

    def test_task_agent_inserts_excel_table_into_docx_and_emits_file_change(self, tmp_path, monkeypatch):
        openpyxl = pytest.importorskip("openpyxl")
        docx_module = pytest.importorskip("docx")

        source_path = tmp_path / "销售台账.xlsx"
        target_path = tmp_path / "雷鸟访问问题.docx"

        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = "销售数据"
        worksheet.append(["姓名", "地区", "销售额"])
        worksheet.append(["张三", "华东", 120])
        worksheet.append(["李四", "华南", 98])
        workbook.save(source_path)
        workbook.close()

        document = docx_module.Document()
        document.add_paragraph("雷鸟访问问题说明")
        document.save(target_path)

        from app.core.agent.task_agent import TaskAgent

        responses = iter([
            {
                "content": "先读取 Excel，并把数据写成 Word 表格。",
                "tool_calls": [{
                    "id": "call_1",
                    "name": "insert_excel_as_docx_table",
                    "args": {
                        "source_path": str(source_path),
                        "target_path": str(target_path),
                        "sheet_name": "销售数据",
                        "table_title": "销售台账",
                    },
                }],
            },
            {
                "content": "已完成 Excel 到 Word 表格写入，并校验目标文档。",
                "tool_calls": [],
            },
        ])

        monkeypatch.setattr(TaskAgent, "_get_provider", lambda self, options=None: object())
        monkeypatch.setattr(
            TaskAgent,
            "_call_llm",
            lambda self, provider, messages, system, tool_defs, options=None: next(responses),
        )

        agent = TaskAgent(model_id="test-model")
        payload = "".join(agent.execute(
            task="将excel数据加入word，做一个新表格",
            files=[
                {"path": str(source_path), "name": source_path.name, "type": "xlsx"},
                {"path": str(target_path), "name": target_path.name, "type": "docx"},
            ],
            options={},
        ))

        events = parse_sse_events(payload.encode("utf-8"))
        assert any(e.get("type") == "file_change" for e in events)
        assert any(
            e.get("type") == "file_change" and str(e.get("path", "")).endswith("雷鸟访问问题.docx")
            for e in events
        )
        assert any(e.get("type") == "done" for e in events)

        updated_doc = docx_module.Document(target_path)
        assert updated_doc.tables
        first_table = updated_doc.tables[0]
        assert first_table.cell(0, 0).text == "姓名"
        assert first_table.cell(1, 0).text == "张三"
        assert first_table.cell(2, 1).text == "华南"


class TestWorkspaceAssistantOpenClawRegression:
    """Source-level regressions for the workspace assistant task path."""

    def test_workspace_assistant_uses_file_change_and_not_workflow_routes(self):
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        assert "evt.type === 'file_change'" in src
        assert "reloadFileByPath" in src
        assert "/api/editor/ai/skill-list" in src
        assert "/api/workflow/list" not in src
        assert "workflow/execute" not in src

    def test_workspace_assistant_prefers_ws_source_path_for_ai_file_context(self):
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        assert "path: state.wsSourcePath || state.filePath || state.fileName || 'current_document'" in src
        assert "file_path: state.wsSourcePath || state.filePath || state.fileName || ''" in src
        assert "state.filePath = json.temp_path || wsPath || null;" in src

    def test_workspace_assistant_samples_long_task_context(self):
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        assert "function _waSampleTaskContext(text, limit = 12000)" in src
        assert "content = _waSampleTaskContext(content);" in src
        assert "content_preview: _waSampleTaskContext(String(file.content_preview || ''))" in src

    def test_workspace_current_file_task_requests_use_openclaw_task_path(self):
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        send_start = src.index("window.WA.sendMessage = () => {")
        send_end = src.index("// ── Auto-save", send_start)
        send_block = src[send_start:send_end]
        pattern = re.compile(
            r"const\s+_hasCurrentTaskFile\s*=\s*!!\(state\.fileName\s*&&\s*context\);[\s\S]*?"
            r"const\s+_hasOpenFileIntent\s*=\s*_isOpenFileIntent\(text\);[\s\S]*?"
            r"const\s+_hasTaskIntent\s*=\s*_isAgentIntent\(text\);[\s\S]*?"
            r"const\s+_useOpenClawTaskForCurrentFile\s*=\s*_hasCurrentTaskFile\s*&&\s*"
            r"\(pinnedSel\s*\|\|\s*_isDocEdit\s*\|\|\s*_hasTaskIntent\);[\s\S]*?"
            r"const\s+_useOpenClawTask\s*=\s*_hasAttachedTaskFiles\s*\|\|\s*_useOpenClawTaskForCurrentFile\s*\|\|\s*_hasTaskIntent\s*\|\|\s*_hasOpenFileIntent;",
            re.MULTILINE,
        )
        assert pattern.search(send_block), (
            "task-capable requests should prefer the OpenClaw ai_task path before the generic agent route"
        )

    def test_workspace_task_intents_do_not_fall_back_to_generic_agent_route(self):
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        send_start = src.index("window.WA.sendMessage = () => {")
        send_end = src.index("// ── Auto-save", send_start)
        send_block = src[send_start:send_end]
        assert "const _useGenericAgent = !_useOpenClawTask && state.useAgentMode;" in send_block
        assert "const _hasTaskIntent = _isAgentIntent(text);" in send_block

    def test_workspace_agent_intent_detector_includes_check_review_tasks(self):
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        send_start = src.index("window.WA.sendMessage = () => {")
        send_end = src.index("// ── Auto-save", send_start)
        send_block = src[send_start:send_end]
        agent_start = send_block.index("const _isAgentIntent = (t) => {")
        agent_end = send_block.index("let fullMessage = text;", agent_start)
        agent_block = send_block[agent_start:agent_end]
        assert "检查" in agent_block
        assert "校验" in agent_block

    def test_workspace_send_message_has_no_dead_multi_file_prompt_branch(self):
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        send_start = src.index("window.WA.sendMessage = () => {")
        send_end = src.index("// ── Auto-save", send_start)
        send_block = src[send_start:send_end]
        assert "state._aiFileContext && state._aiFileContext.length && !_hasAttachedTaskFiles" not in send_block
        assert "[多文档内容同步模式]" not in send_block
        assert "[多文档分析模式]" not in send_block

    def test_workspace_open_file_intents_use_openclaw_quick_path(self):
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        send_start = src.index("window.WA.sendMessage = () => {")
        send_end = src.index("// ── Auto-save", send_start)
        send_block = src[send_start:send_end]
        assert "const _isOpenFileIntent = (t) =>" in send_block
        assert "const _hasOpenFileIntent = _isOpenFileIntent(text);" in send_block
        assert "openIntentText: text," in send_block

        task_fn_start = src.index("async function _waSendToOpenClawTask(taskText, loadingEl, opts) {")
        task_fn_end = src.index("  function _toolDisplayName(", task_fn_start)
        task_block = src[task_fn_start:task_fn_end]
        assert "const _trimmed = String(opts.openIntentText || taskText || '').trim();" in task_block

    def test_workspace_input_autopin_requires_live_editor_selection(self):
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        assert "function _getLiveEditorSelectionForAI()" in src
        input_start = src.find("const _waInput = $('wa-user-input');")
        input_end = src.find("// ── Split.js Init", input_start)
        assert input_start != -1 and input_end != -1
        input_section = src[input_start:input_end]
        assert "const liveSelection = _getLiveEditorSelectionForAI();" in input_section
        assert "if (liveSelection) {" in input_section
        assert "_pinSelectionChip(liveSelection);" in input_section

    def test_workspace_chat_proposals_replace_streaming_bubble(self):
        """Doc-edit proposals should replace the temporary chat bubble instead of duplicating it."""
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        fn_start = src.find("async function _waSendToChat(message, loadingEl, opts) {")
        fn_end = src.find("window.WA.sendMessage = () => {", fn_start)
        assert fn_start != -1 and fn_end != -1
        send_chat = src[fn_start:fn_end]
        done_start = send_chat.find("} else if (evt.type === 'done') {")
        done_end = send_chat.find("} else if (evt.type === 'error') {", done_start)
        assert done_start != -1 and done_end != -1
        done_block = send_chat[done_start:done_end]
        assert "const propMatch = fullText.match" in done_block
        assert "if (proposalData) {" in done_block
        assert "loadingEl.remove();" in done_block
        assert "_handleProposals(proposalData);" in done_block

    def test_workspace_proposal_card_filters_duplicate_rationale_text(self):
        """Proposal cards should hide rationale text when it just repeats original/proposed content."""
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        assert "function _getProposalRationaleText(proposal)" in src
        assert "rationaleKey === originalKey || rationaleKey === proposedKey" in src

    def test_workspace_proposal_buttons_stay_single_line_and_equal_width(self):
        """Proposal action buttons should share width and keep labels on one line."""
        css = Path("web/static/css/workspace.css").read_text(encoding="utf-8")
        assert ".wa-proposal-actions .wa-proposal-btn" in css
        assert "flex: 1 1 0;" in css
        assert "white-space: nowrap;" in css
        assert "min-height: 34px;" in css

    def test_agent_loop_sends_sanitized_proposal_summary(self):
        """Structured proposal summary should reuse the sanitized note, not raw clean_text."""
        src = Path("app/core/agent/agent_loop.py").read_text(encoding="utf-8")
        assert 'proposal_summary = proposals[0].get("rationale", "")' in src
        assert 'yield evt_proposal(proposals, proposal_summary)' in src

    def test_workspace_assistant_docx_helpers_stay_outside_browser_ctx(self):
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        show_ctx_idx = src.index("window.WA._showBrowserCtx")
        for symbol in (
            "function _cloneSerializable(",
            "function _getDocxRenderOpts(",
            "function _cacheDocxTabState(",
            "function _serializeEditorForTab(",
        ):
            symbol_idx = src.index(symbol)
            assert symbol_idx < show_ctx_idx, (
                f"{symbol} must remain top-level before window.WA._showBrowserCtx "
                "so DOCX open/render helpers stay visible outside the browser context menu handler"
            )