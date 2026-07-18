from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_runtime_and_personal_data_stay_ignored() -> None:
    ignore_rules = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert {
        "/.codex-runtime/",
        "config/file_rag_index/",
        "config/memory_rag_index/",
        "config/skill_ratings.json",
        "config/suggestions.db",
        "config/test_*.db",
        "config/user_behavior.db",
    } <= ignore_rules


@pytest.mark.unit
def test_pytest_sources_do_not_target_repository_test_databases() -> None:
    for relative_path in (
        "tests/test_proactive_features.py",
        "tests/test_trigger_params_integration.py",
    ):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "config/test_" not in source


@pytest.mark.unit
def test_smart_features_script_remains_a_manual_isolated_demo() -> None:
    path = ROOT / "tests/test_smart_features.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    collected_functions = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]

    assert collected_functions == []
    assert "TemporaryDirectory(" in source
    assert "os.chdir(temp_dir)" in source
