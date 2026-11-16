import os
from pathlib import Path

from app.core.agent import task_tools, task_tools_common
from app.core.agent.path_utils import resolve_existing_path
from app.core.config import workspace_runtime


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


def test_task_tools_resolve_path_supports_upload_filename(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (tmp_path / "dist").mkdir()

    target = uploads / "notes.txt"
    target.write_text("hello", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(task_tools_common, "_WORKSPACE_ROOT", str(workspace))

    resolved = task_tools._resolve_path("notes.txt")
    assert resolved == str(target)


def test_task_tools_rejects_workspace_prefix_traversal(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sibling = tmp_path / "workspace_evil"
    sibling.mkdir()
    secret = sibling / "secret.txt"
    secret.write_text("outside workspace", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "app.core.agent.task_tools_common._WORKSPACE_ROOT", str(workspace)
    )

    escaped = "../workspace_evil/secret.txt"
    assert task_tools._safe_resolve(escaped) is None
    assert task_tools._resolve_path(escaped) is None
    assert task_tools._resolve_path(escaped, must_exist=False) is None


def test_task_tools_uses_portable_workspace_when_frozen(tmp_path, monkeypatch):
    portable_workspace = tmp_path / "workspace"
    monkeypatch.setattr("app.core.agent.task_tools_common._WORKSPACE_ROOT", None)
    monkeypatch.setattr(
        workspace_runtime,
        "get_workspace_root",
        lambda: str(portable_workspace),
    )

    assert task_tools._get_workspace_root() == str(portable_workspace)
