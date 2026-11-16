"""Host-scope plumbing and persisted DOCX semantic-format regressions."""

import io
import zipfile
from types import SimpleNamespace

import pytest
from docx import Document

from app.core.agent import frontend_observability as frontend
from app.core.agent.toolkits.builtin.document_ui_plugin import DocumentUIPlugin
from app.core.file.exporters.docx_exporter import export_docx


@pytest.fixture
def context():
    return SimpleNamespace(
        request_id="request-semantic",
        session_id="chat-semantic",
        tenant_id="local",
        principal_id="user",
        task_id="task-semantic",
        run_id="run-semantic",
        frontend_document_scope={
            "frontend_session_id": "browser-semantic",
            "document_path": "report.docx",
            "file_id": "semantic-file",
            "allowed_operations": ("read", "edit", "save"),
        },
    )


def test_document_scope_and_operation_are_host_only_and_receipt_is_complete(
    monkeypatch, context
):
    calls = []
    receipt = {
        "document_path": "report.docx",
        "file_id": "semantic-file",
        "applied": True,
        "revision_before": "v1",
        "revision_after": "v2",
        "before_text": "原文" * 3000,
        "after_text": "新文" * 3000,
        "persisted": False,
        "undo_token": "opaque",
    }
    monkeypatch.setattr(
        frontend,
        "enqueue_frontend_action",
        lambda **kwargs: calls.append(kwargs)
        or {"success": True, "action": {"id": kwargs["action_id"]}},
    )
    monkeypatch.setattr(
        frontend,
        "wait_frontend_action",
        lambda **kwargs: {
            "action": {"status": "completed", "ok": True, "result": receipt}
        },
    )
    plugin = DocumentUIPlugin()
    result = plugin.ui_apply_edit(
        "v1",
        receipt["before_text"],
        receipt["after_text"],
        "op1",
        scope={
            "kind": "table_cell",
            "table_id": "node:2",
            "row_index": 0,
            "cell_index": 1,
        },
        invocation_context=context,
    )
    queued = calls[0]
    assert queued["trusted_scope"] == {
        "request_id": "request-semantic",
        "session_id": "chat-semantic",
        "tenant_id": "local",
        "principal_id": "user",
        "task_id": "task-semantic",
        "run_id": "run-semantic",
        "frontend_session_id": "browser-semantic",
        "document_path": "report.docx",
        "file_id": "semantic-file",
    }
    assert queued["operation_id"] == "op1"
    assert "trusted_scope" not in queued["options"]
    assert len(queued["options"]["anchor_text"]) == 6000
    assert (
        result["before_text"] == receipt["before_text"]
        and result["after_text"] == receipt["after_text"]
    )
    assert result["persisted"] is False
    status_calls = []
    monkeypatch.setattr(
        frontend,
        "frontend_action_status",
        lambda **kwargs: status_calls.append(kwargs)
        or {"success": True, "action": {"status": "unknown"}},
    )
    assert (
        plugin.ui_action_status("op1", invocation_context=context)["action"]["status"]
        == "unknown"
    )
    assert status_calls[0]["action_id"] == queued["action_id"]
    assert status_calls[0]["trusted_scope"] == queued["trusted_scope"]


def test_scoped_read_pagination_and_rejected_scope_do_not_queue_mutation(
    monkeypatch, context
):
    calls = []
    monkeypatch.setattr(
        frontend,
        "enqueue_frontend_action",
        lambda **kwargs: calls.append(kwargs)
        or {"success": True, "action": {"id": "read"}},
    )
    monkeypatch.setattr(
        frontend,
        "wait_frontend_action",
        lambda **kwargs: {
            "action": {
                "status": "completed",
                "ok": True,
                "result": {
                    "document_path": "report.docx",
                    "file_id": "semantic-file",
                    "revision": "v1",
                    "blocks": [],
                },
            }
        },
    )
    plugin = DocumentUIPlugin()
    plugin.ui_read_context(
        start_block_id="block:1",
        start_offset=4000,
        max_chars=8000,
        invocation_context=context,
    )
    assert calls[0]["options"]["start_offset"] == 4000
    context.frontend_document_scope["allowed_operations"] = ("read",)
    with pytest.raises(PermissionError):
        plugin.ui_apply_edit("v1", "old", "new", "op", invocation_context=context)
    assert len(calls) == 1


def test_docx_export_keeps_nested_run_marks_and_links_in_body_and_table():
    raw = export_docx(
        {
            "html": '<p>Outside <a href="https://example.test/reference"><strong>链接😀</strong></a></p>'
            '<table><tr><td><p><a href="mailto:user@example.test"><em>单元格</em></a></p></td></tr></table>'
            "<ul><li><p>Keep bullet</p></li></ul>"
        }
    )
    reopened = Document(io.BytesIO(raw))
    assert reopened.paragraphs[-1].style.name == "List Bullet"
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        xml = archive.read("word/document.xml").decode()
        rels = archive.read("word/_rels/document.xml.rels").decode()
    assert xml.count("<w:hyperlink ") == 2
    assert (
        "https://example.test/reference" in rels and "mailto:user@example.test" in rels
    )
    assert "<w:b/>" in xml and "<w:i/>" in xml
    assert "链接😀" in xml and "单元格" in xml


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "file:///C:/secret.txt",
        "data:text/html,bad",
        "relative/path",
    ],
)
def test_unsafe_docx_hyperlinks_never_write_original(tmp_path, href):
    original = tmp_path / "source.docx"
    original.write_bytes(export_docx({"html": "<p>Original untouched</p>"}))
    before = original.read_bytes()
    with pytest.raises(ValueError, match="hyperlink scheme"):
        export_docx(
            {"html": f'<p><a href="{href}">unsafe</a></p>'}, original_path=str(original)
        )
    assert original.read_bytes() == before
