"""Scoped semantic document tools backed by real browser execution receipts."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

from app.core.agent import frontend_observability as frontend
from app.core.agent.base import AgentPlugin


class DocumentUIPlugin(AgentPlugin):
    toolkit_source = "core:document_ui"

    @property
    def name(self):
        return "DocumentUI"

    @property
    def description(self):
        return "Read, edit and save the explicitly scoped open document using verified UI receipts."

    def get_tools(self):
        scope = {
            "type": "object",
            "description": "Optional exact block, table-cell or list-item scope from ui_read_context. Paths are valid only at expected_revision.",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["document", "paragraphs", "table_cell", "list_item"],
                },
                "block_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 100,
                },
                "container_id": {"type": "string"},
                "table_id": {"type": "string"},
                "row_index": {"type": "integer", "minimum": 0},
                "cell_index": {"type": "integer", "minimum": 0},
                "list_id": {"type": "string"},
                "item_index": {"type": "integer", "minimum": 0},
            },
            "additionalProperties": False,
        }
        revision = {
            "type": "string",
            "minLength": 1,
            "description": "Exact revision from the latest ui_read_context or ui_apply_edit receipt.",
        }
        operation = {
            "type": "string",
            "minLength": 1,
            "maxLength": 200,
            "description": "Stable unique ID for this logical operation. Reuse this ID when retrying, never for different edits.",
        }
        definitions = [
            (
                "ui_read_context",
                self.ui_read_context,
                "Read the actual current document and selection with its editor revision. DOCX blocks expose exact paragraph/table/list scope IDs; follow next_block_id and next_offset for truncated content. Plain text uses start_offset. Must precede editing; requires a host-bound document scope.",
                {
                    "scope": scope,
                    "start_block_id": {"type": "string"},
                    "start_offset": {"type": "integer", "minimum": 0},
                    "max_chars": {"type": "integer", "minimum": 200, "maximum": 16000},
                    "max_blocks": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                [],
                True,
            ),
            (
                "ui_apply_edit",
                self.ui_apply_edit,
                "Atomically replace an exact text anchor in the scoped document. DOCX supports multiple paragraphs, exact table cells and list items while preserving block structure and unchanged formatting; replacements must retain paragraph count. Returns actual before/after, revision and undo token. Editor changes require ui_save to persist.",
                {
                    "expected_revision": revision,
                    "anchor_text": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 16000,
                    },
                    "replacement": {"type": "string", "maxLength": 32000},
                    "scope": scope,
                    "operation_id": operation,
                    "anchor_occurrence": {"type": "integer", "minimum": 1},
                },
                ["expected_revision", "anchor_text", "replacement", "operation_id"],
                False,
            ),
            (
                "ui_action_status",
                self.ui_action_status,
                "Read the durable execution status and exact receipt for an operation_id from this trusted request/document. Unknown execution is never retried automatically.",
                {"operation_id": operation},
                ["operation_id"],
                True,
            ),
            (
                "ui_save",
                self.ui_save,
                "Save the scoped editor revision and verify persisted bytes by readback. A queued, timed-out, dirty or failed save is never success.",
                {
                    "expected_revision": revision,
                    "expected_source_sha256": {
                        "type": "string",
                        "pattern": "^[a-f0-9]{64}$",
                        "description": "Original source_sha256 returned by ui_read_context; never substitute the hash of externally changed disk content.",
                    },
                    "operation_id": operation,
                },
                ["expected_revision", "expected_source_sha256", "operation_id"],
                False,
            ),
        ]
        return [
            {
                "name": name,
                "func": func,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
                "read_only": read_only,
                "requires_invocation_context": True,
                "timeout_seconds": 35.0,
                "capabilities": ("document.ui",),
            }
            for name, func, description, properties, required, read_only in definitions
        ]

    @staticmethod
    def _scope(invocation_context, operation: str):
        scope = getattr(invocation_context, "frontend_document_scope", None)
        if not isinstance(scope, Mapping) or operation not in scope.get(
            "allowed_operations", ()
        ):
            raise PermissionError(
                "No trusted open-document scope permits this operation"
            )
        if not all(
            scope.get(key)
            for key in ("frontend_session_id", "document_path", "file_id")
        ):
            raise PermissionError("Incomplete trusted document identity")
        return scope

    @staticmethod
    def _trusted_scope(invocation_context, scope):
        return {
            **{
                key: str(getattr(invocation_context, key, "") or "")
                for key in (
                    "request_id",
                    "session_id",
                    "tenant_id",
                    "principal_id",
                    "task_id",
                    "run_id",
                )
            },
            **{
                key: str(scope[key])
                for key in ("frontend_session_id", "document_path", "file_id")
            },
        }

    @staticmethod
    def _operation_action_id(invocation_context, scope, operation_id):
        request_id = str(getattr(invocation_context, "request_id", "") or "").strip()
        if not request_id:
            raise PermissionError("Document writes require a trusted request identity")
        namespace = "\0".join(
            (
                request_id,
                str(getattr(invocation_context, "session_id", "")),
                scope["frontend_session_id"],
                scope["file_id"],
                operation_id,
            )
        )
        return "document-" + hashlib.sha256(namespace.encode()).hexdigest()

    def _run(
        self,
        action: str,
        *,
        invocation_context,
        operation: str,
        operation_id: str = "",
        **options,
    ):
        scope = self._scope(invocation_context, operation)
        options.update(document_path=scope["document_path"], file_id=scope["file_id"])
        action_id = ""
        if operation_id:
            action_id = self._operation_action_id(
                invocation_context, scope, operation_id
            )
        queued = frontend.enqueue_frontend_action(
            action=action,
            target_session_id=scope["frontend_session_id"],
            path=scope["document_path"],
            options=options,
            action_id=action_id,
            expires_after_ms=20000,
            trusted_scope=self._trusted_scope(invocation_context, scope),
            operation_id=operation_id,
        )
        if not queued.get("success"):
            raise RuntimeError(queued.get("error") or "Could not queue document action")
        action_id = queued["action"]["id"]
        waited = frontend.wait_frontend_action(action_id=action_id, timeout_ms=20000)
        receipt = waited.get("action") or {}
        if receipt.get("status") != "completed" or receipt.get("ok") is not True:
            state = receipt.get("status") or "unavailable"
            raise RuntimeError(
                f"Document action {action_id} is {state}, not completed: {receipt.get('error') or 'No browser receipt; do not assume it ran or retry with a new operation ID'}"
            )
        result = receipt.get("result") or {}
        if (
            frontend._document_path(result.get("document_path"))
            != frontend._document_path(scope["document_path"])
            or result.get("file_id") != scope["file_id"]
        ):
            raise RuntimeError(
                "Document receipt identity does not match the trusted scope"
            )
        return {"action_id": action_id, "status": "completed", **result}

    def ui_read_context(
        self,
        scope=None,
        start_block_id="",
        start_offset=0,
        max_chars=4000,
        max_blocks=24,
        *,
        invocation_context,
    ):
        result = self._run(
            "ui_read_context",
            invocation_context=invocation_context,
            operation="read",
            scope=scope or {},
            start_block_id=start_block_id,
            start_offset=start_offset,
            max_chars=max_chars,
            max_blocks=max_blocks,
        )
        if not result.get("revision"):
            raise RuntimeError("Browser returned no document revision")
        return result

    def ui_action_status(self, operation_id: str, *, invocation_context):
        scope = self._scope(invocation_context, "read")
        return frontend.frontend_action_status(
            action_id=self._operation_action_id(
                invocation_context, scope, operation_id
            ),
            trusted_scope=self._trusted_scope(invocation_context, scope),
        )

    def ui_apply_edit(
        self,
        expected_revision: str,
        anchor_text: str,
        replacement: str,
        operation_id: str,
        anchor_occurrence: int | None = None,
        scope=None,
        *,
        invocation_context,
    ):
        if not expected_revision or not anchor_text or not operation_id:
            raise ValueError(
                "Editing requires a read revision, exact anchor and stable operation_id"
            )
        options = dict(
            expected_revision=expected_revision,
            anchor_text=anchor_text,
            replacement=replacement,
            scope=scope or {},
        )
        if anchor_occurrence is not None:
            options["anchor_occurrence"] = anchor_occurrence
        result = self._run(
            "ui_apply_edit",
            invocation_context=invocation_context,
            operation="edit",
            operation_id=operation_id,
            **options,
        )
        if (
            result.get("applied") is not True and result.get("reason") != "no_change"
        ) or not result.get("revision_after"):
            raise RuntimeError("Browser did not confirm an applied document edit")
        return result

    def ui_save(
        self,
        expected_revision: str,
        expected_source_sha256: str,
        operation_id: str,
        *,
        invocation_context,
    ):
        if not expected_revision or not operation_id:
            raise ValueError(
                "Saving requires an exact editor revision and stable operation_id"
            )
        result = self._run(
            "ui_save",
            invocation_context=invocation_context,
            operation="save",
            operation_id=operation_id,
            expected_revision=expected_revision,
            expected_source_sha256=expected_source_sha256,
        )
        if (
            result.get("persisted") is not True
            or result.get("unsaved_changes")
            or not result.get("raw_sha256")
        ):
            raise RuntimeError(
                "Save receipt does not confirm persisted, unchanged editor content"
            )
        if result.get("src_written"):
            from app.core.config.workspace_runtime import get_workspace_root

            root = Path(get_workspace_root()).resolve()
            target = Path(result["document_path"])
            target = (
                target.resolve() if target.is_absolute() else (root / target).resolve()
            )
            # Scope came from the host-observed open document, never model paths.
            if (
                not target.is_file()
                or hashlib.sha256(target.read_bytes()).hexdigest()
                != result["raw_sha256"]
            ):
                raise RuntimeError(
                    "Saved source file failed byte-for-byte readback verification"
                )
            if (
                result.get("verified") is not True
                or result.get("source_sha256") != result["raw_sha256"]
                or result.get("previous_source_sha256") != expected_source_sha256
            ):
                raise RuntimeError("Server did not verify the saved source revision")
            result["readback_verified"] = True
        elif result.get("file_handle_readback_verified") is True:
            result["readback_verified"] = True
        else:
            raise RuntimeError(
                "Save reached only a temporary copy; source readback is unverified"
            )
        return result
