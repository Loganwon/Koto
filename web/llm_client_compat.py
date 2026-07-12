# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Backward-compatibility shim.

The canonical implementation has moved to
`app.core.llm.llm_client_compat`.  This module remains as a re-export
so existing callers continue to work while they are migrated.
"""

# Re-export everything from the canonical location
from app.core.llm.llm_client_compat import *  # noqa: F401, F403
