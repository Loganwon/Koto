from app.core.agent.file_task_classification_write import (
    apply_write_intent_reason_codes,
)


def test_write_intent_reason_codes_add_write_marker():
    result = apply_write_intent_reason_codes(
        write_intent=True,
        explicit_output_mode="",
        diagnostic_request=False,
        reason_codes=["followup_apply_write_intent"],
    )

    assert result.reason_codes == [
        "followup_apply_write_intent",
        "write_intent",
    ]


def test_write_intent_reason_codes_marks_answer_mode_override_for_non_diagnostic():
    result = apply_write_intent_reason_codes(
        write_intent=True,
        explicit_output_mode="answer",
        diagnostic_request=False,
        reason_codes=[],
    )

    assert result.reason_codes == [
        "write_intent",
        "answer_mode_overridden_by_write_intent",
    ]


def test_write_intent_reason_codes_does_not_override_diagnostic_answer_mode():
    result = apply_write_intent_reason_codes(
        write_intent=True,
        explicit_output_mode="answer",
        diagnostic_request=True,
        reason_codes=[],
    )

    assert result.reason_codes == ["write_intent"]


def test_write_intent_reason_codes_leave_readonly_reasons_unchanged():
    result = apply_write_intent_reason_codes(
        write_intent=False,
        explicit_output_mode="answer",
        diagnostic_request=False,
        reason_codes=["readonly_write_negation"],
    )

    assert result.reason_codes == ["readonly_write_negation"]
