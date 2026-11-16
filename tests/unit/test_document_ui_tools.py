from __future__ import annotations

import hashlib
import time
from dataclasses import replace

import pytest

from app.core.agent import frontend_observability as frontend
from app.core.agent.kernel import ToolCall, ToolExecutor
from app.core.agent.tool_registry import ToolRegistry
from app.core.agent.toolkits.builtin.document_ui_plugin import DocumentUIPlugin

_DELIVERED = {}


def _complete_browser_action(action_id="", **kwargs):
    """Simulate the selected browser returning the actual delivery capability."""
    status = frontend.frontend_action_status(action_id).get("action") or {}
    if status.get("status") == "queued":
        frontend.next_frontend_action(session_id=status["target_session_id"])
    delivery = _DELIVERED.get(action_id, {})
    result = dict(kwargs.pop("result", {}) or {})
    expected = (delivery.get("options") or {}).get("expected_revision")
    if delivery.get("action") == "ui_apply_edit" and result.get("applied"):
        result.setdefault("revision_before", expected)
    if delivery.get("action") == "ui_save" and result.get("persisted"):
        result.setdefault("revision", expected)
    return frontend.complete_frontend_action(
        action_id=action_id,
        browser_id=delivery.get("browser_id", ""),
        delivery_token=delivery.get("delivery_token", ""),
        request_id=delivery.get("request_id", ""),
        session_id=delivery.get("session_id", ""),
        result=result,
        **kwargs,
    )


@pytest.fixture
def document_scope(monkeypatch, tmp_path):
    from app.core.tasks.task_ledger import TaskLedger

    ledger = TaskLedger(str(tmp_path / "actions.sqlite"))
    monkeypatch.setattr(frontend, "get_ledger", lambda: ledger)
    original_next = frontend.next_frontend_action
    _DELIVERED.clear()

    def receive_dispatch(*args, **kwargs):
        response = original_next(*args, **kwargs)
        if response.get("action"):
            _DELIVERED[response["action"]["id"]] = response["action"]
        return response

    monkeypatch.setattr(frontend, "next_frontend_action", receive_dispatch)
    monkeypatch.setattr(frontend, "_append_file", lambda events: None)
    frontend._EVENTS.clear()
    frontend._ACTIONS.clear()
    frontend._DOCUMENT_OPERATION_LEDGER.clear()
    frontend.record_frontend_event(
        {
            "type": "snapshot",
            "session_id": "browser-a",
            "details": {
                "workspace": {
                    "activeTabPath": "report.txt",
                    "fileId": "file123",
                    "fileType": "text",
                }
            },
        }
    )
    context = frontend.bind_frontend_document_context(
        None,
        {
            "frontend_session_id": "browser-a",
            "document_path": "report.txt",
            "file_id": "file123",
        },
        session_id="task-session",
    )
    monkeypatch.setattr(
        "app.core.config.workspace_runtime.get_workspace_root", lambda: str(tmp_path)
    )
    yield context, tmp_path
    ledger._conn.close()
    _DELIVERED.clear()
    frontend._EVENTS.clear()
    frontend._ACTIONS.clear()
    frontend._DOCUMENT_OPERATION_LEDGER.clear()


def test_scope_uses_observed_browser_and_document_not_client_permissions(
    document_scope,
):
    context, _ = document_scope
    context.require_identity()
    assert context.frontend_document_scope["allowed_operations"] == (
        "read",
        "edit",
        "save",
    )
    for patch in (
        {"file_id": "another"},
        {"document_path": "secret.txt"},
        {"frontend_session_id": "browser-b"},
    ):
        scope = {
            "frontend_session_id": "browser-a",
            "document_path": "report.txt",
            "file_id": "file123",
            **patch,
        }
        assert frontend.bind_frontend_document_context(None, scope) is None
    with pytest.raises(TypeError):
        context.frontend_document_scope["file_id"] = "another"


def test_stale_snapshot_cannot_bind_scope(document_scope):
    frontend._EVENTS[-1]["server_ts"] = time.time() - 121
    assert (
        frontend.bind_frontend_document_context(
            None,
            {
                "frontend_session_id": "browser-a",
                "document_path": "report.txt",
                "file_id": "file123",
            },
        )
        is None
    )


def test_document_tools_are_trusted_and_registered_on_existing_catalog(document_scope):
    registry = ToolRegistry()
    registry.register_plugin(DocumentUIPlugin())
    spec = registry.catalog.get("ui_apply_edit")
    assert spec.requires_invocation_context is True
    assert "invocation_context" not in spec.input_schema["properties"]
    executor = ToolExecutor(registry.catalog)
    assert not executor.invoke(ToolCall("ui_read_context")).ok
    assert not executor.invoke(
        ToolCall("ui_read_context", {"invocation_context": {}})
    ).ok


def test_action_retry_is_idempotent_and_result_cannot_be_overwritten(document_scope):
    kwargs = dict(
        action="ui_apply_edit",
        target_session_id="browser-a",
        action_id="edit-1",
        options={"replacement": "new"},
    )
    first = frontend.enqueue_frontend_action(**kwargs)
    second = frontend.enqueue_frontend_action(**kwargs)
    assert first["action"]["id"] == second["action"]["id"]
    assert len(frontend._ACTIONS) == 1
    assert frontend.next_frontend_action(session_id="browser-b")["action"] is None
    assert (
        frontend.next_frontend_action(session_id="browser-a")["action"]["id"]
        == "edit-1"
    )
    assert frontend.next_frontend_action(session_id="browser-a")["action"] is None
    _complete_browser_action(action_id="edit-1", result={"applied": True})
    duplicate = _complete_browser_action(
        action_id="edit-1", ok=False, error="contradictory retry"
    )
    assert duplicate["duplicate"] and duplicate["action"]["status"] == "completed"
    conflict = frontend.enqueue_frontend_action(
        **{**kwargs, "options": {"replacement": "different"}}
    )
    assert not conflict["success"]


def test_undelivered_timeout_expires_action_and_never_executes_later(document_scope):
    queued = frontend.enqueue_frontend_action(
        action="ui_apply_edit", target_session_id="browser-a"
    )
    waited = frontend.wait_frontend_action(
        action_id=queued["action"]["id"], timeout_ms=0
    )
    assert waited["timed_out"] and waited["action"]["status"] == "expired"
    assert frontend.next_frontend_action(session_id="browser-a")["action"] is None
    assert not _complete_browser_action(
        action_id=queued["action"]["id"], result={"applied": True}
    )["success"]


def test_completed_operation_deduplicates_after_supervision_feed_rotates(
    document_scope,
):
    kwargs = dict(
        action="ui_apply_edit",
        target_session_id="browser-a",
        action_id="stable-edit",
        options={"replacement": "new"},
    )
    frontend.enqueue_frontend_action(**kwargs)
    _complete_browser_action(action_id="stable-edit", result={"applied": True})
    for index in range(201):
        frontend.enqueue_frontend_action(
            action="snapshot", action_id=f"snapshot-{index}"
        )
    repeated = frontend.enqueue_frontend_action(**kwargs)
    assert repeated["action"]["status"] == "completed"
    assert repeated["action"]["result"]["applied"] is True
    assert all(item["id"] != "stable-edit" for item in frontend._ACTIONS)


def test_delivered_timeout_is_unknown_and_retry_does_not_execute_again(document_scope):
    kwargs = dict(
        action="ui_save",
        target_session_id="browser-a",
        action_id="slow-save",
        options={"expected_revision": "v1"},
    )
    frontend.enqueue_frontend_action(**kwargs)
    frontend.next_frontend_action(session_id="browser-a")
    waited = frontend.wait_frontend_action(action_id="slow-save", timeout_ms=0)
    assert waited["timed_out"] and waited["action"]["status"] == "delivered"
    assert frontend.enqueue_frontend_action(**kwargs)["action"]["status"] == "delivered"
    assert frontend.next_frontend_action(session_id="browser-a")["action"] is None
    _complete_browser_action(action_id="slow-save", result={"persisted": True})
    assert (
        frontend.frontend_action_status("slow-save")["action"]["status"] == "completed"
    )


@pytest.mark.parametrize("first_action", ["ui_apply_edit", "ui_save"])
@pytest.mark.parametrize("next_action", ["ui_apply_edit", "ui_save"])
def test_unconfirmed_delivered_mutation_blocks_new_operation_until_receipt(
    document_scope, first_action, next_action
):
    options = {"document_path": "report.txt", "file_id": "file123"}
    initial = dict(
        action=first_action,
        target_session_id="browser-a",
        path="report.txt",
        action_id="unknown-first",
        options=options,
    )
    frontend.enqueue_frontend_action(**initial)
    writes = [frontend.next_frontend_action(session_id="browser-a")["action"]["id"]]
    assert (
        frontend.wait_frontend_action(action_id="unknown-first", timeout_ms=0)[
            "action"
        ]["status"]
        == "delivered"
    )
    second = dict(
        action=next_action,
        target_session_id="browser-a",
        path="report.txt",
        action_id="different-operation-id",
        options=options,
    )
    blocked = frontend.enqueue_frontend_action(**second)
    assert not blocked["success"] and blocked["status"] == "blocked"
    assert blocked["pending_action_id"] == "unknown-first"
    assert frontend.next_frontend_action(session_id="browser-a")["action"] is None
    assert writes == ["unknown-first"]
    # Reads may inspect the actual document, and same-ID retries only wait/query.
    frontend.enqueue_frontend_action(
        action="ui_read_context",
        target_session_id="browser-a",
        path="report.txt",
        options=options,
    )
    assert (
        frontend.next_frontend_action(session_id="browser-a")["action"]["action"]
        == "ui_read_context"
    )
    assert (
        frontend.enqueue_frontend_action(**initial)["action"]["status"] == "delivered"
    )
    assert frontend.next_frontend_action(session_id="browser-a")["action"] is None
    _complete_browser_action(action_id="unknown-first", result={"applied": True})
    assert frontend.enqueue_frontend_action(**second)["success"]
    writes.append(frontend.next_frontend_action(session_id="browser-a")["action"]["id"])
    assert writes == ["unknown-first", "different-operation-id"]


def test_already_queued_mutation_waits_for_prior_delivery_receipt(document_scope):
    options = {"document_path": "report.txt", "file_id": "file123"}
    for operation_id in ("first-queued", "second-queued"):
        assert frontend.enqueue_frontend_action(
            action="ui_apply_edit",
            target_session_id="browser-a",
            path="report.txt",
            action_id=operation_id,
            options=options,
        )["success"]
    assert (
        frontend.next_frontend_action(session_id="browser-a")["action"]["id"]
        == "first-queued"
    )
    assert frontend.next_frontend_action(session_id="browser-a")["action"] is None
    _complete_browser_action(action_id="first-queued", result={"applied": True})
    assert (
        frontend.next_frontend_action(session_id="browser-a")["action"]["id"]
        == "second-queued"
    )


def test_tool_cannot_bypass_unknown_write_with_a_new_model_operation_id(
    document_scope, monkeypatch
):
    context, _ = document_scope
    waits = []

    def unknown_receipt(action_id, timeout_ms):
        waits.append(action_id)
        frontend.next_frontend_action(session_id="browser-a")
        return {**frontend.frontend_action_status(action_id), "timed_out": True}

    monkeypatch.setattr(frontend, "wait_frontend_action", unknown_receipt)
    plugin = DocumentUIPlugin()
    with pytest.raises(RuntimeError, match="delivered, not completed"):
        plugin.ui_apply_edit(
            "v1", "Old", "New", "edit-first", invocation_context=context
        )
    with pytest.raises(RuntimeError, match="no confirmed receipt"):
        plugin.ui_apply_edit(
            "v1", "Old", "New", "edit-again", invocation_context=context
        )
    assert len(waits) == 1
    assert len(frontend._DOCUMENT_OPERATION_LEDGER) == 1
    assert frontend.next_frontend_action(session_id="browser-a")["action"] is None


def _browser_receipt(monkeypatch, result, *, ok=True):
    def wait(action_id, timeout_ms):
        delivered = frontend.next_frontend_action(session_id="browser-a")["action"]
        assert delivered and delivered["id"] == action_id
        return _complete_browser_action(
            action_id=action_id,
            ok=ok,
            result=result,
            error="browser conflict" if not ok else "",
        )

    monkeypatch.setattr(frontend, "wait_frontend_action", wait)


def test_real_completed_receipt_reaches_tool_result(document_scope, monkeypatch):
    context, _ = document_scope
    _browser_receipt(
        monkeypatch,
        {
            "document_path": "report.txt",
            "file_id": "file123",
            "revision": "editor-v1",
            "content": "actual browser text",
        },
    )
    result = DocumentUIPlugin().ui_read_context(invocation_context=context)
    assert result["content"] == "actual browser text"
    assert result["status"] == "completed"


@pytest.mark.parametrize(
    "result,ok",
    [
        ({}, False),
        (
            {"document_path": "different.txt", "file_id": "file123", "revision": "v1"},
            True,
        ),
    ],
)
def test_failed_or_wrong_document_receipts_are_not_success(
    document_scope, monkeypatch, result, ok
):
    context, _ = document_scope
    _browser_receipt(monkeypatch, result, ok=ok)
    with pytest.raises(RuntimeError):
        DocumentUIPlugin().ui_read_context(invocation_context=context)


def test_queued_is_never_a_successful_tool_receipt(document_scope, monkeypatch):
    context, _ = document_scope
    monkeypatch.setattr(
        frontend,
        "wait_frontend_action",
        lambda **kw: frontend.frontend_action_status(kw["action_id"]),
    )
    with pytest.raises(RuntimeError, match="queued, not completed"):
        DocumentUIPlugin().ui_read_context(invocation_context=context)


def test_operation_ids_are_scoped_to_trusted_logical_requests(
    document_scope, monkeypatch
):
    context, _ = document_scope
    first_context = replace(context, request_id="request-one")
    second_context = replace(context, request_id="request-two")
    executed = []

    def receive(action_id, timeout_ms):
        status = frontend.frontend_action_status(action_id)["action"]
        if status["status"] == "completed":
            return {"success": True, "action": status}
        delivered = frontend.next_frontend_action(session_id="browser-a")["action"]
        assert delivered and delivered["id"] == action_id
        executed.append(action_id)
        return _complete_browser_action(
            action_id=action_id,
            result={
                "document_path": "report.txt",
                "file_id": "file123",
                "applied": True,
                "revision_after": "after-edit",
            },
        )

    monkeypatch.setattr(frontend, "wait_frontend_action", receive)
    plugin = DocumentUIPlugin()
    args = ("same-original-revision", "Old", "New", "edit-1")
    first = plugin.ui_apply_edit(*args, invocation_context=first_context)
    retry = plugin.ui_apply_edit(*args, invocation_context=first_context)
    # The user may undo manually and ask the same thing in the same conversation.
    # A new trusted HTTP request must execute, even with identical model arguments.
    second = plugin.ui_apply_edit(*args, invocation_context=second_context)
    assert first["action_id"] == retry["action_id"]
    assert second["action_id"] != first["action_id"]
    assert executed == [first["action_id"], second["action_id"]]


def test_mutation_without_trusted_request_id_cannot_reuse_session_namespace(
    document_scope,
):
    context, _ = document_scope
    with pytest.raises(PermissionError, match="request identity"):
        DocumentUIPlugin().ui_apply_edit(
            "v1",
            "Old",
            "New",
            "edit-1",
            invocation_context=replace(context, request_id=""),
        )


def test_save_verifies_actual_source_bytes(document_scope, monkeypatch):
    context, tmp_path = document_scope
    raw = b"edited content"
    (tmp_path / "report.txt").write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    _browser_receipt(
        monkeypatch,
        {
            "document_path": "report.txt",
            "file_id": "file123",
            "persisted": True,
            "src_written": True,
            "verified": True,
            "source_sha256": digest,
            "raw_sha256": digest,
            "previous_source_sha256": "0" * 64,
            "unsaved_changes": False,
        },
    )
    result = DocumentUIPlugin().ui_save(
        "editor-v2", "0" * 64, "save-1", invocation_context=context
    )
    assert result["readback_verified"] is True


def test_false_save_claim_fails_independent_readback(document_scope, monkeypatch):
    context, tmp_path = document_scope
    (tmp_path / "report.txt").write_text("different content", encoding="utf-8")
    _browser_receipt(
        monkeypatch,
        {
            "document_path": "report.txt",
            "file_id": "file123",
            "persisted": True,
            "src_written": True,
            "verified": True,
            "source_sha256": "a" * 64,
            "raw_sha256": "a" * 64,
            "previous_source_sha256": "0" * 64,
            "unsaved_changes": False,
        },
    )
    with pytest.raises(RuntimeError, match="readback"):
        DocumentUIPlugin().ui_save(
            "editor-v2", "0" * 64, "save-false", invocation_context=context
        )
