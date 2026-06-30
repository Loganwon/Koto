# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Unified API response helpers.

All route files SHOULD use these instead of ad-hoc jsonify({...}) calls
to ensure consistent response format across the entire API surface.

Format: {"ok": true, "data": ...} for success
        {"ok": false, "error": "...", "code": "ERROR_CODE"} for errors
"""

from __future__ import annotations

from flask import jsonify


def ok(data: object = None) -> tuple:
    """Return a standard 200 success response."""
    payload: dict = {"ok": True}
    if data is not None:
        payload["data"] = data
    return jsonify(payload), 200


def err(message: str, status: int = 400, code: str | None = None) -> tuple:
    """Return a standard error response."""
    payload: dict = {"ok": False, "error": str(message)}
    if code:
        payload["code"] = code
    return jsonify(payload), status


def not_found(message: str = "资源不存在") -> tuple:
    """404 shortcut."""
    return err(message, 404, "NOT_FOUND")


def forbidden(message: str = "路径不合法") -> tuple:
    """403 shortcut."""
    return err(message, 403, "FORBIDDEN")


def bad_request(message: str) -> tuple:
    """400 shortcut."""
    return err(message, 400, "BAD_REQUEST")


def server_error(message: str = "内部服务器错误") -> tuple:
    """500 shortcut."""
    return err(message, 500, "INTERNAL_ERROR")
