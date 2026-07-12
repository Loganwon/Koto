#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Provider-neutral compatibility surface.
try:
    from app.core.llm import provider_compat as genai
    from app.core.llm.provider_compat import types

    HAS_GENAI_V2 = True
except ImportError:
    HAS_GENAI_V2 = False


class SearchService:
    """
    Compatibility wrapper for search. Grounded cloud search is disabled until
    an active provider exposes a verified grounding contract.
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        self.client = None
        if HAS_GENAI_V2 and self.api_key:
            try:
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.error(f"Failed to initialize GenAI v2 client: {e}")

    def search(self, query: str) -> Dict[str, Any]:
        """Reject this retired grounding path with an actionable route."""
        return {
            "success": False,
            "error": "Grounded cloud search is not configured; use the web search workflow.",
        }
