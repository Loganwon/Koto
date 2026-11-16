#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Verify web/ package structure integrity after reorganization."""

import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


# ── Documents package ────────────────────────────────────────────────────────

DOCUMENTS_EXPORTS = [
    ("web.documents", "DocumentComparator"),
    ("web.documents", "DocumentPlanner"),
    ("web.documents", "DocumentReader"),
    ("web.documents", "FileQualityGate"),
    ("web.documents", "save_docx"),
    ("web.documents", "save_pdf"),
    ("web.documents", "embed_annotations"),
    ("web.documents", "pdf_to_docx"),
    ("web.documents", "read_annotations"),
    ("web.documents", "remove_watermark"),
    ("web.documents", "apply_page_ops"),
    ("web.documents", "convert_to_docx"),
    ("web.documents", "needs_conversion"),
]


@pytest.mark.parametrize("module_name,attr", DOCUMENTS_EXPORTS)
def test_documents_package_exports(module_name, attr):
    mod = importlib.import_module(module_name)
    assert hasattr(mod, attr), f"{module_name} missing {attr}"


# ── Proactive package ────────────────────────────────────────────────────────

PROACTIVE_EXPORTS = [
    ("web.proactive", "SuggestionEngine"),
    ("web.proactive", "SmartFeedback"),
    ("web.proactive", "get_trigger_system"),
    ("web.proactive", "get_proactive_dialogue_engine"),
]


@pytest.mark.parametrize("module_name,attr", PROACTIVE_EXPORTS)
def test_proactive_package_exports(module_name, attr):
    mod = importlib.import_module(module_name)
    assert hasattr(mod, attr), f"{module_name} missing {attr}"


# ── Knowledge package ────────────────────────────────────────────────────────

KNOWLEDGE_EXPORTS = [
    ("web.knowledge", "KnowledgeGraph"),
    ("web.knowledge", "ConceptExtractor"),
    ("web.knowledge", "WebSearcher"),
    ("web.knowledge", "search_web"),
]


@pytest.mark.parametrize("module_name,attr", KNOWLEDGE_EXPORTS)
def test_knowledge_package_exports(module_name, attr):
    mod = importlib.import_module(module_name)
    assert hasattr(mod, attr), f"{module_name} missing {attr}"


# ── Tasks package ────────────────────────────────────────────────────────────

TASKS_EXPORTS = [
    ("web.tasks", "LocalExecutor"),
    ("web.tasks", "TemplateLibrary"),
    ("web.tasks", "OperationHistory"),
]


@pytest.mark.parametrize("module_name,attr", TASKS_EXPORTS)
def test_tasks_package_exports(module_name, attr):
    mod = importlib.import_module(module_name)
    assert hasattr(mod, attr), f"{module_name} missing {attr}"


# ── Files package ────────────────────────────────────────────────────────────

FILES_EXPORTS = [
    ("web.files", "FileProcessor"),
    ("web.files", "BatchFileProcessor"),
    ("web.files", "ConsistencyChecker"),
    ("web.files", "CrossAppDataPipeline"),
    ("web.files", "ClipboardOCRAssistant"),
    ("web.files", "get_work_file_library"),
]


@pytest.mark.parametrize("module_name,attr", FILES_EXPORTS)
def test_files_package_exports(module_name, attr):
    mod = importlib.import_module(module_name)
    assert hasattr(mod, attr), f"{module_name} missing {attr}"


RETIRED_ROOT_SHIMS = {
    "code_generator.py",
    "auto_catalog_scheduler.py",
    "batch_file_ops.py",
    "batch_processor.py",
    "calendar_manager.py",
    "chat_system_instruction.py",
    "clipboard_ocr_assistant.py",
    "concept_extractor.py",
    "consistency_checker.py",
    "context_analyzer.py",
    "context_injector.py",
    "data_pipeline.py",
    "doc_converter.py",
    "doc_planner.py",
    "document_comparator.py",
    "document_editor.py",
    "document_generator.py",
    "document_reader.py",
    "document_validator.py",
    "editor_ai_text.py",
    "file_analyzer.py",
    "file_converter.py",
    "file_editor.py",
    "file_fields_extractor.py",
    "file_indexer.py",
    "file_organizer.py",
    "file_processor.py",
    "file_qa.py",
    "file_quality_checker.py",
    "file_scanner.py",
    "file_task_stream.py",
    "filegen_time_context.py",
    "image_generator.py",
    "insight_reporter.py",
    "knowledge_graph.py",
    "local_executor.py",
    "operation_history.py",
    "organize_cleanup.py",
    "pdf_annotator.py",
    "proactive_dialogue.py",
    "proactive_trigger.py",
    "processed_file_network.py",
    "reminder_manager.py",
    "search_backend.py",
    "smart_feedback.py",
    "suggestion_engine.py",
    "track_changes_editor.py",
    "template_library.py",
    "task_queue.py",
    "task_scheduler.py",
    "web_searcher.py",
    "work_file_library.py",
}

RETIRED_PACKAGE_SHIMS = {
    "app/core/services/feedback_loop.py",
    "app/core/services/quality_evaluator.py",
    "app/core/services/search_service.py",
    "web/files/filegen_time_context.py",
    "app/core/collaboration/__init__.py",
    "app/core/collaboration/aggregator.py",
    "app/core/collaboration/delegate.py",
    "app/core/collaboration/messaging.py",
    "app/core/toolkits/agent_tool_bridge.py",
    "app/core/toolkits/bridge.py",
    "app/core/toolkits/tool_executor.py",
    "app/core/routing/intent_analyzer.py",
    "app/core/routing/local_model_router.py",
    "app/core/routing/ai_router.py",
    "app/api/training_routes.py",
    "app/core/learning/training_data_builder.py",
    "app/core/learning/training_db.py",
    "app/core/learning/synthetic_data_generator.py",
    "app/core/learning/memory_to_training.py",
    "app/core/agent/file_task_classification/__init__.py",
    "app/core/routing/routing_config.py",
    "app/core/routing/routing_rule_chain.py",
    "app/core/routing/rule_router.py",
    "app/core/routing/smart_dispatcher.py",
    "app/core/routing/task_classifier.py",
    "app/core/services/context_analyzer.py",
    "app/core/services/context_injector.py",
    "models/task_classifier/clf.pkl",
    "models/task_classifier/config.json",
    "models/task_classifier/label_encoder.pkl",
    "models/task_classifier/training_data.json",
    "models/task_classifier/training_data_v2.json",
    "scripts/extract_classifier_data.py",
    "scripts/train_task_classifier.py",
    "web/documents/doc_annotation.py",
    "web/documents/document_generator.py",
    "web/documents/document_reader.py",
    "web/documents/pdf_annotator.py",
    "web/documents/track_changes_editor.py",
    "web/files/file_converter.py",
    "web/proactive/proactive_trigger.py",
    "web/services/intent/__init__.py",
    "web/services/intent/analysis_classifier.py",
    "web/services/intent/annotation_classifier.py",
    "web/services/intent/file_gen_classifier.py",
}


def test_retired_domain_root_shims_stay_deleted():
    assert all(not (ROOT / "web" / name).exists() for name in RETIRED_ROOT_SHIMS)

    retired_modules = {f"web.{Path(name).stem}" for name in RETIRED_ROOT_SHIMS}
    for source_root in (ROOT / "app", ROOT / "web", ROOT / "launcher", ROOT / "src"):
        for path in source_root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            source = path.read_text(encoding="utf-8-sig")
            for module_name in retired_modules:
                assert (
                    module_name not in source
                ), f"{path} still references {module_name}"


def test_retired_package_shims_and_programmatic_intent_routes_stay_deleted():
    assert all(not (ROOT / path).exists() for path in RETIRED_PACKAGE_SHIMS)


# ── No circular imports ──────────────────────────────────────────────────────


def test_no_circular_import_between_proactive_and_knowledge():
    """Verify that proactive and knowledge can be imported together."""
    from web.knowledge import KnowledgeGraph, WebSearcher  # noqa: F401
    from web.proactive import SuggestionEngine  # noqa: F401
