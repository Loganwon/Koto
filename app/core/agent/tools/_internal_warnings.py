#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Internal helpers: warning merging."""

from __future__ import annotations

from typing import Any


def _merge_warnings(*parts: Any) -> str:
    """Merge multiple warning strings with Chinese semicolon separator."""
    cleaned = [str(part).strip() for part in parts if str(part or "").strip()]
    return "\uff1b".join(cleaned)
