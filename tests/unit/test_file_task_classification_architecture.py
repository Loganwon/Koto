# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _body_between(source: str, start_marker: str, end_marker: str) -> str:
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


def _classification_facade() -> str:
    return _read("app/core/agent/file_task_classification/__init__.py")


def test_file_task_classification_runtime_uses_package_surface() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    facade = _classification_facade()

    assert "from app.core.agent.file_task_classification import" in runtime
    assert "from app.core.agent.file_task_classification_flags import" not in runtime
    assert (
        "from app.core.agent.file_task_classification_finalizer import" not in runtime
    )
    assert "from app.core.agent.file_task_classification_followup import" not in runtime
    assert "from app.core.agent.file_task_classification_recipes import" not in runtime
    assert "from app.core.agent.file_task_classification_reasons import" not in runtime
    assert "from app.core.agent.file_task_classification_state import" not in runtime
    assert "from app.core.agent.file_task_classification_write import" not in runtime
    assert "from app.core.agent.file_task_decision_context import" not in runtime
    assert "from app.core.agent.file_task_intent_adjudication import" not in runtime
    assert "from app.core.agent.file_task_intent_adjudicator import" not in runtime
    assert "file_task_classification_flags import" in facade
    assert "file_task_classification_finalizer import" in facade
    assert "file_task_classification_state import" in facade
    assert "file_task_decision_context import" in facade
    assert "file_task_intent_adjudication import" in facade
    assert "file_task_intent_adjudicator import" in facade


def test_file_task_decision_context_is_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/file_task_decision_context.py")
    facade = _classification_facade()

    assert "from app.core.agent.file_task_classification import" in runtime
    assert "from app.core.agent.file_task_decision_context import" in facade
    assert "FileTaskDecisionContext(" not in runtime
    assert "FileTaskRoutingDecision.from_mapping" not in runtime
    assert "def build_decision_context_payload(" in helper
    assert "def routing_decision_payload(" in helper
    assert "def trusted_file_task_routing_decision(" in helper
    assert "FileTaskDecisionContext(" in helper
    assert "FileTaskRoutingDecision.from_mapping" in helper


def test_file_task_intent_adjudicator_orchestration_is_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/file_task_intent_adjudicator.py")
    facade = _classification_facade()

    assert "from app.core.agent.file_task_classification import" in runtime
    assert "from app.core.agent.file_task_intent_adjudicator import" in facade
    assert "TaskClassifier" not in runtime
    assert "_intent_adjudication_normalize_response" not in runtime
    assert "def adjudicate_intent_if_needed(" in helper
    assert "def should_adjudicate_trusted_route(" in helper
    assert "TaskClassifier.classify" in helper
    assert "normalize_intent_adjudication_response" in helper


def test_file_task_intent_adjudication_contract_context_is_extracted_from_runtime() -> (
    None
):
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/file_task_classification_contract.py")
    facade = _classification_facade()
    body = _body_between(
        runtime,
        "    def _apply_intent_adjudication(",
        "    def _normalize_mainline_contract(",
    )

    assert "from app.core.agent.file_task_classification_contract import" in facade
    assert "from app.core.agent.file_task_classification import" in runtime
    assert "build_intent_adjudication_contract_context(" in body
    assert "_has_readonly_write_negation(" not in body
    assert "_has_artifact_creation_intent(" not in body
    assert "_has_global_readonly_write_negation(" not in body
    assert "_has_strong_write_intent(" not in body
    assert "class IntentAdjudicationContractContext" in helper
    assert "def build_intent_adjudication_contract_context(" in helper
    assert "has_readonly_write_negation(" in helper
    assert "has_artifact_creation_intent(" in helper


def test_file_task_mainline_contract_context_is_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/file_task_classification_contract.py")
    body = _body_between(
        runtime,
        "    def _normalize_mainline_contract(",
        "    def _demote_classification_to_read(",
    )

    assert "build_mainline_contract_context(" in body
    assert "docx_annotation_has_contract=lambda" not in body
    assert "write_has_contract_anchor=lambda" not in body
    assert "docx_annotation_contract_for_request(" not in helper
    assert "def _write_has_contract_anchor(" not in runtime
    assert "def _has_create_or_export_contract(" not in runtime
    assert "class MainlineContractContext" in helper
    assert "def build_mainline_contract_context(" in helper
    assert "docx_annotation_has_contract: Callable" in helper
    assert "docx_annotation_anchor = docx_annotation_has_contract" in helper
    assert "docx_annotation_has_contract as" not in helper
    assert "write_has_contract_anchor(" in helper


def test_file_task_classification_flow_is_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/file_task_classification_flow.py")
    state_helper = _read("app/core/agent/file_task_classification_state.py")

    assert "from app.core.agent.file_task_classification_flow import" not in runtime
    assert "build_classification_flow(" not in runtime
    assert "from app.core.agent.file_task_classification_flow import" in state_helper
    assert "build_classification_flow(" in state_helper
    assert "class FileTaskClassificationFlow" in helper
    assert "def build_classification_flow(" in helper
    assert "workflow_checkpoint_resume" in helper
    assert "followup_action:" in helper
    assert "stepwise_resume_forced_write_intent" in helper


def test_file_task_classification_signals_are_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/file_task_classification_signals.py")
    state_helper = _read("app/core/agent/file_task_classification_state.py")
    classify_body = _body_between(
        runtime,
        "    def _classify_request(",
        "    def _effective_planner_classification(",
    )

    assert "from app.core.agent.file_task_classification_signals import" not in runtime
    assert "build_classification_signals(" not in classify_body
    assert "from app.core.agent.file_task_classification_signals import" in state_helper
    assert "build_classification_signals(" in state_helper
    assert "matched_native_capability_names(" not in classify_body
    assert "semantic_markers(" not in classify_body
    assert "request_file_types(" not in classify_body
    assert "request_target_file_type(" not in classify_body
    assert "def build_classification_signals(" in helper
    assert "matched_native_capability_names(" in helper
    assert "semantic_markers(" in helper
    assert "request_file_types(" in helper
    assert "request_target_file_type(" in helper


def test_file_task_classification_pipeline_state_builds_signals_and_flow() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/file_task_classification_state.py")
    facade = _classification_facade()
    classify_body = _body_between(
        runtime,
        "    def _classify_request(",
        "    def _effective_planner_classification(",
    )

    assert "from app.core.agent.file_task_classification_state import" in facade
    assert "from app.core.agent.file_task_classification import" in runtime
    assert "build_classification_pipeline_state(" in runtime
    assert "build_classification_signals(" not in classify_body
    assert "build_classification_flow(" not in classify_body
    assert "class FileTaskClassificationPipelineState" in helper
    assert "def build_classification_pipeline_state(" in helper
    assert "build_classification_signals(" in helper
    assert "build_classification_flow(" in helper


def test_file_task_classification_flags_are_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/file_task_classification_flags.py")
    facade = _classification_facade()

    assert "from app.core.agent.file_task_classification_flags import" in facade
    assert "from app.core.agent.file_task_classification import" in runtime
    assert "apply_classification_intent_overrides(" in runtime
    assert "def apply_classification_intent_overrides(" in helper
    assert "diagnostic_overrode_write_intent" in helper
    assert "readonly_overrode_write_intent" in helper
    assert "answer_mode_overrode_write_intent" in helper


def test_file_task_followup_annotation_overrides_are_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/file_task_classification_followup.py")
    facade = _classification_facade()

    assert "from app.core.agent.file_task_classification_followup import" in facade
    assert "from app.core.agent.file_task_classification import" in runtime
    assert "apply_followup_annotation_overrides(" in runtime
    assert "followup_previous_task_family:annotate" not in runtime
    assert "followup_apply_write_intent" not in runtime
    assert "docx_annotation_forced_write_intent" not in runtime
    assert "def apply_followup_annotation_overrides(" in helper
    assert "followup_previous_task_family:annotate" in helper
    assert "followup_apply_write_intent" in helper
    assert "docx_annotation_forced_write_intent" in helper


def test_file_task_write_intent_reasons_are_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/file_task_classification_write.py")
    facade = _classification_facade()
    classify_body = _body_between(
        runtime,
        "    def _classify_request(",
        "    def _effective_planner_classification(",
    )

    assert "from app.core.agent.file_task_classification_write import" in facade
    assert "from app.core.agent.file_task_classification import" in runtime
    assert "apply_write_intent_reason_codes(" in runtime
    assert '"write_intent"' not in classify_body
    assert "answer_mode_overridden_by_write_intent" not in classify_body
    assert "def apply_write_intent_reason_codes(" in helper
    assert '"write_intent"' in helper
    assert "answer_mode_overridden_by_write_intent" in helper


def test_file_task_classification_recipes_are_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/file_task_classification_recipes.py")
    facade = _classification_facade()

    assert "from app.core.agent.file_task_classification_recipes import" in facade
    assert "from app.core.agent.file_task_classification import" in runtime
    assert "apply_recipe_classification(" in runtime
    assert "recipe_matches(" not in runtime
    assert "recipe_match_request =" not in runtime
    assert "def apply_recipe_classification(" in helper
    assert "def recipe_request_for_classification(" in helper
    assert "分步 长PDF DOCX 总结" in helper
    assert "recipe_matches(" in helper


def test_file_task_classification_reasons_are_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/file_task_classification_reasons.py")
    facade = _classification_facade()

    assert "from app.core.agent.file_task_classification_reasons import" in facade
    assert "from app.core.agent.file_task_classification import" in runtime
    assert "build_classification_reason_codes(" in runtime
    assert "planner_deferred:model_first" not in runtime
    assert "native_tool_gap:" not in runtime
    assert "capability:{name}" not in runtime
    assert "semantic_reason_codes(" not in runtime
    assert "def build_classification_reason_codes(" in helper
    assert "planner_deferred:model_first" in helper
    assert "native_tool_gap:" in helper
    assert "capability:{name}" in helper
    assert "semantic_reason_codes(" in helper


def test_file_task_classification_finalizer_is_extracted_from_runtime() -> None:
    runtime = _read("app/core/agent/file_task_runtime.py")
    helper = _read("app/core/agent/file_task_classification_finalizer.py")
    facade = _classification_facade()

    assert "from app.core.agent.file_task_classification_finalizer import" in facade
    assert "from app.core.agent.file_task_classification import" in runtime
    assert "build_final_classification(" in runtime
    assert "return FileTaskClassification(" not in runtime
    assert "classification_target_file_type(" not in runtime
    assert "classification_confidence(" not in runtime
    assert "def build_final_classification(" in helper
    assert "def classification_target_file_type(" in helper
    assert "def classification_confidence(" in helper
    assert "return FileTaskClassification(" in helper
