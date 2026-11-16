from __future__ import annotations

import ast
import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_runtime_and_personal_data_stay_ignored() -> None:
    ignore_rules = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert {
        "/.codex-runtime/",
        "config/file_rag_index/",
        "config/memory_rag_index/",
        "config/suggestions.db",
        "config/test_*.db",
        "config/user_behavior.db",
        "/config/kb_config.json",
        "/app/core/workspace/calendar/events.json",
        "/app/core/workspace/reminders/reminders.json",
        "/app/core/workspace/tasks/scheduled_tasks.json",
        "/data/calendar/",
        "/data/auth/",
        "/data/reminders/",
        "/data/secrets/",
        "/data/tasks/",
        "/data/*.json.bak",
        "/data/db/*.sqlite*",
        "/data/file_rag_index/",
        "/data/rag_index/",
    } <= ignore_rules


@pytest.mark.unit
def test_mutable_runtime_defaults_live_outside_source_config(monkeypatch) -> None:
    from app.core.agent.file_task_followup import _default_store_path as followup_path
    from app.core.agent.file_task_session_store import (
        _default_store_path as summary_path,
    )
    from app.core.agent.file_task_session_store import _plan_store_path as plan_path
    from app.core.config.runtime_storage import runtime_data_path, runtime_database_path
    from app.core.services.kb_config import _default_config_path as kb_path

    for variable in (
        "KOTO_FILE_TASK_FOLLOWUP_PATH",
        "KOTO_FILE_TASK_SUMMARY_PATH",
        "KOTO_FILE_TASK_PLAN_PATH",
        "KOTO_KB_CONFIG_PATH",
        "KOTO_DB_DIR",
        "KOTO_RUNTIME_DATA_DIR",
        "KOTO_FILE_INDEX_PATH",
        "KOTO_RATING_DB_PATH",
        "KOTO_SHADOW_OBSERVATIONS_PATH",
        "KOTO_TOKEN_USAGE_PATH",
        "KOTO_PROACTIVE_QUEUE_PATH",
        "KOTO_TRIGGERS_PATH",
        "KOTO_RAG_INDEX_DIR",
        "KOTO_FILE_NETWORK_DB_PATH",
        "KOTO_MEMORY_PATH",
    ):
        monkeypatch.delenv(variable, raising=False)

    for path in (followup_path(), summary_path(), plan_path(), kb_path()):
        assert path.parent.name != "config"
        assert path.parent.name == "data"

    assert runtime_database_path("koto_checkpoints.sqlite").parent.name == "db"
    assert runtime_database_path("koto_checkpoints.sqlite").parent.parent.name == "data"
    assert runtime_data_path("file_index.json").parent.name == "data"
    assert runtime_data_path("shadow_observations.json").parent.name == "data"


@pytest.mark.unit
def test_memory_consumers_use_the_canonical_runtime_path() -> None:
    morning = (ROOT / "app/core/services/morning_brief.py").read_text(encoding="utf-8")
    telegram = (ROOT / "app/core/services/telegram_bot.py").read_text(encoding="utf-8")

    assert "_default_memory_path" in morning
    assert "_default_memory_path" in telegram
    assert '"config" / "memory.json"' not in morning
    assert '"config" / "memory.json"' not in telegram


@pytest.mark.unit
def test_addon_state_defaults_use_runtime_data(monkeypatch, tmp_path: Path) -> None:
    from app.core.agent.addons import audit, store

    monkeypatch.delenv("KOTO_ADDON_AUDIT_DB_PATH", raising=False)
    monkeypatch.delenv("KOTO_ADDON_REGISTRY_PATH", raising=False)
    monkeypatch.delenv("KOTO_DB_DIR", raising=False)
    monkeypatch.setenv("KOTO_RUNTIME_DATA_DIR", str(tmp_path / "data"))
    missing_legacy = lambda *_parts: tmp_path / "missing"  # noqa: E731
    monkeypatch.setattr(audit, "legacy_config_path", missing_legacy)
    monkeypatch.setattr(store, "legacy_config_path", missing_legacy)

    assert audit._default_path().parent.name == "db"
    assert audit._default_path().parent.parent.name == "data"
    assert store._default_store_path().parent.name == "data"


@pytest.mark.unit
def test_web_security_state_does_not_default_to_source_config() -> None:
    auth_source = (ROOT / "web/blueprints/auth.py").read_text(encoding="utf-8")
    factory_source = (ROOT / "web/app_factory.py").read_text(encoding="utf-8")
    library_source = (ROOT / "web/files/work_file_library.py").read_text(
        encoding="utf-8"
    )

    assert '"config/users.json"' not in auth_source
    assert '"config/activation_codes.json"' not in auth_source
    assert '/ "config" / "jwt_secret.txt"' not in factory_source
    assert 'config_dir / "work_file_library.db"' not in library_source


@pytest.mark.unit
def test_file_analyzer_does_not_silently_collect_training_samples() -> None:
    source = (ROOT / "app/core/services/file_analyzer.py").read_text(encoding="utf-8")

    assert "_save_training_sample" not in source
    assert "file_classify_samples.jsonl" not in source


@pytest.mark.unit
def test_sqlite_runtime_migration_preserves_all_shared_tables(tmp_path: Path) -> None:
    from app.core.config.runtime_storage import prepare_runtime_database

    legacy = tmp_path / "legacy" / "koto_checkpoints.sqlite"
    target = tmp_path / "data" / "db" / "koto_checkpoints.sqlite"
    legacy.parent.mkdir(parents=True)
    with sqlite3.connect(legacy) as connection:
        connection.execute("CREATE TABLE checkpoints (id TEXT PRIMARY KEY)")
        connection.execute("CREATE TABLE koto_tasks (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO checkpoints VALUES ('checkpoint-1')")
        connection.execute("INSERT INTO koto_tasks VALUES ('task-1')")

    result = prepare_runtime_database(target, legacy_paths=(legacy,))

    assert result == target
    assert legacy.is_file()
    with sqlite3.connect(target) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"checkpoints", "koto_tasks"} <= tables
        assert connection.execute("SELECT id FROM checkpoints").fetchone() == (
            "checkpoint-1",
        )
        assert connection.execute("SELECT id FROM koto_tasks").fetchone() == ("task-1",)


@pytest.mark.unit
def test_plain_runtime_migration_keeps_legacy_file(tmp_path: Path) -> None:
    from app.core.config.runtime_storage import migrate_legacy_file

    legacy = tmp_path / "config" / "shadow_observations.json"
    target = tmp_path / "data" / "shadow_observations.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"enabled": true}', encoding="utf-8")

    result = migrate_legacy_file(target, legacy_paths=(legacy,))

    assert result == target
    assert legacy.read_text(encoding="utf-8") == '{"enabled": true}'
    assert target.read_text(encoding="utf-8") == '{"enabled": true}'


@pytest.mark.unit
def test_runtime_directory_migration_keeps_legacy_index(tmp_path: Path) -> None:
    from app.core.config.runtime_storage import migrate_legacy_directory

    legacy = tmp_path / "config" / "rag_index"
    target = tmp_path / "data" / "rag_index"
    legacy.mkdir(parents=True)
    (legacy / "metadata.json").write_text('{"count": 2}', encoding="utf-8")

    result = migrate_legacy_directory(target, legacy_paths=(legacy,))

    assert result == target
    assert (legacy / "metadata.json").is_file()
    assert (target / "metadata.json").read_text(encoding="utf-8") == '{"count": 2}'


@pytest.mark.unit
def test_kb_config_writes_to_selected_runtime_store(tmp_path: Path) -> None:
    from app.core.services.kb_config import KBConfig

    knowledge_root = tmp_path / "knowledge"
    knowledge_root.mkdir()
    runtime_config = tmp_path / "runtime" / "kb_config.json"

    config = KBConfig(runtime_config)
    assert config.set_root(str(knowledge_root)) is True

    assert runtime_config.is_file()
    persisted = json.loads(runtime_config.read_text(encoding="utf-8"))
    assert persisted["root_dir"] == str(knowledge_root.resolve())


@pytest.mark.unit
def test_pytest_sources_do_not_target_repository_test_databases() -> None:
    for relative_path in ("tests/test_trigger_params_integration.py",):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "config/test_" not in source


@pytest.mark.unit
def test_smart_features_script_remains_a_manual_isolated_demo() -> None:
    path = ROOT / "tests/test_smart_features.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    collected_functions = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]

    assert collected_functions == []
    assert "TemporaryDirectory(" in source
    assert "os.chdir(temp_dir)" in source
