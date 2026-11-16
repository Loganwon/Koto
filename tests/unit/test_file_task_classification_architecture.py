from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "app" / "core" / "agent"


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_file_task_classification_is_deterministic_before_kernel() -> None:
    planning = _read("app/core/agent/file_task_planning.py")
    plan_phase = _read("app/core/agent/runtime/plan_phase.py")

    assert "_adjudicate_intent_if_needed" not in planning
    assert "_call_model(" not in planning
    assert "resolve_classification_policy(" in plan_phase
    assert "_call_model(" not in plan_phase


def test_retired_ai_intent_adjudicator_stays_deleted() -> None:
    assert not (AGENT_ROOT / "file_task_intent_adjudicator.py").exists()
    planning = _read("app/core/agent/file_task_planning.py")
    projection = _read("app/core/agent/file_task_intent_adjudication.py")

    assert "file_task_intent_adjudicator" not in planning
    assert "intent_adjudicator_system_prompt" not in projection
    assert "normalize_intent_adjudication_response" not in projection


def test_classification_helpers_remain_outside_kernel() -> None:
    kernel = _read("app/core/agent/kernel/runtime.py")

    for module_name in (
        "file_task_classification_policy",
        "file_task_classification_finalizer",
    ):
        assert module_name not in kernel


def test_fragmented_classification_pipeline_stays_deleted() -> None:
    for module_name in (
        "file_task_classification_state.py",
        "file_task_classification_signals.py",
        "file_task_classification_flow.py",
        "file_task_classification_flags.py",
        "file_task_classification_write.py",
        "file_task_classification_reasons.py",
        "file_task_classification_contract.py",
    ):
        assert not (AGENT_ROOT / module_name).exists()

    phase = _read("app/core/agent/runtime/plan_phase.py")
    assert phase.count("resolve_classification_policy(") == 1
    assert "classification_signals" not in phase
    assert "override_flags" not in phase


def test_pre_kernel_planning_does_not_select_semantic_recipes() -> None:
    for relative in (
        "app/core/agent/runtime/plan_phase.py",
        "app/core/agent/file_task_intent_planner.py",
        "app/core/agent/file_task_whitebox.py",
    ):
        source = _read(relative)
        assert "select_task_recipe" not in source
        assert "recipe_matches" not in source

    assert not (AGENT_ROOT / "file_task_classification_recipes.py").exists()
    assert not (AGENT_ROOT / "file_task_classification_semantics.py").exists()
    assert not (AGENT_ROOT / "file_task_recipes.py").exists()

    production = "\n".join(
        path.read_text(encoding="utf-8")
        for path in AGENT_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    )
    assert "select_task_recipe" not in production
    assert "recipe_matches" not in production


def test_mainline_contract_is_resolved_inside_the_single_policy() -> None:
    phase = _read("app/core/agent/runtime/plan_phase.py")
    planning = _read("app/core/agent/file_task_planning.py")
    policy = _read("app/core/agent/file_task_classification_policy.py")

    assert "_normalize_mainline_contract(" not in phase
    assert "_normalize_mainline_contract(" not in planning
    assert "mainline_contract:v1" in policy
    assert "mainline_contract:keyword_write_demoted" in policy
    assert phase.count("resolve_classification_policy(") == 1
