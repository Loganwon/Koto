"""Unit tests for SkillAutoBuilder additions.

Covers:
- _DOMAIN_TO_TASK_TYPES is a dict with required domain keys
- Each value is a non-empty list of strings
- _infer_task_types("coding")  → contains "CODER"
- _infer_task_types("writing") → contains "FILE_GEN"
- _infer_task_types("unknown") → defaults to ["CHAT"]
- StyleProfile round-trip: to_dict() → from_dict() produces an equivalent object
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# _DOMAIN_TO_TASK_TYPES structure
# ---------------------------------------------------------------------------


REQUIRED_DOMAINS = {"coding", "writing", "research", "finance", "legal"}


class TestDomainToTaskTypes:
    def test_is_dict(self):
        from app.core.skills.skill_auto_builder import _DOMAIN_TO_TASK_TYPES

        assert isinstance(_DOMAIN_TO_TASK_TYPES, dict)

    @pytest.mark.parametrize("domain", sorted(REQUIRED_DOMAINS))
    def test_required_domain_present(self, domain):
        from app.core.skills.skill_auto_builder import _DOMAIN_TO_TASK_TYPES

        assert (
            domain in _DOMAIN_TO_TASK_TYPES
        ), f"domain '{domain}' missing from _DOMAIN_TO_TASK_TYPES"

    @pytest.mark.parametrize("domain", sorted(REQUIRED_DOMAINS))
    def test_value_is_nonempty_list_of_strings(self, domain):
        from app.core.skills.skill_auto_builder import _DOMAIN_TO_TASK_TYPES

        value = _DOMAIN_TO_TASK_TYPES[domain]
        assert isinstance(value, list), f"value for '{domain}' must be a list"
        assert len(value) > 0, f"value for '{domain}' must not be empty"
        for item in value:
            assert isinstance(item, str), f"all items for '{domain}' must be strings"


# ---------------------------------------------------------------------------
# _infer_task_types
# ---------------------------------------------------------------------------


class TestInferTaskTypes:
    def test_coding_contains_coder(self):
        from app.core.skills.skill_auto_builder import _infer_task_types

        result = _infer_task_types("coding")
        assert isinstance(result, list)
        assert "CODER" in result

    def test_writing_contains_file_gen(self):
        from app.core.skills.skill_auto_builder import _infer_task_types

        result = _infer_task_types("writing")
        assert isinstance(result, list)
        assert "FILE_GEN" in result

    def test_unknown_domain_defaults_to_chat(self):
        from app.core.skills.skill_auto_builder import _infer_task_types

        result = _infer_task_types("unknown_domain_xyz")
        assert isinstance(result, list)
        assert "CHAT" in result

    def test_research_contains_research_task(self):
        from app.core.skills.skill_auto_builder import _infer_task_types

        result = _infer_task_types("research")
        assert "RESEARCH" in result

    def test_returns_list_for_all_required_domains(self):
        from app.core.skills.skill_auto_builder import _infer_task_types

        for domain in REQUIRED_DOMAINS:
            result = _infer_task_types(domain)
            assert isinstance(result, list) and len(result) > 0


# ---------------------------------------------------------------------------
# StyleProfile round-trip
# ---------------------------------------------------------------------------


class TestStyleProfileRoundTrip:
    def test_default_round_trip(self):
        from app.core.skills.skill_auto_builder import StyleProfile

        original = StyleProfile()
        d = original.to_dict()
        restored = StyleProfile.from_dict(d)

        assert restored.formality == pytest.approx(original.formality)
        assert restored.verbosity == pytest.approx(original.verbosity)
        assert restored.empathy == pytest.approx(original.empathy)
        assert restored.domain == original.domain
        assert restored.language == original.language

    def test_custom_values_round_trip(self):
        from app.core.skills.skill_auto_builder import StyleProfile

        original = StyleProfile(
            formality=0.9,
            verbosity=0.1,
            empathy=0.8,
            structure=0.7,
            creativity=0.6,
            technicality=0.95,
            positivity=0.3,
            proactivity=0.2,
            humor=0.05,
            conciseness=0.85,
            domain="coding",
            language="en",
        )
        d = original.to_dict()
        restored = StyleProfile.from_dict(d)

        for field in (
            "formality",
            "verbosity",
            "empathy",
            "structure",
            "creativity",
            "technicality",
            "positivity",
            "proactivity",
            "humor",
            "conciseness",
        ):
            assert getattr(restored, field) == pytest.approx(
                getattr(original, field)
            ), f"field '{field}' mismatch after round-trip"

        assert restored.domain == "coding"
        assert restored.language == "en"

    def test_to_dict_has_all_keys(self):
        from app.core.skills.skill_auto_builder import StyleProfile

        d = StyleProfile().to_dict()
        expected_keys = {
            "formality",
            "verbosity",
            "empathy",
            "structure",
            "creativity",
            "technicality",
            "positivity",
            "proactivity",
            "humor",
            "conciseness",
            "domain",
            "language",
        }
        assert expected_keys.issubset(d.keys())

    def test_from_dict_ignores_unknown_keys(self):
        from app.core.skills.skill_auto_builder import StyleProfile

        d = StyleProfile().to_dict()
        d["unexpected_key"] = "ignored"
        # Should not raise
        restored = StyleProfile.from_dict(d)
        assert isinstance(restored, StyleProfile)
