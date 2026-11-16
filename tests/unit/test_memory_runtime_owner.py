from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_background_extraction_uses_manager_owned_implementation(monkeypatch):
    import web.memory_runtime as memory_runtime
    from app.core.learning.response_evaluator import ResponseEvaluator

    manager = MagicMock()
    manager.should_auto_extract.return_value = True
    manager.auto_extract_from_conversation.return_value = {
        "memories": ["用户偏好简洁输出"],
        "profile_updates": {"communication_style": {"preferred_detail_level": "brief"}},
    }
    monkeypatch.setattr(memory_runtime, "get_memory_manager", lambda: manager)
    monkeypatch.setattr(ResponseEvaluator, "evaluate_async", lambda **kwargs: None)

    class _ImmediateThread:
        def __init__(self, *, target, daemon):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(memory_runtime.threading, "Thread", _ImmediateThread)
    history = [{"role": "user", "parts": ["我偏好简洁输出"]}]

    memory_runtime._start_memory_extraction(
        "我偏好简洁输出",
        "好的，以后会保持简洁。",
        history=history,
        task_type="CHAT",
        session_name="test-session",
    )

    manager.should_auto_extract.assert_called_once_with(
        "我偏好简洁输出",
        "好的，以后会保持简洁。",
        "CHAT",
    )
    manager.auto_extract_from_conversation.assert_called_once_with(
        "我偏好简洁输出",
        "好的，以后会保持简洁。",
        history,
        task_type="CHAT",
        session_name="test-session",
    )


@pytest.mark.unit
def test_personality_matrix_has_one_runtime_definition():
    source = (ROOT / "app/core/services/memory_manager.py").read_text(
        encoding="utf-8-sig"
    )
    tree = ast.parse(source)
    definitions = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "PersonalityMatrix"
    ]

    assert len(definitions) == 1


@pytest.mark.unit
def test_production_code_cannot_reenter_retired_memory_modules():
    offenders = []
    retired_modules = (
        ROOT / "web/memory_manager.py",
        ROOT / "web/enhanced_memory_manager.py",
        ROOT / "web/memory_integration.py",
        ROOT / "app/core/memory/memory_reflector.py",
    )
    assert all(not path.exists() for path in retired_modules)

    for base in (ROOT / "app", ROOT / "web"):
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            source = path.read_text(encoding="utf-8-sig")
            if any(
                retired_import in source
                for retired_import in (
                    "web.memory_manager",
                    "web.enhanced_memory_manager",
                    "web.memory_integration",
                    "app.core.memory.memory_reflector",
                    "from memory_manager import",
                    "from enhanced_memory_manager import",
                    "from memory_integration import",
                )
            ):
                offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []
    spec_source = (ROOT / "koto.spec").read_text(encoding="utf-8-sig")
    assert "'web.memory_manager'" not in spec_source
    assert "'web.enhanced_memory_manager'" not in spec_source
    assert "'web.memory_integration'" not in spec_source

    runtime_source = (ROOT / "web/memory_runtime.py").read_text(encoding="utf-8-sig")
    assert "MemoryIntegration" not in runtime_source
    assert "MemoryReflector" not in runtime_source
    assert "_quality_llm" not in runtime_source
    assert ".auto_extract_from_conversation(" in runtime_source

    manager_source = (ROOT / "app/core/services/memory_manager.py").read_text(
        encoding="utf-8-sig"
    )
    assert "def update_personality_async(" not in manager_source
    assert "PersonalityMatrix.update_async(" not in manager_source


@pytest.mark.unit
def test_core_does_not_depend_on_web_memory_runtime():
    offenders = []
    for path in (ROOT / "app/core").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        imports_web_memory_runtime = any(
            (
                isinstance(node, ast.Import)
                and any(alias.name == "web.memory_runtime" for alias in node.names)
            )
            or (
                isinstance(node, ast.ImportFrom) and node.module == "web.memory_runtime"
            )
            for node in ast.walk(tree)
        )
        if imports_web_memory_runtime:
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []
