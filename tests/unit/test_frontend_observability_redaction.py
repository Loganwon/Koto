# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

from flask import Flask


def test_frontend_observability_api_redacts_sensitive_payloads(tmp_path, monkeypatch):
    from app.api import mcp_routes
    from app.api.mcp_routes import mcp_bp
    from app.core.agent import frontend_observability

    monkeypatch.setattr(mcp_routes, "get_mcp_status", lambda: {})
    monkeypatch.setattr(
        frontend_observability,
        "_event_log_path",
        lambda: tmp_path / "frontend_observability.jsonl",
    )
    frontend_observability.clear_frontend_events()

    app = Flask(__name__)
    app.register_blueprint(mcp_bp)
    client = app.test_client()

    posted = client.post(
        "/api/mcp/frontend-event",
        json={
            "type": "input",
            "message": "login",
            "session_id": "frontend-session",
            "details": {
                "apiKey": "sk-live-secret",
                "nested": {"authorization": "Bearer abc123"},
                "safe": "visible",
            },
        },
    )
    assert posted.status_code == 200

    events = client.get("/api/mcp/frontend-events?limit=1").get_json()["events"]
    details = events[0]["details"]
    assert details["apiKey"] == "[redacted]"
    assert details["nested"]["authorization"] == "[redacted]"
    assert details["safe"] == "visible"
    assert "sk-live-secret" not in (tmp_path / "frontend_observability.jsonl").read_text(
        encoding="utf-8"
    )
