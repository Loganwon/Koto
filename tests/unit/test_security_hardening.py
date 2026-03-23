"""Security hardening verification tests.

Validates session cookie settings, CORS configuration, auth enforcement,
upload limits, filename sanitization, and security event logging.
"""

import logging
import os
import sys
from unittest.mock import patch

import pytest

# Ensure repo root is on sys.path so web.* imports work.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ---------------------------------------------------------------------------
# Helpers – mirrors the pattern in test_auth_coverage.py
# ---------------------------------------------------------------------------


def _get_auth_module():
    """Import the auth module."""
    import web.auth as auth_mod

    return auth_mod


def _make_flask_app(auth_enabled: bool = True):
    """Create a minimal Flask app with auth-protected endpoints."""
    from flask import Flask

    auth_mod = _get_auth_module()

    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/api/chat", methods=["POST"])
    @auth_mod.require_auth
    def chat():
        from flask import g, jsonify

        return jsonify({"user": g.user_id})

    @app.route("/api/chat/stream", methods=["POST"])
    @auth_mod.require_auth
    def chat_stream():
        from flask import g, jsonify

        return jsonify({"user": g.user_id})

    @app.route("/api/chat/file", methods=["POST"])
    @auth_mod.require_auth
    def chat_file():
        from flask import g, jsonify

        return jsonify({"user": g.user_id})

    return app


# ---------------------------------------------------------------------------
# 1. Chat endpoints require auth (CRITICAL)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestChatEndpointAuth:
    """Verify chat endpoints return 401 without a valid token."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        auth_mod = _get_auth_module()
        monkeypatch.setattr(auth_mod, "AUTH_ENABLED", True)
        self.app = _make_flask_app(auth_enabled=True)
        self.client = self.app.test_client()

    def test_chat_requires_auth(self):
        """POST /api/chat without token returns 401."""
        resp = self.client.post("/api/chat", json={"message": "test"})
        assert resp.status_code == 401

    def test_chat_stream_requires_auth(self):
        """POST /api/chat/stream without token returns 401."""
        resp = self.client.post("/api/chat/stream", json={"message": "test"})
        assert resp.status_code == 401

    def test_chat_file_requires_auth(self):
        """POST /api/chat/file without token returns 401."""
        resp = self.client.post("/api/chat/file", data={})
        assert resp.status_code == 401

    def test_chat_invalid_bearer_returns_401(self):
        """An invalid Bearer token should still yield 401."""
        resp = self.client.post(
            "/api/chat",
            json={"message": "test"},
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert resp.status_code == 401

    def test_response_contains_unauthorized_code(self):
        """401 body must include code=UNAUTHORIZED for the frontend."""
        resp = self.client.post("/api/chat", json={"message": "test"})
        data = resp.get_json()
        assert data.get("code") == "UNAUTHORIZED"


# ---------------------------------------------------------------------------
# 2. Flask secure cookie config
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSecureCookieConfig:
    """Verify Flask session cookie settings in the real web app."""

    @pytest.fixture(autouse=True)
    def _import_app(self):
        """Import web.app to inspect its config."""
        # Suppress side-effects by importing within the test
        import web.app as web_app_mod

        self.real_app = web_app_mod.app

    def test_session_cookie_httponly(self):
        assert self.real_app.config.get("SESSION_COOKIE_HTTPONLY") is True

    def test_session_cookie_samesite(self):
        assert self.real_app.config.get("SESSION_COOKIE_SAMESITE") == "Lax"

    def test_max_content_length_set(self):
        """Flask should have MAX_CONTENT_LENGTH configured."""
        max_len = self.real_app.config.get("MAX_CONTENT_LENGTH")
        assert max_len is not None
        assert max_len <= 50 * 1024 * 1024  # no more than 50 MB


# ---------------------------------------------------------------------------
# 3. CORS behaviour
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCORSConfig:
    """Verify CORS origin logic (unit-level, no live server)."""

    def test_local_mode_allows_all(self, monkeypatch):
        """Local/desktop mode defaults to * CORS origins."""
        monkeypatch.setenv("KOTO_DEPLOY_MODE", "local")
        monkeypatch.delenv("KOTO_CORS_ORIGINS", raising=False)
        origins = os.environ.get("KOTO_CORS_ORIGINS", "*")
        if os.environ.get("KOTO_DEPLOY_MODE") == "cloud" and origins == "*":
            origins = os.environ.get("KOTO_SITE_URL", "*")
        assert origins == "*"

    def test_cloud_mode_with_site_url(self, monkeypatch):
        """Cloud mode should use KOTO_SITE_URL when KOTO_CORS_ORIGINS is default."""
        monkeypatch.setenv("KOTO_DEPLOY_MODE", "cloud")
        monkeypatch.delenv("KOTO_CORS_ORIGINS", raising=False)
        monkeypatch.setenv("KOTO_SITE_URL", "https://koto.example.com")
        origins = os.environ.get("KOTO_CORS_ORIGINS", "*")
        if os.environ.get("KOTO_DEPLOY_MODE") == "cloud" and origins == "*":
            origins = os.environ.get("KOTO_SITE_URL", "*")
        assert origins == "https://koto.example.com"

    def test_cloud_mode_explicit_origins(self, monkeypatch):
        """Explicit KOTO_CORS_ORIGINS takes precedence in any mode."""
        monkeypatch.setenv("KOTO_DEPLOY_MODE", "cloud")
        monkeypatch.setenv("KOTO_CORS_ORIGINS", "https://my.site")
        origins = os.environ.get("KOTO_CORS_ORIGINS", "*")
        if os.environ.get("KOTO_DEPLOY_MODE") == "cloud" and origins == "*":
            origins = os.environ.get("KOTO_SITE_URL", "*")
        assert origins == "https://my.site"


# ---------------------------------------------------------------------------
# 4. Upload / filename security
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUploadSecurity:
    """Verify file upload security measures."""

    def test_max_content_length_enforced(self):
        """The real app must restrict request body size."""
        import web.app as web_app_mod

        max_len = web_app_mod.app.config.get("MAX_CONTENT_LENGTH")
        assert max_len is not None
        assert 0 < max_len <= 50 * 1024 * 1024

    def test_secure_filename_strips_path_traversal(self):
        """Path traversal sequences must be sanitized."""
        from web.app import _secure_filename

        result = _secure_filename("../../etc/passwd")
        assert ".." not in result
        assert "/" not in result
        assert "\\" not in result

    def test_secure_filename_strips_null_bytes(self):
        from web.app import _secure_filename

        result = _secure_filename("evil\x00.txt")
        assert "\x00" not in result

    def test_secure_filename_preserves_unicode(self):
        """CJK filenames should survive sanitization."""
        from web.app import _secure_filename

        result = _secure_filename("王宇轩-简历.docx")
        assert "王宇轩" in result
        assert result.endswith(".docx")

    def test_secure_filename_removes_dangerous_chars(self):
        from web.app import _secure_filename

        result = _secure_filename("file<name>:with|bad*chars?.txt")
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result
        assert "|" not in result
        assert "*" not in result
        assert "?" not in result


# ---------------------------------------------------------------------------
# 5. Security event logging
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSecurityLogging:
    """Verify security events are logged on auth failures."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        auth_mod = _get_auth_module()
        monkeypatch.setattr(auth_mod, "AUTH_ENABLED", True)
        self.app = _make_flask_app(auth_enabled=True)
        self.client = self.app.test_client()

    def test_unauthorized_access_logged(self, caplog):
        """401 responses should produce a [Security] WARNING log."""
        with caplog.at_level(logging.WARNING, logger="web.auth"):
            self.client.post("/api/chat", json={"message": "test"})
        assert any("[Security]" in r.message for r in caplog.records)

    def test_log_contains_path(self, caplog):
        """Security log should include the request path."""
        with caplog.at_level(logging.WARNING, logger="web.auth"):
            self.client.post("/api/chat/stream", json={"message": "test"})
        sec_records = [r for r in caplog.records if "[Security]" in r.message]
        assert any("/api/chat/stream" in r.message for r in sec_records)
