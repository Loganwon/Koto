from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

DEEPSEEK_KEY_ENV_NAMES = (
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_KEY",
    "DS_API_KEY",
    "DS_KEY",
)

DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-pro"

_PLACEHOLDER_VALUES = {
    "",
    "your_api_key_here",
    "YOUR_API_KEY_HERE",
    "None",
    "none",
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def normalize_deepseek_api_key(value: Optional[str]) -> str:
    text = str(value or "").strip().strip('"').strip("'")
    return "" if text in _PLACEHOLDER_VALUES else text


def _candidate_key_files() -> list[Path]:
    root = project_root()
    home = Path.home()
    candidates = [
        root / "config" / "deepseek_config.env",
        root / "deepseek_config.env",
        home / "Desktop" / "DS_KEY",
        home / "Desktop" / "DS_KEY.txt",
    ]
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend(
            [
                exe_dir / "config" / "deepseek_config.env",
                exe_dir.parent / "DS_KEY",
                exe_dir.parent / "DS_KEY.txt",
            ]
        )
    candidates.extend(
        [
            Path.cwd() / "deepseek_config.env",
            Path.cwd().parent / "deepseek_config.env",
            Path.cwd() / "DS_KEY",
            Path.cwd() / "DS_KEY.txt",
        ]
    )
    return candidates


def find_deepseek_config_path() -> Optional[Path]:
    seen = set()
    for path in _candidate_key_files():
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


def load_deepseek_config_env(override: bool = False) -> Optional[Path]:
    config_path = find_deepseek_config_path()
    if not config_path:
        return None

    if config_path.name.upper().startswith("DS_KEY"):
        key = normalize_deepseek_api_key(config_path.read_text(encoding="utf-8-sig"))
        if key and (override or not os.getenv("DEEPSEEK_API_KEY")):
            os.environ["DEEPSEEK_API_KEY"] = key
        return config_path

    try:
        from dotenv import load_dotenv
    except ImportError:
        return None

    load_dotenv(str(config_path), override=override)
    return config_path


def _read_key_from_env_file(path: Path) -> Optional[str]:
    try:
        if path.name.upper().startswith("DS_KEY"):
            return normalize_deepseek_api_key(path.read_text(encoding="utf-8-sig"))

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
        if name.strip() not in DEEPSEEK_KEY_ENV_NAMES:
            continue
        key = normalize_deepseek_api_key(value)
        if key:
            return key
    return None


def get_deepseek_api_key(
    explicit_key: Optional[str] = None,
    *,
    ensure_loaded: bool = True,
) -> Optional[str]:
    key = normalize_deepseek_api_key(explicit_key)
    if key:
        return key

    for env_name in DEEPSEEK_KEY_ENV_NAMES:
        key = normalize_deepseek_api_key(os.getenv(env_name))
        if key:
            return key

    if ensure_loaded:
        config_path = find_deepseek_config_path()
        if config_path:
            key = _read_key_from_env_file(config_path)
            if key:
                return key
    return None


def has_deepseek_api_key(*, ensure_loaded: bool = True) -> bool:
    return bool(get_deepseek_api_key(ensure_loaded=ensure_loaded))


def set_runtime_deepseek_api_key(api_key: str) -> str:
    normalized = normalize_deepseek_api_key(api_key)
    if not normalized:
        raise ValueError("Invalid DeepSeek API key")
    for env_name in DEEPSEEK_KEY_ENV_NAMES:
        os.environ[env_name] = normalized
    return normalized


def write_deepseek_config_file(
    api_key: str,
    *,
    api_base: str = DEEPSEEK_DEFAULT_BASE_URL,
    header: str = "# Koto DeepSeek Configuration",
) -> Path:
    normalized = normalize_deepseek_api_key(api_key)
    if not normalized:
        raise ValueError("Invalid DeepSeek API key")

    config_path = project_root() / "config" / "deepseek_config.env"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"{header}\n",
        f"DEEPSEEK_API_KEY={normalized}\n",
        f"DEEPSEEK_BASE_URL={str(api_base or '').strip()}\n",
    ]
    config_path.write_text("".join(lines), encoding="utf-8")
    return config_path
