# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
MemoryRouter — Unified memory read dispatcher for Koto.

Single entry point that retrieves and merges all relevant memory layers
before each response, replacing scattered per-component calls with a
single coordinated read:

  Layer 1 — UserProfile  : communication preferences, technical background
  Layer 2 — Long-term mem: user facts, decisions, reminders (vector search)
             - v1.7: Smart filtering with relevance scoring, recency decay,
               and deduplication to cut ~50% token waste
  Layer 3 — Session context is handled upstream by ContextWindowManager
             and passed in via the `extra_context` parameter.

Usage (web/app.py — after ContextWindowManager.manage()):

    from app.core.memory.memory_router import MemoryRouter
    mem_block = MemoryRouter.read(
        query=user_input,
        session_name=session_name,
        get_memory_fn=get_memory_manager,
    )
    if mem_block:
        system_instruction += mem_block
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# How many raw candidates to retrieve before scoring
_MEMORY_CANDIDATE_K: int = 8
# How many scored memories to actually inject
_MEMORY_INJECT_K: int = 4
# Minimum relevance score to include a memory (0-1 scale)
_MIN_RELEVANCE_SCORE: float = 0.15
# Recency decay half-life in days (memories older than this get halved score)
_DECAY_HALF_LIFE_DAYS: float = 30.0
# Category importance weight boost
_CATEGORY_BOOST: float = 0.25
# Jaccard n-gram similarity threshold for deduplication
_DEDUP_THRESHOLD: float = 0.6

# ── Task-type → Cube priority mapping ──────────────────────────────────────────────────
_TASK_CUBE_MAP: dict[str, list[str]] = {
    "CHAT": ["user_fact", "preference", "user_preference"],
    "RESEARCH": ["topic_summary", "user_fact", "preference"],
    "WEB_SEARCH": ["topic_summary", "user_fact"],
    "CODER": ["user_fact", "user_preference", "correction", "preference"],
    "FILE_GEN": ["user_fact", "user_preference", "preference"],
    "AGENT": ["decision", "reminder", "user_fact"],
    "MULTI_STEP": ["decision", "reminder", "user_fact"],
}

# ── Category base importance (higher = always more relevant) ──────────────
_CATEGORY_BASE_IMPORTANCE: dict[str, float] = {
    "user_fact": 0.9,
    "user_preference": 0.85,
    "preference": 0.8,
    "correction": 0.75,
    "decision": 0.7,
    "reminder": 0.65,
    "topic_summary": 0.5,
    "session_summary": 0.3,
}


class MemoryRouter:
    """Stateless dispatcher — all persistent state lives in the injected manager."""

    @classmethod
    def read(
        cls,
        query: str,
        session_name: str,
        get_memory_fn: Callable[[], Any],
        include_profile: bool = True,
        extra_context: Optional[str] = None,
        task_type: str = "CHAT",
    ) -> str:
        """
        Retrieve and format memory context for the current query.

        Uses a three-stage pipeline:
          1. Retrieve: Gather candidates from vector + keyword search
          2. Score: Compute composite relevance (semantic + recency + category)
          3. Filter: Deduplicate, threshold, and take Top-K

        Returns:
            A formatted string block ready to append to system_instruction,
            or an empty string if nothing useful was found.
        """
        parts: list[str] = []

        # ── Layer 0: session context passed in from ContextWindowManager ──────
        if extra_context and extra_context.strip():
            parts.append(extra_context.strip())

        try:
            mgr = get_memory_fn()
            if mgr is None:
                return _format_block(parts)

            # ── Layer 1: UserProfile ──────────────────────────────────────────
            if include_profile:
                try:
                    profile = getattr(mgr, "user_profile", None)
                    if profile and hasattr(profile, "to_context_string"):
                        pctx = profile.to_context_string().strip()
                        if pctx:
                            parts.append(pctx)
                except Exception as e:
                    logger.debug(f"[MemoryRouter] Profile layer error: {e}")

            # ── Layer 2: Long-term memory — Smart Filtered ────────────────────
            try:
                boost_cats = _TASK_CUBE_MAP.get(task_type, [])
                candidates = _retrieve_candidates(mgr, query, boost_cats)

                if candidates:
                    scored = _score_and_rank(candidates, query, task_type, boost_cats)
                    deduped = _deduplicate(scored)
                    final = [
                        (score, h)
                        for score, h in deduped
                        if score >= _MIN_RELEVANCE_SCORE
                    ][:_MEMORY_INJECT_K]

                    if final:
                        lines = []
                        for score, h in final:
                            cat = h.get("category", "?")
                            content = (h.get("content") or "").strip()
                            if content:
                                content_short = (
                                    content[:150] + "…"
                                    if len(content) > 150
                                    else content
                                )
                                lines.append(f"  [{cat}] {content_short}")
                        if lines:
                            parts.append(
                                "[长期记忆 — 与本次对话相关]\n" + "\n".join(lines)
                            )
                            logger.debug(
                                f"[MemoryRouter] 注入 {len(lines)} 条记忆 "
                                f"(从 {len(candidates)} 候选中筛选, "
                                f"得分范围 {final[-1][0]:.2f}-{final[0][0]:.2f})"
                            )

            except Exception as e:
                logger.debug(f"[MemoryRouter] Memory search layer error: {e}")

        except Exception as e:
            logger.debug(f"[MemoryRouter] read() error: {e}")

        return _format_block(parts)


# ══════════════════════════════════════════════════════════════════════════════
# Stage 1: Retrieve raw candidates
# ══════════════════════════════════════════════════════════════════════════════


def _retrieve_candidates(
    mgr: Any, query: str, boost_cats: list
) -> List[Dict]:
    """Gather raw candidates from vector + keyword search, deduplicated by id."""
    hits: list = []
    seen_ids: set = set()

    # 1a. Vector search (FAISS hybrid)
    vec_fn = getattr(mgr, "search_vector_memories", None)
    if vec_fn and query:
        try:
            for h in vec_fn(query, limit=_MEMORY_CANDIDATE_K) or []:
                mid = h.get("id")
                if mid not in seen_ids:
                    seen_ids.add(mid)
                    h["_source"] = "vector"
                    hits.append(h)
        except Exception as _ve:
            logger.debug(f"[MemoryRouter] Vector search error: {_ve}")

    # 1b. Keyword search — fills remaining slots
    kw_fn = getattr(mgr, "search_memories", None)
    if kw_fn and query and len(hits) < _MEMORY_CANDIDATE_K:
        try:
            for h in (
                kw_fn(
                    query,
                    limit=_MEMORY_CANDIDATE_K,
                    boost_categories=boost_cats or None,
                )
                or []
            ):
                mid = h.get("id")
                if mid not in seen_ids:
                    seen_ids.add(mid)
                    h["_source"] = "keyword"
                    hits.append(h)
                    if len(hits) >= _MEMORY_CANDIDATE_K:
                        break
        except Exception as _ke:
            logger.debug(f"[MemoryRouter] Keyword search error: {_ke}")

    return hits


# ══════════════════════════════════════════════════════════════════════════════
# Stage 2: Score & Rank
# ══════════════════════════════════════════════════════════════════════════════


def _score_and_rank(
    hits: List[Dict],
    query: str,
    task_type: str,
    boost_cats: List[str],
) -> List[Tuple[float, Dict]]:
    """
    Compute a composite relevance score for each memory hit.

    Score = semantic_signal * recency_decay * category_boost

    Components:
    - semantic_signal: 1.0 for vector hits (pre-filtered by FAISS),
                       0.5 baseline for keyword hits + keyword overlap bonus
    - recency_decay:   exp(-λ * age_days), half-life = _DECAY_HALF_LIFE_DAYS
    - category_boost:  bonus for task-relevant categories
    """
    query_tokens = set(_bigrams(query.lower()))
    now = datetime.now()
    decay_lambda = math.log(2) / max(_DECAY_HALF_LIFE_DAYS, 1.0)
    scored: List[Tuple[float, Dict]] = []

    for h in hits:
        # ── Semantic signal ──
        if h.get("_source") == "vector":
            semantic = 0.8  # Vector search already pre-filters semantically
        else:
            # Keyword hit: compute content overlap
            content = (h.get("content") or "").lower()
            content_tokens = set(_bigrams(content))
            if query_tokens and content_tokens:
                overlap = len(query_tokens & content_tokens) / max(
                    len(query_tokens), 1
                )
                semantic = 0.4 + min(overlap * 0.6, 0.5)
            else:
                semantic = 0.4

        # ── Recency decay ──
        recency = _compute_recency(h, now, decay_lambda)

        # ── Category boost ──
        cat = h.get("category", "")
        cat_score = _CATEGORY_BASE_IMPORTANCE.get(cat, 0.4)
        if cat in boost_cats:
            cat_score = min(cat_score + _CATEGORY_BOOST, 1.0)

        # ── Composite score ──
        score = semantic * recency * cat_score
        scored.append((score, h))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def _compute_recency(hit: Dict, now: datetime, decay_lambda: float) -> float:
    """Compute time-decay factor from memory's created_at timestamp."""
    created = hit.get("created_at") or hit.get("timestamp") or ""
    if not created:
        return 0.7  # Unknown age → moderate penalty

    try:
        if isinstance(created, (int, float)):

            dt = datetime.fromtimestamp(created)
        else:
            # Try common datetime formats
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(str(created)[:19], fmt)
                    break
                except ValueError:
                    continue
            else:
                return 0.7

        age_days = max((now - dt).total_seconds() / 86400.0, 0.0)
        return math.exp(-decay_lambda * age_days)
    except Exception:
        return 0.7


# ══════════════════════════════════════════════════════════════════════════════
# Stage 3: Deduplicate
# ══════════════════════════════════════════════════════════════════════════════


def _deduplicate(
    scored: List[Tuple[float, Dict]],
) -> List[Tuple[float, Dict]]:
    """Remove near-duplicate memories (by content Jaccard similarity)."""
    result: List[Tuple[float, Dict]] = []
    seen_bigrams: List[set] = []

    for score, h in scored:
        content = (h.get("content") or "").strip().lower()
        if not content:
            continue
        bg = set(_bigrams(content))

        # Check against already-selected memories
        is_dup = False
        for existing_bg in seen_bigrams:
            if existing_bg and bg:
                jaccard = len(bg & existing_bg) / max(len(bg | existing_bg), 1)
                if jaccard >= _DEDUP_THRESHOLD:
                    is_dup = True
                    break

        if not is_dup:
            result.append((score, h))
            seen_bigrams.append(bg)

    return result


def _bigrams(text: str) -> List[str]:
    """Extract character bigrams for Jaccard similarity."""
    if len(text) < 2:
        return [text]
    return [text[i : i + 2] for i in range(len(text) - 1)]


def _format_block(parts: list[str]) -> str:
    """Wrap non-empty parts in a labelled context block."""
    body = "\n\n".join(p for p in parts if p)
    if not body:
        return ""
    return (
        "\n\n─────────────────────────────────────────"
        "\n## 🧠 个人记忆上下文\n\n"
        + body
        + "\n─────────────────────────────────────────"
    )
