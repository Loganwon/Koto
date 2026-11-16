"""Test that the opt-in Swagger surface is wired correctly."""

import pytest
from flask import Flask

from web.app_observability import configure_observability


class _NullLogger:
    def debug(self, *args, **kwargs):
        pass

    info = warning = debug


class TestApiDocs:
    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        monkeypatch.setenv("KOTO_ENABLE_API_DOCS", "1")
        app = Flask("swagger-opt-in-test")
        app.config["TESTING"] = True

        @app.get("/health")
        def health():
            """Test health endpoint.
            ---
            responses:
              200:
                description: healthy
            """
            return {"status": "ok"}

        configure_observability(
            app,
            _NullLogger(),
            "test",
            lambda: ({"error": "unauthorized"}, 401),
        )
        self.client = app.test_client()

    def test_apidocs_accessible(self):
        resp = self.client.get("/apidocs/")
        assert resp.status_code == 200

    def test_apispec_json(self):
        resp = self.client.get("/apispec.json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "info" in data
        assert data["info"]["title"] == "Koto API"

    def test_api_paths_documented(self):
        resp = self.client.get("/apispec.json")
        data = resp.get_json()
        paths = data.get("paths", {})
        # At least health endpoints should be documented
        assert len(paths) > 0
