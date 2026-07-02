from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.core.agent.file_task_classification_contract import (
    has_create_or_export_contract,
    write_has_contract_anchor,
)
from app.core.agent.file_task_contract import FileTaskClassification
from app.core.agent.file_task_intent_predicates import (
    has_artifact_creation_intent,
    has_global_readonly_write_negation,
    has_readonly_write_negation,
    has_strong_write_intent,
)


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
