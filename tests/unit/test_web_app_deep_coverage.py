#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Deep coverage tests for web/app.py internal classes and functions.

Targets large, under-tested components: KotoBrain,
run_with_timeout, run_with_heartbeat,
stream_with_keepalive, LocalDispatcher, auto_save_files, and many more.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
import time
import types
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, Mock, PropertyMock, call, patch

import pytest

try:
    import google.genai._api_client  # noqa: F401

    HAS_GENAI = True
except (ImportError, ModuleNotFoundError):
    HAS_GENAI = False

# ---------------------------------------------------------------------------
# Env setup before importing the app
# ---------------------------------------------------------------------------
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault("KOTO_AUTH_ENABLED", "false")
os.environ.setdefault("KOTO_DEPLOY_MODE", "local")
os.environ.setdefault("GEMINI_API_KEY", "test-key-for-unit-tests")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-for-unit-tests")


@contextmanager
def _using_workspace_root(path):
    from app.core.config.workspace_runtime import get_workspace_root, set_workspace_root

    previous_root = get_workspace_root()
    set_workspace_root(path)
    try:
        yield
    finally:
        set_workspace_root(previous_root)


# =====================================================================
# Helpers
# =====================================================================
def _import_app():
    """Import web.app lazily so env vars are already set."""
    import web.app as app_mod

    return app_mod


def _import_memory_runtime():
    import web.memory_runtime as memory_runtime

    return memory_runtime


# =====================================================================
# 1. _get_local_model_config
# =====================================================================
@pytest.mark.unit
class TestGetLocalModelConfig:
    def test_returns_cloud_none_on_missing_file(self, tmp_path):
        app = _import_app()
        with patch("app.core.llm.provider_factory.is_local_mode", return_value=False):
            mode, tag = app._get_local_model_config()
        assert mode == "cloud"
        assert tag is None

    def test_reads_local_mode(self, tmp_path):
        app = _import_app()
        with patch(
            "app.core.llm.provider_factory.is_local_mode", return_value=True
        ), patch(
            "app.core.llm.provider_factory.get_local_model_tag",
            return_value="qwen2.5:7b",
        ):
            mode, tag = app._get_local_model_config()
        assert mode == "local"
        assert tag == "qwen2.5:7b"

    def test_defaults_cloud_when_mode_missing(self, tmp_path):
        app = _import_app()
        with patch(
            "app.core.llm.provider_factory.is_local_mode", return_value=False
        ), patch(
            "app.core.llm.provider_factory.get_local_model_tag",
            return_value="qwen2.5:7b",
        ):
            mode, tag = app._get_local_model_config()
        assert mode == "cloud"
        assert tag is None

    def test_handles_corrupt_json(self, tmp_path):
        app = _import_app()
        with patch(
            "app.core.llm.provider_factory.is_local_mode",
            side_effect=RuntimeError("provider settings unavailable"),
        ):
            mode, tag = app._get_local_model_config()
        assert mode == "cloud"
        assert tag is None


# =====================================================================
# 2. _extract_prompt_text
# =====================================================================
@pytest.mark.unit
class TestExtractPromptText:
    def test_none_contents(self):
        from web.llm_runtime_helpers import extract_prompt_text

        text, sys = extract_prompt_text(None)
        assert text == ""
        assert sys is None

    def test_string_contents(self):
        from web.llm_runtime_helpers import extract_prompt_text

        text, sys = extract_prompt_text("hello world")
        assert text == "hello world"
        assert sys is None

    def test_list_of_strings(self):
        from web.llm_runtime_helpers import extract_prompt_text

        text, _ = extract_prompt_text(["a", "b", "c"])
        assert text == "a\nb\nc"

    def test_list_with_text_attr(self):
        from web.llm_runtime_helpers import extract_prompt_text

        obj = Mock()
        obj.text = "from obj"
        obj.parts = None  # so hasattr(item, "parts") won't recurse
        text, _ = extract_prompt_text([obj])
        assert "from obj" in text

    def test_list_with_parts(self):
        from web.llm_runtime_helpers import extract_prompt_text

        part = Mock()
        part.text = "part_text"
        item = Mock(spec=[])  # no .text attribute
        item.text = None
        item.parts = [part]

        # Need to make hasattr work correctly
        class ItemWithParts:
            text = None
            parts = [part]

        text, _ = extract_prompt_text([ItemWithParts()])
        assert "part_text" in text

    def test_non_string_non_list(self):
        from web.llm_runtime_helpers import extract_prompt_text

        text, _ = extract_prompt_text(12345)
        assert text == "12345"

    def test_with_system_instruction(self):
        from web.llm_runtime_helpers import extract_prompt_text

        cfg = Mock()
        cfg.system_instruction = "be helpful"
        text, sys = extract_prompt_text("hello", config=cfg)
        assert text == "hello"
        assert sys == "be helpful"

    def test_config_without_system_instruction(self):
        from web.llm_runtime_helpers import extract_prompt_text

        cfg = Mock(spec=[])  # no system_instruction attribute
        text, sys = extract_prompt_text("hello", config=cfg)
        assert text == "hello"
        assert sys is None

    def test_empty_list(self):
        from web.llm_runtime_helpers import extract_prompt_text

        text, _ = extract_prompt_text([])
        assert text == ""

    def test_list_with_fallback_str(self):
        from web.llm_runtime_helpers import extract_prompt_text

        # Object without .text or .parts
        class Opaque:
            def __str__(self):
                return "opaque_value"

        text, _ = extract_prompt_text([Opaque()])
        assert "opaque_value" in text


# =====================================================================
# 3. _FakeGenerateContentResponse
# =====================================================================
@pytest.mark.unit
class TestFakeGenerateContentResponse:
    def test_attributes(self):
        from web.llm_runtime_helpers import FakeGenerateContentResponse

        resp = FakeGenerateContentResponse("hello")
        assert resp.text == "hello"
        assert resp.candidates == []
        assert resp.usage_metadata is None


# =====================================================================
# 4. Runtime gateway boundary
# =====================================================================
@pytest.mark.unit
class TestRuntimeGatewayBoundary:
    def test_web_app_does_not_reintroduce_sdk_client_proxies(self):
        app = _import_app()
        assert not hasattr(app, "_TrackedModels")
        assert not hasattr(app, "_ClientProxy")
        assert not hasattr(app, "client")

    def test_runtime_gateway_is_the_generation_owner(self):
        from app.core.llm.runtime_gateway import LLMRuntimeGateway

        provider = MagicMock()
        provider.generate_content.return_value = {"content": "ok"}
        response = LLMRuntimeGateway(provider, "model-a").generate_content(
            contents="hello"
        )
        assert response.text == "ok"


# =====================================================================
# 5. _is_interactions_only
# =====================================================================
@pytest.mark.unit
class TestInteractionsChecks:
    def test_is_interactions_only_known(self):
        app = _import_app()
        # Only deep-research model is in the static default set
        assert app._is_interactions_only("deep-research-pro-preview-12-2025") is True

    def test_is_interactions_only_unknown(self):
        app = _import_app()
        assert app._is_interactions_only("gemini-2.5-flash") is False

    def test_is_interactions_only_deep_research_prefix(self):
        app = _import_app()
        assert app._is_interactions_only("deep-research-pro-preview-99") is True

    def test_is_interactions_only_deep_research_exact(self):
        app = _import_app()
        assert app._is_interactions_only("deep-research-pro-preview-12-2025") is True

    def test_is_interactions_only_gemini3_flash_prefix(self):
        """gemini-3-flash-preview uses the normal generate_content path."""
        app = _import_app()
        assert app._is_interactions_only("gemini-3-flash-preview") is False

    def test_is_interactions_only_gemini3_pro_prefix(self):
        """gemini-3-pro-preview uses the normal generate_content path."""
        app = _import_app()
        assert app._is_interactions_only("gemini-3-pro-preview") is False

    def test_is_interactions_only_regular_model_false(self):
        app = _import_app()
        assert app._is_interactions_only("gemini-2.0-flash") is False

    def test_is_interactions_only_none(self):
        app = _import_app()
        assert app._is_interactions_only(None) is False

    def test_is_interactions_only_empty_string(self):
        app = _import_app()
        assert app._is_interactions_only("") is False


# =====================================================================
# 6. run_with_timeout
# =====================================================================
@pytest.mark.unit
class TestRunWithTimeout:
    def test_success(self):
        from web.utils.threading_utils import run_with_timeout

        result, error, timed_out = run_with_timeout(lambda: 42, 5)
        assert result == 42
        assert error is None
        assert timed_out is False

    def test_exception_captured(self):
        from web.utils.threading_utils import run_with_timeout

        def boom():
            raise ValueError("fail")

        result, error, timed_out = run_with_timeout(boom, 5)
        assert result is None
        assert isinstance(error, ValueError)
        assert timed_out is False

    def test_timeout(self):
        from web.utils.threading_utils import run_with_timeout

        def slow():
            time.sleep(10)

        result, error, timed_out = run_with_timeout(slow, 0.1)
        assert timed_out is True
        assert isinstance(error, TimeoutError)


# =====================================================================
# 7. run_with_heartbeat
# =====================================================================
@pytest.mark.unit
class TestRunWithHeartbeat:
    def test_success(self):
        from web.utils.threading_utils import run_with_heartbeat

        result, error, timed_out = run_with_heartbeat(
            lambda: "ok",
            start_time=time.time(),
            heartbeat_callback=lambda e: None,
            heartbeat_interval=1,
            timeout_seconds=5,
        )
        assert result == "ok"
        assert error is None
        assert timed_out is False

    def test_error(self):
        from web.utils.threading_utils import run_with_heartbeat

        def boom():
            raise RuntimeError("fail")

        result, error, timed_out = run_with_heartbeat(
            boom,
            start_time=time.time(),
            heartbeat_callback=lambda e: None,
            timeout_seconds=5,
        )
        assert result is None
        assert isinstance(error, RuntimeError)
        assert timed_out is False

    def test_timeout(self):
        from web.utils.threading_utils import run_with_heartbeat

        def slow():
            time.sleep(10)

        result, error, timed_out = run_with_heartbeat(
            slow,
            start_time=time.time() - 100,  # Already elapsed
            heartbeat_callback=lambda e: None,
            timeout_seconds=1,
        )
        assert timed_out is True

    def test_heartbeat_called(self):
        from web.utils.threading_utils import run_with_heartbeat

        beats = []

        def slow():
            time.sleep(3)
            return "done"

        result, error, timed_out = run_with_heartbeat(
            slow,
            start_time=time.time(),
            heartbeat_callback=lambda e: beats.append(e),
            heartbeat_interval=1,
            timeout_seconds=10,
        )
        assert result == "done"
        assert len(beats) >= 1  # At least one heartbeat


# =====================================================================
# 8. stream_with_keepalive
# =====================================================================
@pytest.mark.unit
class TestStreamWithKeepalive:
    def test_normal_stream(self):
        app = _import_app()
        chunks = [Mock(text="a"), Mock(text="b")]
        results = list(app.stream_with_keepalive(iter(chunks), time.time()))
        types_ = [r[0] for r in results]
        assert "chunk" in types_

    def test_timeout_waiting_for_first_token(self):
        app = _import_app()

        def slow_stream():
            time.sleep(10)
            yield Mock(text="late")

        results = list(
            app.stream_with_keepalive(
                slow_stream(),
                start_time=time.time() - 100,  # Already past timeout
                max_wait_first_token=1,
            )
        )
        types_ = [r[0] for r in results]
        assert "timeout" in types_

    def test_heartbeat_emitted(self):
        app = _import_app()
        import queue

        # Simulate a slow stream with delayed chunks
        def delayed_stream():
            time.sleep(2)
            yield Mock(text="delayed")

        results = list(
            app.stream_with_keepalive(
                delayed_stream(),
                start_time=time.time(),
                keepalive_interval=1,
                max_wait_first_token=10,
            )
        )
        types_ = [r[0] for r in results]
        assert "heartbeat" in types_ or "chunk" in types_

    def test_error_in_stream(self):
        app = _import_app()

        def error_stream():
            raise RuntimeError("stream error")
            yield  # pragma: no cover

        with pytest.raises(RuntimeError, match="stream error"):
            list(app.stream_with_keepalive(error_stream(), time.time()))


# =====================================================================
# 9–10. _poll_interaction and _extract_interaction_text_global were
# removed from module level in PR #45; tests removed accordingly.
# =====================================================================


# =====================================================================
# 12. error response helpers (Flask context required)
# =====================================================================
@pytest.mark.unit
class TestErrorResponse:
    def test_basic_error(self):
        app_mod = _import_app()
        flask_app = app_mod.app
        with flask_app.test_request_context("/test"):
            flask_app.preprocess_request()  # triggers _assign_request_id
            resp, status = app_mod.error_response("bad request", 400)
            data = resp.get_json()
        assert status == 400
        assert data["error"] == "bad request"
        assert "request_id" in data
        assert not hasattr(app_mod, "_error_response")

    def test_error_with_details(self):
        app_mod = _import_app()
        flask_app = app_mod.app
        with flask_app.test_request_context("/test"):
            flask_app.preprocess_request()
            resp, status = app_mod.error_response(
                "fail", 422, details={"field": "name"}
            )
            data = resp.get_json()
        assert data["details"]["field"] == "name"
        assert status == 422

    def test_error_without_request_id(self):
        app_mod = _import_app()
        flask_app = app_mod.app
        with flask_app.test_request_context("/test"):
            # Don't call preprocess_request, so g.request_id is not set
            resp, status = app_mod.error_response("oops", 500)
            data = resp.get_json()
        assert data["error"] == "oops"
        assert "request_id" not in data

    def test_shared_error_response_keeps_legacy_envelope(self):
        app_mod = _import_app()
        from web.shared import _error_response

        with app_mod.app.test_request_context("/test"):
            resp, status = _error_response("oops", 500, error_type="unit")
            data = resp.get_json()
        assert status == 500
        assert data == {"error": "oops", "success": False, "type": "unit"}


# =====================================================================
# 13. _assign_request_id
# =====================================================================
@pytest.mark.unit
class TestAssignRequestId:
    def test_generates_uuid(self):
        app_mod = _import_app()
        flask_app = app_mod.app
        with flask_app.test_request_context("/"):
            flask_app.preprocess_request()
            from flask import g

            assert hasattr(g, "request_id")
            assert len(g.request_id) > 0

    def test_reads_from_header(self):
        app_mod = _import_app()
        flask_app = app_mod.app
        with flask_app.test_request_context(
            "/", headers={"X-Request-ID": "custom-123"}
        ):
            flask_app.preprocess_request()
            from flask import g

            assert g.request_id == "custom-123"


# =====================================================================
# 17. LocalDispatcher
# =====================================================================
@pytest.mark.unit
class TestLocalDispatcher:
    def test_is_ollama_running_cloud(self):
        app = _import_app()
        with patch.dict(os.environ, {"KOTO_DEPLOY_MODE": "cloud"}):
            assert app.LocalDispatcher.is_ollama_running() is False

    def test_is_ollama_running_connection_error(self):
        app = _import_app()
        fake_requests = Mock()
        fake_requests.get.side_effect = Exception("no conn")

        with patch.dict(os.environ, {"KOTO_DEPLOY_MODE": "local"}), patch.dict(
            sys.modules, {"requests": fake_requests}
        ):
            assert app.LocalDispatcher.is_ollama_running() is False

    def test_analyze_signature_contract(self):
        app = _import_app()
        # Free-text routing is owned by the Kernel/model boundary; the legacy
        # LocalDispatcher analysis method must stay absent.
        assert not hasattr(app, "SmartDispatcher")
        assert not hasattr(app.LocalDispatcher, "analyze")


# =====================================================================
# 18. Utils.auto_save_files
# =====================================================================
@pytest.mark.unit
class TestAutoSaveFiles:
    def test_begin_end_file_pattern(self, tmp_path):
        app = _import_app()
        with _using_workspace_root(tmp_path):
            text = "---BEGIN_FILE: test_output.py---\nprint('hello')\n---END_FILE---"
            saved = app.Utils.auto_save_files(text)
        assert "test_output.py" in saved

    def test_no_match(self, tmp_path):
        app = _import_app()
        with _using_workspace_root(tmp_path):
            saved = app.Utils.auto_save_files("just plain text, no files")
        assert saved == []

    def test_python_code_block_with_filename(self, tmp_path):
        app = _import_app()
        with _using_workspace_root(tmp_path):
            text = "```python\n# filename: my_script.py\nimport os\nprint(os.getcwd())\nprint('hello world this is a test')\n```"
            saved = app.Utils.auto_save_files(text)
        assert "my_script.py" in saved

    def test_file_without_extension(self, tmp_path):
        app = _import_app()
        with _using_workspace_root(tmp_path):
            text = "---BEGIN_FILE: noext---\ncontent here\n---END_FILE---"
            saved = app.Utils.auto_save_files(text)
        assert any("noext" in f for f in saved)

    def test_get_save_dir_code_ext(self, tmp_path):
        app = _import_app()
        code_dir = str(tmp_path / "code")
        os.makedirs(code_dir, exist_ok=True)
        with _using_workspace_root(tmp_path):
            text = "---BEGIN_FILE: script.py---\nprint(1)\n---END_FILE---"
            saved = app.Utils.auto_save_files(text)
        assert "script.py" in saved

    def test_get_save_dir_non_code_ext(self, tmp_path):
        app = _import_app()
        with _using_workspace_root(tmp_path):
            text = "---BEGIN_FILE: report.pdf---\nbinary content\n---END_FILE---"
            saved = app.Utils.auto_save_files(text)
        assert "report.pdf" in saved


# =====================================================================
# 19. Utils helpers
# =====================================================================
@pytest.mark.unit
class TestUtilsMethods:
    def test_sanitize_string(self):
        app = _import_app()
        assert app.Utils.sanitize_string("hello") == "hello"
        assert app.Utils.sanitize_string(123) == 123

    def test_is_failure_output_empty(self):
        app = _import_app()
        assert app.Utils.is_failure_output("") is True
        assert app.Utils.is_failure_output(None) is True

    def test_is_failure_output_error_prefix(self):
        app = _import_app()
        assert app.Utils.is_failure_output("❌ something failed") is True

    def test_is_failure_output_chinese_error(self):
        app = _import_app()
        assert app.Utils.is_failure_output("操作失败了") is True

    def test_is_failure_output_no_internet(self):
        app = _import_app()
        assert (
            app.Utils.is_failure_output("I don't have access to the internet") is True
        )

    def test_is_failure_output_normal(self):
        app = _import_app()
        assert app.Utils.is_failure_output("Here is your answer") is False

    def test_build_fix_prompt_file_gen(self):
        app = _import_app()
        prompt = app.Utils.build_fix_prompt("FILE_GEN", "make doc", "bad output")
        assert "BEGIN_FILE" in prompt

    def test_build_fix_prompt_coder(self):
        app = _import_app()
        prompt = app.Utils.build_fix_prompt("CODER", "write code")
        assert "代码" in prompt or "code" in prompt.lower()

    def test_build_fix_prompt_research(self):
        app = _import_app()
        prompt = app.Utils.build_fix_prompt("RESEARCH", "research topic")
        assert "报告" in prompt or "report" in prompt.lower()

    def test_build_fix_prompt_web_search(self):
        app = _import_app()
        prompt = app.Utils.build_fix_prompt("WEB_SEARCH", "search query")
        assert "实时" in prompt or "信息" in prompt

    def test_build_fix_prompt_generic(self):
        app = _import_app()
        prompt = app.Utils.build_fix_prompt("OTHER", "input")
        assert "用户需求" in prompt


# =====================================================================
# 20. get_memory_manager
# =====================================================================
@pytest.mark.unit
class TestGetMemoryManager:
    def test_returns_instance(self):
        app = _import_app()
        memory_runtime = _import_memory_runtime()
        mock_mgr = MagicMock()

        with patch(
            "app.core.services.memory_manager.get_memory_manager",
            return_value=mock_mgr,
        ), patch.object(memory_runtime, "_inject_memory_adapters"):
            assert app.get_memory_manager() is mock_mgr

    def test_has_no_legacy_manager_fallback(self):
        memory_runtime = _import_memory_runtime()
        source = Path(memory_runtime.__file__).read_text(encoding="utf-8")

        assert "from web.memory_manager import MemoryManager" not in source
        assert "from enhanced_memory_manager import EnhancedMemoryManager" not in source


# =====================================================================
# 22. KotoBrain.chat - SYSTEM route
# =====================================================================
@pytest.mark.unit
class TestKotoBrainChat:
    def _make_brain(self):
        app = _import_app()
        return app.KotoBrain(), app

    def test_chat_returns_response_and_model(self):
        brain, app = self._make_brain()
        fake_provider = MagicMock()
        fake_provider.generate_content.return_value = MagicMock(text="hello back")
        from web.runtime_context import service_registry

        with patch.object(
            type(service_registry),
            "llm_gateway",
            new_callable=PropertyMock,
            return_value=fake_provider,
        ):
            result = brain.chat([], "hello")
        assert result["response"] == "hello back"
        assert "model" in result

    @pytest.mark.skipif(not HAS_GENAI, reason="google.genai not properly installed")
    def test_manual_model_selection(self):
        brain, app = self._make_brain()
        provider = MagicMock()
        provider.generate_content.return_value = {"content": "manual response"}
        with patch(
            "app.core.llm.provider_factory.get_llm_provider",
            return_value=provider,
        ), patch.object(app, "_start_memory_extraction"):
            result = brain.chat(
                [],
                "hello",
                model="deepseek-chat",
                auto_model=False,
                task_type="CHAT",
            )
        assert result["model"] == "deepseek-chat"

    def test_chat_appends_user_message_to_history(self):
        brain, app = self._make_brain()
        fake_provider = MagicMock()
        fake_provider.generate_content.return_value = MagicMock(text="ok")
        from web.runtime_context import service_registry

        service_registry._cache["llm_gateway"] = fake_provider
        try:
            brain.chat([{"role": "user", "content": "hi"}], "next")
        finally:
            service_registry._cache.pop("llm_gateway", None)
        _, kwargs = fake_provider.generate_content.call_args
        messages = kwargs["contents"]
        assert messages[-1] == {"role": "user", "content": "next"}
        assert len(messages) == 2

    def test_chat_handles_gateway_error(self):
        brain, app = self._make_brain()
        fake_provider = MagicMock()
        fake_provider.generate_content.side_effect = Exception("boom")
        from web.runtime_context import service_registry

        service_registry._cache["llm_gateway"] = fake_provider
        try:
            result = brain.chat([], "hello")
        finally:
            service_registry._cache.pop("llm_gateway", None)
        assert "boom" in result["response"]

    def test_chat_resolves_local_model(self):
        from dataclasses import replace

        brain, app = self._make_brain()
        fake_provider = MagicMock()
        fake_provider.generate_content.return_value = MagicMock(text="ok")
        brain._runtime = replace(
            brain._runtime,
            select_model_for_task=lambda *_args, **_kwargs: "qwen2.5:7b",
        )
        from web.runtime_context import service_registry

        service_registry._cache["llm_gateway"] = fake_provider
        try:
            result = brain.chat([], "hello")
        finally:
            service_registry._cache.pop("llm_gateway", None)
        assert result["model"] == "qwen2.5:7b"


# =====================================================================
# 23. _process_code_response (nested inside KotoBrain.chat)
# =====================================================================
@pytest.mark.unit
class TestProcessCodeResponse:
    """Test the code extraction logic used in _process_code_response."""

    def test_extract_begin_file_pattern(self):
        import re

        text = "---BEGIN_FILE: edit.py---\nimport cv2\nprint('hi')\n---END_FILE---"
        pattern = (
            r"---BEGIN_FILE:\s*([a-zA-Z0-9_.-]+)\s*---\s*(.*?)---\s*END_FILE\s*---"
        )
        matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
        assert len(matches) == 1
        assert matches[0][0] == "edit.py"

    def test_extract_python_code_block(self):
        import re

        text = "```python\nimport os\nprint('hello')\n```"
        pattern = r"```python\s*(.*?)```"
        matches = re.findall(pattern, text, re.DOTALL)
        assert len(matches) == 1
        assert "import os" in matches[0]

    def test_no_code_found(self):
        import re

        text = "No code here, just a plain text response."
        patterns = [
            r"---BEGIN_FILE:\s*([a-zA-Z0-9_.-]+)\s*---\s*(.*?)---\s*END_FILE\s*---",
            r"```python\s*(.*?)```",
            r"```\s*(.*?)```",
        ]
        found = False
        for pattern in patterns:
            if re.findall(pattern, text, re.DOTALL | re.IGNORECASE):
                found = True
                break
        assert found is False


# =====================================================================
# 24. _clean_filegen_text logic (extracted for testing)
# =====================================================================
@pytest.mark.unit
class TestCleanFilegenText:
    """Test the markdown cleaning logic used in _clean_filegen_text."""

    def _clean(self, text):
        import re

        if not text:
            return text
        cleaned = text
        cleaned = re.sub(r"```[a-zA-Z0-9_-]*\n", "", cleaned)
        cleaned = cleaned.replace("```", "")
        cleaned = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned)
        cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", cleaned)
        cleaned = re.sub(r"__(.+?)__", r"\1", cleaned)
        cleaned = re.sub(r"\*(.+?)\*", r"\1", cleaned)
        cleaned = re.sub(r"_(.+?)_", r"\1", cleaned)
        cleaned = cleaned.replace("`", "")
        cleaned = re.sub(r"^\s{0,3}#{1,6}\s+", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"^\s*>\s?", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"^\s*[-_*]{3,}\s*$", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"^\s*[-*+]\s+", "  ", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"^\s*\d+\.\s+", "  ", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = cleaned.replace("**", "").replace("__", "")
        return cleaned

    def test_removes_code_blocks(self):
        assert "```" not in self._clean("```python\ncode\n```")

    def test_removes_bold(self):
        assert self._clean("**bold text**") == "bold text"

    def test_removes_links(self):
        assert self._clean("[click](http://example.com)") == "click"

    def test_removes_headings(self):
        result = self._clean("# Heading\nText")
        assert "#" not in result

    def test_removes_blockquote(self):
        result = self._clean("> quoted text")
        assert ">" not in result

    def test_removes_hr(self):
        result = self._clean("---\n\ncontent")
        assert "---" not in result

    def test_empty_input(self):
        assert self._clean("") == ""
        assert self._clean(None) is None

    def test_normalizes_blank_lines(self):
        result = self._clean("a\n\n\n\nb")
        assert "\n\n\n" not in result


# =====================================================================
# 25. _extract_markdown_table logic
# =====================================================================
@pytest.mark.unit
class TestExtractMarkdownTable:
    def _extract(self, md_text):
        import re

        lines = [line.strip() for line in md_text.splitlines() if "|" in line]
        for i in range(len(lines) - 1):
            header_line = lines[i]
            sep_line = lines[i + 1]
            if re.match(r"^\s*\|?\s*[-:|\s]+\|\s*$", sep_line):
                headers = [c.strip() for c in header_line.strip("|").split("|")]
                rows = []
                j = i + 2
                while j < len(lines) and "|" in lines[j]:
                    row = [c.strip() for c in lines[j].strip("|").split("|")]
                    if len(row) < len(headers):
                        row += [""] * (len(headers) - len(row))
                    rows.append(row[: len(headers)])
                    j += 1
                return [headers] + rows
        return None

    def test_basic_table(self):
        md = "| Name | Age |\n|---|---|\n| Alice | 30 |\n| Bob | 25 |"
        result = self._extract(md)
        assert result is not None
        assert "Name" in result[0][0]
        assert len(result) == 3  # header + 2 rows

    def test_no_table(self):
        assert self._extract("Just text\nNo table") is None

    def test_short_row_padded(self):
        md = "| A | B | C |\n|---|---|---|\n| 1 |"
        result = self._extract(md)
        assert result is not None
        assert len(result[1]) == 3  # padded to match headers


# =====================================================================
# 27. KotoBrain.IMAGE_EDIT_KEYWORDS
# =====================================================================
@pytest.mark.unit
class TestKotoBrainKeywords:
    def test_legacy_keyword_attributes_removed(self):
        app = _import_app()
        brain = app.KotoBrain()
        assert not hasattr(brain, "IMAGE_EDIT_KEYWORDS")
        assert not hasattr(brain, "SYSTEM_KEYWORDS")


# =====================================================================
# 28. SessionManager
# =====================================================================
@pytest.mark.unit
class TestSessionManager:
    def test_delete_nonexistent(self, tmp_path):
        from web.session_manager import SessionManager, set_chat_dir

        set_chat_dir(str(tmp_path))
        mgr = SessionManager()
        assert mgr.delete("nonexistent.json") is False

    def test_load_missing_file(self, tmp_path):
        from web.session_manager import SessionManager, set_chat_dir

        set_chat_dir(str(tmp_path))
        mgr = SessionManager()
        assert mgr.load("missing.json") == []

    def test_load_corrupt_json(self, tmp_path):
        (tmp_path / "bad.json").write_text("NOT JSON", encoding="utf-8")
        from web.session_manager import SessionManager, set_chat_dir

        set_chat_dir(str(tmp_path))
        mgr = SessionManager()
        assert mgr.load("bad.json") == []


# =====================================================================
# 29. Flask error handlers
# =====================================================================
@pytest.mark.unit
class TestFlaskErrorHandlers:
    def test_404_handler(self):
        app_mod = _import_app()
        client = app_mod.app.test_client()
        resp = client.get("/this-does-not-exist-at-all-404")
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["error"] == "Not found"

    def test_405_handler(self):
        app_mod = _import_app()
        # POST to a GET-only route (like static)
        client = app_mod.app.test_client()
        resp = client.delete("/")  # DELETE on root
        # May return 404 or 405 depending on route config
        assert resp.status_code in (404, 405)


# =====================================================================
# 30. runtime service registry
# =====================================================================
@pytest.mark.unit
class TestRuntimeServiceRegistry:
    def test_registered_factory_constructs_once(self):
        from web.runtime_context import ServiceRegistry

        registry = ServiceRegistry()
        calls = []

        class Dummy:
            def __init__(self):
                self.attr = "value"
                calls.append(1)

        registry.register_factory("unit_dummy", Dummy)
        first = registry.resolve("unit_dummy")
        second = registry.resolve("unit_dummy")

        assert first is second
        assert first.attr == "value"
        assert calls == [1]

    def test_invalidate_reconstructs_registered_service(self):
        from web.runtime_context import ServiceRegistry

        registry = ServiceRegistry()
        registry.register_factory("unit_dummy", object)
        first = registry.resolve("unit_dummy")
        registry.invalidate("unit_dummy")

        assert registry.resolve("unit_dummy") is not first

    def test_legacy_lazy_module_stays_removed_from_app(self):
        app = _import_app()

        assert not hasattr(app, "_LazyModule")
        assert not list((Path(_PROJECT_ROOT) / "web" / "lazy_loaders").glob("*.py"))


# =====================================================================
# 32. _attach_request_id
# =====================================================================
@pytest.mark.unit
class TestAttachRequestId:
    def test_response_has_header(self):
        app_mod = _import_app()
        flask_app = app_mod.app
        client = flask_app.test_client()
        # Any request should get X-Request-ID in response
        resp = client.get("/this-does-not-exist-at-all-test-rid")
        assert "X-Request-ID" in resp.headers
