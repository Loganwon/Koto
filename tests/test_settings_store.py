"""Durability and concurrency tests for the shared user-settings store."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import app.core.config.settings_store as settings_store
from app.core.config.settings_store import (
    atomic_update_settings,
    load_settings_document,
)


def test_concurrent_thread_patches_preserve_unrelated_sections(tmp_path):
    settings_path = tmp_path / "user_settings.json"

    def write(index: int) -> None:
        atomic_update_settings(
            settings_path,
            {f"worker_{index}": {"saved": True, "index": index}},
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(16)))

    persisted = json.loads(settings_path.read_text(encoding="utf-8"))
    for index in range(16):
        assert persisted[f"worker_{index}"] == {"saved": True, "index": index}


def test_concurrent_process_patches_do_not_clobber_each_other(tmp_path):
    settings_path = tmp_path / "user_settings.json"
    script = (
        "import os;"
        "from app.core.config.settings_store import atomic_update_settings;"
        "atomic_update_settings(os.environ['SETTINGS_PATH'],"
        "{os.environ['WORKER_KEY']: {'saved': True}})"
    )
    processes = []
    for index in range(6):
        env = os.environ.copy()
        env["SETTINGS_PATH"] = str(settings_path)
        env["WORKER_KEY"] = f"process_{index}"
        env["PYTHONPATH"] = os.pathsep.join([os.getcwd(), env.get("PYTHONPATH", "")])
        processes.append(
            subprocess.Popen(
                [sys.executable, "-c", script],
                cwd=os.getcwd(),
                env=env,
            )
        )

    for process in processes:
        assert process.wait(timeout=20) == 0

    persisted = json.loads(settings_path.read_text(encoding="utf-8"))
    for index in range(6):
        assert persisted[f"process_{index}"] == {"saved": True}


def test_corrupt_primary_recovers_last_known_good_backup(tmp_path):
    settings_path = tmp_path / "user_settings.json"
    atomic_update_settings(settings_path, {"appearance": {"theme": "forest"}})
    settings_path.write_text("{broken", encoding="utf-8")

    recovered = load_settings_document(settings_path)

    assert recovered["appearance"]["theme"] == "forest"
    assert json.loads(settings_path.read_text(encoding="utf-8")) == recovered
    assert list(tmp_path.glob("user_settings.json.corrupt-*"))


def test_replace_top_level_does_not_remove_other_sections(tmp_path):
    settings_path = tmp_path / "user_settings.json"
    atomic_update_settings(
        settings_path,
        {
            "appearance": {"theme": "ocean", "ui_zoom": 1.2},
            "skills": {"alpha": {"enabled": True}},
        },
    )

    updated = atomic_update_settings(
        settings_path,
        {"appearance": {"theme": "light"}},
        replace_top_level={"appearance"},
    )

    assert updated["appearance"] == {"theme": "light"}
    assert updated["skills"] == {"alpha": {"enabled": True}}


def test_stale_crash_lock_is_reclaimed(tmp_path):
    settings_path = tmp_path / "user_settings.json"
    lock_path = tmp_path / "user_settings.json.lock"
    lock_path.write_text("dead-process", encoding="ascii")
    stale_time = time.time() - 30
    os.utime(lock_path, (stale_time, stale_time))

    updated = atomic_update_settings(settings_path, {"appearance": {"theme": "ocean"}})

    assert updated["appearance"]["theme"] == "ocean"
    assert not lock_path.exists()


def test_transient_windows_replace_error_is_retried(tmp_path, monkeypatch):
    settings_path = tmp_path / "user_settings.json"
    original_replace = settings_store.os.replace
    attempts = {"count": 0}

    def flaky_replace(source, target):
        attempts["count"] += 1
        if attempts["count"] == 1:
            error = PermissionError("temporarily locked")
            error.winerror = 32
            raise error
        return original_replace(source, target)

    monkeypatch.setattr(settings_store.os, "replace", flaky_replace)

    updated = atomic_update_settings(settings_path, {"appearance": {"ui_zoom": 1.1}})

    assert updated["appearance"]["ui_zoom"] == 1.1
    assert attempts["count"] >= 2
