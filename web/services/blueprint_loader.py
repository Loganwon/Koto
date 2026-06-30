# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

from __future__ import annotations

from logging import Logger

from flask import Flask

from web import app_blueprints as _app_blueprints

_blueprints_registered = False


def register_all_blueprints(app: Flask, logger: Logger):
    """Compatibility wrapper around the single blueprint registration owner."""
    global _blueprints_registered
    if _blueprints_registered:
        return None
    _blueprints_registered = True

    previous = _app_blueprints._blueprints_registered
    try:
        _app_blueprints._blueprints_registered = False
        return _app_blueprints.register_blueprints_deferred(app, logger)
    finally:
        _app_blueprints._blueprints_registered = previous
