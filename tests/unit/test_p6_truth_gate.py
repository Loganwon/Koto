from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = json.loads(
    (ROOT / "config" / "p6_quality_gates.json").read_text(encoding="utf-8")
)


def _python_sources(relative_root: str) -> list[Path]:
    return sorted((ROOT / relative_root).rglob("*.py"))


def test_retired_systems_are_absent_from_real_task_lanes() -> None:
    hits: list[str] = []
    for relative_root in GATE["truth_roots"]:
        for path in _python_sources(relative_root):
            source = path.read_text(encoding="utf-8")
            for token in GATE["retired_test_tokens"]:
                if token in source:
                    hits.append(f"{path.relative_to(ROOT).as_posix()}: {token}")
    assert hits == []


def test_offline_evaluation_keeps_the_real_file_task_runtime() -> None:
    source = (ROOT / "tests" / "evaluation" / "conftest.py").read_text(encoding="utf-8")
    assert "create_runtime_llm_gateway" in source
    assert 'monkeypatch.setattr(FileTaskModelClient, "call", fake_call)' in source
    assert "monkeypatch.setattr(FileTaskRuntime" not in source
    assert "def fake_run(" not in source


def test_current_real_task_surfaces_remain_covered() -> None:
    for relative_path, tokens in GATE["required_current_tokens"].items():
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        missing = [token for token in tokens if token not in source]
        assert missing == [], f"{relative_path} missing current tokens: {missing}"


def test_workspace_browser_tests_use_the_unified_shell() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8") for path in _python_sources("tests/e2e")
    )
    assert 'f"{e2e_base_url}/workspace"' not in sources
    assert 'f"{base_url}/workspace"' not in sources
