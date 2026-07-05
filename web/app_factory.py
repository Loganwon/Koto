from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask, request
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

    cors_origins = _resolve_cors_origins()
    CORS(app, origins=cors_origins)

    _csrf.init_app(app)
    app.extensions["csrf"] = _csrf

    # Add cache-control headers for static assets
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

    # Register service registry shutdown on app teardown
    try:
        from web.runtime_context import service_registry
        import atexit
        atexit.register(service_registry.shutdown)
    except Exception:
        pass

    return app, _read_app_version(), cors_origins
