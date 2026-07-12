from __future__ import annotations


def test_save_and_register_registers_intent_binding_once(monkeypatch, tmp_path):
    import app.core.skills.skill_recorder as recorder
    from app.core.skills.skill_schema import SkillDefinition

    registrations: list[str] = []

    class FakeSkillManager:
        @staticmethod
        def register_custom(skill_def):
            return True

    monkeypatch.setattr(recorder, "_SKILLS_DIR", str(tmp_path))
    monkeypatch.setattr(recorder, "_get_skill_manager", lambda: FakeSkillManager)
    monkeypatch.setattr(
        recorder,
        "_auto_register_intent_binding",
        lambda skill_def: registrations.append(skill_def.id),
    )

    skill = SkillDefinition(
        id="registration_once",
        name="Registration once",
        icon="🧪",
        category="domain",
        description="Regression test skill.",
    )

    assert recorder.SkillRecorder.save_and_register(skill) == skill.id
    assert registrations == [skill.id]
    assert (tmp_path / f"{skill.id}.json").is_file()
