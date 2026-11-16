from pathlib import Path
from types import SimpleNamespace

from app.core.agent.file_task_artifact_transaction import (
    cleanup_run_owned_paths,
    commit_staged_artifact,
    committed_file_changes,
    run_scoped_staging_path,
)


def test_run_scoped_staging_path_is_hidden_and_run_owned(tmp_path):
    target = tmp_path / "report.docx"

    staging = run_scoped_staging_path(
        SimpleNamespace(run_id="run:financial/01"),
        str(target),
    )

    assert staging.parent == tmp_path
    assert staging.name == ".report.run_financial_01.koto-partial.docx"


def test_commit_staged_artifact_atomically_replaces_target(tmp_path):
    target = tmp_path / "report.docx"
    staging = tmp_path / ".report.run.koto-partial.docx"
    target.write_text("old", encoding="utf-8")
    staging.write_text("new", encoding="utf-8")

    assert commit_staged_artifact(staging, str(target)) is True
    assert target.read_text(encoding="utf-8") == "new"
    assert not staging.exists()


def test_cleanup_run_owned_paths_preserves_preexisting_artifacts(tmp_path):
    staging = tmp_path / ".report.run.koto-partial.docx"
    generated = tmp_path / "generated.png"
    preexisting = tmp_path / "existing.png"
    for path in (staging, generated, preexisting):
        path.write_bytes(b"data")

    cleanup_run_owned_paths(
        staging,
        [generated, preexisting],
        preexisting_paths=[preexisting],
    )

    assert not staging.exists()
    assert not generated.exists()
    assert preexisting.exists()


def test_committed_file_changes_hide_the_staging_path(tmp_path):
    staging = tmp_path / ".report.run.koto-partial.docx"
    target = tmp_path / "report.docx"

    changes = committed_file_changes(
        [
            {
                "path": str(staging),
                "target_path": str(staging),
                "operation": "write_docx_content",
            },
            {"path": str(tmp_path / "chart.png"), "operation": "create_image"},
        ],
        staging_path=staging,
        target_path=str(target),
    )

    assert changes[0]["path"] == str(target)
    assert changes[0]["target_path"] == str(target)
    assert changes[1]["path"] == str(tmp_path / "chart.png")
