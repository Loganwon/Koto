# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Shared model capability helpers used by routing and providers."""

from __future__ import annotations

import os
from typing import Iterable, Set

DEFAULT_INTERACTIONS_ONLY_MODELS: frozenset[str] = frozenset(
    {
        "deep-research-pro-preview-12-2025",
    }
)

INTERACTIONS_ONLY_PREFIXES: tuple[str, ...] = (
    "deep-research-",
)


def normalize_model_id(model_id: str | None) -> str:
    """Normalize model identifiers from API and call sites."""
    mid = str(model_id or "").strip()
    if mid.startswith("models/"):
        mid = mid[len("models/") :]
    return mid


def _parse_env_model_set(env_var: str) -> Set[str]:
    raw = os.getenv(env_var, "")
    if not raw:
        return set()

    out: Set[str] = set()
    for item in raw.split(","):
        mid = normalize_model_id(item)
        if mid:
            out.add(mid)
    return out


def get_interactions_only_model_set(
    extra_models: Iterable[str] | None = None,
) -> Set[str]:
    """Build interactions-only model set from defaults + env + dynamic extras."""
    models: Set[str] = set(DEFAULT_INTERACTIONS_ONLY_MODELS)
    models.update(_parse_env_model_set("KOTO_INTERACTIONS_ONLY_MODELS"))

    if extra_models:
        for mid in extra_models:
            norm = normalize_model_id(mid)
            if norm:
                models.add(norm)
    return models


def is_interactions_only_model(
    model_id: str | None,
    extra_models: Iterable[str] | None = None,
) -> bool:
    """True if model must use Interactions API instead of generate_content."""
    normalized = normalize_model_id(model_id)
    if not normalized:
        return False

    normalized_lower = normalized.lower()
    model_set = {m.lower() for m in get_interactions_only_model_set(extra_models)}
    if normalized_lower in model_set:
        return True

    return any(
        normalized_lower.startswith(prefix) for prefix in INTERACTIONS_ONLY_PREFIXES
    )


def get_model_blocklist_from_env() -> Set[str]:
    """Optional dynamic blocklist for emergency model suppression."""
    return _parse_env_model_set("KOTO_MODEL_BLOCKLIST")
