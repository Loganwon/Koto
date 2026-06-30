# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

KOTO_CREATED_RESULT_MARKER = "__koto_created__:"
KOTO_MODIFIED_RESULT_MARKER = "__koto_modified__:"

KOTO_CREATED_RESULT_KEY = "__koto_created__"
KOTO_MODIFIED_RESULT_KEY = "__koto_modified__"
KOTO_CREATED_FALLBACK_KEY = "_koto_created"
KOTO_MODIFIED_FALLBACK_KEY = "_koto_modified"


def result_key_for_marker(marker: str) -> str:
    return (
        KOTO_CREATED_RESULT_KEY
        if marker == KOTO_CREATED_RESULT_MARKER
        else KOTO_MODIFIED_RESULT_KEY
    )


def fallback_key_for_marker(marker: str) -> str:
    return (
        KOTO_CREATED_FALLBACK_KEY
        if marker == KOTO_CREATED_RESULT_MARKER
        else KOTO_MODIFIED_FALLBACK_KEY
    )
