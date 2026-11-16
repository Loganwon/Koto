from __future__ import annotations

from unittest.mock import MagicMock


def test_auto_catalog_default_settings_path_uses_canonical_settings(
    monkeypatch, tmp_path
):
    from app.core.config import user_settings
    from app.core.services.auto_catalog_scheduler import AutoCatalogScheduler

    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", str(settings_file))

    auto_catalog = AutoCatalogScheduler()

    assert auto_catalog.settings_file == str(settings_file)


def test_auto_catalog_default_backup_lives_under_workspace(monkeypatch, tmp_path):
    from app.core.config import workspace_runtime
    from app.core.services.auto_catalog_scheduler import AutoCatalogScheduler

    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}", encoding="utf-8")
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(workspace_runtime, "get_workspace_root", lambda: str(workspace))

    auto_catalog = AutoCatalogScheduler(settings_file=str(settings_file))

    assert auto_catalog.get_backup_directory() == str(
        workspace / "_organize" / "_backups"
    )


def test_auto_catalog_registers_canonical_trigger(monkeypatch, tmp_path):
    from app.core.services.auto_catalog_scheduler import AutoCatalogScheduler

    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}", encoding="utf-8")
    trigger = MagicMock()
    trigger.trigger_id = "trigger-1"
    trigger.job_payload = {"preset_key": "settings_auto_catalog"}
    registry = MagicMock()
    registry.list_all.return_value = [trigger]
    monkeypatch.setattr(
        "app.core.jobs.trigger_registry.get_trigger_registry", lambda: registry
    )

    auto_catalog = AutoCatalogScheduler(settings_file=str(settings_file))
    auto_catalog._register_scheduled_task()

    registry.update.assert_called_once()
    registry.start.assert_called_once_with(active_trigger_ids={"trigger-1"})
    assert auto_catalog.catalog_trigger_id == "trigger-1"


def test_auto_catalog_disable_removes_registered_trigger(tmp_path):
    from app.core.services.auto_catalog_scheduler import AutoCatalogScheduler

    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}", encoding="utf-8")
    auto_catalog = AutoCatalogScheduler(settings_file=str(settings_file))
    registry = MagicMock()
    auto_catalog.trigger_registry = registry
    auto_catalog.catalog_trigger_id = "trigger-1"

    auto_catalog._cancel_scheduled_task()

    registry.remove.assert_called_once_with("trigger-1")
    assert auto_catalog.catalog_trigger_id is None


def test_auto_catalog_disable_removes_persisted_trigger_after_restart(
    monkeypatch, tmp_path
):
    from app.core.services.auto_catalog_scheduler import AutoCatalogScheduler

    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}", encoding="utf-8")
    trigger = MagicMock()
    trigger.trigger_id = "persisted-trigger"
    trigger.job_payload = {"preset_key": "settings_auto_catalog"}
    registry = MagicMock()
    registry.list_all.return_value = [trigger]
    monkeypatch.setattr(
        "app.core.jobs.trigger_registry.get_trigger_registry", lambda: registry
    )
    auto_catalog = AutoCatalogScheduler(settings_file=str(settings_file))

    auto_catalog._cancel_scheduled_task()

    registry.remove.assert_called_once_with("persisted-trigger")
    assert auto_catalog.catalog_trigger_id is None


def test_trigger_registry_scopes_managed_start_to_requested_ids(monkeypatch):
    from app.core.jobs import trigger_registry as trigger_module

    monkeypatch.setattr(
        trigger_module.TriggerRegistry, "_load_persisted", lambda self: None
    )
    monkeypatch.setattr(
        trigger_module.TriggerRegistry, "ensure_recommended_triggers", lambda self: None
    )
    thread = MagicMock()
    monkeypatch.setattr(trigger_module.threading, "Thread", lambda **_kwargs: thread)

    registry = trigger_module.TriggerRegistry()
    registry.start(active_trigger_ids={"catalog"})
    registry.start(active_trigger_ids={"another"})

    assert registry._active_trigger_ids == {"catalog", "another"}
    assert thread.start.call_count == 2
