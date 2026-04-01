# -*- coding: utf-8 -*-
"""
Unit tests for PR #62 fixes:
  1. /editor page route serves univer-dist/index.html
  2. /editor/assets/<filename> serves static bundles
  3. editor_docs_bp is registered in _web_bp_configs
  4. socket_handler imports cleanly and registers /doc namespace events
"""

from __future__ import annotations

import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# ── Stub heavy optional deps so this file loads without a full runtime ────────


def _stub(name: str) -> MagicMock:
    if name not in sys.modules:
        sys.modules[name] = MagicMock()
    return sys.modules[name]


for _m in [
    "vosk",
    "pynput",
    "pynput.keyboard",
    "pynput.mouse",
    "pyaudio",
    "sounddevice",
    "cv2",
    "pdfplumber",
    "PIL",
    "PIL.Image",
    "flask_sock",
    "sentence_transformers",
]:
    _stub(_m)

os.environ.setdefault("KOTO_AUTH_ENABLED", "false")
os.environ.setdefault("KOTO_DEPLOY_MODE", "local")
os.environ.pop("SENTRY_DSN", None)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def pages_client(tmp_path_factory):
    """Minimal Flask app with pages_bp registered — no monolith import needed."""
    import importlib

    from flask import Flask

    app = Flask(
        __name__,
        template_folder=str(
            (
                __import__("pathlib").Path(__file__).resolve().parents[2]
                / "web"
                / "templates"
            )
        ),
        static_folder=str(
            (
                __import__("pathlib").Path(__file__).resolve().parents[2]
                / "web"
                / "static"
            )
        ),
    )
    app.config["TESTING"] = True

    from web.blueprints.pages import pages_bp

    app.register_blueprint(pages_bp)
    with app.test_client() as c:
        yield c


# ─────────────────────────────────────────────────────────────────────────────
# 1. /editor  page route
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestEditorPageRoute:
    def test_editor_returns_200(self, pages_client):
        resp = pages_client.get("/editor")
        assert resp.status_code == 200, resp.get_data(as_text=True)[:300]

    def test_editor_content_type_html(self, pages_client):
        resp = pages_client.get("/editor")
        assert "text/html" in resp.content_type

    def test_editor_contains_univer_container(self, pages_client):
        body = pages_client.get("/editor").get_data(as_text=True)
        assert "univer-container" in body or "file-assistant-root" in body

    def test_editor_loads_socket_io(self, pages_client):
        body = pages_client.get("/editor").get_data(as_text=True)
        assert "socket.io" in body.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 2. /editor/assets/<filename>  static assets route
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestEditorAssetsRoute:
    def test_existing_asset_returns_200(self, pages_client):
        resp = pages_client.get("/editor/assets/koto-patch.js")
        assert resp.status_code == 200, resp.get_data(as_text=True)[:200]

    def test_existing_css_asset_returns_200(self, pages_client):
        resp = pages_client.get("/editor/assets/main.css")
        assert resp.status_code == 200

    def test_nonexistent_asset_returns_404(self, pages_client):
        resp = pages_client.get("/editor/assets/does_not_exist_xyz.js")
        assert resp.status_code == 404

    def test_asset_content_type_js(self, pages_client):
        resp = pages_client.get("/editor/assets/koto-patch.js")
        assert "javascript" in resp.content_type or "text" in resp.content_type


# ─────────────────────────────────────────────────────────────────────────────
# 3. editor_docs_bp is present in the blueprint config list in web/app.py
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestEditorDocsBpRegistration:
    def test_editor_docs_in_web_bp_configs(self):
        """editor_docs_bp must appear in _web_bp_configs so it gets registered."""
        import ast
        from pathlib import Path

        app_py = Path(__file__).resolve().parents[2] / "web" / "app.py"
        src = app_py.read_text(encoding="utf-8")
        assert (
            "editor_docs_bp" in src
        ), "editor_docs_bp not found in web/app.py — blueprint was not registered"
        assert (
            "web.blueprints.editor_docs" in src
        ), "web.blueprints.editor_docs module not referenced in web/app.py"

    def test_editor_docs_bp_importable(self):
        from web.blueprints.editor_docs import editor_docs_bp

        assert editor_docs_bp is not None
        assert editor_docs_bp.name == "editor_docs"

    def test_editor_docs_bp_has_expected_routes(self):
        from flask import Flask

        from web.blueprints.editor_docs import editor_docs_bp

        app = Flask(__name__)
        app.register_blueprint(editor_docs_bp)
        rules = {r.rule for r in app.url_map.iter_rules()}
        assert "/api/editor/docs" in rules
        assert "/api/editor/docs/<doc_id>" in rules
        assert "/api/editor/docs/import" in rules


# ─────────────────────────────────────────────────────────────────────────────
# 4. socket_handler  — imports cleanly and registers /doc namespace events
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSocketHandler:
    def test_socket_handler_importable(self):
        from app.core.socket_handler import register_socket_events

        assert callable(register_socket_events)

    def test_register_socket_events_calls_socketio_on(self):
        """register_socket_events must register at least connect/disconnect/client_request."""
        from app.core.socket_handler import register_socket_events

        recorded: list[tuple] = []

        class _FakeSocketIO:
            def on(self, event, namespace=None):
                def decorator(fn):
                    recorded.append((event, namespace))
                    return fn

                return decorator

        register_socket_events(_FakeSocketIO())

        events = {(e, ns) for e, ns in recorded}
        assert ("connect", "/doc") in events
        assert ("disconnect", "/doc") in events
        assert ("client_request", "/doc") in events

    def test_doc_ai_request_event_registered(self):
        from app.core.socket_handler import register_socket_events

        recorded: list[tuple] = []

        class _FakeSocketIO:
            def on(self, event, namespace=None):
                def decorator(fn):
                    recorded.append((event, namespace))
                    return fn

                return decorator

        register_socket_events(_FakeSocketIO())
        events = {e for e, _ in recorded}
        assert "doc_ai_request" in events

    def test_prompts_dict_has_required_keys(self):
        from app.core.socket_handler import PROMPTS

        for key in (
            "polish",
            "translate",
            "summarize",
            "continue_writing",
            "rewrite",
            "annotate",
        ):
            assert key in PROMPTS, f"Missing prompt key: {key}"
