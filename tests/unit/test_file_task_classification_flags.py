from app.core.agent.file_task_classification_flags import (
    apply_classification_intent_overrides,
)


def test_classification_flags_force_stepwise_pdf_docx_write():
    flags = apply_classification_intent_overrides(
        request_kind="new_task",
        followup_action="",
        summary_request=False,
        docx_report_request=False,
        write_intent=False,
        raw_write_intent=False,
        diagnostic_request=False,
        readonly_write_negation=False,
        clear_docx_review_request=False,
        docx_compare_annotate_request=False,
        docx_annotation_request=False,
        raw_docx_annotation_request=False,
        explicit_output_mode="",
        artifact_creation_intent=False,
        explicit_write_intent=False,
        strong_write_intent=False,
        force_long_pdf_docx_write=False,
        stepwise_pdf_docx_resume=True,
        reason_codes=[],
    )

    assert flags.summary_request is True
    assert flags.docx_report_request is True
    assert flags.write_intent is True
    assert flags.raw_write_intent is True


def test_classification_flags_followup_question_without_artifact_becomes_diagnostic():
    flags = apply_classification_intent_overrides(
        request_kind="followup",
        followup_action="question",
        summary_request=False,
        docx_report_request=False,
        write_intent=True,
        raw_write_intent=False,
        diagnostic_request=False,
        readonly_write_negation=False,
        clear_docx_review_request=False,
        docx_compare_annotate_request=False,
        docx_annotation_request=True,
        raw_docx_annotation_request=True,
        explicit_output_mode="",
        artifact_creation_intent=False,
        explicit_write_intent=False,
        strong_write_intent=False,
        force_long_pdf_docx_write=False,
        stepwise_pdf_docx_resume=False,
        reason_codes=[],
    )

    assert flags.diagnostic_request is True
    assert flags.write_intent is False
    assert flags.docx_annotation_request is False
    assert "followup_question" in flags.reason_codes
    assert "diagnostic_overrode_write_intent" in flags.reason_codes
    assert "diagnostic_overrode_docx_annotation" in flags.reason_codes


def test_classification_flags_readonly_negation_blocks_write_and_annotation():
    flags = apply_classification_intent_overrides(
        request_kind="new_task",
        followup_action="",
        summary_request=False,
        docx_report_request=False,
        write_intent=True,
        raw_write_intent=True,
        diagnostic_request=False,
        readonly_write_negation=True,
        clear_docx_review_request=False,
        docx_compare_annotate_request=False,
        docx_annotation_request=True,
        raw_docx_annotation_request=True,
        explicit_output_mode="",
        artifact_creation_intent=False,
        explicit_write_intent=True,
        strong_write_intent=True,
        force_long_pdf_docx_write=False,
        stepwise_pdf_docx_resume=False,
        reason_codes=[],
    )

    assert flags.write_intent is False
    assert flags.docx_annotation_request is False
    assert "readonly_write_negation" in flags.reason_codes
    assert "readonly_overrode_write_intent" in flags.reason_codes
    assert "readonly_overrode_docx_annotation" in flags.reason_codes


def test_classification_flags_answer_mode_only_demotes_soft_write():
    soft = apply_classification_intent_overrides(
        request_kind="new_task",
        followup_action="",
        summary_request=False,
        docx_report_request=False,
        write_intent=True,
        raw_write_intent=True,
        diagnostic_request=False,
        readonly_write_negation=False,
        clear_docx_review_request=False,
        docx_compare_annotate_request=False,
        docx_annotation_request=False,
        raw_docx_annotation_request=False,
        explicit_output_mode="answer",
        artifact_creation_intent=False,
        explicit_write_intent=True,
        strong_write_intent=False,
        force_long_pdf_docx_write=False,
        stepwise_pdf_docx_resume=False,
        reason_codes=[],
    )
    strong = apply_classification_intent_overrides(
        request_kind="new_task",
        followup_action="",
        summary_request=False,
        docx_report_request=False,
        write_intent=True,
        raw_write_intent=True,
        diagnostic_request=False,
        readonly_write_negation=False,
        clear_docx_review_request=False,
        docx_compare_annotate_request=False,
        docx_annotation_request=False,
        raw_docx_annotation_request=False,
        explicit_output_mode="answer",
        artifact_creation_intent=False,
        explicit_write_intent=True,
        strong_write_intent=True,
        force_long_pdf_docx_write=False,
        stepwise_pdf_docx_resume=False,
        reason_codes=[],
    )

    assert soft.write_intent is False
    assert "answer_mode_overrode_write_intent" in soft.reason_codes
    assert strong.write_intent is True
    assert "answer_mode_overrode_write_intent" not in strong.reason_codes
