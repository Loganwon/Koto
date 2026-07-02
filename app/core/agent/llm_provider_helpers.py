from __future__ import annotations

from typing import Any, Optional

from app.core.shared.llm_helpers import (
    get_local_provider,
    is_ollama_alive,
    is_online_failure,
)


def pick_online_model(request: Optional[Any] = None) -> str:
    preferred_model = ""
    if request and isinstance(getattr(request, "extra", None), dict):
        preferred_model = str(request.extra.get("preferred_model") or "").strip()
        if preferred_model.lower() in {"auto", "cloud", "local"}:
            preferred_model = ""
    if preferred_model:
        return preferred_model
    try:
        from web.runtime_context import get_model_id

        model = get_model_id("CHAT")
        if model:
            return model
    except Exception:
        pass
    return "gemini-2.5-flash"


def get_provider(model: str = "", model_mode: str = ""):
    from app.core.llm.model_selection import get_provider_for_model_mode
    from app.core.llm.provider_factory import get_llm_provider

    provider_name = get_provider_for_model_mode(model_mode)
    return get_llm_provider(
        provider=provider_name,
        model=model,
        allow_local_fallback=False,
    )


def call_llm_sync(prompt: str, use_local_only: bool = False) -> Optional[str]:
    """Synchronous LLM call for code generation, with local fallback."""
    if use_local_only:
        if not is_ollama_alive():
            return None
        try:
            local = get_local_provider()
            result = local.generate_content(prompt=prompt, stream=False)
            if isinstance(result, dict):
                return result.get("content", "")
            return str(result) if result else None
        except Exception:
            return None

    try:
        model = pick_online_model()
        provider = get_provider(model=model)
        result = provider.generate_content(prompt=prompt, model=model, stream=False)
        if isinstance(result, dict):
            return result.get("content", "")
        return str(result) if result else None
    except Exception:
        if is_ollama_alive():
            try:
                local = get_local_provider()
                result = local.generate_content(prompt=prompt, stream=False)
                if isinstance(result, dict):
                    return result.get("content", "")
                return str(result) if result else None
            except Exception:
                pass
        return None
