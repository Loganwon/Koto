"""Model discovery and probe policy used by document feedback workflows."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, Iterable, List, Optional

from app.core.llm.model_capabilities import (
    is_interactions_only_model,
    normalize_model_id,
)
from app.core.llm.model_selection import is_archived_cloud_model


logger = logging.getLogger("web.document_feedback")


def list_available_models(
    *,
    client: Any,
    is_local_client: bool,
    resolve_runtime_model_id: Callable[[Optional[str]], str],
    interactions_only_models: Iterable[str],
    timeout_seconds: int = 10,
) -> List[Dict[str, str]]:
    """List generate-content models without allowing discovery to block the UI."""
    if not client:
        return []
    if is_local_client:
        local_model = resolve_runtime_model_id(None)
        return [{"name": local_model, "display_name": local_model}] if local_model else []

    result_holder: Dict[str, Any] = {"models": None}

    def fetch_models() -> None:
        try:
            models = []
            for model in client.models.list():
                name = normalize_model_id(getattr(model, "name", ""))
                if not name:
                    continue
                supported = getattr(model, "supported_generation_methods", None)
                if supported is not None and "generateContent" not in supported:
                    continue
                if is_interactions_only_model(name, interactions_only_models):
                    continue
                if is_archived_cloud_model(name):
                    continue
                models.append(
                    {
                        "name": name,
                        "display_name": getattr(model, "display_name", "") or name,
                    }
                )
            result_holder["models"] = models
        except Exception:
            result_holder["models"] = []

    thread = threading.Thread(target=fetch_models, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)
    models = result_holder["models"]
    if models is None:
        logger.warning("[DocumentFeedback] models.list() timed out; using empty fallback")
        return []
    return models


def select_best_model(
    *,
    preferred: str,
    models: List[Dict[str, str]],
    interactions_only_models: Iterable[str],
) -> str:
    """Choose a safe preferred model from the discovered catalog."""
    safe_preferred = (
        preferred
        if not is_interactions_only_model(preferred, interactions_only_models)
        and not is_archived_cloud_model(preferred)
        else "deepseek-chat"
    )
    if not models:
        return safe_preferred

    available = {str(model.get("name") or "") for model in models}
    for candidate in (safe_preferred, "deepseek-chat"):
        if candidate in available:
            if candidate != preferred:
                logger.info("[DocumentFeedback] model fallback: %s -> %s", preferred, candidate)
            return candidate

    logger.warning("[DocumentFeedback] no matching model; using %s", safe_preferred)
    return safe_preferred


def format_model_table(models: List[Dict[str, str]]) -> str:
    if not models:
        return "（暂时无法获取可用模型列表）"
    rows = ["| 模型ID | 显示名称 |", "| --- | --- |"]
    rows.extend(f"| {model['name']} | {model['display_name']} |" for model in models)
    return "\n".join(rows)


def probe_working_model(
    *,
    preferred: str,
    client: Any,
    is_local_client: bool,
    resolve_runtime_model_id: Callable[[Optional[str]], str],
    interactions_only_models: Iterable[str],
    timeout_seconds: int = 12,
) -> Optional[str]:
    """Return the first responsive safe candidate, avoiding archived fallbacks."""
    resolved_preferred = resolve_runtime_model_id(preferred)
    if not client or is_local_client:
        return resolved_preferred

    from app.core.llm.provider_compat import types as google_types

    candidates = list(dict.fromkeys([resolved_preferred, "deepseek-chat"]))
    candidates = [
        candidate
        for candidate in candidates
        if not is_interactions_only_model(candidate, interactions_only_models)
        and not is_archived_cloud_model(candidate)
    ]
    for candidate in candidates:
        result: Dict[str, Any] = {"ok": False, "error": ""}

        def try_candidate(model_id: str = candidate) -> None:
            try:
                client.models.generate_content(
                    model=model_id,
                    contents="1",
                    config=google_types.GenerateContentConfig(
                        temperature=0.0, max_output_tokens=5
                    ),
                )
                result["ok"] = True
            except Exception as exc:
                result["error"] = str(exc)

        thread = threading.Thread(target=try_candidate, daemon=True)
        thread.start()
        thread.join(timeout_seconds)
        if thread.is_alive():
            logger.info("[DocumentFeedback] probe %s timed out", candidate)
            continue
        if result["ok"]:
            logger.info("[DocumentFeedback] probe succeeded: %s", candidate)
            return candidate

        error = str(result["error"])
        if any(token in error.lower() for token in ("503", "unavailable", "overloaded", "high demand")):
            logger.warning("[DocumentFeedback] %s is overloaded; trying next model", candidate)
            continue
        logger.error("[DocumentFeedback] %s probe failed: %s", candidate, error[:100])
        break

    logger.warning("[DocumentFeedback] no probe candidate is available")
    return None
