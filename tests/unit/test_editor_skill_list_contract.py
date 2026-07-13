from __future__ import annotations

from flask import Flask


def test_runtime_entry_keeps_definition_tags_for_editor_filtering():
    from app.core.skills.skill_manager import SkillManager
    from app.core.skills.skill_schema import SkillDefinition

    entry = SkillManager._runtime_entry_from_definition(
        SkillDefinition(
            id="excel_helper",
            name="Excel helper",
            icon="📊",
            category="domain",
            description="Uses spreadsheet skills.",
            tags=["excel", "xlsx"],
        )
    )

    assert entry["tags"] == ["excel", "xlsx"]


def _client():
    from web.blueprints.editor_ai import editor_ai_bp

    app = Flask(__name__)
    app.register_blueprint(editor_ai_bp)
    return app.test_client()


def test_skill_list_returns_all_enabled_runtime_entries(monkeypatch):
    from app.core.skills.skill_manager import SkillManager

    monkeypatch.setattr(
        SkillManager,
        "list_runtime_entries",
        classmethod(
            lambda cls: {
                "xlsx": {"id": "xlsx", "enabled": True, "file_types": ["xlsx"]},
                "docx": {"id": "docx", "file_types": ["docx"]},
                "disabled": {
                    "id": "disabled",
                    "enabled": False,
                    "file_types": ["xlsx"],
                },
            }
        ),
    )

    response = _client().get("/api/editor/ai/skill-list")

    assert response.status_code == 200
    assert response.get_json() == {
        "skills": [
            {"id": "xlsx", "enabled": True, "file_types": ["xlsx"]},
            {"id": "docx", "file_types": ["docx"]},
        ]
    }


def test_skill_list_filters_enabled_runtime_entries_by_file_type(monkeypatch):
    from app.core.skills.skill_manager import SkillManager

    monkeypatch.setattr(
        SkillManager,
        "list_runtime_entries",
        classmethod(
            lambda cls: {
                "xlsx": {"id": "xlsx", "enabled": True, "file_types": ["xlsx"]},
                "tagged": {"id": "tagged", "enabled": True, "tags": ["xlsx"]},
                "docx": {"id": "docx", "enabled": True, "file_types": ["docx"]},
                "disabled": {
                    "id": "disabled",
                    "enabled": False,
                    "file_types": ["xlsx"],
                },
            }
        ),
    )

    response = _client().get("/api/editor/ai/skill-list?file_type=xlsx")

    assert response.status_code == 200
    assert response.get_json() == {
        "skills": [
            {"id": "xlsx", "enabled": True, "file_types": ["xlsx"]},
            {"id": "tagged", "enabled": True, "tags": ["xlsx"]},
        ]
    }


def test_skill_list_reports_runtime_read_failures(monkeypatch):
    from app.core.skills.skill_manager import SkillManager

    def fail(cls):
        raise RuntimeError("runtime registry unavailable")

    monkeypatch.setattr(SkillManager, "list_runtime_entries", classmethod(fail))

    response = _client().get("/api/editor/ai/skill-list?file_type=xlsx")

    assert response.status_code == 500
    assert response.get_json() == {
        "error": "skill_list_unavailable",
        "message": "技能列表加载失败：RuntimeError: runtime registry unavailable",
    }
