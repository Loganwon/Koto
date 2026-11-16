from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from src import external_open
from src.external_open import (
    consume_external_open_requests,
    enqueue_external_open_arguments,
    enqueue_external_open_requests,
    open_default_apps_settings,
    parse_external_open_paths,
)


def test_external_open_arguments_accept_only_existing_primary_editor_files(tmp_path):
    supported = [
        tmp_path / "report.docx",
        tmp_path / "book.xlsx",
        tmp_path / "deck.pptx",
        tmp_path / "paper.pdf",
    ]
    for path in supported:
        path.write_bytes(b"fixture")
    ignored = tmp_path / "notes.txt"
    ignored.write_text("not registered", encoding="utf-8")

    result = parse_external_open_paths(
        [
            "--setup",
            str(supported[0]),
            str(ignored),
            str(supported[0]),
            *map(str, supported[1:]),
        ]
    )

    assert result == [str(path.resolve()) for path in supported]


def test_external_open_request_survives_second_process_handoff(tmp_path):
    app_root = tmp_path / "installed"
    document = tmp_path / "outside" / "report.docx"
    document.parent.mkdir()
    document.write_bytes(b"docx")

    assert enqueue_external_open_requests(app_root, [str(document)]) is True
    assert consume_external_open_requests(app_root) == [str(document.resolve())]
    assert consume_external_open_requests(app_root) == []


def test_external_open_arguments_enqueue_only_once_per_process(tmp_path, monkeypatch):
    monkeypatch.delenv("KOTO_EXTERNAL_OPEN_ARGS_ENQUEUED", raising=False)
    document = tmp_path / "report.docx"
    document.write_text("document", encoding="utf-8")

    assert enqueue_external_open_arguments(tmp_path, [str(document)]) is True
    assert enqueue_external_open_arguments(tmp_path, [str(document)]) is False
    assert consume_external_open_requests(tmp_path) == [str(document.resolve())]


def test_external_open_consumer_discards_malformed_requests(tmp_path):
    request_dir = tmp_path / ".ipc" / "open_requests"
    request_dir.mkdir(parents=True)
    malformed = request_dir / "bad.json"
    malformed.write_text("not json", encoding="utf-8")
    wrong_schema = request_dir / "wrong.json"
    wrong_schema.write_text(
        json.dumps({"schema_version": 999, "paths": [str(tmp_path / "x.docx")]}),
        encoding="utf-8",
    )

    assert consume_external_open_requests(tmp_path) == []
    assert not malformed.exists()
    assert not wrong_schema.exists()


def test_external_open_paths_are_bounded_and_deduplicated(tmp_path):
    documents = [tmp_path / f"report-{index}.docx" for index in range(20)]
    for document in documents:
        document.write_bytes(b"docx")

    result = parse_external_open_paths(
        [str(documents[0]), str(documents[0]), *map(str, documents[1:])]
    )

    assert result == [str(path.resolve()) for path in documents[:16]]


def test_external_open_consumer_processes_request_files_in_bounded_batches(tmp_path):
    documents = [tmp_path / f"report-{index}.docx" for index in range(33)]
    for document in documents:
        document.write_bytes(b"docx")
        assert enqueue_external_open_requests(tmp_path, [str(document)]) is True

    assert consume_external_open_requests(tmp_path) == [
        str(path.resolve()) for path in documents[:32]
    ]
    assert consume_external_open_requests(tmp_path) == [str(documents[32].resolve())]


def test_external_open_enqueue_cleans_partial_write_after_atomic_replace_failure(
    tmp_path, monkeypatch
):
    document = tmp_path / "report.docx"
    document.write_bytes(b"docx")

    def fail_replace(*args, **kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(external_open.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        enqueue_external_open_requests(tmp_path, [str(document)])

    request_dir = tmp_path / ".ipc" / "open_requests"
    assert list(request_dir.iterdir()) == []


def test_external_open_consumer_cleans_only_abandoned_temporary_writes(tmp_path):
    request_dir = tmp_path / ".ipc" / "open_requests"
    request_dir.mkdir(parents=True)
    abandoned = request_dir / "abandoned.tmp"
    active = request_dir / "active.tmp"
    abandoned.write_bytes(b"partial")
    active.write_bytes(b"partial")
    stale_time = time.time() - external_open._STALE_TEMP_SECONDS - 1
    os.utime(abandoned, (stale_time, stale_time))

    assert consume_external_open_requests(tmp_path) == []
    assert not abandoned.exists()
    assert active.exists()


def test_default_apps_settings_targets_koto_registration(monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr(external_open.sys, "platform", "win32")
    monkeypatch.setattr(external_open.os, "startfile", opened.append, raising=False)

    assert open_default_apps_settings() == (True, None)
    assert opened == ["ms-settings:defaultapps?registeredAppUser=Koto"]


def test_default_apps_settings_falls_back_for_older_windows(monkeypatch):
    opened: list[str] = []

    def open_uri(uri: str) -> None:
        opened.append(uri)
        if "registeredAppUser" in uri:
            raise OSError("deep link unsupported")

    monkeypatch.setattr(external_open.sys, "platform", "win32")
    monkeypatch.setattr(external_open.os, "startfile", open_uri, raising=False)

    assert open_default_apps_settings() == (True, None)
    assert opened == [
        "ms-settings:defaultapps?registeredAppUser=Koto",
        "ms-settings:defaultapps",
    ]


def test_default_apps_settings_is_desktop_only(monkeypatch):
    monkeypatch.setattr(external_open.sys, "platform", "linux")

    success, error = open_default_apps_settings()

    assert success is False
    assert "Windows" in str(error)
