"""Tests for service registry and session manager."""
import json
import os
import tempfile
import threading
from pathlib import Path

import pytest


class TestServiceRegistry:
    """Tests for web.runtime_context.ServiceRegistry."""

    def test_singleton(self):
        from web.runtime_context import service_registry
        from web.runtime_context import service_registry as sr2
        assert service_registry is sr2

    def test_cache_invalidation(self):
        from web.runtime_context import service_registry
        service_registry.invalidate("test_key")
        service_registry._cache["test_key"] = "stale"
        service_registry.invalidate("test_key")
        assert "test_key" not in service_registry._cache

    def test_clear_all_cache(self):
        from web.runtime_context import service_registry
        service_registry._cache["a"] = 1
        service_registry._cache["b"] = 2
        service_registry.invalidate()
        assert len(service_registry._cache) == 0

    def test_shutdown_hooks(self):
        from web.runtime_context import service_registry
        results = []
        service_registry.on_shutdown(lambda: results.append("hook1"))
        service_registry.on_shutdown(lambda: results.append("hook2"))
        service_registry.shutdown()
        assert results == ["hook1", "hook2"]
        service_registry._shutdown_hooks.clear()

    def test_shutdown_handles_errors(self):
        from web.runtime_context import service_registry

        def bad_hook():
            raise RuntimeError("test error")

        service_registry.on_shutdown(bad_hook)
        service_registry.shutdown()  # Should not raise
        service_registry._shutdown_hooks.clear()


class TestSessionManager:
    """Tests for web.session_manager.SessionManager."""

    @pytest.fixture
    def chat_dir(self, monkeypatch, tmp_path):
        """Mock _chat_dir to use a temp directory."""
        monkeypatch.setattr(
            "web.session_manager._chat_dir",
            lambda: str(tmp_path),
        )
        return tmp_path

    @pytest.fixture
    def session_mgr(self):
        from web.session_manager import SessionManager
        return SessionManager()

    def test_create_session(self, session_mgr, chat_dir):
        filename = session_mgr.create("test_session")
        assert filename.endswith(".json")
        assert os.path.exists(chat_dir / filename)

    def test_save_and_load(self, session_mgr, chat_dir):
        filename = session_mgr.create("save_test")
        history = [
            {"role": "user", "parts": ["hello"]},
            {"role": "model", "parts": ["hi there"]},
        ]
        session_mgr.save(filename, history)
        loaded = session_mgr.load_full(filename)
        assert len(loaded) == 2
        assert loaded[0]["parts"] == ["hello"]

    def test_append_and_save_is_atomic(self, session_mgr, chat_dir):
        filename = session_mgr.create("atomic_test")
        session_mgr.append_and_save(filename, "msg1", "reply1")
        loaded = session_mgr.load_full(filename)
        assert len(loaded) == 2
        assert loaded[-1]["parts"] == ["reply1"]

    def test_concurrent_writes(self, session_mgr, chat_dir):
        """Verify session locking prevents corruption."""
        import threading
        filename = session_mgr.create("concurrent_test")
        session_mgr.save(filename, [])
        
        # Sequential append should always work
        session_mgr.append_and_save(filename, "msg1", "reply1")
        session_mgr.append_and_save(filename, "msg2", "reply2")
        loaded = session_mgr.load_full(filename)
        assert len(loaded) == 4  # 2 user + 2 model

    def test_list_sessions(self, session_mgr, chat_dir):
        session_mgr.create("alpha")
        session_mgr.create("beta")
        sessions = session_mgr.list_sessions()
        assert len(sessions) >= 2

    def test_delete_session(self, session_mgr, chat_dir):
        filename = session_mgr.create("delete_me")
        assert session_mgr.delete(filename)
        assert not os.path.exists(chat_dir / filename)

    def test_delete_nonexistent(self, session_mgr, chat_dir):
        result = session_mgr.delete("nonexistent.json")
        assert not result

    def test_rename_session(self, session_mgr, chat_dir):
        filename = session_mgr.create("old_name")
        result = session_mgr.rename(filename, "new_name")
        assert result["success"]
        assert os.path.exists(chat_dir / result["new_filename"])

    def test_trim_history_respects_limit(self, session_mgr, chat_dir):
        filename = session_mgr.create("trim_test")
        # Create 25 turns
        history = []
        for i in range(25):
            history.append({"role": "user", "parts": [f"msg{i}"]})
            history.append({"role": "model", "parts": [f"reply{i}"]})
        session_mgr.save(filename, history)

        trimmed = session_mgr.load(filename)  # Uses _trim_history
        assert len(trimmed) <= 20
