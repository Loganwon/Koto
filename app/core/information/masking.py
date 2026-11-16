"""Deterministic field masking used after source-side authorization."""

from __future__ import annotations

import hashlib
from typing import Any


def mask_value(value: Any, strategy: str) -> Any:
    if strategy == "none" or value is None:
        return value
    text = str(value)
    if strategy == "full":
        return "***"
    if strategy == "hash":
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    if strategy == "last4":
        return "*" * max(0, len(text) - 4) + text[-4:]
    if strategy == "account_partial":
        if len(text) <= 8:
            return "*" * len(text)
        return text[:4] + "*" * (len(text) - 8) + text[-4:]
    if strategy == "document_id_partial":
        if len(text) <= 6:
            return "*" * len(text)
        return text[:3] + "*" * (len(text) - 5) + text[-2:]
    if strategy == "phone_partial":
        if len(text) <= 7:
            return "*" * len(text)
        return text[:3] + "*" * (len(text) - 7) + text[-4:]
    if strategy == "name_partial":
        return text[:1] + "*" * max(1, len(text) - 1)
    raise ValueError(f"unsupported masking strategy: {strategy}")


__all__ = ["mask_value"]
