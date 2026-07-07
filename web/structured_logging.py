# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Structured JSON log formatter.

Usage (in app_factory)::

    from web.structured_logging import install_json_formatter
    install_json_formatter()
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON with request context."""

    def format(self, record: logging.LogRecord) -> str:
        from flask import has_request_context, g, request

        payload: dict = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        if has_request_context():
            rid = getattr(g, "request_id", None)
            if rid:
                payload["rid"] = rid
            try:
                payload["method"] = request.method
                payload["path"] = request.path
            except RuntimeError:
                pass

        if record.exc_info and record.exc_info[1]:
            payload["exc"] = str(record.exc_info[1])

        return json.dumps(payload, ensure_ascii=False, default=str)


def install_json_formatter() -> None:
    """Replace koto logger handlers with JSON formatter."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    for name in ("koto", "koto.app", "koto.routes", "koto.errors", "koto.dedup"):
        logger = logging.getLogger(name)
        for h in list(logger.handlers):
            logger.removeHandler(h)
        logger.propagate = False  # prevent duplicate logs from root logger
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
