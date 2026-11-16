from __future__ import annotations

from flask import Flask


def test_response_api_exposes_existing_rating_store(monkeypatch):
    import app.api.response_routes as routes
    from app.core.learning import rating_store

    class FakeStore:
        def get_stats(self):
            return {"user_ratings": {"total": 2}}

        def user_rating_for(self, msg_id):
            return {"msg_id": msg_id, "stars": 5}

        def model_eval_for(self, msg_id):
            return {"msg_id": msg_id, "overall": 0.9}

        def combined_score(self, msg_id):
            return 0.945

    monkeypatch.setattr(rating_store, "get_rating_store", lambda: FakeStore())
    app = Flask(__name__)
    app.register_blueprint(routes.response_bp)
    client = app.test_client()

    assert client.get("/api/response/stats").get_json()["user_ratings"]["total"] == 2
    detail = client.get("/api/response/message-1").get_json()
    assert detail["combined"] == 0.945
    assert detail["user_rating"]["stars"] == 5


def test_editor_ai_has_no_legacy_skill_runtime_endpoint():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    source = (root / "web/blueprints/editor_ai.py").read_text(encoding="utf-8")
    assert "/api/editor/ai/skill-list" not in source
    assert "skill_runtime_retired" not in source
