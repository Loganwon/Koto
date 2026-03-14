"""
Unit tests for auth routes in web/auth.py:
- /api/auth/login — local mode behavior
- JWT startup validation (_validate_jwt_secret)
- Request ID header on auth responses
"""

import json
import os

import pytest


@pytest.fixture(scope="module")
def local_client():
    """Flask test client with auth disabled (local mode)."""
    os.environ.setdefault("KOTO_AUTH_ENABLED", "false")
    os.environ.setdefault("KOTO_DEPLOY_MODE", "local")
    os.environ.setdefault("KOTO_JWT_SECRET", "test-secret-for-unit-tests-32chars!!")

    from web.app import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _post_login(client, payload):
    return client.post(
        "/api/auth/login",
        data=json.dumps(payload),
        content_type="application/json",
    )


# ── Local mode (auth disabled) ────────────────────────────────────────────────


class TestLoginLocalMode:
    """In local mode (AUTH_ENABLED=False) login always succeeds without credentials."""

    def test_returns_200(self, local_client):
        resp = _post_login(local_client, {"email": "anyone@x.com", "password": "pass"})
        assert resp.status_code == 200

    def test_returns_success_true(self, local_client):
        resp = _post_login(local_client, {})
        assert resp.get_json()["success"] is True

    def test_returns_local_token(self, local_client):
        resp = _post_login(local_client, {})
        assert resp.get_json().get("token") == "local"

    def test_user_id_is_local(self, local_client):
        resp = _post_login(local_client, {})
        user = resp.get_json().get("user", {})
        assert user.get("user_id") == "local"

    def test_response_has_request_id_header(self, local_client):
        resp = _post_login(local_client, {})
        assert "X-Request-ID" in resp.headers

    def test_request_id_header_is_non_empty(self, local_client):
        resp = _post_login(local_client, {})
        assert resp.headers.get("X-Request-ID")

    def test_custom_request_id_echoed(self, local_client):
        test_id = "my-custom-req-id-abc123"
        resp = local_client.post(
            "/api/auth/login",
            data=json.dumps({}),
            content_type="application/json",
            headers={"X-Request-ID": test_id},
        )
        assert resp.headers.get("X-Request-ID") == test_id


# ── JWT startup validation ────────────────────────────────────────────────────


class TestJWTStartupValidation:
    """Tests for _validate_jwt_secret() — validates the secret at startup."""

    def _save_restore(self):
        """Context manager helper — save/restore env vars."""
        return {
            "KOTO_JWT_SECRET": os.environ.get("KOTO_JWT_SECRET"),
            "KOTO_DEPLOY_MODE": os.environ.get("KOTO_DEPLOY_MODE"),
        }

    def _restore_env(self, saved):
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_cloud_mode_with_empty_secret_raises(self):
        """Cloud mode with no JWT secret must raise RuntimeError."""
        import web.auth as auth_mod

        saved = self._save_restore()
        try:
            os.environ["KOTO_DEPLOY_MODE"] = "cloud"
            os.environ.pop("KOTO_JWT_SECRET", None)
            with pytest.raises(RuntimeError, match="KOTO_JWT_SECRET"):
                auth_mod._validate_jwt_secret()
        finally:
            self._restore_env(saved)

    def test_local_mode_with_empty_secret_does_not_raise(self):
        """Local mode without JWT secret logs a warning but does not raise."""
        import web.auth as auth_mod

        saved = self._save_restore()
        try:
            os.environ["KOTO_DEPLOY_MODE"] = "local"
            os.environ.pop("KOTO_JWT_SECRET", None)
            result = auth_mod._validate_jwt_secret()
            assert len(result) > 0
        finally:
            self._restore_env(saved)

    def test_with_secret_set_returns_it(self):
        """When KOTO_JWT_SECRET is set, _validate_jwt_secret returns it."""
        import web.auth as auth_mod

        saved = self._save_restore()
        try:
            os.environ["KOTO_JWT_SECRET"] = "my-test-secret-value"
            result = auth_mod._validate_jwt_secret()
            assert result == "my-test-secret-value"
        finally:
            self._restore_env(saved)

    def test_cloud_error_message_includes_generation_hint(self):
        """Error message should include how to generate a secret."""
        import web.auth as auth_mod

        saved = self._save_restore()
        try:
            os.environ["KOTO_DEPLOY_MODE"] = "cloud"
            os.environ.pop("KOTO_JWT_SECRET", None)
            with pytest.raises(RuntimeError) as exc_info:
                auth_mod._validate_jwt_secret()
            msg = str(exc_info.value).lower()
            assert "secrets" in msg or "generate" in msg
        finally:
            self._restore_env(saved)
