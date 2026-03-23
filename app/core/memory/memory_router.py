# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
MemoryRouter — Unified memory read dispatcher for Koto.

Single entry point that retrieves and merges all relevant memory layers
before each response, replacing scattered per-component calls with a
single coordinated read:

  Layer 1 — UserProfile  : communication preferences, technical background
  Layer 2 — Long-term mem: user facts, decisions, reminders (vector search)
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
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# How many long-term memories to retrieve per request
_MEMORY_K: int = 5

# ── Task-type → Cube priority mapping ──────────────────────────────────────────────────
# Category names that get a priority boost inside search_memories() for
# each task type.  Mirrors MemOS Cube-aware multi-granularity dispatch.
_TASK_CUBE_MAP: dict[str, list[str]] = {
    "CHAT": ["user_fact", "preference", "user_preference"],
    "RESEARCH": ["topic_summary", "user_fact", "preference"],
    "WEB_SEARCH": ["topic_summary", "user_fact"],
    "CODER": ["user_fact", "user_preference", "correction", "preference"],
    "FILE_GEN": ["user_fact", "user_preference", "preference"],
    "AGENT": ["decision", "reminder", "user_fact"],
    "MULTI_STEP": ["decision", "reminder", "user_fact"],
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

        Args:
            query:           The user's current message (used for semantic search).
            session_name:    Current session identifier (unused in read, reserved for future).
            get_memory_fn:   Callable that returns the current EnhancedMemoryManager instance.
            include_profile: Whether to inject UserProfile context (True by default).
            extra_context:   Pre-built context from ContextWindowManager paged-in content.
            task_type:       Current routing task type (CHAT/CODER/RESEARCH/AGENT/etc.).
                             Used to prioritise memory categories via _TASK_CUBE_MAP.

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
                        ctx = profile.to_context_string().strip()
                        if ctx:
                            parts.append(ctx)
                except Exception as e:
                    logger.debug(f"[MemoryRouter] Profile layer error: {e}")

            # ── Layer 2: Long-term memory — vector + keyword merged ───────────
            try:
                _boost = _TASK_CUBE_MAP.get(task_type, [])
                hits: list = []
                seen_ids: set = set()

                # 2a. Vector search (FAISS hybrid via search_vector_memories)
                vec_fn = getattr(mgr, "search_vector_memories", None)
                if vec_fn and query:
                    try:
                        for h in vec_fn(query, limit=_MEMORY_K) or []:
                            mid = h.get("id")
                            if mid not in seen_ids:
                                seen_ids.add(mid)
                                hits.append(h)
                    except Exception as _ve:
                        logger.debug(f"[MemoryRouter] Vector search error: {_ve}")

                # 2b. Keyword/scoring search — fills up to _MEMORY_K slots
                kw_fn = getattr(mgr, "search_memories", None)
                if kw_fn and query and len(hits) < _MEMORY_K:
                    try:
                        for h in (
                            kw_fn(
                                query,
                                limit=_MEMORY_K,
                                boost_categories=_boost or None,
                            )
                            or []
                        ):
                            mid = h.get("id")
                            if mid not in seen_ids:
                                seen_ids.add(mid)
                                hits.append(h)
                                if len(hits) >= _MEMORY_K:
                                    break
                    except Exception as _ke:
                        logger.debug(f"[MemoryRouter] Keyword search error: {_ke}")

                if hits:
                    lines = []
                    for h in hits[:_MEMORY_K]:
                        cat = h.get("category", "?")
                        content = (h.get("content") or "").strip()
                        if content:
                            content_short = (
                                content[:150] + "…" if len(content) > 150 else content
                            )
                            lines.append(f"  [{cat}] {content_short}")
                    if lines:
                        parts.append("[长期记忆 — 与本次对话相关]\n" + "\n".join(lines))
            except Exception as e:
                logger.debug(f"[MemoryRouter] Memory search layer error: {e}")

        except Exception as e:
            logger.debug(f"[MemoryRouter] read() error: {e}")

        return _format_block(parts)


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
