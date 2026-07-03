from __future__ import annotations

from app.core.workflows import registry


def test_workflow_executor_registry_covers_known_workflow_classes():
    expected_ids = {
        "action_item_extractor",
        "comm_digest",
        "contract_clause_matrix",
        "contract_diff_markup",
        "cross_format_extractor",
        "data_anomaly_report",
        "data_fill_report",
        "data_format_cleaner",
        "doc_ai_review",
        "doc_deep_compare",
        "doc_smart_compare",
        "email_thread_digest",
        "multi_file_synthesis_report",
        "pptx_data_refresh",
        "questionnaire_filler",
    }

    assert set(registry.registered_workflow_ids()) == expected_ids


def test_workflow_executor_registry_returns_none_for_unknown_id():
    assert registry.get_workflow_executor("missing_workflow") is None


def test_workflow_executor_registry_instantiates_lightweight_executor():
    executor = registry.get_workflow_executor("comm_digest")

    assert executor is not None
    assert executor.WORKFLOW_ID == "comm_digest"
