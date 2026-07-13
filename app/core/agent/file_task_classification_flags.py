from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FileTaskClassificationFlags:
    summary_request: bool = False
    docx_report_request: bool = False
    write_intent: bool = False
    raw_write_intent: bool = False
    diagnostic_request: bool = False
    docx_annotation_request: bool = False
    raw_docx_annotation_request: bool = False
    reason_codes: list[str] = field(default_factory=list)


def apply_classification_intent_overrides(
    *,
    request_kind: str,
    followup_action: str,
    summary_request: bool,
    docx_report_request: bool,
    write_intent: bool,
    raw_write_intent: bool,
    diagnostic_request: bool,
    readonly_write_negation: bool,
    clear_docx_review_request: bool,
    docx_compare_annotate_request: bool,
    docx_annotation_request: bool,
    raw_docx_annotation_request: bool,
    explicit_output_mode: str,
    artifact_creation_intent: bool,
    explicit_write_intent: bool,
    strong_write_intent: bool,
    force_long_pdf_docx_write: bool,
    stepwise_pdf_docx_resume: bool,
    reason_codes: list[str],
) -> FileTaskClassificationFlags:
    reasons = list(reason_codes or [])

    if force_long_pdf_docx_write or stepwise_pdf_docx_resume:
        summary_request = True
        docx_report_request = True
        write_intent = True
        raw_write_intent = True

    followup_question_is_new_artifact = (
        request_kind == "followup"
        and followup_action == "question"
        and (artifact_creation_intent or explicit_write_intent or raw_write_intent)
    )
    if (
        request_kind == "followup"
        and followup_action == "question"
        and not followup_question_is_new_artifact
    ):
        diagnostic_request = True
        reasons.append("followup_question")
    elif followup_question_is_new_artifact:
        reasons.append("followup_question_new_artifact")

    if clear_docx_review_request:
        reasons.append("docx_clear_review_request")
        if not write_intent:
            write_intent = True
            reasons.append("docx_clear_review_forced_write_intent")

    if docx_compare_annotate_request:
        reasons.append("docx_compare_annotate_request")
        if not write_intent:
            write_intent = True
            reasons.append("docx_compare_annotate_forced_write_intent")

    if diagnostic_request:
        reasons.append("diagnostic_request")
        diagnostic_write_signal = (
            write_intent
            or raw_write_intent
            or clear_docx_review_request
            or docx_compare_annotate_request
            or explicit_write_intent
            or strong_write_intent
        )
        if write_intent or raw_write_intent:
            write_intent = False
        if diagnostic_write_signal:
            reasons.append("diagnostic_overrode_write_intent")
        if docx_annotation_request or raw_docx_annotation_request:
            docx_annotation_request = False
            reasons.append("diagnostic_overrode_docx_annotation")

    if readonly_write_negation:
        reasons.append("readonly_write_negation")
        if write_intent or raw_write_intent:
            write_intent = False
            reasons.append("readonly_overrode_write_intent")
        if docx_annotation_request or raw_docx_annotation_request:
            docx_annotation_request = False
            reasons.append("readonly_overrode_docx_annotation")

    if explicit_output_mode == "answer" and not diagnostic_request:
        if (write_intent or raw_write_intent) and not strong_write_intent:
            write_intent = False
            reasons.append("answer_mode_overrode_write_intent")
        if docx_annotation_request or raw_docx_annotation_request:
            docx_annotation_request = False
            reasons.append("answer_mode_overrode_docx_annotation")

    return FileTaskClassificationFlags(
        summary_request=bool(summary_request),
        docx_report_request=bool(docx_report_request),
        write_intent=bool(write_intent),
        raw_write_intent=bool(raw_write_intent),
        diagnostic_request=bool(diagnostic_request),
        docx_annotation_request=bool(docx_annotation_request),
        raw_docx_annotation_request=bool(raw_docx_annotation_request),
        reason_codes=reasons,
    )
