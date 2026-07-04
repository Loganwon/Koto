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


def test_legacy_agent_loop_bridges_use_facade_only() -> None:
    editor_ai = _read("web/blueprints/editor_ai.py")
    socket_handler = _read("app/core/socket_handler.py")
    facade = _read("app/core/agent/legacy_loop_facade.py")
    code_executor = _read("app/core/agent/editor_code_action_executor.py")
    doc_executor = _read("app/core/agent/doc_websocket_loop_executor.py")
    doc_agent_executor = _read("app/core/agent/doc_websocket_agent_executor.py")
    doc_mapper = _read("app/core/agent/doc_websocket_event_mapper.py")
    editor_executor = _read("app/core/agent/editor_quick_action_executor.py")
    editor_loop_executor = _read("app/core/agent/editor_loop_executor.py")

    assert "from app.core.agent.legacy_loop_facade import iter_editor_agent_events" in editor_ai
    assert "from app.core.agent.legacy_loop_facade import iter_doc_agent_events" in socket_handler
    assert "app.core.agent.agent_loop import KotoAgentLoop" not in editor_ai
    assert "app.core.agent.agent_loop import KotoAgentLoop" not in socket_handler
    assert "app.core.agent.agent_loop import KotoAgentLoop" not in facade
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
    assert "from app.core.agent.doc_websocket_event_mapper import emit_agent_event" in socket_handler


def test_agent_execution_entrypoint_matrix_documents_current_boundaries() -> None:
    matrix = _read("docs/AGENT_EXECUTION_ENTRYPOINT_MATRIX.md")

    assert "FileTaskRuntime" in matrix
    assert "UnifiedAgent" in matrix
    assert "LangGraphAgent" in matrix
    assert "KotoAgentLoop" not in matrix
    assert "agent_loop.py" not in matrix
    assert "EditorCodeActionExecutor" in matrix
    assert "EditorQuickActionExecutor" in matrix
    assert "DocWebSocketAgentExecutor" in matrix
    assert "llm_provider_helpers.py" in matrix
    assert "web/blueprints/editor_ai.py" in matrix
    assert "app/core/socket_handler.py" in matrix
    assert "app/core/agent/legacy_loop_facade.py" in matrix
    assert "app/core/agent/editor_loop_executor.py" in matrix
    assert "app/core/agent/doc_websocket_loop_executor.py" in matrix
    assert "app/core/agent/doc_websocket_agent_executor.py" in matrix
    assert "app/core/agent/doc_websocket_event_mapper.py" in matrix
    assert "agent_production_entrypoint_hits" in matrix
