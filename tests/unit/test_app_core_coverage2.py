# -*- coding: utf-8 -*-
"""
Comprehensive unit tests for low-coverage app/core modules.

Targets:
  1. app.core.routing.__init__          (lazy imports)
  2. app.core.goal.goal_job_handler      (goal check handling)
  3. app.core.monitoring.event_database   (SQLite event storage)
  5. app.core.analytics.trend_analyzer    (trend analysis)
  6. app.core.scripts.script_generator    (retired guard)
  8. app.core.ops.remediation_policy      (remediation rules)
 10. app.core.services.rag_service        (RAG service)
"""

import json
import os
import queue
import sqlite3
import tempfile
import threading
import time
from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

try:
    import google.genai._api_client  # noqa: F401

    HAS_GENAI = True
except (ImportError, ModuleNotFoundError):
    HAS_GENAI = False

# ═══════════════════════════════════════════════════════════════════════════════
# 1. Routing __init__ (lazy imports)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestRoutingInit:
    """Tests for app.core.routing.__init__ lazy attribute loading."""

    @patch.dict("sys.modules", {"app.core.routing.tool_router": MagicMock()})
    def test_tool_router_lazy_import(self):
        import app.core.routing as routing_mod

        result = routing_mod.__getattr__("ToolRouter")
        assert result is not None

    @patch.dict("sys.modules", {"app.core.routing.tool_router": MagicMock()})
    def test_get_tool_router_lazy_import(self):
        import app.core.routing as routing_mod

        result = routing_mod.__getattr__("get_tool_router")
        assert result is not None

    def test_unknown_attribute_raises(self):
        import app.core.routing as routing_mod

        with pytest.raises(AttributeError, match="has no attribute"):
            routing_mod.__getattr__("NonExistentClass")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. GoalJobHandler
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestGoalJobHandler:
    """Tests for app.core.goal.goal_job_handler."""

    def test_register_goal_handler(self):
        from app.core.goal.goal_job_handler import register_goal_handler

        runner = MagicMock()
        register_goal_handler(runner)
        runner.register_handler.assert_called_once_with(
            "goal_check",
            pytest.importorskip("app.core.goal.goal_job_handler")._handle_goal_check,
        )

    def test_handle_missing_goal_id(self):
        from app.core.goal.goal_job_handler import _handle_goal_check

        ctx = MagicMock()
        ctx.payload = {}
        result = _handle_goal_check(ctx)
        assert "缺少 goal_id" in result

    @patch("app.core.goal.goal_manager.get_goal_manager")
    def test_handle_goal_not_found(self, mock_get_gm):
        from app.core.goal.goal_job_handler import _handle_goal_check

        mock_gm = MagicMock()
        mock_gm.get.return_value = None
        mock_get_gm.return_value = mock_gm
        ctx = MagicMock()
        ctx.payload = {"goal_id": "abc12345"}
        result = _handle_goal_check(ctx)
        assert "未找到目标" in result

    @patch("app.core.goal.goal_manager.get_goal_manager")
    def test_handle_goal_inactive_status(self, mock_get_gm):
        from app.core.goal.goal_job_handler import _handle_goal_check
        from app.core.goal.goal_manager import GoalStatus

        mock_goal = MagicMock()
        mock_goal.title = "Test Goal"
        # Use an actual non-ACTIVE GoalStatus member
        non_active = [s for s in GoalStatus if s != GoalStatus.ACTIVE]
        mock_goal.status = non_active[0] if non_active else MagicMock()

        mock_gm = MagicMock()
        mock_gm.get.return_value = mock_goal
        mock_get_gm.return_value = mock_gm

        ctx = MagicMock()
        ctx.payload = {"goal_id": "abc12345"}
        result = _handle_goal_check(ctx)
        assert "跳过执行" in result

    @patch("app.core.goal.goal_manager.get_goal_manager")
    def test_handle_goal_agent_exception(self, mock_get_gm):
        from app.core.goal.goal_job_handler import _handle_goal_check
        from app.core.goal.goal_manager import GoalStatus

        mock_goal = MagicMock()
        mock_goal.status = GoalStatus.ACTIVE
        mock_goal.title = "Test Goal"
        mock_goal.user_goal = "Track something"
        mock_goal.last_result = None
        mock_goal.session_id = "sess-1"
        mock_goal.get_context.return_value = {"progress_summary": "some progress"}

        mock_run = MagicMock()
        mock_run.run_id = "run-1"

        mock_gm = MagicMock()
        mock_gm.get.return_value = mock_goal
        mock_gm.start_run.return_value = mock_run
        mock_get_gm.return_value = mock_gm

        ctx = MagicMock()
        ctx.payload = {"goal_id": "abc12345"}
        ctx.task_id = "task-1"
        ctx.is_cancelled.return_value = False

        with patch(
            "app.core.agent.kernel_agent_service.get_kernel_agent",
            side_effect=Exception("LLM error"),
        ):
            result = _handle_goal_check(ctx)
            assert result is not None
            mock_gm.finish_run.assert_called_once()

    @patch("app.core.goal.goal_manager.get_goal_manager")
    def test_handle_goal_completed_status_tag(self, mock_get_gm):
        """When agent returns STATUS:COMPLETED, goal should be marked complete."""
        from app.core.goal.goal_job_handler import _handle_goal_check
        from app.core.goal.goal_manager import GoalStatus

        mock_goal = MagicMock()
        mock_goal.status = GoalStatus.ACTIVE
        mock_goal.title = "Test Goal"
        mock_goal.user_goal = "Track something"
        mock_goal.last_result = None
        mock_goal.session_id = "sess-1"
        mock_goal.get_context.return_value = {}

        mock_run = MagicMock()
        mock_run.run_id = "run-1"

        mock_gm = MagicMock()
        mock_gm.get.return_value = mock_goal
        mock_gm.start_run.return_value = mock_run
        mock_get_gm.return_value = mock_gm

        ctx = MagicMock()
        ctx.payload = {"goal_id": "abc12345"}
        ctx.task_id = "task-1"
        ctx.is_cancelled.return_value = False

        # Mock KernelAgent to return STATUS:COMPLETED
        mock_step = MagicMock()
        mock_step.step_type = MagicMock()
        mock_step.step_type.value = "answer"
        mock_step.content = "Goal done\nSTATUS:COMPLETED"

        mock_agent = MagicMock()
        mock_agent.run.return_value = [mock_step]

        with patch(
            "app.core.agent.kernel_agent_service.get_kernel_agent",
            return_value=mock_agent,
        ):
            result = _handle_goal_check(ctx)
            assert result is not None
            mock_gm.complete.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# 3. EventDatabase
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestEventDatabase:
    """Tests for app.core.monitoring.event_database.EventDatabase."""

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path):
        """Create an EventDatabase with a temp DB path."""
        from app.core.monitoring.event_database import EventDatabase

        db = EventDatabase.__new__(EventDatabase)
        db.DB_PATH = tmp_path / "test_events.db"
        db.lock = threading.Lock()
        db._local = threading.local()
        db._ensure_db_exists()
        self.db = db

    def test_save_event_returns_positive_id(self):
        event = {
            "timestamp": "2025-01-01T10:00:00",
            "event_type": "cpu_high",
            "severity": "high",
            "metric_name": "cpu",
            "metric_value": 95.0,
            "threshold": 80.0,
            "description": "CPU too high",
        }
        eid = self.db.save_event(event)
        assert eid > 0

    def test_get_events_returns_saved_events(self):
        event = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event_type": "memory_high",
            "severity": "medium",
            "description": "Memory usage elevated",
        }
        self.db.save_event(event)
        events = self.db.get_events(hours_back=1)
        assert len(events) >= 1
        assert events[0]["event_type"] == "memory_high"

    def test_get_events_filter_by_type(self):
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.db.save_event(
            {"timestamp": now, "event_type": "cpu_high", "severity": "high"}
        )
        self.db.save_event(
            {"timestamp": now, "event_type": "disk_full", "severity": "low"}
        )
        events = self.db.get_events(event_type="cpu_high", hours_back=1)
        assert all(e["event_type"] == "cpu_high" for e in events)

    def test_get_events_filter_by_severity(self):
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.db.save_event(
            {"timestamp": now, "event_type": "cpu_high", "severity": "high"}
        )
        self.db.save_event({"timestamp": now, "event_type": "mem", "severity": "low"})
        events = self.db.get_events(severity="high", hours_back=1)
        assert all(e["severity"] == "high" for e in events)

    def test_get_stats_empty(self):
        stats = self.db.get_stats(days_back=7)
        assert stats["total_events"] == 0

    def test_save_and_get_stats(self):
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.db.save_event(
            {"timestamp": now, "event_type": "cpu_high", "severity": "high"}
        )
        self.db.save_event(
            {"timestamp": now, "event_type": "mem", "severity": "medium"}
        )
        stats = self.db.get_stats(days_back=1)
        assert stats["total_events"] == 2

    def test_save_remediation_action(self):
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        eid = self.db.save_event(
            {"timestamp": now, "event_type": "test", "severity": "low"}
        )
        aid = self.db.save_remediation_action(
            eid, "restart_service", result={"ok": True}
        )
        assert aid > 0

    def test_update_remediation_status(self):
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        eid = self.db.save_event(
            {"timestamp": now, "event_type": "test", "severity": "low"}
        )
        aid = self.db.save_remediation_action(eid, "restart_service")
        result = self.db.update_remediation_status(
            aid, "completed", result={"success": True}
        )
        assert result is True

    def test_clear_old_events(self):
        old_ts = "2020-01-01T00:00:00"
        self.db.save_event(
            {"timestamp": old_ts, "event_type": "old", "severity": "low"}
        )
        deleted = self.db.clear_old_events(days_old=1)
        assert deleted >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 5. TrendAnalyzer
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestTrendAnalyzer:
    """Tests for app.core.analytics.trend_analyzer.TrendAnalyzer."""

    @pytest.fixture
    def analyzer(self):
        from app.core.analytics.trend_analyzer import TrendAnalyzer

        return TrendAnalyzer()

    def test_analyze_empty_events(self, analyzer):
        result = analyzer.analyze_event_trends([])
        assert "error" in result

    def test_analyze_event_trends_basic(self, analyzer):
        events = [
            {"event_type": "cpu_high", "severity": "high"},
            {"event_type": "cpu_high", "severity": "high"},
            {"event_type": "cpu_high", "severity": "medium"},
            {"event_type": "disk_full", "severity": "low"},
        ]
        result = analyzer.analyze_event_trends(events, hours_back=24)
        assert result["total_events"] == 4
        assert "cpu_high" in result["event_types"]
        assert result["avg_events_per_hour"] > 0
        assert len(result["top_trends"]) >= 1

    def test_predict_issues_empty(self, analyzer):
        result = analyzer.predict_issues([])
        assert "warnings" in result or result.get("predictions") == []

    def test_predict_issues_high_frequency(self, analyzer):
        events = [{"event_type": "cpu_high"}] * 12
        result = analyzer.predict_issues(events)
        assert result["total_risk_count"] >= 1
        preds = result["predictions"]
        assert any(p["risk_level"] == "high" for p in preds)

    def test_predict_issues_with_metrics(self, analyzer):
        events = [{"event_type": "mem"}] * 3
        metrics = {"cpu_usage": 90.0, "memory_usage": 92.0}
        result = analyzer.predict_issues(events, metrics=metrics)
        preds = result["predictions"]
        issues = [p["issue"] for p in preds]
        assert any("CPU" in i for i in issues)
        assert any("Memory" in i for i in issues)

    def test_get_historical_comparison_no_data(self, analyzer):
        result = analyzer.get_historical_comparison({"cpu_usage": 50}, {})
        assert "message" in result

    def test_get_historical_comparison_with_data(self, analyzer):
        current = {"cpu_usage": 80, "memory_usage": 70, "disk_usage": 60}
        historical = {"avg_cpu": 50, "avg_memory": 60, "avg_disk": 55}
        result = analyzer.get_historical_comparison(current, historical)
        assert "cpu" in result["comparisons"]
        assert result["comparisons"]["cpu"]["status"] == "above"

    def test_anomaly_score_empty(self, analyzer):
        assert analyzer.get_anomaly_score([]) == 0.0

    def test_anomaly_score_levels(self, analyzer):
        assert analyzer.get_anomaly_score([{"e": 1}] * 1, hours_back=24) == 0.0
        assert analyzer.get_anomaly_score([{"e": 1}] * 30, hours_back=24) == 0.1
        assert analyzer.get_anomaly_score([{"e": 1}] * 80, hours_back=24) == 0.3
        assert analyzer.get_anomaly_score([{"e": 1}] * 200, hours_back=24) == 0.6
        assert analyzer.get_anomaly_score([{"e": 1}] * 300, hours_back=24) == 0.9


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Retired ScriptGenerator
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestScriptGenerator:
    """Guard that system fix script generation remains retired."""

    def test_script_generator_removed(self):
        assert not Path("app/core/scripts/script_generator.py").exists()
        assert not Path("app/core/scripts/__init__.py").exists()


# ═══════════════════════════════════════════════════════════════════════════════
# 8. RemediationPolicy
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestRemediationPolicy:
    """Tests for app.core.ops.remediation_policy."""

    @pytest.fixture
    def policy(self):
        from app.core.ops.remediation_policy import RemediationPolicy

        return RemediationPolicy()

    def test_init_has_builtin_rules(self, policy):
        rules = policy.list_rules()
        names = [r["name"] for r in rules]
        assert "gc_on_memory_pressure" in names
        assert "notify_model_fallback" in names

    def test_add_rule(self, policy):
        from app.core.ops.remediation_policy import RemediationRule

        policy.add_rule(
            RemediationRule(
                name="test_rule",
                trigger_event="test_event",
                action=lambda e, c: None,
            )
        )
        names = [r["name"] for r in policy.list_rules()]
        assert "test_rule" in names

    def test_remove_rule(self, policy):
        from app.core.ops.remediation_policy import RemediationRule

        policy.add_rule(
            RemediationRule(
                name="to_remove", trigger_event="x", action=lambda e, c: None
            )
        )
        policy.remove_rule("to_remove")
        names = [r["name"] for r in policy.list_rules()]
        assert "to_remove" not in names

    def test_enable_disable_rule(self, policy):
        policy.enable_rule("gc_on_memory_pressure", enabled=False)
        rules = {r["name"]: r for r in policy.list_rules()}
        assert rules["gc_on_memory_pressure"]["enabled"] is False
        policy.enable_rule("gc_on_memory_pressure", enabled=True)
        rules = {r["name"]: r for r in policy.list_rules()}
        assert rules["gc_on_memory_pressure"]["enabled"] is True

    def test_should_fire_respects_cooldown(self, policy):
        from app.core.ops.remediation_policy import RemediationRule

        rule = RemediationRule(
            name="test_cd",
            trigger_event="evt",
            action=lambda e, c: None,
            cooldown_seconds=9999,
        )
        rule.last_fired = time.monotonic()
        assert policy._should_fire(rule, "evt", time.monotonic()) is False

    def test_should_fire_min_occurrences(self, policy):
        from app.core.ops.remediation_policy import RemediationRule

        rule = RemediationRule(
            name="test_min",
            trigger_event="evt",
            action=lambda e, c: None,
            min_occurrences=5,
            window_seconds=60,
        )
        # Not enough events
        assert policy._should_fire(rule, "evt", time.monotonic()) is False

    def test_handle_fires_matching_rule(self, policy):
        from app.core.ops.remediation_policy import RemediationRule

        fired = []
        policy.add_rule(
            RemediationRule(
                name="test_fire",
                trigger_event="my_event",
                action=lambda e, c: fired.append(True),
                cooldown_seconds=0,
            )
        )
        event = MagicMock()
        event.event_type = "my_event"
        policy.handle(event)
        # Give the thread time to execute
        time.sleep(0.3)
        assert len(fired) >= 1

    @patch("app.core.ops.remediation_policy.gc.collect", return_value=10)
    def test_action_gc(self, mock_gc):
        from app.core.ops.remediation_policy import _action_gc

        _action_gc(MagicMock(), {})
        mock_gc.assert_called_once()

    def test_action_log_model_fallback(self):
        from app.core.ops.remediation_policy import _action_log_model_fallback

        event = MagicMock()
        event.detail = {"from": "gemini", "to": "local", "reason": "timeout"}
        _action_log_model_fallback(event, {})  # Should not raise

    def test_action_warn_queue_backlog(self):
        from app.core.ops.remediation_policy import _action_warn_queue_backlog

        _action_warn_queue_backlog(MagicMock(), {})  # Should not raise


# ═══════════════════════════════════════════════════════════════════════════════
# 10. RAGService
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestRAGService:
    """Tests for app.core.services.rag_service.RAGService."""

    def test_init_creates_dir(self, tmp_path):
        from app.core.services.rag_service import RAGService

        idx_dir = tmp_path / "rag_idx"
        svc = RAGService(index_dir=str(idx_dir), auto_load=False)
        assert idx_dir.exists()

    def test_stats_no_index(self, tmp_path):
        from app.core.services.rag_service import RAGService

        svc = RAGService(index_dir=str(tmp_path / "empty_rag"), auto_load=False)
        stats = svc.stats()
        assert stats["initialized"] is False
        assert stats["doc_count"] == 0

    def test_clear_empty(self, tmp_path):
        from app.core.services.rag_service import RAGService

        svc = RAGService(index_dir=str(tmp_path / "rag"), auto_load=False)
        assert svc.clear() is True
        assert svc._doc_count == 0

    def test_retrieve_empty_index(self, tmp_path):
        from app.core.services.rag_service import RAGService

        svc = RAGService(index_dir=str(tmp_path / "rag"), auto_load=False)
        results = svc.retrieve("hello")
        assert results == []

    def test_save_no_vectorstore(self, tmp_path):
        from app.core.services.rag_service import RAGService

        svc = RAGService(index_dir=str(tmp_path / "rag"), auto_load=False)
        assert svc.save() is True

    def test_load_no_index_file(self, tmp_path):
        from app.core.services.rag_service import RAGService

        svc = RAGService(index_dir=str(tmp_path / "rag"), auto_load=False)
        assert svc.load() is False

    def test_split_text(self, tmp_path):
        from app.core.services.rag_service import RAGService

        svc = RAGService(index_dir=str(tmp_path / "rag"), auto_load=False)
        text = "Hello world. " * 200
        chunks = svc._split_text(text, source="test")
        assert len(chunks) >= 1
        assert chunks[0].metadata["source"] == "test"

    def test_hybrid_retrieve_empty(self, tmp_path):
        from app.core.services.rag_service import RAGService

        svc = RAGService(index_dir=str(tmp_path / "rag"), auto_load=False)
        results = svc.hybrid_retrieve("query")
        assert results == []

    def test_missing_embedding_backend_falls_back_to_persisted_lexical_search(
        self, tmp_path, monkeypatch
    ):
        import app.core.services.rag_service as rag_module

        def unavailable(*args, **kwargs):
            raise rag_module.EmbeddingBackendUnavailable("test backend unavailable")

        monkeypatch.setattr(rag_module, "_get_embeddings", unavailable)
        index_dir = tmp_path / "lexical_rag"
        svc = rag_module.RAGService(index_dir=str(index_dir), auto_load=False)

        assert svc.index_text("Koto 支持真实前端文件测试", source="memory_1") == 1
        assert svc.stats()["retrieval_backend"] == "lexical"
        assert svc.retrieve("前端文件", k=3)[0]["source"] == "memory_1"

        restored = rag_module.RAGService(index_dir=str(index_dir), auto_load=True)
        assert restored.stats()["initialized"] is True
        assert restored.retrieve("Koto 测试", k=3)[0]["source"] == "memory_1"

    def test_ollama_embedding_adapter_uses_current_local_api(self, monkeypatch):
        import app.core.services.rag_service as rag_module

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"embeddings":[[0.1,0.2]]}'

        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["body"] = request.data
            captured["timeout"] = timeout
            return FakeResponse()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        adapter = rag_module._OllamaLocalEmbeddings("nomic-embed-text")

        assert adapter.embed_query("Koto") == [0.1, 0.2]
        assert captured["url"].endswith("/api/embed")
        assert b'"input": ["Koto"]' in captured["body"]

    def test_tokenize_function(self):
        from app.core.services.rag_service import _tokenize

        tokens = _tokenize("hello world test")
        assert len(tokens) > 0

    def test_rag_answer_no_chunks(self, tmp_path):
        from app.core.services.rag_service import RAGService

        svc = RAGService(index_dir=str(tmp_path / "rag"), auto_load=False)
        result = svc.rag_answer("what is koto?")
        assert result["context_used"] is False
        assert result["answer"] is None
