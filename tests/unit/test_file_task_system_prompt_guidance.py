from app.core.agent.file_task_system_prompt_guidance import (
    build_file_task_system_prompt_guidance,
)


def test_system_prompt_guidance_keeps_followup_context_only():
    guidance = build_file_task_system_prompt_guidance(
        followup_context={"kind": "review_last_task", "followup_action": "improve"},
    )

    assert "继续优化" in guidance.followup_guidance
    assert set(guidance.__dataclass_fields__) == {"followup_guidance"}


def test_system_prompt_guidance_is_empty_without_followup():
    guidance = build_file_task_system_prompt_guidance(
        followup_context={},
    )

    assert guidance.followup_guidance == ""
