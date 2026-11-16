from __future__ import annotations

import ast
import json
from pathlib import Path

from scripts.run_p6_golden_tasks import (
    build_command,
    load_cases,
    node_ids,
    select_cases,
)

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "tests" / "golden" / "p6_real_tasks.json"


def _load() -> dict:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def _declared_test_node(node_id: str) -> bool:
    parts = node_id.split("::")
    path = ROOT / parts[0]
    if not path.is_file() or len(parts) < 2:
        return False
    tree = ast.parse(path.read_text(encoding="utf-8"))
    scope = tree.body
    for name in parts[1:]:
        match = next(
            (
                node
                for node in scope
                if isinstance(
                    node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                )
                and node.name == name
            ),
            None,
        )
        if match is None:
            return False
        scope = match.body if isinstance(match, ast.ClassDef) else []
    return True


def test_golden_corpus_has_required_real_task_coverage():
    corpus = _load()
    cases = corpus["cases"]
    assert corpus["schema_version"] == 1
    assert len(cases) >= 16
    assert {case["surface"] for case in cases} == set(corpus["required_surfaces"])
    assert set(corpus["required_operations"]) <= {case["operation"] for case in cases}
    assert set(corpus["required_environments"]) <= {
        environment for case in cases for environment in case["environments"]
    }
    assert {case["priority"] for case in cases} == {"P0", "P1"}


def test_golden_cases_have_machine_verifiable_oracles_and_unique_ids():
    cases = _load()["cases"]
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))
    for case in cases:
        assert case["real_task"].strip()
        assert case["fixture_profile"].strip()
        assert case["node_ids"]
        assert case["oracle"]["kind"].strip()
        assert len(case["oracle"]["assertions"]) >= 2
        assert case["oracle"]["evidence"].strip()


def test_every_golden_node_resolves_to_a_real_collected_test_declaration():
    missing = [node for node in node_ids(load_cases()) if not _declared_test_node(node)]
    assert missing == []


def test_user_reported_failure_modes_are_explicit_p0_cases():
    p0 = {case["id"] for case in load_cases() if case["priority"] == "P0"}
    assert {
        "startup-no-provider",
        "startup-local-model-mismatch",
        "docx-review-large-corpus",
        "pdf-text-anchor-zoom-reload",
        "pdf-watermark-cleanup",
        "pdf-to-office-conversion",
    } <= p0


def test_golden_runner_filters_without_dropping_or_duplicating_nodes():
    pdf_cases = select_cases(surface="pdf")
    assert pdf_cases and {case["surface"] for case in pdf_cases} == {"pdf"}
    command = build_command(pdf_cases, ["-q"])
    assert command[1:3] == ["-m", "pytest"]
    assert command[-1] == "-q"
    assert len(node_ids(pdf_cases)) == len(set(node_ids(pdf_cases)))
