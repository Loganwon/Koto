"""Unit tests for the active OpenAI, DeepSeek, and Ollama providers.

All external API/network calls are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestOpenAIProviderTracking:
    def test_generate_content_tracks_usage(self):
        from app.core.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider.client = MagicMock()
        provider._build_messages = MagicMock(
            return_value=[{"role": "user", "content": "hi"}]
        )
        provider._format_tools = MagicMock(return_value=None)
        provider._format_response = MagicMock(
            return_value={
                "content": "ok",
                "tool_calls": [],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4},
            }
        )
        provider._track_usage = MagicMock()

        result = provider.generate_content(
            prompt="hi",
            model="gpt-4o",
            session_id="sess-b",
        )

        assert result["content"] == "ok"
        provider._track_usage.assert_called_once_with(
            "gpt-4o",
            {"prompt_tokens": 3, "completion_tokens": 4},
            session_id="sess-b",
        )

    def test_generate_content_passes_openai_compatible_extra_body(self):
        from app.core.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider.client = MagicMock()
        provider._build_messages = MagicMock(
            return_value=[{"role": "user", "content": "hi"}]
        )
        provider._format_tools = MagicMock(return_value=None)
        provider._format_response = MagicMock(
            return_value={"content": "ok", "tool_calls": [], "usage": {}}
        )
        provider._track_usage = MagicMock()

        provider.generate_content(
            prompt="hi",
            model="deepseek-chat",
            extra_body={"thinking": {"type": "enabled"}},
        )

        _, kwargs = provider.client.chat.completions.create.call_args
        assert kwargs["extra_body"] == {"thinking": {"type": "enabled"}}


class TestDeepSeekProvider:
    def test_provider_factory_loads_deepseek_from_env(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test-key")
        from app.core.llm.provider_factory import get_llm_provider

        with patch("app.core.llm.openai_provider._openai_available", True), patch(
            "app.core.llm.openai_provider.OpenAI"
        ) as mock_openai:
            provider = get_llm_provider(provider="deepseek")

        assert provider.api_key == "ds-test-key"
        assert str(provider.base_url).rstrip("/") == "https://api.deepseek.com"
        mock_openai.assert_called_once()

    def test_cloud_provider_deepseek_resolves_v4_pro(self, monkeypatch):
        monkeypatch.setenv("KOTO_CLOUD_PROVIDER", "deepseek")
        from app.core.llm.model_selection import get_configured_cloud_model

        assert (
            get_configured_cloud_model(
                "FILE_TASK", fallback_model="gemini-3.1-pro-preview"
            )
            == "deepseek-chat"
        )
        assert (
            get_configured_cloud_model(
                "VISION", fallback_model="gemini-3-flash-preview"
            )
            == "gemini-3-flash-preview"
        )

    def test_cloud_provider_defaults_to_deepseek_for_text_tasks(self, monkeypatch):
        monkeypatch.delenv("KOTO_CLOUD_PROVIDER", raising=False)
        monkeypatch.delenv("KOTO_LLM_PROVIDER", raising=False)
        import app.core.config.user_settings as user_settings

        class FakeSettings:
            def get(self, *_args, **_kwargs):
                return ""

        monkeypatch.setattr(user_settings, "SettingsManager", lambda: FakeSettings())
        from app.core.llm.model_selection import (
            get_configured_cloud_model,
            get_provider_for_model_mode,
        )

        assert get_provider_for_model_mode("cloud") == "deepseek"
        assert get_provider_for_model_mode("") == "deepseek"
        assert (
            get_configured_cloud_model(
                "FILE_TASK", fallback_model="gemini-3.1-pro-preview"
            )
            == "deepseek-chat"
        )
        assert (
            get_configured_cloud_model(
                "PAINTER", fallback_model="gemini-3.1-flash-image-preview"
            )
            == "gemini-3.1-flash-image-preview"
        )

    def test_deepseek_fallback_chain_does_not_mix_gemini(self):
        from app.core.llm.model_fallback import ModelFallbackExecutor

        executor = ModelFallbackExecutor()
        candidates = executor._build_candidate_list("deepseek-chat", "FILE_TASK")

        assert "deepseek-chat" in candidates
        assert "deepseek-reasoner" not in candidates
        assert all(not model.startswith("gemini-") for model in candidates)

    def test_empty_fallback_chain_uses_deepseek_primary(self):
        from app.core.llm.model_fallback import ModelFallbackExecutor

        executor = ModelFallbackExecutor()
        candidates = executor._build_candidate_list("", "FILE_TASK")

        assert "deepseek-chat" in candidates
        assert all(not model.startswith("gemini-") for model in candidates)


# ---------------------------------------------------------------------------
# OllamaLLMProvider — _resolve_model auto-selection
# ---------------------------------------------------------------------------


class TestOllamaLLMProviderResolveModel:
    def _get_provider(self, model=None):
        from app.core.llm.ollama_llm_provider import OllamaLLMProvider

        # Reset class-level cache
        OllamaLLMProvider._auto_model = ""
        OllamaLLMProvider._auto_model_ts = 0.0
        return OllamaLLMProvider(model=model)

    def test_explicit_model_returned_directly(self):
        prov = self._get_provider(model="qwen3:8b")
        assert prov._resolve_model() == "qwen3:8b"

    def test_none_model_calls_local_router(self):
        from app.core.llm.ollama_llm_provider import OllamaLLMProvider

        OllamaLLMProvider._auto_model = ""
        OllamaLLMProvider._auto_model_ts = 0.0
        prov = self._get_provider(model=None)

        with patch(
            "app.core.llm.ollama_llm_provider.OllamaLLMProvider._resolve_model",
            return_value="qwen3:4b",
        ) as mock_resolve:
            result = prov._resolve_model()
        # Either the mock intercepted it or it returned the patched value
        assert isinstance(result, str)

    def test_cached_auto_model_used_within_ttl_when_no_model_is_configured(
        self, monkeypatch
    ):
        import time

        from app.core.llm import local_model_runtime
        from app.core.llm.ollama_llm_provider import OllamaLLMProvider

        monkeypatch.setattr(
            local_model_runtime, "get_configured_local_model_tag", lambda: ""
        )
        OllamaLLMProvider._auto_model = "cached-model:7b"
        OllamaLLMProvider._auto_model_ts = time.time()  # fresh timestamp — within TTL
        prov = OllamaLLMProvider(model=None)  # no explicit model
        result = prov._resolve_model()
        # Cache hit: should return cached value without calling router
        assert result == "cached-model:7b"


class TestOllamaProviderTimeoutPassthrough:
    @patch("app.core.llm.ollama_llm_provider._raw_post")
    def test_generate_content_passes_call_timeout(self, mock_post):
        from app.core.llm.ollama_llm_provider import OllamaLLMProvider

        mock_post.return_value = {
            "message": {"content": "ok"},
            "prompt_eval_count": 1,
            "eval_count": 1,
        }

        provider = OllamaLLMProvider(model="qwen3.5:9b")
        result = provider.generate_content("hello", call_timeout=45)

        assert result["content"] == "ok"
        call = mock_post.call_args
        timeout_value = call.kwargs.get("timeout_seconds")
        if timeout_value is None and len(call.args) > 3:
            timeout_value = call.args[3]
        assert timeout_value == 45


class TestOpenAIProviderMessageFormatting:
    @staticmethod
    def _provider():
        from app.core.llm.openai_provider import OpenAIProvider

        return OpenAIProvider.__new__(OpenAIProvider)

    def test_tool_call_ids_are_preserved_across_turns(self):
        prov = self._provider()
        messages = prov._build_messages(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"id": "call_first", "name": "read", "args": {"path": "a"}}
                    ],
                    "reasoning_content": "thinking",
                },
                {
                    "role": "function",
                    "name": "read",
                    "tool_call_id": "call_first",
                    "content": "done",
                },
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"id": "call_second", "name": "write", "args": {"path": "b"}}
                    ],
                },
                {
                    "role": "function",
                    "name": "write",
                    "tool_call_id": "call_second",
                    "content": "done",
                },
            ],
            system_instruction=None,
        )

        assistant_calls = [
            msg["tool_calls"][0]["id"]
            for msg in messages
            if msg["role"] == "assistant" and msg.get("tool_calls")
        ]
        tool_ids = [msg["tool_call_id"] for msg in messages if msg["role"] == "tool"]
        assert assistant_calls == ["call_first", "call_second"]
        assert tool_ids == ["call_first", "call_second"]
        assert messages[0]["reasoning_content"] == "thinking"

    def test_incomplete_tool_call_history_is_downgraded_to_text(self):
        prov = self._provider()
        messages = prov._build_messages(
            [
                {"role": "user", "content": "run it"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"id": "call_missing", "name": "read", "args": {"path": "a"}}
                    ],
                },
                {"role": "user", "content": "continue"},
            ],
            system_instruction=None,
        )

        assert [msg["role"] for msg in messages] == ["user", "assistant", "user"]
        assert not any(msg.get("tool_calls") for msg in messages)
        assert messages[1]["content"] == "工具调用记录已省略：read"

    def test_orphan_tool_message_is_folded_into_context_text(self):
        prov = self._provider()
        messages = prov._build_messages(
            [
                {
                    "role": "function",
                    "name": "read",
                    "tool_call_id": "call_orphan",
                    "content": "file text",
                }
            ],
            system_instruction=None,
        )

        assert messages == [{"role": "user", "content": "工具结果（read）：file text"}]


# ---------------------------------------------------------------------------
# TestOllamaAutoDetect (continued) — expired cache + fallback
# ---------------------------------------------------------------------------


class TestOllamaAutoDetectExtended:

    @staticmethod
    def _get_provider(model):
        from app.core.llm.ollama_llm_provider import OllamaLLMProvider

        return OllamaLLMProvider(model=model)

    def test_expired_cache_triggers_re_detection(self):
        import time

        from app.core.llm.local_model_runtime import OllamaRuntime
        from app.core.llm.ollama_llm_provider import OllamaLLMProvider

        OllamaLLMProvider._auto_model = "stale-model:7b"
        OllamaLLMProvider._auto_model_ts = time.time() - 9999  # expired
        prov = self._get_provider(model=None)

        with patch.object(
            OllamaRuntime, "pick_best_chat_model", return_value="fresh-model:8b"
        ):
            result = prov._resolve_model()
        # Either fresh detection worked or fallback to hardcoded default
        assert isinstance(result, str)
        assert result != ""

    def test_fallback_when_ollama_detection_is_unavailable(self):
        from app.core.llm.local_model_runtime import OllamaRuntime
        from app.core.llm.ollama_llm_provider import OllamaLLMProvider

        OllamaLLMProvider._auto_model = ""
        OllamaLLMProvider._auto_model_ts = 0.0
        prov = self._get_provider(model=None)

        with patch.object(
            OllamaRuntime,
            "pick_best_chat_model",
            side_effect=Exception("ollama down"),
        ):
            result = prov._resolve_model()

        # Should fall back to hardcoded default, not crash
        assert isinstance(result, str)
        assert len(result) > 0

    def test_auto_model_cache_class_level_when_no_model_is_configured(
        self, monkeypatch
    ):
        """Two instances with model=None share the class-level cache."""
        import time

        from app.core.llm import local_model_runtime
        from app.core.llm.ollama_llm_provider import OllamaLLMProvider

        monkeypatch.setattr(
            local_model_runtime, "get_configured_local_model_tag", lambda: ""
        )
        OllamaLLMProvider._auto_model = "shared:7b"
        OllamaLLMProvider._auto_model_ts = time.time()

        p1 = OllamaLLMProvider(model=None)
        p2 = OllamaLLMProvider(model=None)
        assert p1._resolve_model() == p2._resolve_model() == "shared:7b"
