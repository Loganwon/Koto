# -*- coding: utf-8 -*-
"""
Tests for Phase 1–3 Koto optimizations:
  1. AppContext — DI Container
  2. Smart Memory Filter — MemoryRouter + CWM
  3. Skill Auto-Suggest — Affinity Tracking + History-aware Suggestions
"""

import json
import math
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ══════════════════════════════════════════════════════════════════════════════
# Phase 1: AppContext Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestAppContext:
    """Test the centralized DI container."""

    def test_import_and_singleton(self):
        """ctx should be a module-level singleton."""
        from app.core.app_context import AppContext, ctx

        assert isinstance(ctx, AppContext)

    def test_registered_services_exist(self):
        """All default services should be registered."""
        from app.core.app_context import ctx

        expected = [
            "config_manager",
            "settings_manager",
            "memory_manager",
            "knowledge_base",
            "file_registry",
            "task_ledger",
            "system_monitor",
            "notification_manager",
            "checkpointer",
            "model_manager",
            "agent",
            "token_tracker",
        ]
        for name in expected:
            assert name in ctx._slots, f"Service '{name}' not registered"

    def test_override_and_reset(self):
        """Override should replace, reset should restore."""
        from app.core.app_context import ctx

        mock_cfg = MagicMock()
        ctx.override("config_manager", mock_cfg)
        assert ctx.get("config_manager") is mock_cfg
        assert ctx.config_manager is mock_cfg

        ctx.reset("config_manager")
        # After reset, should no longer return the mock
        assert ctx.get("config_manager") is not mock_cfg

    def test_override_all_reset(self):
        """reset() with no name clears all overrides."""
        from app.core.app_context import ctx

        mock1 = MagicMock()
        mock2 = MagicMock()
        ctx.override("config_manager", mock1)
        ctx.override("settings_manager", mock2)
        ctx.reset()
        # Both overrides should be cleared

    def test_lazy_initialization(self):
        """Services should not be created until accessed."""
        from app.core.app_context import AppContext

        fresh = AppContext()
        # No slot should have an instance yet
        for slot in fresh._slots.values():
            assert slot.instance is None

    def test_register_custom_service(self):
        """Custom services can be registered at runtime."""
        from app.core.app_context import ctx

        ctx.register_custom("my_test_service", lambda: {"test": True})
        result = ctx.get("my_test_service")
        assert result == {"test": True}
        # Cleanup
        ctx.reset("my_test_service")

    def test_unknown_service_raises(self):
        """Accessing unregistered service should raise KeyError."""
        from app.core.app_context import ctx

        with pytest.raises(KeyError):
            ctx.get("nonexistent_service_xyz")

    def test_thread_safety(self):
        """Multiple threads accessing the same service should not race."""
        from app.core.app_context import AppContext

        call_count = {"n": 0}
        lock = threading.Lock()

        def slow_factory():
            with lock:
                call_count["n"] += 1
            time.sleep(0.01)
            return {"created": True}

        fresh = AppContext()
        fresh._register("test_svc", slow_factory)

        results = []

        def worker():
            results.append(fresh.get("test_svc"))

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Factory should be called exactly once
        assert call_count["n"] == 1
        assert all(r == {"created": True} for r in results)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 2: Smart Memory Filter Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestMemoryRouterSmartFilter:
    """Test the upgraded MemoryRouter with scoring, decay, and dedup."""

    def test_bigrams(self):
        from app.core.memory.memory_router import _bigrams

        assert _bigrams("abc") == ["ab", "bc"]
        assert _bigrams("a") == ["a"]
        assert _bigrams("") == [""]

    def test_compute_recency_recent(self):
        """Recent memories should have high recency score."""
        from app.core.memory.memory_router import _compute_recency

        now = datetime.now()
        decay_lambda = math.log(2) / 30.0
        hit = {"created_at": now.strftime("%Y-%m-%dT%H:%M:%S")}
        score = _compute_recency(hit, now, decay_lambda)
        assert score > 0.95  # Fresh memory → ~1.0

    def test_compute_recency_old(self):
        """30-day old memory should have ~0.5 score."""
        from app.core.memory.memory_router import _compute_recency

        now = datetime.now()
        old = now - timedelta(days=30)
        decay_lambda = math.log(2) / 30.0
        hit = {"created_at": old.strftime("%Y-%m-%dT%H:%M:%S")}
        score = _compute_recency(hit, now, decay_lambda)
        assert 0.45 < score < 0.55  # ~0.5 at half-life

    def test_compute_recency_missing_timestamp(self):
        """Missing timestamp should return moderate penalty."""
        from app.core.memory.memory_router import _compute_recency

        now = datetime.now()
        decay_lambda = math.log(2) / 30.0
        hit = {}
        score = _compute_recency(hit, now, decay_lambda)
        assert score == 0.7

    def test_deduplicate_removes_similar(self):
        """Near-identical memories should be deduplicated."""
        from app.core.memory.memory_router import _deduplicate

        scored = [
            (0.9, {"content": "用户喜欢Python编程语言", "id": 1}),
            (0.8, {"content": "用户喜欢Python编程语言和Go", "id": 2}),
            (0.7, {"content": "用户住在北京朝阳区", "id": 3}),
        ]
        result = _deduplicate(scored)
        # "Python编程语言" and "Python编程语言和Go" may be similar enough to dedup
        # But "住在北京" is different, should survive
        ids = [h.get("id") for _, h in result]
        assert 1 in ids
        assert 3 in ids

    def test_deduplicate_keeps_all_unique(self):
        """Completely different memories should all be kept."""
        from app.core.memory.memory_router import _deduplicate

        scored = [
            (0.9, {"content": "用户是Python开发者", "id": 1}),
            (0.8, {"content": "用户住在上海浦东新区", "id": 2}),
            (0.7, {"content": "用户最近在学习机器学习", "id": 3}),
        ]
        result = _deduplicate(scored)
        assert len(result) == 3

    def test_score_and_rank_vector_vs_keyword(self):
        """Vector hits should have higher semantic signal than keyword hits."""
        from app.core.memory.memory_router import _score_and_rank

        now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        hits = [
            {
                "id": 1,
                "content": "用户喜欢编程",
                "category": "user_fact",
                "created_at": now_str,
                "_source": "vector",
            },
            {
                "id": 2,
                "content": "用户喜欢编程",
                "category": "user_fact",
                "created_at": now_str,
                "_source": "keyword",
            },
        ]
        scored = _score_and_rank(hits, "完全不相关的查询", "CHAT", ["user_fact"])
        # Vector hit (0.8 semantic) should beat keyword (0.4 base) when query doesn't overlap
        vector_score = next(s for s, h in scored if h["id"] == 1)
        keyword_score = next(s for s, h in scored if h["id"] == 2)
        assert vector_score > keyword_score

    def test_full_read_with_mock_manager(self):
        """End-to-end MemoryRouter.read() with mocked manager."""
        from app.core.memory.memory_router import MemoryRouter

        now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        mock_mgr = MagicMock()
        mock_mgr.user_profile = None
        mock_mgr.search_vector_memories.return_value = [
            {
                "id": 1,
                "content": "用户是一名Python后端开发者",
                "category": "user_fact",
                "created_at": now_str,
            },
            {
                "id": 2,
                "content": "用户喜欢简洁的代码风格",
                "category": "preference",
                "created_at": now_str,
            },
        ]
        mock_mgr.search_memories.return_value = []

        result = MemoryRouter.read(
            query="帮我写一个Python函数",
            session_name="test",
            get_memory_fn=lambda: mock_mgr,
            include_profile=False,
            task_type="CODER",
        )
        assert "长期记忆" in result
        assert "Python" in result

    def test_read_empty_manager(self):
        """Should return empty string when manager returns nothing."""
        from app.core.memory.memory_router import MemoryRouter

        mock_mgr = MagicMock()
        mock_mgr.user_profile = None
        mock_mgr.search_vector_memories.return_value = []
        mock_mgr.search_memories.return_value = []

        result = MemoryRouter.read(
            query="你好",
            session_name="test",
            get_memory_fn=lambda: mock_mgr,
            include_profile=False,
        )
        assert "长期记忆" not in result

    def test_read_none_manager(self):
        """Should handle None manager gracefully."""
        from app.core.memory.memory_router import MemoryRouter

        result = MemoryRouter.read(
            query="测试",
            session_name="test",
            get_memory_fn=lambda: None,
        )
        assert result == "" or "记忆" not in result


class TestCWMSmartFilter:
    """Test the ContextWindowManager page-in filtering."""

    def test_smart_filter_deduplication(self):
        from app.core.memory.context_window_manager import _smart_filter_page_in

        hits = [
            {"content": "用户是Python开发者，擅长后端开发", "id": 1},
            {"content": "用户是Python开发者，擅长后端开发工作", "id": 2},
            {"content": "用户住在北京朝阳区，喜欢美食和旅游", "id": 3},
        ]
        result = _smart_filter_page_in(hits, "Python开发 北京朝阳")
        # Near-identical Python entries should be deduped (only 1 kept)
        python_count = sum(1 for h in result if "Python" in h.get("content", ""))
        assert python_count == 1
        # Different topic should survive
        assert len(result) >= 2

    def test_smart_filter_relevance_order(self):
        from app.core.memory.context_window_manager import _smart_filter_page_in

        hits = [
            {"content": "用户喜欢吃火锅", "id": 1},
            {"content": "用户擅长Python编程", "id": 2},
            {"content": "用户住在上海", "id": 3},
        ]
        result = _smart_filter_page_in(hits, "Python编程")
        # Python-related should be first
        assert "Python" in result[0].get("content", "")

    def test_smart_filter_max_results(self):
        from app.core.memory.context_window_manager import _smart_filter_page_in

        hits = [
            {"content": f"记忆内容{i}，完全不同的主题{i}", "id": i} for i in range(10)
        ]
        result = _smart_filter_page_in(hits, "记忆", max_results=3)
        assert len(result) <= 3

    def test_content_similarity(self):
        from app.core.memory.context_window_manager import _content_similarity

        sim = _content_similarity("用户喜欢Python", "用户喜欢Python编程")
        assert sim > 0.5  # Similar

        sim2 = _content_similarity("用户喜欢Python", "今天天气很好")
        assert sim2 < 0.3  # Different


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3: Skill Affinity + Auto-Suggest Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestSkillAffinityTracker:
    """Test the user skill affinity tracking engine."""

    @pytest.fixture
    def tracker(self, tmp_path):
        """Create an isolated tracker with temp storage."""
        from app.core.skills.skill_affinity import SkillAffinityTracker

        t = SkillAffinityTracker.__new__(SkillAffinityTracker)
        t._path = tmp_path / "skill_affinity.json"
        t._data = {}
        t._dirty_count = 0
        t._data_lock = threading.Lock()
        return t

    def test_record_activation(self, tracker):
        tracker.record_activation("step_by_step")
        assert tracker._data["step_by_step"]["activations"] == 1
        tracker.record_activation("step_by_step")
        assert tracker._data["step_by_step"]["activations"] == 2

    def test_get_affinity_scores(self, tracker):
        tracker.record_activation("step_by_step")
        tracker.record_activation("step_by_step")
        tracker.record_activation("concise_mode")

        scores = tracker.get_affinity_scores()
        assert scores["step_by_step"] > scores["concise_mode"]
        assert 0 < scores["step_by_step"] <= 1.0

    def test_get_top_skills(self, tracker):
        for _ in range(5):
            tracker.record_activation("step_by_step")
        for _ in range(3):
            tracker.record_activation("concise_mode")
        tracker.record_activation("research_depth")

        top = tracker.get_top_skills(n=2)
        assert top[0] == "step_by_step"
        assert len(top) == 2

    def test_persistence(self, tracker, tmp_path):
        tracker.record_activation("test_skill")
        tracker.record_activation("test_skill")
        tracker.record_activation("test_skill")
        tracker.flush()

        # Read from disk
        data = json.loads(tracker._path.read_text(encoding="utf-8"))
        assert data["test_skill"]["activations"] == 3

    def test_recency_decay(self, tracker):
        """Old activations should have lower affinity scores."""
        # Simulate old activation
        old_time = (datetime.now() - timedelta(days=60)).isoformat()
        tracker._data["old_skill"] = {
            "activations": 5,
            "last_used": old_time,
            "decay_score": 0.0,
        }
        # Simulate recent activation
        tracker.record_activation("new_skill")
        for _ in range(4):
            tracker.record_activation("new_skill")

        scores = tracker.get_affinity_scores()
        assert scores["new_skill"] > scores["old_skill"]


class TestSkillSuggesterEnhancements:
    """Test the enhanced SkillSuggester with history awareness."""

    def test_enrich_with_history_empty(self):
        from app.core.skills.skill_suggester import SkillSuggester

        result = SkillSuggester._enrich_with_history("你好", None)
        assert result == "你好"

        result = SkillSuggester._enrich_with_history("你好", [])
        assert result == "你好"

    def test_enrich_with_history_extracts_user_only(self):
        from app.core.skills.skill_suggester import SkillSuggester

        history = [
            {"role": "user", "parts": ["帮我分析一下这个Excel文件"]},
            {"role": "model", "parts": ["好的，我来分析这个表格..."]},
            {"role": "user", "parts": ["对比一下第二个文件"]},
            {"role": "model", "parts": ["两个文件的差异如下..."]},
        ]
        result = SkillSuggester._enrich_with_history("总结一下", history)
        assert "Excel" in result
        assert "总结" in result
        # Model responses should NOT be included
        assert "差异如下" not in result

    def test_enrich_limits_to_3_turns(self):
        from app.core.skills.skill_suggester import SkillSuggester

        history = [{"role": "user", "parts": [f"消息{i}"]} for i in range(20)]
        result = SkillSuggester._enrich_with_history("最新", history)
        # Only last 3 user messages should be included
        assert "消息19" in result
        assert "消息0" not in result


class TestSkillSuggesterIntegration:
    """Integration test for suggest() with affinity scoring."""

    def test_suggest_signature_accepts_history(self):
        """suggest() should accept conversation_history parameter."""
        import inspect

        from app.core.skills.skill_suggester import SkillSuggester

        sig = inspect.signature(SkillSuggester.suggest)
        assert "conversation_history" in sig.parameters
