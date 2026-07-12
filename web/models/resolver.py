# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Model resolution functions extracted from web/app.py.

Resolves model IDs, handles fallback logic, task-lock validation, and alias
lookups.  All mutable state lives in module-level variables initialised by
``init_resolver()`` from the main application module.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.services.model_manager import ModelManager

_logger = logging.getLogger("koto.models.resolver")

# ---------------------------------------------------------------------------
# Module-level state (set by init_resolver)
# ---------------------------------------------------------------------------

_model_manager: "ModelManager | None" = None
_model_map: dict[str, str] = {}
_model_aliases: dict[str, str] = {}
_model_task_requirements: dict[str, object] = {}
_score_model_for_task = None  # callable(caps: dict, task: str) -> float

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MODEL_LOCK_TASK_ALIASES: dict[str, str] = {
    "DOC_ANNOTATE": "FILE_TASK",
    "FILE_SEARCH": "AGENT",
    "MEETING_EXTRACT": "FILE_TASK",
    "MULTI_STEP": "AGENT",
    "COMPLEX": "AGENT",
}

# ---------------------------------------------------------------------------
# Public initialisation
# ---------------------------------------------------------------------------


def init_resolver(
    *,
    model_manager: "ModelManager | None" = None,
    model_map: dict[str, str] | None = None,
    model_aliases: dict[str, str] | None = None,
    model_task_requirements: dict[str, object] | None = None,
    score_model_for_task=None,
) -> None:
    """Seed the resolver with runtime state from the main application."""
    global _model_manager, _model_map, _model_aliases
    global _model_task_requirements, _score_model_for_task
    if model_manager is not None:
        _model_manager = model_manager
    if model_map is not None:
        _model_map = model_map
    if model_aliases is not None:
        _model_aliases = model_aliases
    if model_task_requirements is not None:
        _model_task_requirements = model_task_requirements
    if score_model_for_task is not None:
        _score_model_for_task = score_model_for_task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize(value: str) -> str:
    """Lightweight normalisation used inside this module.

    Delegates to ``app.core.llm.model_capabilities.normalize_model_id`` when
    available; otherwise falls back to a simple lower+strip.
    """
    try:
        from app.core.llm.model_capabilities import (
            normalize_model_id,
        )

        return normalize_model_id(value)
    except ImportError:
        return str(value or "").strip().lower()


# ---------------------------------------------------------------------------
# Resolution functions
# ---------------------------------------------------------------------------


def resolve_model_alias(model_id: str) -> str:
    normalized = _normalize(str(model_id or "").strip())
    if not normalized:
        return ""
    resolved = _model_aliases.get(normalized, normalized)
    from app.core.llm.provider_boundary import normalize_public_model

    return normalize_public_model(resolved)


def resolve_model_lock_task(task_type: str) -> str:
    normalized = str(task_type or "").strip().upper()
    if not normalized:
        return ""
    if normalized in _model_task_requirements:
        return normalized
    return _MODEL_LOCK_TASK_ALIASES.get(normalized, "")


def model_supports_locked_task(model_id: str, task_type: str) -> bool:
    if _model_manager is None:
        return True

    resolved_task = resolve_model_lock_task(task_type)
    if not resolved_task:
        return True

    caps = _model_manager._cached_caps.get(model_id)
    if not caps:
        return True

    if caps.get("image_gen", False) and resolved_task != "PAINTER":
        return False

    if _score_model_for_task is None:
        return True
    return _score_model_for_task(caps, resolved_task) >= 0


def pick_available_fallback_model(
    fallback_model: str,
    task_type: str,
    available_model_ids: list[str],
) -> str:
    fallback = resolve_model_alias(fallback_model)
    ordered_ids = [
        str(item or "").strip()
        for item in (available_model_ids or [])
        if str(item or "").strip()
    ]
    available_ids = set(ordered_ids)

    if not ordered_ids:
        return fallback

    if fallback and fallback in available_ids:
        return fallback

    task_candidates: list[str] = []
    resolved_task = resolve_model_lock_task(task_type)
    if resolved_task:
        task_candidates.append(resolved_task)

    normalized_task = str(task_type or "").strip().upper()
    if normalized_task and normalized_task not in task_candidates:
        task_candidates.append(normalized_task)

    if _model_manager is not None:
        for candidate_task in task_candidates:
            try:
                routed_model = _model_manager.get_model_for_task(candidate_task)
            except Exception:
                routed_model = None
            routed_model = resolve_model_alias(routed_model or "")
            if routed_model and routed_model in available_ids:
                return routed_model

    for candidate_task in task_candidates + ["FILE_TASK", "AGENT", "CHAT"]:
        routed_model = resolve_model_alias(_model_map.get(candidate_task, ""))
        if routed_model and routed_model in available_ids:
            return routed_model

    return ordered_ids[0]


def resolve_requested_model_id(
    requested_model: str,
    fallback_model: str = "",
    task_type: str = "",
) -> str:
    normalized = resolve_model_alias(requested_model)
    resolved_fallback = resolve_model_alias(fallback_model)
    try:
        from app.core.llm.model_selection import get_configured_cloud_model

        cloud_fallback = get_configured_cloud_model(
            task_type=task_type,
            fallback_model=resolved_fallback,
        )
    except Exception:
        cloud_fallback = resolved_fallback

    if _model_manager is None:
        if not normalized or normalized in {"auto", "local", "cloud"}:
            return cloud_fallback
        return normalized

    try:
        available_ids = [
            str(item.get("id", "")).strip()
            for item in _model_manager.get_available_models()
            if item.get("id")
        ]
    except Exception as exc:
        _logger.debug(
            "[ModelLock] 获取可用模型列表失败，跳过显式模型校验: %s", exc
        )
        if not normalized or normalized in {"auto", "local", "cloud"}:
            return cloud_fallback
        return normalized

    if not normalized or normalized in {"auto", "local", "cloud"}:
        if (
            cloud_fallback
            and cloud_fallback not in available_ids
            and cloud_fallback.lower().startswith("deepseek")
        ):
            return cloud_fallback
        return pick_available_fallback_model(
            resolved_fallback, task_type, available_ids
        )

    if available_ids and normalized not in set(available_ids):
        if normalized.lower().startswith("deepseek"):
            return normalized
        resolved_target = pick_available_fallback_model(
            resolved_fallback, task_type, available_ids
        )
        _logger.warning(
            "[ModelLock] 请求的模型 %s 当前不可用，回退到 %s",
            normalized,
            resolved_target or "cloud",
        )
        return resolved_target

    if not model_supports_locked_task(normalized, task_type):
        resolved_target = pick_available_fallback_model(
            resolved_fallback, task_type, available_ids
        )
        _logger.warning(
            "[ModelLock] 请求的模型 %s 不满足任务 %s 的能力约束，回退到 %s",
            normalized,
            task_type or "unknown",
            resolved_target or "cloud",
        )
        return resolved_target

    return normalized
