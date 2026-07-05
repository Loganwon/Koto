# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Backward-compatible re-export of user settings from app.core.config.user_settings.

New imports should use ``from app.core.config.user_settings import ...`` directly.
"""

from app.core.config.user_settings import *  # noqa: F401, F403
