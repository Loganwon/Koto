#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Proactive dialogue, triggers, and suggestion engine."""

from app.core.services.proactive_trigger import get_trigger_system  # noqa: F401
from web.proactive.proactive_dialogue import get_proactive_dialogue_engine  # noqa: F401
from web.proactive.suggestion_engine import SuggestionEngine  # noqa: F401
from web.proactive.smart_feedback import SmartFeedback  # noqa: F401
