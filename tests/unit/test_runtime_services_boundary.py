# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_service_blueprints_use_runtime_services_boundary() -> None:
    service_helpers = [
        "get_behavior_monitor",
        "get_suggestion_engine",
        "get_insight_reporter",
        "get_notification_manager",
        "get_proactive_dialogue",
        "get_context_awareness",
        "get_trigger_system",
        "get_auto_execution",
        "get_knowledge_graph",
        "get_file_editor",
        "get_file_indexer",
        "get_concept_extractor",
        "get_file_organizer",
        "get_file_analyzer",
        "get_batch_ops_manager",
        "get_organize_root",
    ]
    for path in [
        "web/blueprints/analytics.py",
        "web/blueprints/proactive.py",
        "web/blueprints/execution.py",
        "web/blueprints/knowledge.py",
        "web/blueprints/file_editor.py",
        "web/blueprints/file_organize.py",
    ]:
        source = _read(path)

        assert "from web.runtime_services import" in source
        assert "call_app_factory(" not in source
        assert "get_app_attr(" not in source
        for helper in service_helpers:
            assert f"from web.runtime_context import {helper}" not in source


def test_runtime_services_do_not_depend_on_web_app_bridge() -> None:
    source = _read("web/runtime_services.py")
    runtime_context = _read("web/runtime_context.py")

    assert "sys.modules" not in source
    assert 'importlib.import_module("web.app")' not in source
    assert "from web.lazy_loaders." in source
    for helper in [
        "get_behavior_monitor",
        "get_suggestion_engine",
        "get_insight_reporter",
        "get_notification_manager",
        "get_proactive_dialogue",
        "get_context_awareness",
        "get_trigger_system",
        "get_auto_execution",
        "get_knowledge_graph",
        "get_file_editor",
        "get_file_indexer",
        "get_concept_extractor",
        "get_file_organizer",
        "get_file_analyzer",
        "get_batch_ops_manager",
        "get_organize_root",
    ]:
        assert f"def {helper}(" in source
        assert f"def {helper}(" not in runtime_context
