"""Unit tests for precompiled regex patterns across the codebase.

Verifies that module-level and instance-level compiled patterns are
``re.Pattern`` objects and match (or reject) the expected inputs.
"""

from __future__ import annotations

import re

import pytest

# ---------------------------------------------------------------------------
# 1. ConsistencyChecker._compiled_patterns
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConsistencyCheckerPatterns:
    """Verify precompiled variant patterns in ConsistencyChecker.__init__."""

    @pytest.fixture()
    def checker(self):
        from web.files.consistency_checker import ConsistencyChecker

        return ConsistencyChecker()

    def test_compiled_patterns_are_re_pattern(self, checker):
        for _term, variants in checker._compiled_patterns.items():
            for variant_str, pattern in variants:
                assert isinstance(
                    pattern, re.Pattern
                ), f"Expected re.Pattern for variant '{variant_str}', got {type(pattern)}"

    @pytest.mark.parametrize(
        "term, variant_text",
        [
            ("人工智能", "AI"),
            ("人工智能", "ai"),
            ("人工智能", "A.I."),
            ("人工智能", "artificial intelligence"),
            ("机器学习", "ML"),
            ("机器学习", "machine learning"),
            ("深度学习", "DL"),
            ("深度学习", "deep learning"),
            ("自然语言处理", "NLP"),
            ("自然语言处理", "natural language processing"),
        ],
    )
    def test_patterns_match_expected_variants(self, checker, term, variant_text):
        matched = False
        for _variant_str, pattern in checker._compiled_patterns[term]:
            if pattern.search(variant_text):
                matched = True
                break
        assert matched, f"No pattern for '{term}' matched '{variant_text}'"

    def test_patterns_work_with_cjk_text(self, checker):
        text = "我们使用AI进行自然语言处理NLP研究"
        for term, variants in checker._compiled_patterns.items():
            for _variant_str, pattern in variants:
                # Should not raise; just exercise CJK mixed text
                pattern.search(text)

    def test_patterns_work_with_ascii_text(self, checker):
        text = "We use machine learning and deep learning for NLP tasks"
        matches = {}
        for term, variants in checker._compiled_patterns.items():
            for variant_str, pattern in variants:
                if pattern.search(text):
                    matches.setdefault(term, []).append(variant_str)

        assert "机器学习" in matches
        assert "深度学习" in matches
        assert "自然语言处理" in matches

    def test_patterns_are_case_insensitive(self, checker):
        for _term, variants in checker._compiled_patterns.items():
            for variant_str, pattern in variants:
                assert (
                    pattern.flags & re.IGNORECASE
                ), f"Pattern for '{variant_str}' is not case-insensitive"
