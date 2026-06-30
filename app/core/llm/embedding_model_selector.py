from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

_EMBEDDING_KEY_ENV_NAMES = (
    "GEMINI_API_KEY",
    "API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_GENAI_API_KEY",
)

_DEFAULT_EMBEDDING_MODEL = "models/gemini-embedding-2"
_FALLBACK_EMBEDDING_MODELS = (
    _DEFAULT_EMBEDDING_MODEL,
    "models/gemini-embedding-001",
    "models/gemini-embedding-2-preview",
)


def normalize_gemini_embedding_model(model_id: Optional[str]) -> str:
    text = str(model_id or "").strip()
    if not text:
        return _DEFAULT_EMBEDDING_MODEL
    if not text.startswith("models/"):
        text = f"models/{text}"
    return text


def _embedding_candidates() -> tuple[str, ...]:
    configured = normalize_gemini_embedding_model(
        os.environ.get("KOTO_GEMINI_EMBEDDING_MODEL")
    )
    ordered = [configured]
    ordered.extend(_FALLBACK_EMBEDDING_MODELS)

    deduped = []
    seen = set()
    for item in ordered:
        normalized = normalize_gemini_embedding_model(item)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return tuple(deduped)


def _resolve_api_key(explicit_key: Optional[str]) -> str:
    if explicit_key:
        return str(explicit_key).strip()
    for env_name in _EMBEDDING_KEY_ENV_NAMES:
        value = str(os.environ.get(env_name) or "").strip()
        if value:
            return value
    return ""


def _iter_embed_models(api_key: str) -> Iterable[str]:
    if not api_key:
        return ()

    try:
        import google.genai as genai

        client = genai.Client(api_key=api_key)
        available = []
        for model in client.models.list():
            methods = list(
                getattr(model, "supported_actions", None)
                or getattr(model, "supported_generation_methods", None)
                or []
            )
            lowered = {str(method).lower() for method in methods}
            if "embedcontent" in lowered:
                available.append(normalize_gemini_embedding_model(model.name))
        return tuple(available)
    except Exception as exc:
        logger.debug("[EmbeddingModelSelector] 列举 embedding models 失败: %s", exc)
        return ()


@lru_cache(maxsize=8)
def resolve_gemini_embedding_model(explicit_key: Optional[str] = None) -> str:
    api_key = _resolve_api_key(explicit_key)
    candidates = _embedding_candidates()
    available = set(_iter_embed_models(api_key))

    if available:
        for candidate in candidates:
            if candidate in available:
                return candidate
        for model_id in sorted(available):
            if "embedding" in model_id:
                return model_id

    return candidates[0]
