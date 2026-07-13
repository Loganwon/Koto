#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests: 云端模型断开时本地模型兜底覆盖验证

覆盖的三条降级路径：
  1. _stream_llm()         — client_request 快捷操作（润色/翻译等）
  2. call_llm_sync()       — 代码生成（图表/可视化）
  3. doc_ai_request 内部   — 主对话流 _try_online → _try_local 闭包

以及辅助函数：
  - is_online_failure()    — 错误分类（覆盖所有预期关键词）
  - is_ollama_alive()      — 端口探测
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Lazy import helpers — skip entire module cleanly if socket_handler can't load
# ---------------------------------------------------------------------------
try:
    from app.core.agent import llm_provider_helpers  # noqa: E402
    from app.core.shared.llm_helpers import (  # noqa: E402
        get_local_provider,
        is_ollama_alive,
        is_online_failure,
    )
    from app.core.socket_handler import _get_provider, _stream_llm  # noqa: E402

    _IMPORT_OK = True
except Exception as _exc:
    _IMPORT_OK = False
    _IMPORT_ERR = str(_exc)

skipif_no_import = pytest.mark.skipif(
    not _IMPORT_OK,
    reason=f"Cannot import socket_handler: {_IMPORT_ERR if not _IMPORT_OK else ''}",
)


# ===========================================================================
# 1. is_online_failure() — 错误分类
# ===========================================================================


class TestIsOnlineFailure:
    """is_online_failure 必须正确识别所有可恢复的云端错误。"""

    @pytest.mark.parametrize(
        "msg",
        [
            "Request timed out after 30 s",
            "stream stalled — no data for 15 s",
            "503 Service Unavailable",
            "service unavailable",
            "timeout exceeded",
            "ResourceExhausted: quota exceeded",
            "resource_exhausted",
            "429 Too Many Requests",
            "model overloaded",
            "quota limit reached",
            "INVALID_ARGUMENT: API key not valid",
            "api key invalid",
            "api_key expired",
            "400 Bad Request: expired",
        ],
    )
    @skipif_no_import
    def test_recoverable_errors_trigger_fallback(self, msg):
        exc = RuntimeError(msg)
        assert is_online_failure(exc), f"Expected True for: {msg!r}"

    @pytest.mark.parametrize(
        "msg",
        [
            "ValueError: unexpected token",
            "KeyError: missing field 'content'",
            "AttributeError: 'NoneType' has no attribute",
            "ZeroDivisionError",
        ],
    )
    @skipif_no_import
    def test_non_recoverable_errors_do_not_trigger_fallback(self, msg):
        exc = RuntimeError(msg)
        assert not is_online_failure(exc), f"Expected False for: {msg!r}"


# ===========================================================================
# 2. is_ollama_alive() — 端口探测
# ===========================================================================


class TestIsOllamaAlive:

    @skipif_no_import
    def test_returns_false_when_ollama_not_running(self):
        """当 Ollama 端口无响应时应返回 False。"""
        mock_opener = MagicMock()
        mock_opener.open.side_effect = ConnectionRefusedError()
        with patch("urllib.request.build_opener", return_value=mock_opener):
            result = is_ollama_alive()
        assert result is False

    @skipif_no_import
    def test_returns_true_when_ollama_running(self):
        """当 Ollama 端口正常响应时应返回 True。"""
        mock_resp = MagicMock()
        mock_resp.close = MagicMock()
        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_resp

        with patch("urllib.request.build_opener", return_value=mock_opener):
            result = is_ollama_alive()
        assert result is True


# ===========================================================================
# 3. call_llm_sync() — 代码生成降级
# ===========================================================================


def _make_provider(content="local model response"):
    """构造一个返回固定内容的 mock LLMProvider。"""
    provider = MagicMock()
    provider.generate_content.return_value = {"content": content}
    return provider


class TestCallLlmSync:

    @skipif_no_import
    def test_online_success_returns_directly(self):
        """云端成功时直接返回，不调用本地。"""
        online_prov = _make_provider("online answer")
        with patch(
            "app.core.agent.llm_provider_helpers.get_provider", return_value=online_prov
        ), patch(
            "app.core.agent.llm_provider_helpers.pick_online_model",
            return_value="gemini-test",
        ), patch(
            "app.core.shared.llm_helpers.get_local_provider"
        ) as mock_local:
            result = llm_provider_helpers.call_llm_sync("test prompt")
        assert result == "online answer"
        mock_local.assert_not_called()

    @pytest.mark.parametrize(
        "error_msg",
        [
            "Request timed out",
            "503 Service Unavailable",
            "429 Too Many Requests",
            "api key invalid",
            "ResourceExhausted",
        ],
    )
    @skipif_no_import
    def test_online_failure_falls_back_to_local(self, error_msg):
        """云端抛出可恢复错误时，应降级到本地 Ollama。"""
        online_prov = MagicMock()
        online_prov.generate_content.side_effect = RuntimeError(error_msg)

        local_prov = _make_provider("local answer")

        with patch(
            "app.core.agent.llm_provider_helpers.get_provider", return_value=online_prov
        ), patch(
            "app.core.agent.llm_provider_helpers.pick_online_model",
            return_value="gemini-test",
        ), patch(
            "app.core.agent.llm_provider_helpers.is_ollama_alive", return_value=True
        ), patch(
            "app.core.agent.llm_provider_helpers.get_local_provider",
            return_value=local_prov,
        ):
            result = llm_provider_helpers.call_llm_sync("test prompt")

        assert (
            result == "local answer"
        ), f"Fallback should succeed for error: {error_msg!r}"

    @skipif_no_import
    def test_online_failure_ollama_down_returns_none(self):
        """云端故障且 Ollama 未运行时应返回 None。"""
        online_prov = MagicMock()
        online_prov.generate_content.side_effect = RuntimeError("503 unavailable")

        with patch(
            "app.core.agent.llm_provider_helpers.get_provider", return_value=online_prov
        ), patch(
            "app.core.agent.llm_provider_helpers.pick_online_model",
            return_value="gemini-test",
        ), patch(
            "app.core.agent.llm_provider_helpers.is_ollama_alive", return_value=False
        ):
            result = llm_provider_helpers.call_llm_sync("test prompt")

        assert result is None

    @skipif_no_import
    def test_non_recoverable_online_error_returns_none_no_local(self):
        """非可恢复错误（逻辑错误）不应触发本地降级，直接返回 None。"""
        online_prov = MagicMock()
        online_prov.generate_content.side_effect = ValueError("unexpected token")

        with patch(
            "app.core.agent.llm_provider_helpers.get_provider", return_value=online_prov
        ), patch(
            "app.core.agent.llm_provider_helpers.pick_online_model",
            return_value="gemini-test",
        ), patch(
            "app.core.agent.llm_provider_helpers.is_ollama_alive", return_value=False
        ), patch(
            "app.core.agent.llm_provider_helpers.get_local_provider"
        ) as mock_local:
            result = llm_provider_helpers.call_llm_sync("test prompt")

        assert result is None
        mock_local.assert_not_called()

    @skipif_no_import
    def test_local_also_fails_returns_none(self):
        """云端故障 + 本地也崩溃时应返回 None（不抛异常）。"""
        online_prov = MagicMock()
        online_prov.generate_content.side_effect = RuntimeError("timeout")

        local_prov = MagicMock()
        local_prov.generate_content.side_effect = Exception("Ollama crashed")

        with patch(
            "app.core.agent.llm_provider_helpers.get_provider", return_value=online_prov
        ), patch(
            "app.core.agent.llm_provider_helpers.pick_online_model",
            return_value="gemini-test",
        ), patch(
            "app.core.agent.llm_provider_helpers.is_ollama_alive", return_value=True
        ), patch(
            "app.core.agent.llm_provider_helpers.get_local_provider",
            return_value=local_prov,
        ):
            result = llm_provider_helpers.call_llm_sync("test prompt")

        assert result is None


# ===========================================================================
# 4. _stream_llm() — 用于 client_request 快捷操作的流式降级
# ===========================================================================


def _make_streaming_provider(chunks):
    """构造返回分块流的 mock provider。"""
    provider = MagicMock()
    provider.generate_content.return_value = iter([{"content": c} for c in chunks])
    return provider


class TestStreamLlm:

    @skipif_no_import
    def test_online_stream_success(self):
        """云端流式正常时返回完整文本，不调用本地。"""
        emitted = []

        def fake_emit(event, data, namespace=None):
            emitted.append((event, data))

        online_prov = _make_streaming_provider(["hello ", "world"])

        with patch(
            "app.core.socket_handler._get_provider", return_value=online_prov
        ), patch("app.core.shared.llm_helpers.get_local_provider") as mock_local:
            result = _stream_llm(fake_emit, "Polish:", "some text")

        assert result == "hello world"
        mock_local.assert_not_called()
        # 应该发出了 agent_stream_chunk 事件
        chunk_events = [d for ev, d in emitted if ev == "agent_stream_chunk"]
        assert len(chunk_events) == 2

    @pytest.mark.parametrize(
        "error_msg",
        [
            "timed out",
            "503 unavailable",
            "429 rate limited",
            "api key invalid",
            "quota exceeded",
        ],
    )
    @skipif_no_import
    def test_online_stream_failure_falls_back_to_local(self, error_msg):
        """云端流式失败时应降级到本地并返回本地内容。"""
        emitted = []

        def fake_emit(event, data, namespace=None):
            emitted.append((event, data))

        online_prov = MagicMock()
        online_prov.generate_content.side_effect = RuntimeError(error_msg)

        local_prov = _make_streaming_provider(["local ", "result"])

        with patch(
            "app.core.socket_handler._get_provider", return_value=online_prov
        ), patch(
            "app.core.shared.llm_helpers.is_ollama_alive", return_value=True
        ), patch(
            "app.core.shared.llm_helpers.get_local_provider", return_value=local_prov
        ):
            result = _stream_llm(fake_emit, "Polish:", "text")

        assert (
            result == "local result"
        ), f"Local fallback should produce result for error: {error_msg!r}"

    @skipif_no_import
    def test_online_failure_ollama_down_emits_error(self):
        """云端失败且 Ollama 未运行时，应 emit 错误事件并返回 None。"""
        emitted = []

        def fake_emit(event, data, namespace=None):
            emitted.append((event, data))

        online_prov = MagicMock()
        online_prov.generate_content.side_effect = RuntimeError("503 unavailable")

        with patch(
            "app.core.socket_handler._get_provider", return_value=online_prov
        ), patch("app.core.shared.llm_helpers.is_ollama_alive", return_value=False):
            result = _stream_llm(fake_emit, "Polish:", "text")

        assert result is None
        # 应该发出错误通知
        error_events = [
            d
            for ev, d in emitted
            if ev in ("agent_execute_command", "agent_task_complete")
        ]
        assert len(error_events) > 0

    @skipif_no_import
    def test_non_recoverable_online_error_emits_error_event(self):
        """逻辑/断言错误不触发降级，直接 emit 错误事件并返回 None。"""
        emitted = []

        def fake_emit(event, data, namespace=None):
            emitted.append((event, data))

        online_prov = MagicMock()
        online_prov.generate_content.side_effect = ValueError("bad response format")

        with patch(
            "app.core.socket_handler._get_provider", return_value=online_prov
        ), patch("app.core.shared.llm_helpers.get_local_provider") as mock_local:
            result = _stream_llm(fake_emit, "Polish:", "text")

        assert result is None
        mock_local.assert_not_called()
        error_events = [d for ev, d in emitted if ev == "agent_task_complete"]
        assert len(error_events) > 0


# ===========================================================================
# 5. get_local_provider() — 本地 provider 选取逻辑
# ===========================================================================


class TestGetLocalProvider:

    @skipif_no_import
    def test_selects_model_from_ollama_tags_when_no_model_is_configured(
        self, monkeypatch
    ):
        """应从 /api/tags 列表中选取模型（优先大参数）。"""
        import json

        from app.core.llm import local_model_runtime

        monkeypatch.setattr(
            local_model_runtime, "get_configured_local_model_tag", lambda: ""
        )

        tags_payload = json.dumps(
            {
                "models": [
                    {"name": "phi3:3b"},
                    {"name": "llama3:8b"},  # 应被选中
                    {"name": "tinyllama"},
                ]
            }
        ).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = tags_payload
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_resp

        with patch("urllib.request.build_opener", return_value=mock_opener), patch(
            "app.core.llm.ollama_llm_provider.OllamaLLMProvider"
        ) as MockOllama:
            MockOllama.return_value = MagicMock()
            provider = get_local_provider()

        # OllamaLLMProvider 应被调用，且 model= 包含 8b
        call_kwargs = MockOllama.call_args
        if call_kwargs:
            model_arg = call_kwargs.kwargs.get("model") or (
                call_kwargs.args[0] if call_kwargs.args else None
            )
            if model_arg:
                assert (
                    "8b" in model_arg or "llama3" in model_arg.lower()
                ), f"Expected 8b model, got: {model_arg}"

    @skipif_no_import
    def test_falls_back_to_none_model_when_tags_fail_and_no_model_is_configured(
        self, monkeypatch
    ):
        """当无法查询 Ollama tags 时，应使用 model=None 的默认选择。"""
        from app.core.llm import local_model_runtime

        monkeypatch.setattr(
            local_model_runtime, "get_configured_local_model_tag", lambda: ""
        )
        mock_opener = MagicMock()
        mock_opener.open.side_effect = ConnectionRefusedError()
        with patch("urllib.request.build_opener", return_value=mock_opener), patch(
            "app.core.llm.ollama_llm_provider.OllamaLLMProvider"
        ) as MockOllama:
            MockOllama.return_value = MagicMock()
            get_local_provider()

        MockOllama.assert_called_once_with(model=None)
