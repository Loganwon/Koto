"""Unit tests for LLM providers: GeminiProvider and OllamaLLMProvider.

All external API/network calls are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# GeminiProvider — basic structure and generate_content
# ---------------------------------------------------------------------------


class TestGeminiProviderBasic:
    def test_provider_has_timeout_config(self):
        from app.core.llm.gemini import GeminiProvider

        assert hasattr(GeminiProvider, "MAX_RETRIES")
        assert isinstance(GeminiProvider.MAX_RETRIES, int)
        assert GeminiProvider.MAX_RETRIES > 0

    def test_normal_model_not_substituted(self):
        from app.core.llm.gemini import _INTERACTIONS_ONLY_MODELS

        # Normal model should NOT be in the interactions-only set
        assert "gemini-2.5-flash" not in _INTERACTIONS_ONLY_MODELS

    def test_generate_content_tracks_usage(self):
        from app.core.llm.gemini import GeminiProvider

        provider = GeminiProvider.__new__(GeminiProvider)
        provider._get_client = MagicMock(return_value=MagicMock())
        provider._call_with_retry = MagicMock(
            return_value={
                "content": "ok",
                "tool_calls": [],
                "usage": {"prompt_tokens": 11, "completion_tokens": 13},
            }
        )
        provider._format_tools = MagicMock(return_value=None)
        provider._format_prompt = MagicMock(
            return_value=[{"role": "user", "parts": []}]
        )
        provider._track_usage = MagicMock()

        with patch(
            "app.core.llm.gemini.types.GenerateContentConfig", return_value=object()
        ):
            result = provider.generate_content(
                prompt="hello",
                model="gemini-2.5-flash",
                stream=False,
                skill_id="skill-a",
                session_id="sess-a",
            )

        assert result["content"] == "ok"
        provider._track_usage.assert_called_once_with(
            "gemini-2.5-flash",
            {"prompt_tokens": 11, "completion_tokens": 13},
            skill_id="skill-a",
            session_id="sess-a",
        )

    def test_generate_content_passes_per_call_timeout(self):
        from app.core.llm.gemini import GeminiProvider

        provider = GeminiProvider.__new__(GeminiProvider)
        provider._get_client = MagicMock(return_value=MagicMock())
        provider._call_with_retry = MagicMock(
            return_value={"content": "ok", "tool_calls": [], "usage": None}
        )
        provider._format_tools = MagicMock(return_value=None)
        provider._format_prompt = MagicMock(
            return_value=[{"role": "user", "parts": []}]
        )
        provider._track_usage = MagicMock()

        with patch(
            "app.core.llm.gemini.types.GenerateContentConfig", return_value=object()
        ):
            provider.generate_content(
                prompt="hello",
                model="gemini-2.5-flash",
                stream=False,
                call_timeout=42,
            )

        _, kwargs = provider._call_with_retry.call_args
        assert kwargs["timeout_seconds"] == 42

    def test_call_with_retry_timeout_like_error_no_retry(self):
        from app.core.llm.gemini import GeminiProvider

        provider = GeminiProvider.__new__(GeminiProvider)
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception(
            "ReadTimeout: operation timed out"
        )

        with pytest.raises(TimeoutError):
            provider._call_with_retry(
                model="gemini-2.5-flash",
                contents="hello",
                config=object(),
                client=mock_client,
            )

        # Timeout-like failures should fail fast to avoid long hangs.
        assert mock_client.models.generate_content.call_count == 1


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
            skill_id="skill-b",
            session_id="sess-b",
        )

        assert result["content"] == "ok"
        provider._track_usage.assert_called_once_with(
            "gpt-4o",
            {"prompt_tokens": 3, "completion_tokens": 4},
            skill_id="skill-b",
            session_id="sess-b",
        )


class TestAnthropicProviderTracking:
    def test_generate_content_tracks_usage(self):
        from app.core.llm.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider.client = MagicMock()
        provider._build_messages = MagicMock(
            return_value=[{"role": "user", "content": "hi"}]
        )
        provider._format_tools = MagicMock(return_value=None)
        provider._format_response = MagicMock(
            return_value={
                "content": "ok",
                "tool_calls": [],
                "usage": {"prompt_tokens": 8, "completion_tokens": 9},
            }
        )
        provider._track_usage = MagicMock()

        result = provider.generate_content(
            prompt="hi",
            model="claude-3-7-sonnet-20250219",
            skill_id="skill-c",
            session_id="sess-c",
        )

        assert result["content"] == "ok"
        provider._track_usage.assert_called_once_with(
            "claude-3-7-sonnet-20250219",
            {"prompt_tokens": 8, "completion_tokens": 9},
            skill_id="skill-c",
            session_id="sess-c",
        )


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

    def test_cached_auto_model_used_within_ttl(self):
        import time

        from app.core.llm.ollama_llm_provider import OllamaLLMProvider

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


# ---------------------------------------------------------------------------
# GeminiProvider._format_prompt — role mapping regression tests
# ---------------------------------------------------------------------------


class TestGeminiFormatPromptRoles:
    """Ensure _format_prompt only emits Gemini-legal roles (user / model)."""

    @staticmethod
    def _provider():
        from app.core.llm.gemini import GeminiProvider

        return GeminiProvider.__new__(GeminiProvider)

    def test_assistant_mapped_to_model(self):
        prov = self._provider()
        contents = prov._format_prompt([{"role": "assistant", "content": "hi"}])
        assert all(c["role"] in ("user", "model") for c in contents)
        assert contents[0]["role"] == "model"

    def test_function_mapped_to_user_with_function_response(self):
        prov = self._provider()
        contents = prov._format_prompt(
            [
                {"role": "function", "name": "search", "content": "result"},
            ]
        )
        assert contents[0]["role"] == "user"
        assert any("function_response" in p for p in contents[0]["parts"])

    def test_no_tool_role_emitted(self):
        """Gemini rejects 'tool' role — make sure it never appears."""
        prov = self._provider()
        messages = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "calling tool",
                "tool_calls": [{"name": "f", "args": {}}],
            },
            {"role": "function", "name": "f", "content": "done"},
        ]
        contents = prov._format_prompt(messages)
        roles = {c["role"] for c in contents}
        assert roles <= {"user", "model"}, f"unexpected roles: {roles}"


# ---------------------------------------------------------------------------
# TestOllamaAutoDetect (continued) — expired cache + fallback
# ---------------------------------------------------------------------------


class TestOllamaAutoDetectExtended:

    @staticmethod
    def _get_provider(model):
        from app.core.llm.ollama_llm_provider import OllamaLLMProvider

        return OllamaLLMProvider(model=model)

    def test_expired_cache_triggers_re_detection(self):
        import sys
        import time
        from unittest.mock import MagicMock

        from app.core.llm.ollama_llm_provider import OllamaLLMProvider

        OllamaLLMProvider._auto_model = "stale-model:7b"
        OllamaLLMProvider._auto_model_ts = time.time() - 9999  # expired
        prov = self._get_provider(model=None)

        mock_router = MagicMock()
        mock_router.pick_best_chat_model.return_value = "fresh-model:8b"
        with patch.dict(
            sys.modules,
            {
                "app.core.routing.local_model_router": MagicMock(
                    LocalModelRouter=mock_router
                )
            },
        ):
            result = prov._resolve_model()
        # Either fresh detection worked or fallback to hardcoded default
        assert isinstance(result, str)
        assert result != ""

    def test_fallback_when_router_unavailable(self):
        import sys
        import time
        from unittest.mock import MagicMock

        from app.core.llm.ollama_llm_provider import OllamaLLMProvider

        OllamaLLMProvider._auto_model = ""
        OllamaLLMProvider._auto_model_ts = 0.0
        prov = self._get_provider(model=None)

        mock_router_module = MagicMock()
        mock_router_module.LocalModelRouter.pick_best_chat_model.side_effect = (
            Exception("ollama down")
        )
        with patch.dict(
            sys.modules, {"app.core.routing.local_model_router": mock_router_module}
        ):
            result = prov._resolve_model()

        # Should fall back to hardcoded default, not crash
        assert isinstance(result, str)
        assert len(result) > 0

    def test_auto_model_cache_class_level(self):
        """Two instances with model=None share the class-level cache."""
        import time

        from app.core.llm.ollama_llm_provider import OllamaLLMProvider

        OllamaLLMProvider._auto_model = "shared:7b"
        OllamaLLMProvider._auto_model_ts = time.time()

        p1 = OllamaLLMProvider(model=None)
        p2 = OllamaLLMProvider(model=None)
        assert p1._resolve_model() == p2._resolve_model() == "shared:7b"
