# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Shared SSE framing helpers."""

from __future__ import annotations

import json
from typing import Any, Mapping


class _SseProtocol:
    def chunk(self, payload: Mapping[str, Any]) -> str:
        return f"data: {json.dumps(dict(payload or {}), ensure_ascii=False)}\n\n"


sse = _SseProtocol()

__all__ = ["sse"]
