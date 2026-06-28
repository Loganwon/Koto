from __future__ import annotations

import uuid
from logging import Logger

from flask import Flask, g, jsonify, request


def configure_http_wiring(app: Flask, logger: Logger):
    """Register request correlation and JSON error handlers."""
    existing = app.extensions.get("koto_http_wiring")
    if existing:
        return existing["error_response"]

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

    @app.route("/api/csrf-token", methods=["GET"])
    def _csrf_token():
        try:
            from flask_wtf.csrf import generate_csrf

            token = generate_csrf()
        except Exception:
            token = ""
        return jsonify({"csrf_token": token})

    try:
        from flask_wtf.csrf import CSRFError as _CSRFError

        @app.errorhandler(_CSRFError)
        def _handle_csrf_error(exc):
            return error_response(
                exc.description or "CSRF validation failed",
                400,
                {"code": "CSRF_FAILED"},
            )
    except Exception:  # pragma: no cover
        pass

    try:
        from werkzeug.exceptions import HTTPException as _WerkzeugHTTPException

        @app.errorhandler(_WerkzeugHTTPException)
        def _handle_http_exception(exc):
            # Only intercept non-JSON responses; let specific handlers take priority.
            return error_response(exc.description or exc.name, exc.code)
    except Exception:  # pragma: no cover
        pass

    app.extensions["koto_http_wiring"] = {"error_response": error_response}
    return error_response
