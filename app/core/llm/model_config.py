# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Unified Model Configuration
============================
Single source of truth for Koto model selection — chat model, embedding model,
and mode (cloud/local). Used by both the chat pipeline and the RAG system.

Settings keys (in config/user_settings.json):
  model_mode        : "cloud" | "local"
  local_model       : Ollama chat model tag (e.g. "qwen2.5:7b")
  local_embed_model : Ollama embedding model tag (e.g. "nomic-embed-text")

Fallback defaults when nothing is configured:
  chat model  → "qwen2.5:7b"
  embed model → "nomic-embed-text"

Usage:
    from app.core.llm.model_config import get_chat_model, get_embed_model, get_model_mode

    mode = get_model_mode()        # "local" or "cloud"
    chat = get_chat_model()        # "qwen2.5:7b"
    embed = get_embed_model()      # "nomic-embed-text"
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Sensible defaults for local-only deployment ────────────────────────────
_DEFAULT_CHAT_MODEL = "qwen2.5:7b"
_DEFAULT_EMBED_MODEL = "nomic-embed-text"

# ── Embedding model priority list (tried in order when auto-detecting) ────
_EMBED_MODEL_CANDIDATES = [
    "nomic-embed-text",  # 768 dims, multilingual, 274MB — best balance
    "bge-m3",  # 1024 dims, multilingual SOTA, 1.2GB
    "mxbai-embed-large",  # 1024 dims, English SOTA, 670MB
    "all-minilm",  # 384 dims, lightweight, 45MB
]


def _get_settings() -> dict:
    """Read user settings, returning empty dict on failure."""
    try:
        from app.core.config.user_settings import SettingsManager

        return SettingsManager().get_all()
    except Exception:
        return {}


def get_model_mode() -> str:
    """Return 'local' or 'cloud' based on user configuration.

    Also checks model_setup_done.json for local setup wizard state.
    """
    settings = _get_settings()
    stored = str(settings.get("model_mode") or "").strip().lower()
    if stored in {"local", "ollama"}:
        return "local"
    if stored == "cloud":
        return "cloud"

    # Fallback: check model_setup_done.json
    try:
        import json
        from pathlib import Path

        setup_path = (
            Path(__file__).parent.parent.parent.parent
            / "config"
            / "model_setup_done.json"
        )
        if setup_path.exists():
            setup = json.loads(setup_path.read_text(encoding="utf-8"))
            if setup.get("mode") == "local":
                return "local"
    except Exception:
        pass

    return "cloud"


def get_chat_model() -> str:
    """Return the configured chat model tag for local mode.

    Priority:
      1. user_settings.json: local_model
      2. user_settings.json: ai.local_model
      3. model_setup_done.json: model (setup wizard)
      4. Environment: KOTO_LOCAL_MODEL
      5. Default: qwen2.5:7b
    """
    settings = _get_settings()

    # Check all possible settings keys
    candidates = [
        settings.get("local_model"),
        settings.get("local_model_tag"),
        (settings.get("ai") or {}).get("local_model"),
        (settings.get("ai") or {}).get("local_model_tag"),
    ]
    for val in candidates:
        if (
            val
            and str(val).strip()
            and str(val).strip() not in ("deepseek-chat", "auto", "cloud")
        ):
            tag = str(val).strip()
            logger.debug("[ModelConfig] chat model from settings: %s", tag)
            return tag

    # Check model_setup_done.json
    try:
        import json
        from pathlib import Path

        setup_path = (
            Path(__file__).parent.parent.parent.parent
            / "config"
            / "model_setup_done.json"
        )
        if setup_path.exists():
            setup = json.loads(setup_path.read_text(encoding="utf-8"))
            model = str(setup.get("model", "")).strip()
            if model and model not in ("deepseek-chat",):
                logger.debug("[ModelConfig] chat model from setup wizard: %s", model)
                return model
    except Exception:
        pass

    # Environment variable
    import os

    env_model = os.environ.get("KOTO_LOCAL_MODEL", "").strip()
    if env_model:
        logger.debug("[ModelConfig] chat model from env: %s", env_model)
        return env_model

    logger.debug("[ModelConfig] chat model default: %s", _DEFAULT_CHAT_MODEL)
    return _DEFAULT_CHAT_MODEL


def get_embed_model() -> str:
    """Return the configured embedding model tag.

    Priority:
      1. user_settings.json: local_embed_model
      2. user_settings.json: ai.local_embed_model
      3. Environment: KOTO_EMBED_MODEL
      4. Default: nomic-embed-text
    """
    settings = _get_settings()

    candidates = [
        settings.get("local_embed_model"),
        (settings.get("ai") or {}).get("local_embed_model"),
    ]
    for val in candidates:
        if val and str(val).strip():
            tag = str(val).strip()
            logger.debug("[ModelConfig] embed model from settings: %s", tag)
            return tag

    import os

    env_model = os.environ.get("KOTO_EMBED_MODEL", "").strip()
    if env_model:
        logger.debug("[ModelConfig] embed model from env: %s", env_model)
        return env_model

    logger.debug("[ModelConfig] embed model default: %s", _DEFAULT_EMBED_MODEL)
    return _DEFAULT_EMBED_MODEL


def get_embed_model_candidates() -> list[str]:
    """Return the ordered list of embedding models to try.

    The user's configured model is first, followed by sensible fallbacks.
    """
    configured = get_embed_model()
    candidates = [configured]
    for m in _EMBED_MODEL_CANDIDATES:
        if m not in candidates:
            candidates.append(m)
    return candidates


def resolve_ollama_model(requested: Optional[str] = None) -> str:
    """Resolve which Ollama model to use for a given request.

    If a specific model is requested and looks like an Ollama tag, use it.
    Otherwise fall back to the configured chat model.
    """
    if requested:
        tag = requested.strip()
        # Ollama tags look like "name:size" or "name:latest"
        if ":" in tag or tag in ("llama3", "qwen", "mistral", "gemma", "phi"):
            return tag
    return get_chat_model()


def is_local_mode() -> bool:
    """Shorthand for get_model_mode() == 'local'."""
    return get_model_mode() == "local"
