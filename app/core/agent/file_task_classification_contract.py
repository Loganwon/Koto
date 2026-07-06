# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskRequest,
)
from app.core.agent.file_task_recipes import recipe_matches
from app.core.agent.file_task_intent_predicates import (
    has_artifact_creation_intent,
    has_global_readonly_write_negation,
    has_readonly_write_negation,
    has_strong_write_intent,
)
from app.core.agent.file_task_runtime_utils import _preview


def demote_classification_to_read(
    request: FileTaskRequest,
    files: list[FileTaskFile],
    classification: FileTaskClassification,
    *,
    reason: str,
) -> FileTaskClassification:
    classification.write_intent = False
    classification.docx_annotation_request = False
    classification.output_mode = "answer"
    classification.execution_mode = "generic_tool_loop"
    classification.reason_codes.append(reason)
    if classification.task_family in {
        "annotate",
        "polish",
        "translate",
        "presentation",
        "table_transfer",
        "financial_report",
        "contract_review",
    }:
        classification.task_family = "analyze"
        classification.operation_kind = "read"
    elif str(classification.operation_kind or "").startswith("write"):
        classification.operation_kind = "read"
    return refresh_classification_recipe(request, files, classification)


def refresh_classification_recipe(
    request: FileTaskRequest,
    files: list[FileTaskFile],
    classification: FileTaskClassification,
) -> FileTaskClassification:
    recipe_candidates = recipe_matches(
        request, files, write_intent=classification.write_intent
    )
    selected_recipe_match = recipe_candidates[0] if recipe_candidates else None
    classification.recipe_candidates = [
        item.public_dict() for item in recipe_candidates[:5]
    ]
    if not selected_recipe_match:
        if classification.selected_recipe:
            classification.reason_codes.append("mainline_contract:recipe_cleared")
        classification.selected_recipe = ""
        if classification.execution_mode not in {
            "awaiting_confirmation_resume",
            "followup_contextual",
        }:
            classification.execution_mode = "generic_tool_loop"
        return classification

    classification.selected_recipe = selected_recipe_match.recipe.id
    if selected_recipe_match.recipe.execution_mode != "generic_tool_loop":
        classification.execution_mode = selected_recipe_match.recipe.execution_mode
    for capability in selected_recipe_match.recipe.matched_capabilities:
        if capability not in classification.matched_capabilities:
            classification.matched_capabilities.append(capability)
    classification.task_family = selected_recipe_match.recipe.task_family
    classification.operation_kind = (
        selected_recipe_match.recipe.write_operation_kind
        if classification.write_intent
        else selected_recipe_match.recipe.read_operation_kind
    )
    for code in selected_recipe_match.reason_codes:
        if code not in classification.reason_codes:
            classification.reason_codes.append(code)
    return classification


def apply_intent_adjudication(
    request: FileTaskRequest,
    files: list[FileTaskFile],
    classification: FileTaskClassification,
    adjudication: dict,
    *,
    readonly_write_negation: bool,
    artifact_creation_intent: bool,
    global_readonly_write_negation: bool,
    strong_write_intent: bool,
) -> FileTaskClassification:
    if not isinstance(adjudication, dict) or adjudication.get("status") != "ok":
        if isinstance(adjudication, dict) and adjudication.get("status"):
            classification.reason_codes.append(
                f"ai_intent_adjudicator:{adjudication.get('status')}"
            )
        return classification
    intent = str(adjudication.get("intent") or "").strip().lower()
    confidence = float(adjudication.get("confidence") or 0.0)
    should_write = bool(adjudication.get("should_write"))
    if confidence < 0.55:
        classification.reason_codes.append("ai_intent_adjudicator_low_confidence")
        return classification
    if readonly_write_negation:
        classification.reason_codes.append("ai_intent_adjudicator_readonly_guard")
        return classification
    if classification.diagnostic_request:
        classification.reason_codes.append("ai_intent_adjudicator_diagnostic_guard")
        return classification

    preservable_write_contract = _has_preservable_write_contract(
        classification,
        artifact_creation_intent=artifact_creation_intent,
        strong_write_intent=strong_write_intent,
    )
    output_override = ""
    write_override: bool | None = None
    if intent in {"edit_file", "create_file", "resume_stepwise"} or should_write:
        output_override = "write"
        write_override = True
    elif intent == "analyze_then_confirm":
        if preservable_write_contract and not global_readonly_write_negation:
            classification.reason_codes.append(
                "ai_intent_adjudicator_preserved_explicit_write_contract"
            )
            if artifact_creation_intent:
                classification.reason_codes.append(
                    "ai_intent_adjudicator_preserved_explicit_artifact_write"
                )
            return classification
        output_override = "hybrid"
        write_override = False
    elif intent in {"answer_only", "diagnose_failure"}:
        if preservable_write_contract and not global_readonly_write_negation:
            classification.reason_codes.append(
                "ai_intent_adjudicator_preserved_explicit_write_contract"
            )
            if artifact_creation_intent:
                classification.reason_codes.append(
                    "ai_intent_adjudicator_preserved_explicit_artifact_write"
                )
            return classification
        if not strong_write_intent:
            output_override = "answer"
            write_override = False

    if not output_override:
        classification.reason_codes.append("ai_intent_adjudicator_no_override")
        return classification

    original_output = str(classification.output_mode or "").strip().lower()
    original_write = bool(classification.write_intent)
    classification.output_mode = output_override
    if write_override is not None:
        classification.write_intent = bool(write_override)
    classification.confidence = max(float(classification.confidence or 0.0), confidence)
    classification.reason_codes.append(f"ai_intent_adjudicator:{intent}")
    if (
        original_output != classification.output_mode
        or original_write != classification.write_intent
    ):
        classification.reason_codes.append("ai_intent_adjudicator_override")

    recipe_candidates = recipe_matches(
        request, files, write_intent=classification.write_intent
    )
    selected_recipe_match = recipe_candidates[0] if recipe_candidates else None
    if selected_recipe_match:
        classification.selected_recipe = selected_recipe_match.recipe.id
        classification.recipe_candidates = [
            item.public_dict() for item in recipe_candidates[:5]
        ]
        for capability in selected_recipe_match.recipe.matched_capabilities:
            if capability not in classification.matched_capabilities:
                classification.matched_capabilities.append(capability)
        classification.task_family = selected_recipe_match.recipe.task_family
        classification.operation_kind = (
            selected_recipe_match.recipe.write_operation_kind
            if classification.write_intent
            else selected_recipe_match.recipe.read_operation_kind
        )
        for code in selected_recipe_match.reason_codes:
            if code not in classification.reason_codes:
                classification.reason_codes.append(code)
    return classification


def _has_preservable_write_contract(
    classification: FileTaskClassification,
    *,
    artifact_creation_intent: bool,
    strong_write_intent: bool,
) -> bool:
    if not classification.write_intent:
        return False
    if str(classification.selected_recipe or "").strip():
        return True
    if artifact_creation_intent or strong_write_intent:
        return True
    contract_reason_prefixes = (
        "docx_",
        "spreadsheet_",
        "ppt_",
        "text_selection_",
        "file_copy_",
        "cross_file_",
        "financial_",
        "long_",
        "stepwise_",
    )
    contract_reason_codes = {
        "write_intent",
        "ai_intent_adjudicator_override",
        "ai_intent_adjudicator:edit_file",
        "ai_intent_adjudicator:create_file",
        "ai_intent_adjudicator:resume_stepwise",
    }
    for code in classification.reason_codes:
        item = str(code or "").strip()
        if item in contract_reason_codes:
            return True
        if item.startswith(contract_reason_prefixes):
            return True
    return False


def normalize_mainline_contract(
    request: FileTaskRequest,
    files: list[FileTaskFile],
    classification: FileTaskClassification,
    *,
    explicit_output_mode: str,
    readonly_write_negation: bool,
    has_target_context: bool,
    docx_annotation_has_contract: Callable[[FileTaskClassification], bool],
    write_has_contract_anchor: Callable[[FileTaskClassification], bool],
) -> FileTaskClassification:
    classification.reason_codes.append("mainline_contract:v1")

    if readonly_write_negation:
        return demote_classification_to_read(
            request,
            files,
            classification,
            reason="mainline_contract:readonly_guard",
        )

    if classification.docx_annotation_request and not docx_annotation_has_contract(
        classification
    ):
        classification.docx_annotation_request = False
        classification.reason_codes.append("mainline_contract:docx_annotation_demoted")
        if classification.execution_mode in {
            "annotate_tool_loop",
            "doc_annotate_bridge",
        }:
            classification.execution_mode = "generic_tool_loop"

    if not classification.write_intent:
        return refresh_classification_recipe(request, files, classification)

    if write_has_contract_anchor(classification):
        return refresh_classification_recipe(request, files, classification)

    classification = demote_classification_to_read(
        request,
        files,
        classification,
        reason="mainline_contract:keyword_write_demoted",
    )
    if has_target_context and not explicit_output_mode:
        classification.output_mode = "hybrid"
        classification.reason_codes.append("mainline_contract:target_context_hybrid")
    return classification


def write_has_contract_anchor(
    classification: FileTaskClassification,
    *,
    task_text: str,
    explicit_output_mode: str,
    strong_write_intent: bool,
    docx_annotation_has_contract: bool,
    create_or_export_contract: bool,
) -> bool:
    explicit_mode = str(explicit_output_mode or "").strip().lower()
    if explicit_mode in {"write", "hybrid"}:
        return True
    if classification.request_kind == "resume":
        return True
    if "followup_apply_write_intent" in classification.reason_codes:
        return True
    contract_reason_codes = {
        "long_pdf_stepwise_docx_forced_write_intent",
        "stepwise_resume_forced_write_intent",
        "docx_clear_review_forced_write_intent",
        "docx_compare_annotate_forced_write_intent",
        "followup_apply_write_intent",
        "ai_intent_adjudicator_override",
        "ai_intent_adjudicator:edit_file",
        "ai_intent_adjudicator:create_file",
        "ai_intent_adjudicator:resume_stepwise",
    }
    if any(code in contract_reason_codes for code in classification.reason_codes):
        return True
    if str(classification.selected_recipe or "").strip() in {
        "long_pdf_stepwise_docx_summary",
        "long_docx_stepwise_polish_writeback",
    }:
        return True
    if str(classification.selected_recipe or "").strip() and classification.write_intent:
        return True
    if strong_write_intent:
        return True
    if classification.docx_annotation_request and docx_annotation_has_contract:
        return True
    if create_or_export_contract:
        return True
    return False


def has_create_or_export_contract(task: str) -> bool:
    task_text = str(task or "")
    if not task_text:
        return False
    return bool(
        re.search(
            r"(?:创建|新建|生成|产出|导出|保存为|整理成|做成|create|generate|export|save as).{0,28}(?:\.docx|\.xlsx|\.pptx|\.pdf|word|excel|ppt|文档|表格|幻灯片|报告)",
            task_text,
            re.IGNORECASE,
        )
        or re.search(
            r"(?:write|insert|add|append).{0,32}(?:into|to|in).{0,32}(?:\.docx|\.xlsx|\.pptx|\.pdf|word|excel|ppt|document|spreadsheet|slides?|report)",
            task_text,
            re.IGNORECASE,
        )
    )


def docx_annotation_has_contract(
    classification: FileTaskClassification,
    *,
    request_has_docx: bool,
    direct_docx_annotation_request: bool,
    followup_context: dict,
) -> bool:
    if not request_has_docx:
        return False
    if classification.selected_recipe in {
        "single_docx_review_bridge",
        "pdf_docx_review_bridge",
        "docx_contract_compare_review",
        "docx_compare_annotation",
    }:
        return True
    if "workflow_adapter:doc_annotate_bridge" in classification.reason_codes:
        return True
    if direct_docx_annotation_request:
        return True
    followup_action = (
        str(followup_context.get("followup_action") or "").strip().lower()
        if isinstance(followup_context, dict)
        else ""
    )
    previous_family = (
        str(followup_context.get("previous_task_family") or "").strip().lower()
        if isinstance(followup_context, dict)
        else ""
    )
    previous_execution = (
        str(
            followup_context.get("previous_task_execution_mode")
            or followup_context.get("previous_task_mode")
            or ""
        )
        .strip()
        .lower()
        if isinstance(followup_context, dict)
        else ""
    )
    if (
        followup_action == "improve"
        and (
            previous_family == "annotate"
            or previous_execution in {"annotate_tool_loop", "doc_annotate_bridge"}
        )
        and request_has_docx
    ):
        return True
    return False



@dataclass(frozen=True)
class IntentAdjudicationContractContext:
    readonly_write_negation: bool = False
    artifact_creation_intent: bool = False
    global_readonly_write_negation: bool = False
    strong_write_intent: bool = False


@dataclass(frozen=True)
class MainlineContractContext:
    explicit_output_mode: str = ""
    readonly_write_negation: bool = False
    has_target_context: bool = False
    docx_annotation_has_contract: Callable[[FileTaskClassification], bool] = (
        lambda _classification: False
    )
    write_has_contract_anchor: Callable[[FileTaskClassification], bool] = (
        lambda _classification: False
    )

def build_intent_adjudication_contract_context(
    task_text: str,
) -> IntentAdjudicationContractContext:
    text = str(task_text or "")
    return IntentAdjudicationContractContext(
        readonly_write_negation=has_readonly_write_negation(text),
        artifact_creation_intent=has_artifact_creation_intent(text),
        global_readonly_write_negation=has_global_readonly_write_negation(text),
        strong_write_intent=has_strong_write_intent(text),
    )


def build_mainline_contract_context(
    *,
    task_text: str,
    explicit_output_mode: str,
    readonly_write_negation: bool,
    has_target_context: bool,
    docx_annotation_has_contract: Callable[[FileTaskClassification], bool],
    strong_write_intent: bool,
) -> MainlineContractContext:
    text = str(task_text or "")
    docx_annotation_anchor = docx_annotation_has_contract

    def write_anchor(classification: FileTaskClassification) -> bool:
        return write_has_contract_anchor(
            classification,
            task_text=text,
            explicit_output_mode=explicit_output_mode,
            strong_write_intent=strong_write_intent,
            docx_annotation_has_contract=docx_annotation_anchor(classification),
            create_or_export_contract=has_create_or_export_contract(text),
        )

    return MainlineContractContext(
        explicit_output_mode=str(explicit_output_mode or "").strip().lower(),
        readonly_write_negation=bool(readonly_write_negation),
        has_target_context=bool(has_target_context),
        docx_annotation_has_contract=docx_annotation_anchor,
        write_has_contract_anchor=write_anchor,
    )

