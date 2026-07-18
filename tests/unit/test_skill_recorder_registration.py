from __future__ import annotations

import json


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


def test_llm_analysis_uses_core_provider_boundary(monkeypatch):
    import app.core.llm.model_selection as model_selection
    import app.core.llm.provider_factory as provider_factory
    import app.core.skills.skill_recorder as recorder

    captured = {}

    class FakeProvider:
        def generate_content(self, **kwargs):
            captured.update(kwargs)
            return {
                "content": json.dumps(
                    {
                        "system_prompt": "你是一个结构化助手",
                        "intent_description": "将需求转换为清晰步骤",
                    },
                    ensure_ascii=False,
                )
            }

    monkeypatch.setattr(
        model_selection,
        "get_configured_cloud_model",
        lambda **kwargs: "deepseek-chat",
    )
    monkeypatch.setattr(
        provider_factory,
        "get_llm_provider",
        lambda **kwargs: FakeProvider(),
    )

    result = recorder.SkillRecorder._analyze_with_llm(
        "结构化助手",
        "把复杂任务拆成步骤",
        [{"role": "user", "text": "请帮我整理这个任务"}],
    )

    assert result is not None
    assert result["system_prompt"] == "你是一个结构化助手"
    assert captured["model"] == "deepseek-chat"
    assert captured["stream"] is False
    assert captured["response_format"] == {"type": "json_object"}


def test_llm_analysis_falls_back_when_cloud_provider_is_unavailable(monkeypatch):
    import app.core.llm.model_selection as model_selection
    import app.core.llm.provider_factory as provider_factory
    import app.core.skills.skill_recorder as recorder

    monkeypatch.setattr(
        model_selection,
        "get_configured_cloud_model",
        lambda **kwargs: "deepseek-chat",
    )

    def unavailable_provider(**kwargs):
        raise RuntimeError("cloud unavailable")

    monkeypatch.setattr(
        provider_factory,
        "get_llm_provider",
        unavailable_provider,
    )

    assert (
        recorder.SkillRecorder._analyze_with_llm(
            "结构化助手",
            "把复杂任务拆成步骤",
            [{"role": "user", "text": "请帮我整理这个任务"}],
        )
        is None
    )
