# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
FallbackRouter — last-resort routing logic for compound tasks and RAG context.

These helpers encapsulate the compound-task detection (TaskDecomposer) and
RAG history-continuation analysis (ContextAnalyzer) that SmartDispatcher uses
as a safety net after all fast-track channels have been exhausted.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _get_task_decomposer():
    from app.core.routing.task_decomposer import TaskDecomposer

    return TaskDecomposer


class FallbackRouter:
    """Fallback routing helpers: compound-task detection and RAG context."""

    # ─────────────────────────────────────────────────────────────────────────
    # Compound task detection
    # ─────────────────────────────────────────────────────────────────────────
    @classmethod
    def check_compound_task(cls, user_input: str, LocalExecutor=None) -> "str | None":
        """
        Check whether *user_input* describes a compound multi-step task.

        Uses TaskDecomposer.detect_compound_task() to identify tasks that
        should be decomposed into sub-tasks.

        Returns "MULTI_STEP" if a compound task is detected, otherwise None.

        The *LocalExecutor* argument is accepted for API-compatibility but is
        not used in the current compound-task detection logic.
        """
        try:
            TaskDecomposer = _get_task_decomposer()
            # We need a quick hint for TaskDecomposer — replicate the same
            # keyword heuristic used in SmartDispatcher to avoid circular imports.
            from app.core.routing.rule_router import RuleRouter

            initial_hint = RuleRouter.quick_task_hint(user_input)
            compound_info = TaskDecomposer.detect_compound_task(
                user_input, initial_hint
            )
            if compound_info.get("is_compound"):
                logger.debug(
                    "[FallbackRouter] Compound task detected: '%s'", user_input[:40]
                )
                return "MULTI_STEP"
            return None
        except Exception as exc:
            logger.warning(
                "[FallbackRouter] check_compound_task exception (skipped): %s", exc
            )
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # RAG context continuation
    # ─────────────────────────────────────────────────────────────────────────
    @classmethod
    def check_rag_context(
        cls,
        user_input: str,
        history: list,
        ContextAnalyzer,
    ) -> "str | None":
        """
        Check conversation history for a strong context-continuation signal.

        Returns the related task type (e.g. "WEB_SEARCH", "CODER") if a
        high-confidence continuation is detected, otherwise None.

        Args:
            user_input:      Current user message.
            history:         Conversation history list (must have ≥ 2 entries).
            ContextAnalyzer: An object with an ``analyze_context(user_input,
                             history)`` method, typically injected via
                             SmartDispatcher.configure().
        """
        if not history or len(history) < 2 or not ContextAnalyzer:
            return None
        try:
            context_info = ContextAnalyzer.analyze_context(user_input, history)
            if (
                context_info.get("is_continuation")
                and context_info.get("confidence", 0) > 0.7
            ):
                related_task = context_info.get("related_task")
                if related_task:
                    logger.debug(
                        "[FallbackRouter] RAG continuation → %s for '%s'",
                        related_task,
                        user_input[:40],
                    )
                    return related_task
            return None
        except Exception as exc:
            logger.warning(
                "[FallbackRouter] check_rag_context exception (skipped): %s", exc
            )
            return None
