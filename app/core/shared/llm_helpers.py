"""
Shared LLM infrastructure helpers.

Single canonical implementation used by agent_loop, task_agent, and
socket_handler – replaces three near-identical local copies.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ── Online-failure detection ──────────────────────────────────────────────────


def is_online_failure(exc: Exception) -> bool:
    """Return True if *exc* is a recoverable online-availability failure.

    Checks both the numeric ``status_code`` / ``code`` attribute (carried by
    google-genai / httpx exceptions) AND the string representation, so errors
    are caught even when their ``str()`` doesn't contain the status number.
    """
    # Named exception type short-circuits everything else
    if type(exc).__name__ == "CloudProviderUnavailableError":
        return True

    # Numeric status code check
    _status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if _status_code is not None:
        try:
            if int(_status_code) in (400, 429, 500, 503):
                return True
        except (TypeError, ValueError):
            pass

    s = str(exc).lower()
    return (
        "timed out" in s
        or "stream stalled" in s
        or "503" in s
        or "unavailable" in s
        or "timeout" in s
        or "resourceexhausted" in s
        or "resource_exhausted" in s
        or "429" in s
        or "overloaded" in s
        or "quota" in s
        # API key issues – fall back to local Ollama
        or "invalid_argument" in s
        or "api key" in s
        or "api_key" in s
        or "expired" in s
        or "400" in s
        # Model availability / project access issues
        or "404" in s
        or "model not found" in s
        or "permission denied" in s
        or "does not have access to model" in s
        # Region restriction
        or "location is not supported" in s
        or "failed_precondition" in s
        or "user_location_invalid" in s
        # Network-level failures
        or "deadline_exceeded" in s
        or "server disconnected" in s
        or "disconnected without" in s
        or "connection reset" in s
        or "connection aborted" in s
        or "backend error" in s
        or "service temporarily unavailable" in s
        or "no cloud llm provider configured" in s
        or "gemini cloud provider is not configured" in s
        or "not initialized" in s
    )


# ── Ollama helpers ────────────────────────────────────────────────────────────


def is_ollama_alive() -> bool:
    """Return True if local Ollama is reachable within 2 seconds.

    Uses an explicit no-proxy opener so Windows system-proxy settings
    (e.g. Clash / VPN) do not intercept the localhost connection.
    """
    try:
        import urllib.request as _ur

        _opener = _ur.build_opener(_ur.ProxyHandler({}))
        _opener.open("http://127.0.0.1:11434/api/tags", timeout=2).close()
        return True
    except Exception:
        return False


def get_local_provider(preferred_model: str = ""):
    """Return an :class:`OllamaLLMProvider` for the requested/configured model.

    Uses ``preferred_model`` when the caller already resolved a concrete Ollama
    tag for the active request. Otherwise uses the user-selected runtime tag.
    Only a first-run installation with no saved choice queries ``/api/tags``.
    Falls back to ``model=None`` (OllamaLLMProvider's own auto-selection) when
    the tags query fails.
    """
    from app.core.llm.ollama_llm_provider import OllamaLLMProvider

    preferred = str(preferred_model or "").strip()
    if not preferred:
        try:
            from app.core.llm.local_model_runtime import get_configured_local_model_tag

            preferred = get_configured_local_model_tag()
        except Exception:
            preferred = ""
    if (
        preferred
        and preferred.lower() not in {"auto", "cloud", "local"}
        and not preferred.lower().startswith("gemini")
    ):
        logger.info("[llm_helpers] Using requested local model: %s", preferred)
        return OllamaLLMProvider(model=preferred)

    try:
        import json as _json
        import urllib.request as _ur

        # Use an explicit no-proxy opener for localhost
        _opener = _ur.build_opener(_ur.ProxyHandler({}))
        with _opener.open("http://127.0.0.1:11434/api/tags", timeout=3) as r:
            tags = _json.loads(r.read())
        models = [m["name"] for m in tags.get("models", [])]
        if models:
            preferred = next(
                (
                    m
                    for m in models
                    if any(
                        k in m.lower() for k in ("7b", "8b", "13b", "14b", "32b", "70b")
                    )
                ),
                models[0],
            )
            logger.info("[llm_helpers] Using local model: %s", preferred)
            return OllamaLLMProvider(model=preferred)
    except Exception as exc:
        logger.warning("[llm_helpers] Could not query Ollama model list: %s", exc)
    return OllamaLLMProvider(model=None)
