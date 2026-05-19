from __future__ import annotations

import uuid
from logging import Logger

from flask import Flask, g, jsonify, request


def configure_http_wiring(app: Flask, logger: Logger):
    """Register request correlation and JSON error handlers."""

    @app.before_request
    def _assign_request_id():
        """Assign a correlation ID to every request (read from header or generate)."""
        g.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

    @app.after_request
    def _attach_request_id(response):
        """Attach the correlation ID to every outgoing response."""
        if hasattr(g, "request_id"):
            response.headers["X-Request-ID"] = g.request_id
        return response

    def error_response(message: str, status: int = 400, details=None):
        """Return a standardized JSON error envelope."""
        body = {"error": message, "status": status}
        if details:
            body["details"] = details
        if hasattr(g, "request_id"):
            body["request_id"] = g.request_id
        return jsonify(body), status

    @app.errorhandler(404)
    def _handle_404(exc):
        return error_response("Not found", 404)

    @app.errorhandler(405)
    def _handle_405(exc):
        return error_response("Method not allowed", 405)

    @app.errorhandler(500)
    def _handle_500(exc):
        logger.exception(
            "Unhandled server error [request_id=%s]", getattr(g, "request_id", "-")
        )
        return error_response("Internal server error", 500)

    @app.errorhandler(413)
    def _handle_413(exc):
        return error_response("文件过大，请压缩后重试", 413)

    try:
        from werkzeug.exceptions import HTTPException as _WerkzeugHTTPException

        @app.errorhandler(_WerkzeugHTTPException)
        def _handle_http_exception(exc):
            # Only intercept non-JSON responses; let specific handlers take priority.
            return error_response(exc.description or exc.name, exc.code)
    except Exception:  # pragma: no cover
        pass

    return error_response