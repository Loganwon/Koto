from __future__ import annotations

import json
import threading
import time

import pytest

from src.startup_events import SCHEMA_VERSION, StartupEventRecorder


def test_startup_event_recorder_writes_stable_jsonl_schema(tmp_path) -> None:
    path = tmp_path / "logs" / "startup_events.jsonl"
    recorder = StartupEventRecorder(
        path,
        session_id="session-a",
        parent_session_id="session-parent",
    )

    payload = recorder.record("backend_port_selected", port=5001, used_fallback=True)
    persisted = json.loads(path.read_text(encoding="utf-8"))

    assert persisted == payload
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["session_id"] == "session-a"
    assert payload["parent_session_id"] == "session-parent"
    assert payload["event"] == "backend_port_selected"
    assert payload["port"] == 5001
    assert payload["used_fallback"] is True
    assert payload["elapsed_ms"] >= 0
    assert payload["timestamp"].endswith("+00:00")


def test_startup_event_recorder_redacts_sensitive_details(tmp_path) -> None:
    recorder = StartupEventRecorder(tmp_path / "events.jsonl")

    payload = recorder.record(
        "desktop_start",
        api_key="sk-private",
        launch_token="private-token",
        reason="ordinary",
    )

    assert payload["api_key"] == "[redacted]"
    assert payload["launch_token"] == "[redacted]"
    assert payload["reason"] == "ordinary"
    assert "sk-private" not in (tmp_path / "events.jsonl").read_text(encoding="utf-8")


def test_startup_event_recorder_serializes_concurrent_writers(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    recorder = StartupEventRecorder(path)
    threads = [
        threading.Thread(
            target=recorder.record, args=("window_shown",), kwargs={"index": i}
        )
        for i in range(20)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 20
    assert {row["index"] for row in rows} == set(range(20))


def test_startup_event_recorder_rejects_unbounded_event_names(tmp_path) -> None:
    recorder = StartupEventRecorder(tmp_path / "events.jsonl")

    with pytest.raises(ValueError, match="invalid startup event name"):
        recorder.record("Backend Ready!")


def test_startup_event_recorder_supports_process_origin_and_observed_time(
    tmp_path,
) -> None:
    now = time.monotonic()
    recorder = StartupEventRecorder(
        tmp_path / "events.jsonl", started_at_monotonic=now - 2.0
    )

    payload = recorder.record("python_runtime_ready", occurred_at_monotonic=now - 1.25)

    assert 740 <= payload["elapsed_ms"] <= 760
