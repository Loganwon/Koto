from __future__ import annotations

from pathlib import Path

import pytest

from app.core.workflows.file_store import (
    WORKFLOW_TEMP_PREFIX,
    WorkflowFileAccessError,
    save_workflow_uploads,
    validate_workflow_download_path,
    workflow_upload_dir,
)


class FakeUpload:
    def __init__(self, filename: str, content: bytes = b"data") -> None:
        self.filename = filename
        self.content = content

    def save(self, dst: str) -> None:
        Path(dst).write_bytes(self.content)


def test_workflow_upload_dir_sanitizes_session_id(tmp_path):
    target = workflow_upload_dir("../bad/session", temp_root=tmp_path)

    assert target.parent == tmp_path
    assert target.name.startswith(WORKFLOW_TEMP_PREFIX)
    assert ".." not in target.name
    assert "/" not in target.name


def test_save_workflow_uploads_saves_basename_only(tmp_path):
    result = save_workflow_uploads(
        [FakeUpload("../source.pdf", b"pdf"), FakeUpload("", b"skip")],
        session_id="session-1",
        temp_root=tmp_path,
    )

    assert result.session_id == "session-1"
    assert len(result.paths) == 1
    saved_path = Path(result.paths[0])
    assert saved_path.name == "source.pdf"
    assert saved_path.read_bytes() == b"pdf"
    assert saved_path.parent == tmp_path / "koto_wf_session-1"


def test_validate_workflow_download_path_allows_workflow_temp_file(tmp_path):
    result = save_workflow_uploads(
        [FakeUpload("result.xlsx", b"xlsx")],
        session_id="download",
        temp_root=tmp_path,
    )

    resolved = validate_workflow_download_path(result.paths[0], temp_root=tmp_path)

    assert resolved.name == "result.xlsx"


def test_validate_workflow_download_path_rejects_non_workflow_temp_file(tmp_path):
    outside = tmp_path / "plain.txt"
    outside.write_text("nope", encoding="utf-8")

    with pytest.raises(WorkflowFileAccessError) as exc:
        validate_workflow_download_path(str(outside), temp_root=tmp_path)

    assert exc.value.status_code == 403


def test_validate_workflow_download_path_rejects_missing_file(tmp_path):
    with pytest.raises(WorkflowFileAccessError) as exc:
        validate_workflow_download_path(
            str(tmp_path / "koto_wf_x" / "missing.txt"), temp_root=tmp_path
        )

    assert exc.value.status_code == 404
