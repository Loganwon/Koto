from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask
from flask_cors import CORS


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
    cors_origins = os.environ.get("KOTO_CORS_ORIGINS", "*")
    if os.environ.get("KOTO_DEPLOY_MODE") == "cloud" and cors_origins == "*":
        cors_origins = os.environ.get("KOTO_SITE_URL", "*")
    return cors_origins


def create_flask_app(import_name: str):
    app = Flask(import_name)
    app.config["SECRET_KEY"] = _load_secret_key()
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("KOTO_DEPLOY_MODE") == "cloud"

    cors_origins = _resolve_cors_origins()
    CORS(app, origins=cors_origins)
    return app, _read_app_version(), cors_origins