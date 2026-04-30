# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
MLRouter — wraps TaskClassifier and LocalModelRouter into a single,
importable routing helper.

SmartDispatcher.analyze() contains the primary call-sites; these methods are
provided as reusable, testable extraction points.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


def _get_task_classifier():
    from app.core.routing.task_classifier import TaskClassifier

    return TaskClassifier


def _get_local_model_router():
    from app.core.routing.local_model_router import LocalModelRouter

    return LocalModelRouter


class MLRouter:
    """ML-based routing helpers (TaskClassifier + LocalModelRouter/Ollama)."""

    CONF_THRESHOLD = 0.72

    # ─────────────────────────────────────────────────────────────────────────
    # TaskClassifier integration
    # ─────────────────────────────────────────────────────────────────────────
    @classmethod
    def classify_with_task_classifier(
        cls, user_input: str, client=None
    ) -> "tuple[str, float] | None":
        """
        Attempt classification via the embedded TaskClassifier.

        Returns (task_type, confidence) if confidence >= CONF_THRESHOLD,
        otherwise returns None.

        The *client* argument is accepted for API-compatibility but is not
        forwarded to TaskClassifier.classify() (which is a local model call).
        """
        try:
            TC = _get_task_classifier()
            if not TC.is_available():
                return None
            task_type, confidence = TC.classify(user_input)
            if confidence >= cls.CONF_THRESHOLD:
                logger.debug(
                    "[MLRouter] TaskClassifier: '%s' → %s (%.2f)",
                    user_input[:40],
                    task_type,
                    confidence,
                )
                return task_type, confidence
            return None
        except Exception as exc:
            logger.warning("[MLRouter] TaskClassifier exception (skipped): %s", exc)
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # LocalModelRouter / Ollama integration
    # ─────────────────────────────────────────────────────────────────────────
    @classmethod
    def classify_with_local_model(
        cls, user_input: str
    ) -> "tuple[str, float] | None":
        """
        Attempt classification via the local Ollama model router.

        Returns (task_type, confidence) if confidence >= CONF_THRESHOLD,
        otherwise returns None.
        """
        try:
            LMR = _get_local_model_router()
            if not LMR.is_ollama_available():
                return None
            task_type, conf_str, _src, _hint, _cplx = LMR.classify_with_hint(
                user_input, timeout=3.5
            )
            confidence = 0.0
            if isinstance(conf_str, str):
                match = re.search(r"(\d+\.\d+)", conf_str)
                if match:
                    confidence = float(match.group(1))
            if task_type and confidence >= cls.CONF_THRESHOLD:
                logger.debug(
                    "[MLRouter] LocalModel: '%s' → %s (%.2f)",
                    user_input[:40],
                    task_type,
                    confidence,
                )
                return task_type, confidence
            return None
        except Exception as exc:
            logger.warning("[MLRouter] LocalModel exception (skipped): %s", exc)
            return None
