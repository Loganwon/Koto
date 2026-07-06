# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Structured API error types with user-facing messages.

Usage::

    from web.errors import APIError, bad_request, service_unavailable

    if not session_name:
        raise bad_request("Missing session name", detail="请提供会话名称")
"""

from __future__ import annotations

import logging
from typing import Any

_logger = logging.getLogger("koto.errors")


class APIError(Exception):
    """Base class for API errors with HTTP status and structured payload."""

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"
    message: str = "Internal server error"

    def __init__(self, message: str = "", *, detail: str = "", extras: dict | None = None) -> None:
        self.user_message = message or self.message
        self.detail = detail
        self.extras = extras or {}
        super().__init__(self.user_message)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "error": self.error_code,
            "message": self.user_message,
            "status": self.status_code,
        }
        if self.detail:
            payload["detail"] = self.detail
        if self.extras:
            payload.update(self.extras)
        return payload


# -- 4xx Client Errors -------------------------------------------------------

class BadRequestError(APIError):
    status_code = 400
    error_code = "BAD_REQUEST"
    message = "Bad request"


class UnauthorizedError(APIError):
    status_code = 401
    error_code = "UNAUTHORIZED"
    message = "Authentication required"


class NotFoundError(APIError):
    status_code = 404
    error_code = "NOT_FOUND"
    message = "Resource not found"


class PayloadTooLargeError(APIError):
    status_code = 413
    error_code = "PAYLOAD_TOO_LARGE"
    message = "Request payload too large"


class TooManyRequestsError(APIError):
    status_code = 429
    error_code = "TOO_MANY_REQUESTS"
    message = "Too many requests, please retry later"


# -- 5xx Server Errors -------------------------------------------------------

class ServiceUnavailableError(APIError):
    status_code = 503
    error_code = "SERVICE_UNAVAILABLE"
    message = "Service temporarily unavailable, please retry"


class ModelUnavailableError(ServiceUnavailableError):
    error_code = "MODEL_UNAVAILABLE"
    message = "AI model is currently unavailable, falling back to alternative"


class SandboxError(APIError):
    status_code = 500
    error_code = "SANDBOX_ERROR"
    message = "Code execution failed"


class StreamingError(APIError):
    status_code = 500
    error_code = "STREAMING_ERROR"
    message = "Response streaming interrupted, please retry"


# -- Convenience constructors ------------------------------------------------

def bad_request(msg: str = "", **kwargs: Any) -> BadRequestError:
    return BadRequestError(msg, **kwargs)


def not_found(msg: str = "", **kwargs: Any) -> NotFoundError:
    return NotFoundError(msg, **kwargs)


def service_unavailable(msg: str = "", **kwargs: Any) -> ServiceUnavailableError:
    return ServiceUnavailableError(msg, **kwargs)


def streaming_error(msg: str = "", **kwargs: Any) -> StreamingError:
    return StreamingError(msg, **kwargs)
