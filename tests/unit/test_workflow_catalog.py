from __future__ import annotations

from app.core.workflows.catalog import (
    WORKFLOW_CATALOG,
    get_workflow_definition,
    is_chat_workflow,
    list_workflow_definitions,
)
from app.core.workflows.registry import registered_workflow_ids


def test_workflow_catalog_lists_executor_and_chat_workflows():
    workflow_ids = {workflow["id"] for workflow in list_workflow_definitions()}

    assert "cross_format_extractor" in workflow_ids
    assert "data_format_cleaner" in workflow_ids
    assert "source_grounded_qa" in workflow_ids
    assert "mind_map_gen" in workflow_ids


def test_public_executor_workflows_have_registered_executors():
    executor_ids = set(registered_workflow_ids())
    public_executor_ids = {
        workflow_id
        for workflow_id, workflow in WORKFLOW_CATALOG.items()
        if workflow.get("mode") != "chat"
    }

    assert public_executor_ids.issubset(executor_ids)


def test_workflow_catalog_returns_copies_not_mutable_globals():
    workflow = get_workflow_definition("cross_format_extractor")
    assert workflow is not None

    workflow["name"] = "mutated"

    assert get_workflow_definition("cross_format_extractor")["name"] == "跨格式信息搬运"


def test_workflow_catalog_exposes_related_skill_ids_from_mapping():
    workflow = get_workflow_definition("data_format_cleaner")
    assert workflow is not None

    assert workflow["related_skill_ids"] == [
        "data_format_cleaner",
        "spreadsheet_analyst",
        "excel_data_cleaner",
    ]
    assert "related_skill_ids" not in get_workflow_definition("source_grounded_qa")


def test_workflow_catalog_distinguishes_chat_mode():
    assert is_chat_workflow("source_grounded_qa") is True
    assert is_chat_workflow("cross_format_extractor") is False
    assert get_workflow_definition("missing_workflow") is None
