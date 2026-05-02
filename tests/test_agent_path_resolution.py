import os
from pathlib import Path

from app.core.agent import task_tools
from app.core.agent.path_utils import resolve_existing_path
from app.core.agent.plugins.annotation_plugin import AnnotationPlugin


def test_resolve_existing_path_by_filename(tmp_path, monkeypatch):
    (tmp_path / "workspace").mkdir()
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (tmp_path / "dist").mkdir()

    target = uploads / "sales.xlsx"
    target.write_text("stub", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    resolved, err = resolve_existing_path("sales.xlsx")

    assert err is None
    assert resolved == str(target)


def test_resolve_existing_path_by_relative_prefix(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "uploads").mkdir()
    (tmp_path / "dist").mkdir()

    target = workspace / "demo.csv"
    target.write_text("a,b\n1,2\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    resolved, err = resolve_existing_path("workspace/demo.csv")

    assert err is None
    assert resolved == str(target)


def test_annotation_resolve_docx_supports_relative_filename(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "uploads").mkdir()
    (tmp_path / "dist").mkdir()

    target = workspace / "report.docx"
    target.write_text("stub", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    resolved, err = AnnotationPlugin._resolve_docx_path("report.docx")

    assert err is None
    assert resolved == str(target)


def test_annotation_resolve_docx_rejects_outside_allowed_roots(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "uploads").mkdir()
    (tmp_path / "dist").mkdir()

    outside = tmp_path / "other" / "report.docx"
    outside.parent.mkdir(parents=True)
    outside.write_text("stub", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    resolved, err = AnnotationPlugin._resolve_docx_path(str(outside))

    assert resolved is None
    assert err is not None
    assert "允许的目录" in err


def test_task_tools_resolve_path_supports_upload_filename(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (tmp_path / "dist").mkdir()

    target = uploads / "notes.txt"
    target.write_text("hello", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    task_tools._WORKSPACE_ROOT = str(workspace)

    resolved = task_tools._resolve_path("notes.txt")
    assert resolved == str(target)
