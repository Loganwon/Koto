#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
"""Track-changes mixin ? state and helpers for Word tracked revisions.

The per-revision XML handling lives in ``editor.TrackChangesEditor``; this
mixin only supplies shared state (author, change id counter).
"""

from __future__ import annotations


class _TrackChangesTrackingMixin:
    """Shared state for applying Word tracked changes."""

    def __init__(self, author: str = "Koto AI", change_id: int = 0):
        self.author = str(author or "Koto AI")
        self.change_id = int(change_id or 0)
