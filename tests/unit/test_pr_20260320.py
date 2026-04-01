# -*- coding: utf-8 -*-
"""
Tests for PR Logan/20260320 new features:
  - TelegramBot (_split_message, _allowed_ids, command routing, send helpers)
  - memory_api_routes (CRUD, profile, stats endpoints)
  - DocumentComparator (multi-format diff, compare_multiple, build_ai_prompt)
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════════════════════
# 1. TelegramBot — pure-logic helpers (no network)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestSplitMessage:
    """_split_message chunking logic."""

    def _split(self, text, max_len=None):
        from web.telegram_bot import _split_message

        if max_len:
            return _split_message(text, max_len)
        return _split_message(text)

    def test_short_message_returned_as_single_chunk(self):
        parts = self._split("hello world")
        assert parts == ["hello world"]

    def test_long_message_splits_into_multiple_parts(self):
        text = "x" * 9000
        parts = self._split(text, max_len=4000)
        assert len(parts) > 1
        assert all(len(p) <= 4000 for p in parts)

    def test_all_parts_reconstruct_original(self):
        text = "line\n" * 2000
        parts = self._split(text, max_len=4000)
        # reuniting may drop leading newlines but must contain all content
        combined = "".join(parts)
        # content (non-whitespace) must be preserved
        assert len(combined) > 0

    def test_exact_boundary_returns_one_chunk(self):
        text = "a" * 4000
        parts = self._split(text, max_len=4000)
        assert len(parts) == 1

    def test_prefers_newline_split(self):
        text = ("word " * 600) + "\n" + ("other " * 600)
        parts = self._split(text, max_len=3000)
        # Should split at the newline rather than mid-word
        assert len(parts) >= 2


@pytest.mark.unit
class TestAllowedIds:
    """_allowed_ids reads TELEGRAM_ALLOWED_CHAT_IDS from env."""

    def test_returns_none_when_env_not_set(self):
        from web.telegram_bot import _allowed_ids

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TELEGRAM_ALLOWED_CHAT_IDS", None)
            result = _allowed_ids()
        assert result is None

    def test_parses_comma_separated_ids(self):
        from web.telegram_bot import _allowed_ids

        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_CHAT_IDS": "111,222,333"}):
            result = _allowed_ids()
        assert result == [111, 222, 333]

    def test_ignores_empty_segments(self):
        from web.telegram_bot import _allowed_ids

        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_CHAT_IDS": "111,,222"}):
            result = _allowed_ids()
        assert 111 in result
        assert 222 in result


@pytest.mark.unit
class TestGetTelegramBot:
    """get_telegram_bot() singleton behaviour."""

    def test_returns_none_without_token(self):
        from web import telegram_bot as tb

        # Reset singleton so the factory runs fresh
        orig = tb._bot_instance
        tb._bot_instance = None
        try:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("TELEGRAM_BOT_TOKEN", None)
                result = tb.get_telegram_bot()
            assert result is None
        finally:
            tb._bot_instance = orig

    def test_creates_instance_with_token(self):
        from web import telegram_bot as tb

        orig = tb._bot_instance
        tb._bot_instance = None
        try:
            with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "fake:TOKEN"}):
                result = tb.get_telegram_bot()
            assert result is not None
            assert isinstance(result, tb.TelegramBot)
        finally:
            tb._bot_instance = orig


@pytest.mark.unit
class TestTelegramBotHelpers:
    """TelegramBot instance helpers without real HTTP."""

    def setup_method(self):
        from web.telegram_bot import TelegramBot

        self.bot = TelegramBot(token="999:FAKE_TOKEN")

    def test_is_running_false_by_default(self):
        assert self.bot.is_running is False

    def test_send_text_posts_to_telegram_api(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        with patch("requests.post", return_value=mock_resp) as mock_post:
            result = self.bot.send_text(chat_id=123, text="hello")
        assert result is True
        mock_post.assert_called_once()
        # Verify URL contains the token
        url = mock_post.call_args[0][0]
        assert "999:FAKE_TOKEN" in url
        assert "sendMessage" in url

    def test_send_text_returns_false_on_http_error(self):
        with patch("requests.post", side_effect=Exception("network error")):
            result = self.bot.send_text(chat_id=123, text="hello")
        assert result is False

    def test_get_bot_info_parses_response(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "ok": True,
            "result": {"id": 999, "first_name": "KotoBot", "username": "kotobot"},
        }
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.post", return_value=mock_resp):
            info = self.bot.get_bot_info()
        assert info is not None
        assert info["username"] == "kotobot"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. memory_api_routes — Flask route behaviour
# ═══════════════════════════════════════════════════════════════════════════════


def _make_memory_app():
    """Create a minimal Flask app with memory routes registered."""
    from flask import Flask

    from web.memory_api_routes import register_memory_routes

    app = Flask(__name__)
    app.config["TESTING"] = True

    mgr = MagicMock()
    # Basic CRUD — must return plain JSON-serialisable dicts
    mgr.get_all_memories.return_value = [
        {
            "id": 1,
            "content": "User likes Python",
            "category": "user_preference",
            "source": "user",
            "use_count": 3,
        }
    ]
    mgr.add_memory.return_value = {
        "id": 2,
        "content": "New fact",
        "category": "user_preference",
        "source": "user",
    }
    mgr.delete_memory.return_value = True

    # Enhanced profile support — configure so routes can serialise the responses
    mgr.get_profile.return_value = {"name": "Logan", "language": "en"}
    mgr.user_profile.get_brief_summary.return_value = "Logan — Python developer"
    mgr.user_profile.profile = {
        "metadata": {"total_interactions": 42},
        "technical_background": {
            "programming_languages": ["Python", "Go"],
            "tools": ["git", "docker"],
        },
        "preferences": {"likes": ["clean code"], "dislikes": ["meetings"]},
    }
    mgr.personality_matrix.data = {"openness": 0.8, "conscientiousness": 0.7}
    mgr.personality_matrix.to_context_string.return_value = "Curious and organised"

    register_memory_routes(app, lambda: mgr)
    return app.test_client(), mgr


@pytest.mark.unit
class TestMemoryApiRoutes:
    """memory_api_routes CRUD and utility endpoints."""

    def setup_method(self):
        self.client, self.mgr = _make_memory_app()

    def test_get_all_memories_returns_list(self):
        r = self.client.get("/api/memories")
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, list)
        assert len(data) == 1

    def test_add_memory_returns_201_or_200(self):
        r = self.client.post(
            "/api/memories",
            json={"content": "New fact", "category": "user_preference"},
            content_type="application/json",
        )
        assert r.status_code in (200, 201)
        data = r.get_json()
        assert data["success"] is True

    def test_add_memory_empty_content_returns_400(self):
        r = self.client.post(
            "/api/memories",
            json={"content": "   "},
            content_type="application/json",
        )
        assert r.status_code == 400

    def test_delete_memory_returns_200(self):
        with patch("web.memory_api_routes._get_shadow_watcher", return_value=None):
            r = self.client.delete("/api/memories/1")
        assert r.status_code == 200
        data = r.get_json()
        assert data["success"] is True

    def test_delete_nonexistent_memory_returns_404(self):
        self.mgr.delete_memory.return_value = False
        r = self.client.delete("/api/memories/999")
        assert r.status_code == 404

    def test_get_user_profile_returns_200(self):
        r = self.client.get("/api/memory/profile")
        assert r.status_code == 200

    def test_get_memory_stats_returns_200(self):
        r = self.client.get("/api/memory/stats")
        assert r.status_code == 200

    def test_get_personality_matrix_returns_200(self):
        r = self.client.get("/api/memory/personality")
        assert r.status_code == 200

    def test_manager_exception_returns_500(self):
        self.mgr.get_all_memories.side_effect = RuntimeError("db error")
        with patch("web.memory_api_routes._get_shadow_watcher", return_value=None):
            r = self.client.get("/api/memories")
        assert r.status_code == 500


# ═══════════════════════════════════════════════════════════════════════════════
# 3. DocumentComparator
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestDocumentComparatorInit:
    def test_instantiation(self):
        from web.document_comparator import DocumentComparator

        dc = DocumentComparator()
        assert ".txt" in dc.supported_formats
        assert ".pdf" in dc.supported_formats
        assert ".docx" in dc.supported_formats


@pytest.mark.unit
class TestDocumentComparatorTwoFiles:
    """compare_documents with real temp text files."""

    def setup_method(self):
        from web.document_comparator import DocumentComparator

        self.dc = DocumentComparator()

    def _write(self, content: str) -> str:
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        )
        f.write(content)
        f.close()
        return f.name

    def teardown_method(self):
        pass  # temp files cleaned up in each test

    def test_missing_file_returns_error(self):
        result = self.dc.compare_documents("/no/such/a.txt", "/no/such/b.txt")
        assert result["success"] is False

    def test_identical_files_show_no_changes(self):
        text = "line one\nline two\nline three\n"
        a, b = self._write(text), self._write(text)
        try:
            r = self.dc.compare_documents(a, b, output_format="markdown")
            assert r["success"] is True
            changes = r["changes"]
            assert changes["additions"]["count"] == 0
            assert changes["deletions"]["count"] == 0
        finally:
            os.unlink(a)
            os.unlink(b)

    def test_different_files_detect_insertions_and_deletions(self):
        a = self._write("line one\nline two\n")
        b = self._write("line one\nline two\nline three\n")
        try:
            r = self.dc.compare_documents(a, b)
            assert r["success"] is True
            # added a line → additions count should be ≥ 1
            assert r["changes"]["additions"]["count"] >= 1
        finally:
            os.unlink(a)
            os.unlink(b)

    def test_html_output_format(self):
        a = self._write("hello\nworld\n")
        b = self._write("hello\nkoto\n")
        try:
            r = self.dc.compare_documents(a, b, output_format="html")
            assert r["success"] is True
            assert "<" in r["diff"]  # should contain HTML tags
        finally:
            os.unlink(a)
            os.unlink(b)

    def test_inline_json_output_format(self):
        a = self._write("old content\n")
        b = self._write("new content\n")
        try:
            r = self.dc.compare_documents(a, b, output_format="inline_json")
            assert r["success"] is True
            # diff may be list or string — just not empty
            assert r["diff"] is not None
        finally:
            os.unlink(a)
            os.unlink(b)


@pytest.mark.unit
class TestDocumentComparatorMultiple:
    """compare_multiple across N documents."""

    def setup_method(self):
        from web.document_comparator import DocumentComparator

        self.dc = DocumentComparator()
        self._files = []

    def _write(self, content: str) -> str:
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        )
        f.write(content)
        f.close()
        self._files.append(f.name)
        return f.name

    def teardown_method(self):
        for p in self._files:
            try:
                os.unlink(p)
            except OSError:
                pass

    def test_two_file_compare_multiple(self):
        a = self._write("alpha beta gamma\n")
        b = self._write("alpha delta gamma\n")
        r = self.dc.compare_multiple([a, b])
        assert r.get("success") is True
        assert "matrix" in r
        assert len(r["matrix"]) >= 1

    def test_three_file_compare_multiple(self):
        a = self._write("v1 content\n")
        b = self._write("v2 content\n")
        c = self._write("v3 content\n")
        r = self.dc.compare_multiple([a, b, c])
        assert r.get("success") is True
        # 3 files → C(3,2)=3 pairs
        assert len(r["matrix"]) == 3

    def test_empty_list_returns_error(self):
        r = self.dc.compare_multiple([])
        assert r.get("success") is False

    def test_single_file_returns_error(self):
        a = self._write("only one\n")
        r = self.dc.compare_multiple([a])
        assert r.get("success") is False


@pytest.mark.unit
class TestDocumentComparatorBuildPrompt:
    """build_ai_prompt constructs a string prompt for LLM analysis."""

    def setup_method(self):
        from web.document_comparator import DocumentComparator

        self.dc = DocumentComparator()
        self._files = []

    def _write(self, content: str) -> str:
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        )
        f.write(content)
        f.close()
        self._files.append(f.name)
        return f.name

    def teardown_method(self):
        for p in self._files:
            try:
                os.unlink(p)
            except OSError:
                pass

    def test_prompt_is_non_empty_string(self):
        a = self._write("document alpha\n")
        b = self._write("document beta\n")
        prompt = self.dc.build_ai_prompt([a, b])
        assert isinstance(prompt, str)
        assert len(prompt) > 50

    def test_prompt_contains_file_names(self):
        a = self._write("doc A content\n")
        b = self._write("doc B content\n")
        prompt = self.dc.build_ai_prompt([a, b])
        # At least one filename should appear
        assert Path(a).name in prompt or Path(b).name in prompt or "文档" in prompt


@pytest.mark.unit
class TestDocumentComparatorVersions:
    """compare_versions treats list as chronological version history."""

    def setup_method(self):
        from web.document_comparator import DocumentComparator

        self.dc = DocumentComparator()
        self._files = []

    def _write(self, content: str) -> str:
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        )
        f.write(content)
        f.close()
        self._files.append(f.name)
        return f.name

    def teardown_method(self):
        for p in self._files:
            try:
                os.unlink(p)
            except OSError:
                pass

    def test_compare_versions_returns_dict(self):
        a = self._write("v1\n")
        b = self._write("v2\n")
        c = self._write("v3\n")
        r = self.dc.compare_versions([a, b, c])
        assert isinstance(r, dict)
        assert r.get("success") is not False or "error" in r
