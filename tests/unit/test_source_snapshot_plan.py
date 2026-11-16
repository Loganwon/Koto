import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path("scripts/write_source_snapshot_plan.py")
SPEC = importlib.util.spec_from_file_location("write_source_snapshot_plan", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("scripts/check_release_readiness.ps1", "01_release_and_governance"),
        ("app/core/agent/kernel/runtime.py", "02_agent_and_platform_core"),
        ("app/core/services/file_scanner.py", "03_file_llm_and_services"),
        ("web/blueprints/chat.py", "04_web_backend"),
        ("web/src/workspace/state.ts", "05_frontend_source"),
        ("web/static/js/build/workspace-bundle.js", "06_generated_frontend"),
        ("src/external_open.py", "07_desktop_and_launcher"),
        ("tests/unit/test_external_open.py", "08_tests"),
        (".codex/designs/design_01.md", "09_current_documentation"),
        ("docs/archive/phase_reports/old.md", "10_archived_documentation"),
        ("unknown-root-file.xyz", "99_manual_classification"),
    ],
)
def test_source_snapshot_paths_have_stable_review_owners(path, expected):
    assert MODULE.classify(path) == expected


def test_untracked_runtime_and_large_files_are_risk_flagged(tmp_path):
    database = tmp_path / "private.db"
    database.write_bytes(b"sqlite")
    large = tmp_path / "large.bin"
    large.write_bytes(b"x" * 1_000_001)
    safe = tmp_path / "feature.py"
    safe.write_text("pass\n", encoding="utf-8")

    assert "sensitive_or_runtime_extension" in MODULE.risks(
        tmp_path, "private.db", untracked=True
    )
    assert "large_untracked_file" in MODULE.risks(tmp_path, "large.bin", untracked=True)
    assert MODULE.risks(tmp_path, "feature.py", untracked=True) == ()
    assert MODULE.risks(tmp_path, "private.db", untracked=False) == ()


def test_snapshot_markdown_states_that_it_never_mutates_source():
    report = {
        "pending_count": 0,
        "tracked_count": 0,
        "untracked_count": 0,
        "manual_classification_count": 0,
        "risk_flagged_count": 0,
        "generated_at": "2026-08-28T00:00:00+00:00",
        "batches": [],
    }

    rendered = MODULE.markdown(report)

    assert "never stages, commits, deletes, or rewrites source files" in rendered
    assert "Manual classification paths: **0**" in rendered
