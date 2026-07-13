from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from flask import Flask, g, jsonify, request, url_for
from flask_cors import CORS
try:
    from flask_wtf.csrf import CSRFProtect
except ImportError:
    class CSRFProtect:  # type: ignore[no-redef]
        def init_app(self, app):
            logging.getLogger("koto.app").warning(
                "flask-wtf is not installed; CSRF protection is disabled"
            )

_csrf = CSRFProtect()


def _read_app_version() -> str:
    try:
        return (Path(__file__).parent.parent / "VERSION").read_text(encoding="utf-8").strip()
    except Exception:
        return "unknown"


def _asset_version(static_root: Path, filename: str) -> str:
    """Return a stable cache key that changes only when a shipped asset changes."""
    root = static_root.resolve()
    try:
        asset = (root / filename).resolve()
        asset.relative_to(root)
        return str(asset.stat().st_mtime_ns)
    except (OSError, ValueError):
        # Keep missing assets debuggable without making template rendering fail.
        return "0"


def _load_secret_key() -> str:
    import secrets as _secrets

    key = os.environ.get("KOTO_SECRET_KEY") or os.environ.get("SECRET_KEY")
    if key:
        return key

    key_file = Path(__file__).parent.parent / "config" / "jwt_secret.txt"
    if key_file.exists():
        stored = key_file.read_text(encoding="utf-8").strip()
        if stored:
            return stored

    generated = _secrets.token_urlsafe(32)
    try:
        key_file.write_text(generated, encoding="utf-8")
    except Exception as exc:
        logging.getLogger("koto.app").debug(
            "failed to persist generated secret key: %s",
            exc,
        )
    return generated


def _resolve_cors_origins():
    cors_origins = os.environ.get("KOTO_CORS_ORIGINS", "http://localhost:5820,http://127.0.0.1:5820,http://localhost:5000,http://127.0.0.1:5000")
    if os.environ.get("KOTO_DEPLOY_MODE") == "cloud" and "http://localhost" in cors_origins:
        cors_origins = os.environ.get("KOTO_SITE_URL", cors_origins)
    return cors_origins


def create_flask_app(import_name: str):
    app = Flask(import_name)
    app.config["SECRET_KEY"] = _load_secret_key()
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 3600  # 1-hour cache for static assets (desktop app)
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("KOTO_DEPLOY_MODE") == "cloud"

    @app.context_processor
    def _inject_asset_url():
        static_root = Path(app.static_folder or Path(__file__).parent / "static")

        def asset_url(filename: str) -> str:
            return url_for("static", filename=filename, v=_asset_version(static_root, filename))

        return {"asset_url": asset_url}

    cors_origins = _resolve_cors_origins()
    CORS(app, origins=cors_origins)

    _csrf.init_app(app)
    app.extensions["csrf"] = _csrf

    # Add cache-control headers for static assets

    # ── Request tracing: inject request_id ────────────────────────────
    # ── Request tracing ────────────────────────────────────────────
    @app.before_request
    def _inject_request_id():
        """Inject a unique request_id into every request context."""
        g.request_id = str(uuid.uuid4())[:12]
        g._request_start_ms = int(__import__("time").monotonic() * 1000)

    @app.after_request
    def _set_security_headers(response):
        # CSP: allow inline scripts/styles (desktop app, nonce too heavy)
        # Blocks external script sources, form actions, and plugins
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:; "
            "img-src 'self' data: blob: https:; "
            "frame-src 'self' https:; "
            "connect-src 'self' ws: wss: https:; "
            "form-action 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
        )
        # Prevent MIME type sniffing
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # Prevent clickjacking
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-API-Version", "1.0")
        response.headers.setdefault("X-Koto-Version", _read_app_version())

        return response
    @app.after_request
    def _set_static_cache(response):
        if request.path.startswith("/static/") and response.status_code == 200:
            # Hashed build assets get immutable caching
            if any(ext in request.path for ext in (".woff2", ".woff", ".ttf")):
                response.headers["Cache-Control"] = "public, max-age=604800, immutable"
            elif request.path.endswith(".map"):
                response.headers["Cache-Control"] = "no-cache"
            else:
                response.headers["Cache-Control"] = "public, max-age=3600"
        return response



    # ── Request logging ───────────────────────────────────────────
    @app.after_request
    def _log_request(response):
        """Log every request with method, path, status, duration."""
        rid = getattr(g, "request_id", "-")
        start_ms = getattr(g, "_request_start_ms", 0)
        elapsed = int(__import__("time").monotonic() * 1000) - start_ms
        logger = logging.getLogger("koto.app")
        logger.info(
            "[%s] %s %s → %d (%dms)",
            rid, request.method, request.path,
            response.status_code, elapsed,
        )
        response.headers["X-Request-ID"] = rid
        return response

    # Register service registry shutdown on app teardown
    try:
        from web.runtime_context import service_registry
        import atexit
        atexit.register(service_registry.shutdown)
    except Exception:
        pass

    # ── Request deduplication ─────────────────────────────────────────
    try:
        from web.request_dedup import deduplicator
        app.before_request(deduplicator.check_or_register)
        app.after_request(deduplicator.release_current)
    except Exception:
        pass



    # ── Structured JSON logging ───────────────────────────────────────
    try:
        from web.structured_logging import install_json_formatter
        install_json_formatter()
    except Exception:
        pass



    # ── Structured error handlers ────────────────────────────────────
    from web.errors import APIError

    @app.errorhandler(APIError)
    def _handle_api_error(exc: APIError):
        """Return structured JSON for known API errors."""
        _logger = logging.getLogger("koto.app")
        if exc.status_code >= 500:
            _logger.exception(
                "[APIError] %s status=%d path=%s",
                exc.error_code, exc.status_code, request.path,
            )
        else:
            _logger.warning(
                "[APIError] %s status=%d path=%s detail=%s",
                exc.error_code, exc.status_code, request.path,
                exc.detail or exc.user_message,
            )
        return jsonify(exc.to_dict()), exc.status_code

    @app.errorhandler(Exception)
    def _handle_unhandled_exception(exc):
        request_id = str(uuid.uuid4())[:8]
        logger = logging.getLogger("koto.app")
        # Let HTTP/werkzeug exceptions pass through with their own status
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            return jsonify({
                "error": exc.description or "Request failed",
                "status": exc.code or 500,
            }), exc.code or 500
        logger.exception(
            "[Unhandled] request_id=%s path=%s", request_id, request.path
        )
        return (
            jsonify({
                "error": "Internal server error",
                "message": "服务器内部错误，请重试",
                "request_id": request_id,
                "status": 500,
            }),
            500,
        )

    @app.errorhandler(404)
    def _handle_not_found(exc):
        return jsonify({"error": "Not found", "message": "资源不存在", "status": 404}), 404

    @app.errorhandler(413)
    def _handle_too_large(exc):
        return jsonify({"error": "Payload too large", "message": "文件过大，上限 50 MB", "status": 413}), 413

    @app.errorhandler(429)
    def _handle_rate_limit(exc):
        return jsonify({"error": "Too many requests", "message": "请求过于频繁，请稍后重试", "status": 429}), 429


    # ── Gzip compression WSGI middleware ──────────────────────────────
    import gzip as _gzip, io as _io
    _gzip_app = app

    class _GzipMiddleware:
        """WSGI middleware that gzip-compresses text responses.

        Always calls start_response (required by WSGI spec).
        """
        COMPRESSIBLE_CT = (
            "text/", "application/json", "application/javascript",
            "image/svg", "application/xml"
        )

        def __init__(self, app):
            self.app = app

        def __call__(self, environ, start_response):
            accept = environ.get("HTTP_ACCEPT_ENCODING", "")
            if "gzip" not in accept.lower():
                return self.app(environ, start_response)

            captured = {}

            def _capture(status, headers, exc_info=None):
                captured["status"] = status
                captured["headers"] = headers

            body = list(self.app(environ, _capture))
            status = captured.get("status", "200 OK")
            headers = captured.get("headers", [])

            if not body:
                start_response(status, headers)
                return body

            ct = ""
            for name, value in headers:
                if name.lower() == "content-type":
                    ct = value.lower()
                    break

            if not any(t in ct for t in self.COMPRESSIBLE_CT):
                start_response(status, headers)
                return body

            data = b"".join(body)
            if len(data) < 500:
                start_response(status, headers)
                return body

            buf = _io.BytesIO()
            with _gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as gz:
                gz.write(data)
            compressed = buf.getvalue()

            new_headers = []
            for name, value in headers:
                low = name.lower()
                if low == "content-length":
                    new_headers.append((name, str(len(compressed))))
                elif low == "content-encoding":
                    continue
                else:
                    new_headers.append((name, value))
            new_headers.append(("Content-Encoding", "gzip"))
            new_headers.append(("Vary", "Accept-Encoding"))

            start_response(status, new_headers)
            return [compressed]

    app.wsgi_app = _GzipMiddleware(app.wsgi_app)

    APP_VERSION = _read_app_version()
    return app, APP_VERSION, cors_origins
