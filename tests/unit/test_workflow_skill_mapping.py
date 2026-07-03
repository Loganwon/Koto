from __future__ import annotations

from app.core.skills.builtin_skills import BUILTIN_SKILLS
from app.core.workflows.registry import registered_workflow_ids
from app.core.workflows.skill_mapping import (
    WORKFLOW_SKILL_MAPPINGS,
    get_skill_ids_for_workflow,
    get_workflow_candidates_for_skill,
    get_workflow_skill_mapping,
    list_workflow_skill_mappings,
    workflow_has_skill_mapping,
)


def test_workflow_skill_mapped_skill_ids_exist_in_builtin_skills():
    builtin_ids = {skill["id"] for skill in BUILTIN_SKILLS}

    assert {mapping.skill_id for mapping in WORKFLOW_SKILL_MAPPINGS}.issubset(builtin_ids)


def test_workflow_skill_mapped_executor_ids_are_registered():
    executor_ids = set(registered_workflow_ids())

    for mapping in WORKFLOW_SKILL_MAPPINGS:
        assert set(mapping.executor_ids).issubset(executor_ids)


def test_direct_duplicate_skill_ids_have_single_matching_executor():
    direct_mappings = {
        mapping.skill_id: mapping.executor_ids
        for mapping in WORKFLOW_SKILL_MAPPINGS
        if mapping.relation == "direct"
    }

    assert direct_mappings == {
        "cross_format_extractor": ("cross_format_extractor",),
        "doc_smart_compare": ("doc_smart_compare",),
        "questionnaire_filler": ("questionnaire_filler",),
        "data_format_cleaner": ("data_format_cleaner",),
    }


def test_workflow_candidates_for_skill_are_stable():
    assert get_workflow_candidates_for_skill("multi_doc_synthesis") == (
        "multi_file_synthesis_report",
    )
    assert get_workflow_candidates_for_skill("contract_reviewer") == (
        "contract_clause_matrix",
        "contract_diff_markup",
        "doc_ai_review",
    )
    assert get_workflow_candidates_for_skill("missing_skill") == ()


def test_workflow_skill_mapping_public_shape():
    mapping = get_workflow_skill_mapping("spreadsheet_analyst")
    public_rows = list_workflow_skill_mappings()

    assert mapping is not None
    assert mapping.relation == "candidate"
    assert any(row["skill_id"] == "spreadsheet_analyst" for row in public_rows)
    assert all(isinstance(row["executor_ids"], list) for row in public_rows)


def test_workflow_to_skill_reverse_lookup_is_stable():
    assert get_skill_ids_for_workflow("data_format_cleaner") == (
        "data_format_cleaner",
        "spreadsheet_analyst",
        "excel_data_cleaner",
    )
    assert get_skill_ids_for_workflow("doc_ai_review") == (
        "contract_reviewer",
        "legal_doc_review",
    )
    assert workflow_has_skill_mapping("data_anomaly_report") is True
    assert workflow_has_skill_mapping("missing_workflow") is False
