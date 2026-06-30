# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

_lazy_cache = {}


def _lazy_load(cache_key, web_module, class_name, *, factory=False, args=(), kwargs=None):
    if cache_key not in _lazy_cache:
        try:
            mod = __import__("web." + web_module, fromlist=[class_name])
        except ImportError:
            mod = __import__(web_module, fromlist=[class_name])
        target = getattr(mod, class_name)
        _lazy_cache[cache_key] = (
            target(*(args or ()), **(kwargs or {}))
            if not factory
            else target(*(args or ()), **(kwargs or {}))
        )
    return _lazy_cache[cache_key]
