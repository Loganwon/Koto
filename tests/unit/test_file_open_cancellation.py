from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.file_assistant import (
    FileAssistantService,
    FileOpenCancellationRegistry,
    FileOpenCancelledError,
)


def test_registry_preserves_cancel_that_arrives_before_parse_begins():
    registry = FileOpenCancellationRegistry()
    registry.cancel("session-a", "request_12345678")

    token = registry.begin("session-a", "request_12345678")

    with pytest.raises(FileOpenCancelledError):
        token.raise_if_cancelled()


def test_registry_isolates_same_request_id_between_sessions():
    registry = FileOpenCancellationRegistry()
    registry.cancel("session-a", "request_12345678")

    other_session = registry.begin("session-b", "request_12345678")

    assert other_session.cancelled is False


def test_file_assistant_checks_cancellation_before_reading(tmp_path: Path):
    target = tmp_path / "large.txt"
    target.write_text("content that must not be read", encoding="utf-8")

    with pytest.raises(FileOpenCancelledError):
        FileAssistantService().parse_editor_file(
            target,
            file_id="abc123",
            cancel_check=lambda: (_ for _ in ()).throw(FileOpenCancelledError()),
        )


@pytest.mark.parametrize("value", ["", "short", "bad id", "../request_12345678"])
def test_registry_rejects_untrusted_request_ids(value: str):
    with pytest.raises(ValueError):
        FileOpenCancellationRegistry.validate_request_id(value)


def test_cancel_endpoint_stops_request_when_cancel_arrives_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from flask import Flask

    import web.blueprints.workspace_assistant as routes

    app = Flask(__name__)
    app.secret_key = "cancel-test"
    app.register_blueprint(routes.workspace_assistant_bp)
    request_id = "request_early_cancel_123"
    target = tmp_path / "large.pdf"
    target.write_bytes(b"%PDF")
    monkeypatch.setattr(
        routes._OPEN_FILE_BY_PATH,
        "prepare",
        lambda **_kwargs: SimpleNamespace(
            target_path=target,
            tmp_path=target,
            extension=".pdf",
        ),
    )

    def fail_if_parsed(*_args, **_kwargs):
        raise AssertionError("cancelled file must not enter the parser")

    monkeypatch.setattr(routes._FILE_ASSISTANT, "parse_editor_file", fail_if_parsed)

    with app.test_client() as client:
        cancel = client.post(
            "/api/v1/workspace/open_file/cancel",
            json={"open_request_id": request_id},
        )
        opened = client.post(
            "/api/v1/workspace/open_file_by_path",
            json={"path": "large.pdf", "open_request_id": request_id},
        )

    assert cancel.status_code == 200
    assert cancel.get_json()["status"] == "cancellation_requested"
    assert opened.status_code == 409
    assert opened.get_json()["status"] == "cancelled"
