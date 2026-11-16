"""Explicit key-file loading; file contents are only a credential, never instructions."""

from pathlib import Path
import re

from .contracts import CompanionError
from .model import ModelConfig


def config_from_key_file(path):
    try:
        file = Path(path)
        if file.stat().st_size > 4096:
            raise ValueError("Not a raw credential")
        key = file.read_text(encoding="utf-8-sig").strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{16,512}", key):
            raise ValueError("Not a raw credential")
    except (OSError, UnicodeError, ValueError):
        raise CompanionError(
            "密钥文件无法读取，请提供仅含 API 密钥的 UTF-8 文本。"
        ) from None
    return ModelConfig("https://api.deepseek.com", "deepseek-chat", key).validated()
