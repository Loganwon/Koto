from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from flask import Flask

from app.core.agent import frontend_observability as frontend
from app.core.tasks.frontend_action_store import FrontendActionStore
from app.core.tasks.task_ledger import TaskLedger


@pytest.fixture
def actions(tmp_path, monkeypatch):
    path = str(tmp_path / "ledger.sqlite")
    ledger = TaskLedger(path)
    monkeypatch.setattr(frontend, "get_ledger", lambda: ledger)
    monkeypatch.setattr(frontend, "_append_file", lambda events: None)
    frontend._ACTIONS.clear()
    frontend._DOCUMENT_OPERATION_LEDGER.clear()
    frontend._EVENTS.clear()

    def reopen():
        nonlocal ledger
        ledger._conn.close()
        ledger = TaskLedger(path)
        frontend._ACTIONS.clear()
        frontend._DOCUMENT_OPERATION_LEDGER.clear()
        return ledger

    yield lambda: ledger, reopen, tmp_path
    frontend._ACTIONS.clear()
    frontend._DOCUMENT_OPERATION_LEDGER.clear()
    frontend._EVENTS.clear()
    ledger._conn.close()


def _scope(**patch):
    return dict(
        request_id="request-1",
        session_id="conversation-1",
        frontend_session_id="browser-1",
        document_path="report.txt",
        file_id="file-1",
        tenant_id="local",
        principal_id="user-1",
        **patch,
    )


def _queue(action_id="edit-1", *, action="ui_apply_edit", scope=None, **options):
    return frontend.enqueue_frontend_action(
        action=action,
        action_id=action_id,
        trusted_scope=scope or _scope(),
        operation_id=action_id,
        options={"expected_revision": "revision-1", **options},
    )


def _deliver():
    return frontend.next_frontend_action(session_id="browser-1")["action"]


def _complete(delivery, result, **patch):
    return frontend.complete_frontend_action(
        id=delivery["id"],
        browser_id=delivery["browser_id"],
        delivery_token=delivery["delivery_token"],
        request_id=delivery["request_id"],
        session_id=delivery["session_id"],
        result=result,
        **patch,
    )


def _receipt(**patch):
    return dict(
        document_path="report.txt",
        file_id="file-1",
        revision_before="revision-1",
        revision_after="revision-2",
        applied=True,
        persisted=False,
        before_text="old",
        after_text="new",
        **patch,
    )


@pytest.mark.parametrize(
    "cut", ["queued", "delivered", "editor_done", "receipt_lost", "save_done"]
)
def test_restart_at_five_handoff_boundaries_never_repeats_a_write(actions, cut):
    current, reopen, tmp_path = actions
    source = tmp_path / "report.txt"
    editor = tmp_path / "editor-buffer.txt"
    source.write_text("old", encoding="utf-8")
    editor.write_text("old", encoding="utf-8")
    writes = []
    queued = _queue(action="ui_save" if cut == "save_done" else "ui_apply_edit")
    assert queued["success"]
    delivery = None if cut == "queued" else _deliver()
    if cut in {"editor_done", "receipt_lost"}:
        editor.write_text("new", encoding="utf-8")
        writes.append("editor")
    if cut == "save_done":
        source.write_text("new", encoding="utf-8")
        writes.append("source")
    # Only receipt_lost has a full receipt durably recorded by the browser.
    # A crash after a real edit/save but before this step remains unknown.
    if cut == "receipt_lost":
        browser_receipt = tmp_path / "browser-receipt.json"
        browser_receipt.write_text(
            json.dumps(dict(delivery=delivery, result=_receipt())), encoding="utf-8"
        )
    reopen()
    if cut == "queued":
        delivery = _deliver()
        editor.write_text("new", encoding="utf-8")
        writes.append("editor")
        assert _complete(delivery, _receipt())["action"]["status"] == "completed"
    elif cut == "receipt_lost":
        saved = json.loads(browser_receipt.read_text(encoding="utf-8"))
        assert (
            _complete(saved["delivery"], saved["result"])["action"]["status"]
            == "completed"
        )
        reopen()
        # Lost acknowledgement retries only the receipt, even after another restart.
        duplicate = _complete(
            saved["delivery"], {**saved["result"], "after_text": "must not overwrite"}
        )
        assert duplicate["duplicate"]
        assert duplicate["action"]["result"]["after_text"] == "new"
    else:
        # Simulate expiry of the execution lease, not a claim that the UI ran.
        current()._conn.execute("UPDATE koto_frontend_actions SET lease_until=0")
        current()._conn.commit()
        assert (
            frontend.frontend_action_status("edit-1")["action"]["status"] == "unknown"
        )
        assert _deliver() is None
        retry = _queue(action="ui_save" if cut == "save_done" else "ui_apply_edit")
        assert retry["action"]["status"] == "unknown"
        blocked = _queue("new-id")
        assert not blocked["success"] and blocked["status"] == "blocked"
        assert _queue("inspect", action="ui_read_context")["success"]
        assert _deliver()["action"] == "ui_read_context"
    assert len(writes) == (0 if cut == "delivered" else 1)
    assert source.read_text(encoding="utf-8") == (
        "new" if cut == "save_done" else "old"
    )
    assert _deliver() is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("browser_id", "other-browser"),
        ("delivery_token", "forged"),
        ("request_id", "other-request"),
        ("session_id", "other-conversation"),
    ],
)
def test_wrong_delivery_scope_cannot_forge_or_complete_a_receipt(actions, field, value):
    _queue()
    delivered = _deliver()
    payload = dict(
        id=delivered["id"],
        browser_id=delivered["browser_id"],
        delivery_token=delivered["delivery_token"],
        request_id=delivered["request_id"],
        session_id=delivered["session_id"],
        result=_receipt(),
    )
    payload[field] = value
    assert frontend.complete_frontend_action(**payload)["http_status"] == 403
    assert frontend.frontend_action_status("edit-1")["action"]["status"] == "delivered"
    assert _complete(delivered, _receipt())["success"]


def test_unknown_mutation_blocks_new_browser_and_reopened_document_identity(actions):
    current, reopen, _ = actions
    _queue()
    delivered = _deliver()
    current()._conn.execute("UPDATE koto_frontend_actions SET lease_until=0")
    current()._conn.commit()
    reopen()
    new_scope = {
        **_scope(),
        "frontend_session_id": "new-browser",
        "file_id": "new-file-id",
        "request_id": "new-request",
    }
    blocked = _queue("new-id", scope=new_scope)
    assert blocked["status"] == "blocked"
    assert (
        _queue(
            "path-alias", scope={**new_scope, "document_path": "folder/../report.txt"}
        )["status"]
        == "blocked"
    )
    assert _complete(delivered, _receipt())["action"]["status"] == "completed"
    assert _queue("new-id", scope=new_scope)["success"]


def test_document_mismatch_and_unverified_success_do_not_unlock_a_mutation(actions):
    _queue()
    delivery = _deliver()
    wrong = {**_receipt(), "document_path": "secret.txt"}
    assert _complete(delivery, wrong)["http_status"] == 409
    incomplete = {"document_path": "report.txt", "file_id": "file-1"}
    assert _complete(delivery, incomplete)["action"]["status"] == "unknown"
    assert _queue("bypass")["status"] == "blocked"
    assert _complete(delivery, _receipt())["action"]["status"] == "completed"


def test_cancel_and_expiry_before_dispatch_never_reach_a_browser(actions):
    current, _, _ = actions
    _queue(scope={**_scope(), "task_id": "task-cancel", "run_id": "run-cancel"})
    current().cancel_task("task-cancel")
    assert _deliver() is None
    assert frontend.frontend_action_status("edit-1")["action"]["status"] == "cancelled"
    _queue("expired")
    frontend._action_store().expire("expired")
    assert _deliver() is None
    assert not frontend.complete_frontend_action(
        id="expired", browser_id="browser-1", delivery_token="forged", result=_receipt()
    )["success"]


def test_status_is_request_scoped_and_never_exposes_delivery_capability(actions):
    _queue()
    _deliver()
    status = frontend.frontend_action_status("edit-1", trusted_scope=_scope())
    assert status["success"]
    assert "delivery_token" not in status["action"]
    assert not frontend.frontend_action_status(
        "edit-1", trusted_scope={**_scope(), "request_id": "wrong"}
    )["success"]


def test_full_receipt_survives_restart_and_retention_leaves_a_dedup_tombstone(actions):
    current, reopen, _ = actions
    text = "完整文档" * 4000
    _queue(anchor_text=text, replacement=text[::-1])
    delivery = _deliver()
    receipt = {**_receipt(), "before_text": text, "after_text": text[::-1]}
    assert _complete(delivery, receipt)["success"]
    reopen()
    assert frontend.frontend_action_status("edit-1")["action"]["result"] == receipt
    current()._conn.execute(
        "UPDATE koto_frontend_actions SET updated_ts=?", (time.time() - 8 * 86400,)
    )
    current()._conn.commit()
    assert frontend._action_store().purge() == 1
    repeat = _queue(anchor_text=text, replacement=text[::-1])
    assert repeat["duplicate"] and repeat["action"]["receipt_expired"]
    assert "result" not in repeat["action"]
    assert _deliver() is None


def test_api_missing_capability_and_wrong_scope_fail_closed(actions):
    from app.api.mcp_routes import mcp_bp

    app = Flask(__name__)
    app.register_blueprint(mcp_bp)
    client = app.test_client()
    _queue()
    response = client.get("/api/mcp/frontend-action?session_id=wrong-browser")
    assert response.json["action"] is None
    delivery = client.get("/api/mcp/frontend-action?session_id=browser-1").json[
        "action"
    ]
    assert (
        client.post(
            "/api/mcp/frontend-action-result",
            json={"id": delivery["id"], "result": _receipt()},
        ).status_code
        == 403
    )
    payload = dict(
        id=delivery["id"],
        browser_id=delivery["browser_id"],
        delivery_token=delivery["delivery_token"],
        request_id=delivery["request_id"],
        session_id=delivery["session_id"],
        result=_receipt(),
    )
    assert (
        client.post("/api/mcp/frontend-action-result", json=payload).status_code == 200
    )
    assert client.post("/api/mcp/frontend-action-result", json=payload).json[
        "duplicate"
    ]


def test_two_workers_share_one_atomic_dispatch_owner(actions):
    current, _, _ = actions
    _queue()
    second_ledger = TaskLedger(current()._db_path)
    try:
        stores = [frontend._action_store(), FrontendActionStore(second_ledger)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            dispatched = list(
                pool.map(lambda store: store.dispatch("browser-1"), stores)
            )
        assert len([item for item in dispatched if item]) == 1
        delivery = next(item for item in dispatched if item)
        assert _complete(delivery, _receipt())["success"]
    finally:
        second_ledger._conn.close()


def test_public_supervision_arguments_cannot_grant_a_document_scope(
    actions, monkeypatch
):
    from app.api.mcp_routes import mcp_bp

    app = Flask(__name__)
    app.register_blueprint(mcp_bp)
    monkeypatch.setenv("KOTO_MCP_API_KEY", "test-key")
    for arguments in (
        {"action": "ui_apply_edit", "options": {"file_id": "file-1"}},
        {"action": "click", "trusted_scope": _scope()},
    ):
        response = app.test_client().post(
            "/api/mcp",
            headers={"X-Koto-MCP-Key": "test-key"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "koto_frontend_action", "arguments": arguments},
            },
        )
        data = json.loads(response.json["result"]["content"][0]["text"])
        assert not data["success"]
    assert frontend.frontend_action_status()["actions"] == []


def test_real_kernel_binds_queued_document_action_to_task_cancellation(
    actions, monkeypatch
):
    from app.core.agent.kernel_agent import KernelAgent
    from app.core.agent.tool_registry import ToolRegistry
    from app.core.agent.toolkits.builtin.document_ui_plugin import DocumentUIPlugin

    current, _, _ = actions
    ledger = current()
    frontend.record_frontend_event(
        {
            "type": "snapshot",
            "session_id": "browser-1",
            "details": {
                "workspace": {
                    "activeTabPath": "report.txt",
                    "fileId": "file-1",
                    "fileType": "text",
                }
            },
        }
    )
    context = frontend.bind_frontend_document_context(
        None,
        {
            "frontend_session_id": "browser-1",
            "document_path": "report.txt",
            "file_id": "file-1",
        },
        session_id="conversation-1",
    )
    queued = threading.Event()
    original_enqueue = frontend.enqueue_frontend_action
    captured = []

    def observe_enqueue(*args, **kwargs):
        response = original_enqueue(*args, **kwargs)
        captured.append(response)
        queued.set()
        return response

    monkeypatch.setattr(frontend, "enqueue_frontend_action", observe_enqueue)
    calls = []

    class Provider:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return iter(
                [
                    {
                        "content": "",
                        "stream_final": True,
                        "tool_calls": [
                            {
                                "id": "edit-call",
                                "name": "ui_apply_edit",
                                "args": {
                                    "expected_revision": "v1",
                                    "anchor_text": "old",
                                    "replacement": "new",
                                    "operation_id": "edit-one",
                                },
                            }
                        ],
                    }
                ]
            )

    registry = ToolRegistry()
    registry.register_plugin(DocumentUIPlugin())
    agent = KernelAgent(
        llm_provider=Provider(),
        tool_registry=registry,
        enable_pii_filter=False,
        enable_output_validation=False,
        use_tool_router=False,
        allow_model_fallback=False,
    )
    steps, errors = [], []

    def run():
        try:
            steps.extend(
                agent.run(
                    "edit document",
                    session_id="conversation-1",
                    task_id="real-task",
                    run_id="real-run",
                    task_ledger=ledger,
                    addon_invocation_context=context,
                    stream_events=True,
                )
            )
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert queued.wait(2), "Kernel never queued the host-bound document tool"
        assert captured[0]["success"]
        item = captured[0]["action"]
        assert (item["task_id"], item["run_id"]) == ("real-task", "real-run")
        ledger.cancel_task("real-task")
        assert _deliver() is None
        worker.join(2)
        assert not worker.is_alive()
        assert errors == []
        assert (
            frontend.frontend_action_status(item["id"])["action"]["status"]
            == "cancelled"
        )
        assert ledger.get("real-task").status.value == "cancelled"
        assert len(calls) == 1
    finally:
        ledger.cancel_task("real-task")
        worker.join(2)
