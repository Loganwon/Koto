from __future__ import annotations

import pytest


@pytest.mark.integration
def test_workspace_switch_updates_ui_and_ai_runtime(monkeypatch, tmp_path):
    import web.app as app_module
    import web.shared as shared
    from app.core.agent import task_tools
    from app.core.config.workspace_runtime import get_workspace_root
    from web.runtime_context import service_registry

    previous_root = get_workspace_root()
    settings_path = tmp_path / "user_settings.json"
    target = tmp_path / "selected-workspace"
    target.mkdir()
    (target / "runtime-owner-proof.txt").write_text("ok", encoding="utf-8")
    monkeypatch.setattr(shared, "get_user_settings_path", lambda: str(settings_path))
    monkeypatch.setattr("app.core.agent.task_tools_common._WORKSPACE_ROOT", None)

    app_module.app.config["TESTING"] = True
    try:
        with app_module.app.test_client() as client:
            csrf_token = client.get("/api/csrf-token").get_json()["csrf_token"]
            response = client.post(
                "/api/v1/workspace/set_workspace_dir",
                json={"path": str(target)},
                headers={"X-CSRFToken": csrf_token},
            )
            assert response.status_code == 200, response.get_data(as_text=True)

            current = client.get("/api/v1/workspace/current_dir")
            assert current.status_code == 200
            assert current.get_json()["path"] == str(target.resolve())

            listed = client.get("/api/workspace")
            assert listed.status_code == 200
            assert "runtime-owner-proof.txt" in listed.get_json()["files"]

        expected = str(target.resolve())
        assert service_registry.workspace_dir == expected
        assert app_module.brain._runtime.get_workspace_dir() == expected
        assert task_tools._get_workspace_root() == expected
    finally:
        shared.update_workspace_root(previous_root)
