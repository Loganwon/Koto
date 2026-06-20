from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

GEMINI_KEY_ENV_NAMES = (
    "GEMINI_API_KEY",
    "API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_GENAI_API_KEY",
)

_PLACEHOLDER_VALUES = {
    "",
    "your_api_key_here",
    "YOUR_API_KEY_HERE",
    "None",
    "none",
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def normalize_gemini_api_key(value: Optional[str]) -> str:
    text = str(value or "").strip().strip('"').strip("'")
    return "" if text in _PLACEHOLDER_VALUES else text


def find_gemini_config_path() -> Optional[Path]:
    root = project_root()
    candidates = [
        root / "config" / "gemini_config.env",
        root / "gemini_config.env",
    ]
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "config" / "gemini_config.env")
    candidates.extend(
        [
            Path.cwd() / "gemini_config.env",
            Path.cwd().parent / "gemini_config.env",
        ]
    )

    seen = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        if resolved.exists():
            return resolved
    return None


def load_gemini_config_env(override: bool = False) -> Optional[Path]:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return None

    config_path = find_gemini_config_path()
    if not config_path:
        return None

    load_dotenv(str(config_path), override=override)
    return config_path


def _read_key_from_env_file(path: Path) -> Optional[str]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return None

    for line in lines:
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text.startswith("export "):
            text = text[len("export ") :].strip()
        if "=" not in text:
            continue
        name, value = text.split("=", 1)
        if name.strip() not in GEMINI_KEY_ENV_NAMES:
            continue
        key = normalize_gemini_api_key(value)
        if key:
            return key
    return None


def get_gemini_api_key(
    explicit_key: Optional[str] = None,
    *,
    ensure_loaded: bool = True,
) -> Optional[str]:
    key = normalize_gemini_api_key(explicit_key)
    if key:
        return key

    for env_name in GEMINI_KEY_ENV_NAMES:
        key = normalize_gemini_api_key(os.getenv(env_name))
        if key:
            return key

    if ensure_loaded:
        config_path = find_gemini_config_path()
        if config_path:
            key = _read_key_from_env_file(config_path)
            if key:
                return key
    return None


def has_gemini_api_key(*, ensure_loaded: bool = True) -> bool:
    return bool(get_gemini_api_key(ensure_loaded=ensure_loaded))


def set_runtime_gemini_api_key(api_key: str) -> str:
    normalized = normalize_gemini_api_key(api_key)
    if not normalized:
        raise ValueError("Invalid Gemini API key")

    for env_name in GEMINI_KEY_ENV_NAMES:
        os.environ[env_name] = normalized
    return normalized


def write_gemini_config_file(
    api_key: str,
    *,
    api_base: str = "",
    header: str = "# Koto Configuration",
) -> Path:
    normalized = normalize_gemini_api_key(api_key)
    if not normalized:
        raise ValueError("Invalid Gemini API key")

    config_path = project_root() / "config" / "gemini_config.env"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"{header}\n",
        f"GEMINI_API_KEY={normalized}\n",
        f"API_KEY={normalized}\n",
        f"GOOGLE_API_KEY={normalized}\n",
        f"GOOGLE_GENAI_API_KEY={normalized}\n",
        f"GEMINI_API_BASE={str(api_base or '').strip()}\n",
    ]
    config_path.write_text("".join(lines), encoding="utf-8")
    return config_path
