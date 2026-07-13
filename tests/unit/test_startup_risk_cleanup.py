from __future__ import annotations

from flask import Flask


def test_file_generation_intent_requires_format_and_creation_verb():
    from web.services.intent.file_gen_classifier import is_explicit_file_gen_request

    assert is_explicit_file_gen_request("请生成一份 Excel 销售报表") is True
    assert is_explicit_file_gen_request("这个 PDF 怎么编辑？") is False


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


def test_editor_skill_list_uses_public_skill_manager_surface(monkeypatch):
    from app.core.skills.skill_manager import SkillManager
    from web.blueprints.editor_ai import editor_skill_list

    monkeypatch.setattr(
        SkillManager,
        "list_runtime_entries",
        classmethod(
            lambda cls: {
                "xlsx": {"id": "xlsx", "enabled": True, "file_types": ["xlsx"]},
                "disabled": {
                    "id": "disabled",
                    "enabled": False,
                    "file_types": ["xlsx"],
                },
            }
        ),
    )
    app = Flask(__name__)
    with app.test_request_context("/api/editor/ai/skill-list?file_type=xlsx"):
        data = editor_skill_list().get_json()

    assert data == {"skills": [{"id": "xlsx", "enabled": True, "file_types": ["xlsx"]}]}
