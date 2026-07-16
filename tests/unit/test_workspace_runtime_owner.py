from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


@pytest.mark.unit
def test_workspace_switch_updates_runtime_file_tools_and_editor_plugin(
    monkeypatch, tmp_path
):
    from app.core.agent import task_tools
    from app.core.agent.plugins import workspace_editor_plugin
    from app.core.config.workspace_runtime import (
        clear_workspace_root_override,
        get_workspace_root,
        set_workspace_root,
    )
    from web.runtime_context import ServiceRegistry
    import web.shared as shared

    first = tmp_path / "first-workspace"
    second = tmp_path / "second-workspace"
    first.mkdir()
    second.mkdir()

    clear_workspace_root_override()
    monkeypatch.setattr(task_tools, "_WORKSPACE_ROOT", None)
    registry = ServiceRegistry()
    registry._module = SimpleNamespace(WORKSPACE_DIR=str(tmp_path / "stale-startup-root"))

    try:
        shared.update_workspace_root(str(first))
        assert get_workspace_root() == str(first.resolve())
        assert shared.WORKSPACE_DIR == str(first.resolve())
        assert registry.workspace_dir == str(first.resolve())
        assert task_tools._get_workspace_root() == str(first.resolve())
        assert workspace_editor_plugin._get_workspace_root() == str(first.resolve())

        shared.update_workspace_root(str(second))
        assert registry.workspace_dir == str(second.resolve())
        assert task_tools._get_workspace_root() == str(second.resolve())
        assert workspace_editor_plugin._get_workspace_root() == str(second.resolve())
    finally:
        clear_workspace_root_override()
        shared.WORKSPACE_DIR = get_workspace_root()


@pytest.mark.unit
def test_workspace_runtime_honors_external_settings_file(monkeypatch, tmp_path):
    from app.core.config.workspace_runtime import (
        clear_workspace_root_override,
        get_workspace_root,
    )

    workspace = tmp_path / "portable-workspace"
    settings_path = tmp_path / "user_settings.json"
    settings_path.write_text(
        json.dumps({"storage": {"workspace_dir": str(workspace)}}),
        encoding="utf-8",
    )
    monkeypatch.delenv("KOTO_WORKSPACE_DIR", raising=False)
    monkeypatch.setenv("KOTO_USER_SETTINGS_PATH", str(settings_path))
    clear_workspace_root_override()

    try:
        assert get_workspace_root() == str(workspace.resolve())
    finally:
        clear_workspace_root_override()


@pytest.mark.unit
def test_workspace_reload_preserves_explicit_environment_override(monkeypatch, tmp_path):
    from app.core.config.workspace_runtime import (
        clear_workspace_root_override,
        reload_workspace_root,
        set_workspace_root,
    )

    stale = tmp_path / "stale-runtime-root"
    environment_root = tmp_path / "environment-root"
    monkeypatch.setenv("KOTO_WORKSPACE_DIR", str(environment_root))
    set_workspace_root(stale)

    try:
        assert reload_workspace_root() == str(environment_root.resolve())
    finally:
        clear_workspace_root_override()
