# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_koto_agent_loop_production_entrypoints_are_allowlisted() -> None:
    assert not (ROOT / "app/core/agent/agent_loop.py").exists()
    allowed = set()
    imports = []
    instantiations = []
    for root_name in ("app", "web"):
        for path in (ROOT / root_name).rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            source = path.read_text(encoding="utf-8")
            if "from app.core.agent.agent_loop import KotoAgentLoop" in source:
                imports.append(rel)
            if re.search(r"\bKotoAgentLoop\s*\(", source):
                instantiations.append(rel)

    assert set(imports) == allowed
    assert set(instantiations) == allowed


def test_retired_deep_research_agent_cannot_reenter_production() -> None:
    assert not (ROOT / "app/core/agent/deep_research.py").exists()
    forbidden = ("DeepResearchAgent", "app.core.agent.deep_research")
    hits = []
    for root_name in ("app", "web"):
        for path in (ROOT / root_name).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if any(item in source for item in forbidden):
                hits.append(path.relative_to(ROOT).as_posix())

    assert hits == []


def test_production_transports_import_lifecycle_contract_from_kernel() -> None:
    assert not (ROOT / "app/core/agent/lifecycle.py").exists()
    legacy_import = "app.core.agent.lifecycle"
    hits = []
    for root_name in ("app", "web"):
        for path in (ROOT / root_name).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if legacy_import in source:
                hits.append(path.relative_to(ROOT).as_posix())

    assert hits == []


def test_active_agent_loops_normalize_provider_responses_through_kernel() -> None:
    for relative_path in ("app/core/agent/kernel/runtime.py",):
        source = _read(relative_path)
        assert "ModelResponse.from_raw(" in source
        assert 'response.get("content"' not in source
        assert 'response.get("tool_calls"' not in source


def test_unified_agent_is_retired_and_cannot_reenter_production() -> None:
    assert not (ROOT / "app/core/agent/unified_agent.py").exists()
    legacy_import = "app.core.agent.unified_agent"
    offenders = []
    for root_name in ("app", "web"):
        for path in (ROOT / root_name).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if legacy_import in source:
                offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []


def test_nested_task_agent_is_retired_and_cannot_reenter_production() -> None:
    assert not (ROOT / "app/core/agent/task_agent.py").exists()
    assert not (ROOT / "app/core/skills/skill_runner.py").exists()
    legacy_names = (
        "app.core.agent.task_agent",
        "app.core.skills.skill_runner",
    )
    offenders = []
    for root_name in ("app", "web"):
        for path in (ROOT / root_name).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if any(name in source for name in legacy_names):
                offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []


def test_retired_doc_agent_loop_cannot_reenter_production() -> None:
    assert not (ROOT / "app/core/agent/doc_agent.py").exists()
    assert not (ROOT / "app/core/agent/doc_event_emitter.py").exists()
    forbidden = (
        "app.core.agent.doc_agent",
        "app.core.agent.doc_event_emitter",
        "_use_doc_agent",
        '"use_doc_agent"',
    )
    offenders = []
    for root_name in ("app", "web"):
        for path in (ROOT / root_name).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if any(item in source for item in forbidden):
                offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []


def test_retired_graph_agent_implementations_cannot_reenter_production() -> None:
    retired_paths = (
        "app/core/agent/langgraph_agent.py",
        "app/core/agent/multi_agent.py",
    )
    for relative_path in retired_paths:
        assert not (ROOT / relative_path).exists()

    forbidden = (
        "LangGraphAgent",
        "app.core.agent.langgraph_agent",
        "MultiAgentOrchestrator",
        "app.core.agent.multi_agent",
    )
    hits = []
    for root_name in ("app", "web"):
        for path in (ROOT / root_name).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if any(item in source for item in forbidden):
                hits.append(path.relative_to(ROOT).as_posix())

    assert hits == []


def test_legacy_agent_loop_bridges_use_facade_only() -> None:
    editor_ai = _read("web/blueprints/editor_ai.py")
    socket_handler = _read("app/core/socket_handler.py")
    code_executor = _read("app/core/agent/editor_code_action_executor.py")
    doc_executor = _read("app/core/agent/doc_websocket_loop_executor.py")
    doc_agent_executor = _read("app/core/agent/doc_websocket_agent_executor.py")
    doc_mapper = _read("app/core/agent/doc_websocket_event_mapper.py")
    editor_executor = _read("app/core/agent/editor_quick_action_executor.py")
    editor_loop_executor = _read("app/core/agent/editor_loop_executor.py")

    assert (
        "from app.core.agent.editor_loop_executor import EditorLoopExecutor"
        in editor_ai
    )
    assert (
        "from app.core.agent.doc_websocket_loop_executor import DocWebSocketLoopExecutor"
        in socket_handler
    )
    assert "app.core.agent.agent_loop import KotoAgentLoop" not in editor_ai
    assert "app.core.agent.agent_loop import KotoAgentLoop" not in socket_handler
    assert "from app.core.agent import agent_loop" not in code_executor
    assert "from app.core.agent import agent_loop" not in editor_executor
    assert "KotoAgentLoop" not in code_executor
    assert "KotoAgentLoop" not in editor_executor
    assert "KotoAgentLoop" not in editor_loop_executor
    assert "KotoAgentLoop" not in doc_mapper
    assert "KotoAgentLoop" not in doc_agent_executor
    assert "from app.core.agent.agent_loop import KotoAgentLoop" not in doc_executor
    assert "DocWebSocketAgentExecutor().iter_events(request)" in doc_executor
    assert "EditorCodeActionExecutor.supports(request)" in editor_loop_executor
    assert "EditorQuickActionExecutor().iter_events(request)" in editor_loop_executor
    assert (
        "from app.core.agent.doc_websocket_event_mapper import emit_agent_event"
        in socket_handler
    )


def test_agent_execution_entrypoint_matrix_documents_current_boundaries() -> None:
    matrix = _read("docs/AGENT_EXECUTION_ENTRYPOINT_MATRIX.md")

    assert "FileTaskRuntime" in matrix
    assert "KernelAgent" in matrix
    assert "UnifiedAgent" not in matrix
    assert "LangGraphAgent" not in matrix
    assert "KotoAgentLoop" not in matrix
    assert "agent_loop.py" not in matrix
    assert "EditorCodeActionExecutor" in matrix
    assert "EditorQuickActionExecutor" in matrix
    assert "DocWebSocketAgentExecutor" in matrix
    assert "llm_provider_helpers.py" in matrix
    assert "web/blueprints/editor_ai.py" in matrix
    assert "app/core/socket_handler.py" in matrix
    assert "app/core/agent/editor_loop_executor.py" in matrix
    assert "app/core/agent/doc_websocket_loop_executor.py" in matrix
    assert "app/core/agent/doc_websocket_agent_executor.py" in matrix
    assert "app/core/agent/doc_websocket_event_mapper.py" in matrix
    assert "agent_production_entrypoint_hits" in matrix
