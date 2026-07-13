from web.document_feedback_rules import append_pattern_annotations


def test_rule_executor_applies_length_limit_and_suggestion() -> None:
    annotations = []
    append_pattern_annotations(
        annotations,
        "prefix target suffix",
        [(r"target", lambda _match, text: {"原文片段": text, "修改建议": "替换"})],
        min_length=2,
        max_length=10,
    )

    assert annotations == [{"原文片段": "target", "修改建议": "替换"}]


def test_rule_executor_ignores_oversized_match_after_truncation_policy() -> None:
    annotations = []
    append_pattern_annotations(
        annotations,
        "abcdefghijklmnop",
        [(r"[a-z]+", lambda _match, text: {"原文片段": text})],
        min_length=3,
        max_length=5,
    )

    assert annotations == []
