# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Koto LLM Provider Factory
==========================
Single entry point to get the appropriate LLMProvider based on:
  1. Explicit `provider` argument ("gemini" | "openai" | "anthropic" | "ollama")
  2. `model` prefix  (gpt-* → openai, claude-* → anthropic, gemini-* / default → gemini)
  3. Available API keys in environment

Usage:
    from app.core.llm.provider_factory import get_llm_provider

    provider = get_llm_provider()                        # auto-detect
    provider = get_llm_provider(provider="openai")       # force OpenAI
    provider = get_llm_provider(model="claude-3-7-sonnet-20250219")  # infer from model
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from .base import LLMProvider
from .gemini_config import get_gemini_api_key, has_gemini_api_key

logger = logging.getLogger(__name__)


class CloudProviderUnavailableError(RuntimeError):
    """Raised when a cloud provider is required but not configured."""


# ── Provider registry ─────────────────────────────────────────────────────────


def _load_gemini(api_key: str = None) -> LLMProvider:
    from .gemini import GeminiProvider

    return GeminiProvider(api_key=api_key)


def _load_openai() -> LLMProvider:
    from .openai_provider import OpenAIProvider

    return OpenAIProvider()


def _load_anthropic() -> LLMProvider:
    from .anthropic_provider import AnthropicProvider

    return AnthropicProvider()


def _load_ollama() -> LLMProvider:
    try:
        from .ollama_llm_provider import OllamaLLMProvider

        return OllamaLLMProvider()
    except ImportError:
        from .ollama_provider import OllamaClientProxy  # type: ignore

        return OllamaClientProxy()  # type: ignore


_LOADERS = {
    "gemini": _load_gemini,
    "openai": _load_openai,
    "anthropic": _load_anthropic,
    "ollama": _load_ollama,
}

# Model-name prefix → provider name
_MODEL_PREFIX_MAP = (
    ("gpt-", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("claude-", "anthropic"),
    ("gemini-", "gemini"),
    ("deep-research", "gemini"),
    ("llama", "ollama"),
    ("qwen", "ollama"),
    ("mistral", "ollama"),
    ("phi", "ollama"),
)


def get_llm_provider(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    allow_local_fallback: bool = False,
) -> LLMProvider:
    """
    Return an initialised LLMProvider.

    Selection logic (highest to lowest priority):
    1. `provider` argument (explicit override)
    2. `model` string prefix
    3. Per-request API key in flask.g (set by auth middleware)
    4. Available cloud API keys: GEMINI_API_KEY → OPENAI_API_KEY → ANTHROPIC_API_KEY
    5. Local fallback only when explicitly allowed
    """
    # Collect per-request key from Flask g (if inside a request context)
    request_api_key: Optional[str] = None
    try:
        from flask import g as flask_g

        request_api_key = getattr(flask_g, "api_key", None) or None
    except RuntimeError:
        pass  # Not inside a Flask request context

    # 1. Explicit provider name
    if provider:
        name = provider.lower().strip()
        if name in _LOADERS:
            if name == "gemini" and request_api_key:
                return _load_gemini(api_key=request_api_key)
            if name == "gemini" and has_gemini_api_key():
                return _load_gemini()
            if name == "gemini":
                if allow_local_fallback:
                    logger.warning(
                        "[ProviderFactory] Gemini unavailable, using explicit local fallback"
                    )
                    return _load_ollama()
                raise CloudProviderUnavailableError(
                    "Gemini cloud provider is not configured"
                )
            return _LOADERS[name]()
        logger.warning(
            f"[ProviderFactory] Unknown provider '{provider}', falling back to auto-detect"
        )

    # 2. Infer from model name prefix
    if model:
        m = model.lower()
        for prefix, pname in _MODEL_PREFIX_MAP:
            if m.startswith(prefix):
                if pname == "gemini" and request_api_key:
                    return _load_gemini(api_key=request_api_key)
                if pname == "gemini" and has_gemini_api_key():
                    return _load_gemini()
                if pname == "gemini":
                    if allow_local_fallback:
                        logger.warning(
                            "[ProviderFactory] Gemini model requested without cloud config; using local fallback"
                        )
                        return _load_ollama()
                    raise CloudProviderUnavailableError(
                        f"Gemini cloud provider is not configured for model '{model}'"
                    )
                return _LOADERS[pname]()

    # 3. Per-request key takes priority over global env var
    if request_api_key:
        return _load_gemini(api_key=request_api_key)

    # 4. Auto-detect from available cloud keys
    if has_gemini_api_key():
        return _load_gemini()
    if os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY"):
        return _load_openai()
    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY"):
        return _load_anthropic()

    # 5. Local fallback is opt-in; keep cloud/local systems separated by default.
    if allow_local_fallback:
        logger.warning("[ProviderFactory] No cloud API keys found, trying local Ollama")
        return _load_ollama()

    raise CloudProviderUnavailableError("No cloud LLM provider configured")


def list_available_providers() -> list[str]:
    """Return names of providers whose API keys are present in the environment."""
    available = []
    if get_gemini_api_key():
        available.append("gemini")
    if os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY"):
        available.append("openai")
    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY"):
        available.append("anthropic")
    # Ollama is always potentially available (check runtime)
    try:
        import socket

        s = socket.socket()
        s.settimeout(0.3)
        if s.connect_ex(("127.0.0.1", 11434)) == 0:
            available.append("ollama")
        s.close()
    except Exception:
        import logging

        logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)
    return available
