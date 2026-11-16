# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Koto Brain -- re-export shim.

Implementation moved to `app.core.brain_pkg` package.
This module remains for backward compatibility.
"""

from __future__ import annotations

from app.core.brain_pkg import (  # noqa: F401
    BrainRuntimeServices,
    KotoBrain,
    configure_default_brain_runtime,
)

__all__ = [
    "BrainRuntimeServices",
    "configure_default_brain_runtime",
    "KotoBrain",
]
