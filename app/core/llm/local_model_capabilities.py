"""Small, shared capability probe for installed Ollama models.

Ollama exposes the authoritative capabilities for a model through ``/api/show``.
Keeping that probe here means callers do not need to maintain brittle model-name
deny lists (for example, a small Gemma model that cannot call tools).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from functools import lru_cache
from typing import FrozenSet, Optional

logger = logging.getLogger(__name__)

_OLLAMA_BASE_URL = os.environ.get(
    "OLLAMA_BASE_URL", "http://127.0.0.1:11434"
).rstrip("/")


@lru_cache(maxsize=64)
def get_ollama_model_capabilities(model_tag: str) -> Optional[FrozenSet[str]]:
    """Return Ollama-declared capabilities, or ``None`` when they are unknown.

    Unknown is deliberately distinct from an empty set: a temporary service
    issue must not turn a valid model into a false negative before the actual
    generation request can run.
    """
    model = str(model_tag or "").strip()
    if not model:
        return None
    request = urllib.request.Request(
        f"{_OLLAMA_BASE_URL}/api/show",
        data=json.dumps({"model": model}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=3.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
        capabilities = payload.get("capabilities")
        if not isinstance(capabilities, list):
            return None
        return frozenset(
            str(capability).strip().lower()
            for capability in capabilities
            if str(capability).strip()
        )
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
        logger.debug("[LocalModelCapabilities] unable to inspect %s: %s", model, exc)
        return None


def local_model_supports_tools(model_tag: str) -> Optional[bool]:
    """Return whether an installed local model supports native tool calls.

    ``None`` means Ollama did not provide capability data, so callers should
    let the normal request path decide instead of making an incorrect claim.
    """
    capabilities = get_ollama_model_capabilities(model_tag)
    return None if capabilities is None else "tools" in capabilities


def clear_ollama_capability_cache() -> None:
    """Invalidate stale capability data after a model install/update."""
    get_ollama_model_capabilities.cache_clear()
