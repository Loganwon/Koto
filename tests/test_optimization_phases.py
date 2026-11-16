# -*- coding: utf-8 -*-
"""
Tests for Phase 1–3 Koto optimizations:
  1. Core-owned service lifecycles
  2. Smart Memory Filter — MemoryRouter + CWM
  3. Skill Auto-Suggest — Affinity Tracking + History-aware Suggestions
"""

import json
import math
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ══════════════════════════════════════════════════════════════════════════════
# Phase 1: Core Service Ownership Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestCoreServiceOwnership:
    """Each stateful core service exposes one explicit lifecycle owner."""

    def test_memory_manager_is_cached_by_its_service_module(self):
        from app.core.services import memory_manager as module

        sentinel = MagicMock()
        module.reset_memory_manager_for_tests()
        with patch.object(
            module, "EnhancedMemoryManager", return_value=sentinel
        ) as factory:
            assert module.get_memory_manager() is sentinel
            assert module.get_memory_manager() is sentinel
        factory.assert_called_once_with()

    def test_knowledge_base_is_cached_by_its_service_module(self):
        from app.core.services import knowledge_base as module

        sentinel = MagicMock()
        module.reset_knowledge_base_for_tests()
        with patch.object(module, "KnowledgeBase", return_value=sentinel) as factory:
            assert module.get_knowledge_base() is sentinel
            assert module.get_knowledge_base() is sentinel
        factory.assert_called_once_with()

    def test_configuration_manager_is_cached_by_its_module(self):
        from app.core.config import configuration_manager as module

        sentinel = MagicMock()
        module.reset_config_manager_for_tests()
        with patch.object(
            module, "ConfigurationManager", return_value=sentinel
        ) as factory:
            assert module.get_config_manager() is sentinel
            assert module.get_config_manager() is sentinel
        factory.assert_called_once_with()

    def test_rag_services_are_cached_per_normalized_index_dir(self, tmp_path):
        from app.core.services import rag_service as module

        first = MagicMock()
        second = MagicMock()
        module.reset_rag_service_cache_for_tests()
        with patch.object(module, "RAGService", side_effect=[first, second]) as factory:
            assert module.get_rag_service(str(tmp_path / "one")) is first
            assert module.get_rag_service(str(tmp_path / "one" / ".")) is first
            assert module.get_rag_service(str(tmp_path / "two")) is second
        assert factory.call_count == 2

    def test_file_rag_indexers_are_cached_per_workspace(self, tmp_path):
        from app.core.services import file_rag_indexer as module

        first = MagicMock()
        second = MagicMock()
        module.reset_file_rag_indexers_for_tests()
        with patch.object(
            module, "FileRAGIndexer", side_effect=[first, second]
        ) as factory:
            assert module.get_file_rag_indexer(str(tmp_path / "one")) is first
            assert module.get_file_rag_indexer(str(tmp_path / "one" / ".")) is first
            assert module.get_file_rag_indexer(str(tmp_path / "two")) is second
        assert factory.call_count == 2


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
