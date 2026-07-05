from __future__ import annotations

from typing import Optional

# Only providers with configured API keys are listed as valid modes.
# openai / anthropic can be re-added when corresponding keys are available.
_EXPLICIT_MODEL_MODES = {
    "local",
    "cloud",
    "gemini",
    "deepseek",
    "ollama",
}


def normalize_model_mode(model_mode: Optional[str], default: str = "auto") -> str:
    """Normalize UI/API model mode values.

    Supported explicit modes are `local`, `cloud`, and provider names.
    Legacy `auto` remains accepted as a compatibility input and is mapped to
    the caller-provided default.
    """
    normalized = str(model_mode or "").strip().lower()
    if normalized in _EXPLICIT_MODEL_MODES:
        return normalized
    if normalized in {"", "auto"}:
        return str(default or "auto").strip().lower() or "auto"
    return str(default or "auto").strip().lower() or "auto"


def is_explicit_model_mode(model_mode: Optional[str]) -> bool:
    return str(model_mode or "").strip().lower() in _EXPLICIT_MODEL_MODES
