# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""SSE streaming helpers for file-assistant tasks.

This module owns the file-task streaming path used by the editor AI blueprint.
It keeps the route layer out of ``web.app`` while the larger app module is
gradually split into smaller services.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Iterable

from app.core.services.editor_ai_text import clean_selection_text
from app.core.services.file_task_event_safety import (
    safe_file_task_event_dict as _safe_file_task_event_dict,
)
from app.core.services.file_task_event_semantics import (
    file_task_message as _file_task_message,
)
from app.core.services.file_task_event_semantics import (
    file_task_step_type as _file_task_step_type,
)
from app.core.services.file_task_event_semantics import (
    file_task_terminal_status as _file_task_terminal_status,
)
from app.core.services.file_task_event_semantics import (
    trim_file_task_text as _trim_file_task_text,
)
from app.core.services.file_task_progress_persistence import (
    build_file_task_record_metadata,
    ensure_file_task_record,
    persist_file_task_progress_event,
    persist_file_task_summary_event,
)

logger = logging.getLogger("koto.app")


def _normalize_file_task_payload(data: dict) -> dict:
    from app.core.llm.local_model_runtime import (
        get_configured_local_model_tag,
        get_configured_model_mode,
    )
    from app.core.llm.model_selection import get_configured_cloud_model

    # Continuation state and execution receipts are host-owned. Only the
    # JobRunner may supply them by constructing a trusted FileTaskRequest;
    # accepting them from JSON could fabricate a completed Kernel execution.
    host_owned_fields = {
        "adapter_receipts",
        "file_versions",
        "runtime_adapter",
        "file_task_request",
        "resume_state",
        "checkpoint_callback",
        "checkpoint_owner",
        "owner_id",
        "lease_until",
    }

    def public_fields(value):
        return {
            key: item
            for key, item in value.items()
            if key not in host_owned_fields
            and not str(key).startswith(("_kernel", "_checkpoint", "_lease"))
        }

    payload = public_fields(dict(data or {}))

    raw_task = str(payload.get("task") or payload.get("instruction") or "")
    if raw_task:
        payload["task"] = clean_selection_text(raw_task)
    raw_selection = str(payload.get("selection") or "")
    if raw_selection:
        payload["selection"] = clean_selection_text(raw_selection)

    # The browser may contain a stale task card or an older bundled UI.  File
    # tasks therefore follow the persisted runtime selection, not a model mode
    # supplied by the individual request.  This is the same setting consumed
    # by ordinary chat and the workspace composer.
    model_mode = get_configured_model_mode()
    payload["model_mode"] = model_mode
    raw_options = payload.get("options")
    options = public_fields(raw_options) if isinstance(raw_options, dict) else {}
    if "allow_local_fallback" not in options:
        options["allow_local_fallback"] = False
    payload["options"] = options
    if model_mode == "local":
        # A local task always follows the model selected in Settings.  In
        # particular, resume payloads from older runs can contain a now-stale
        # options.local_model and must not override the current selection.
        # model_id belongs to the cloud-model picker, so it is not meaningful
        # on the Ollama path either.
        payload["model_id"] = ""
        configured_local_model = get_configured_local_model_tag()
        if configured_local_model:
            options["local_model"] = configured_local_model
        else:
            options.pop("local_model", None)
    else:
        payload["model_id"] = get_configured_cloud_model(task_type="FILE_TASK")
        options.pop("local_model", None)
    history = payload.get("history")
    if not isinstance(history, list):
        history = []
    payload["history"] = history[-20:]
    return payload


def _inject_recent_file_task_summary_context(
    payload: dict,
    *,
    load_recent_summaries_fn,
    format_summaries_as_context_fn,
) -> dict:
    try:
        raw_files = payload.get("files") or []
        file_paths = [
            str(item.get("path") or item.get("name") or "")
            for item in raw_files
            if isinstance(item, dict)
        ]
        if payload.get("target_path"):
            file_paths.append(str(payload["target_path"]))
        file_paths = list(dict.fromkeys(path for path in file_paths if path))
        recent = load_recent_summaries_fn(file_paths, limit=5)
        if recent:
            ctx_text = format_summaries_as_context_fn(recent)
            raw_options = payload.get("options")
            options = dict(raw_options) if isinstance(raw_options, dict) else {}
            if ctx_text and not options.get("memory_context"):
                options["memory_context"] = ctx_text
                payload["options"] = options
    except Exception as exc:
        logger.debug(
            "[FileTaskRuntime] recent summary context injection skipped: %s", exc
        )
    return payload


def _file_task_record_metadata(request_payload) -> dict:
    return build_file_task_record_metadata(request_payload)


def _ensure_file_task_record(request_payload) -> str:
    return ensure_file_task_record(request_payload)


def _compact_file_task_stream_payload(payload: dict) -> dict:
    """Remove internal runtime state before sending a file-task SSE frame.

    The supervisor keeps full workflow and plan objects for persistence and
    recovery.  They are both large and implementation-private, so the browser
    receives the stable compact projection instead.
    """
    compact = dict(payload or {})
    compact.pop("workflow_state", None)
    compact.pop("task_plan", None)
    compact["stream_payload_version"] = "compact_v1"
    return compact


def _persist_file_task_progress_event(request_payload, event) -> dict:
    return persist_file_task_progress_event(
        request_payload,
        _safe_file_task_event_dict(event),
    )


def _persist_file_task_summary_event(
    request_payload,
    event,
    *,
    save_task_summary_fn,
) -> None:
    persist_file_task_summary_event(
        request_payload,
        event,
        save_task_summary_fn=save_task_summary_fn,
        artifact_status_fn=_file_task_artifact_status,
    )


def _file_task_event_to_safe_sse(event) -> str:
    from app.core.agent.file_task_contract import event_to_sse

    # Keep this POST/fetch transport compatible with data-only clients.  The
    # JSON fact already carries event_id/run_id/seq.  Durable GET recovery uses
    # ProgressEvent.to_sse(), including the standard SSE id cursor.
    return event_to_sse(_safe_file_task_event_dict(event))


def _file_task_change_path(change: dict) -> str:
    for key in (
        "path",
        "file_path",
        "output_path",
        "target_path",
        "destination",
        "revised_file",
    ):
        value = str((change or {}).get(key) or "").strip()
        if value:
            return value.replace("\\", "/")
    return ""


def _append_file_task_artifact_changes(file_changes: list[dict], changes) -> None:
    seen = {
        (
            _file_task_change_path(item).lower(),
            str(item.get("operation") or "").strip().lower(),
            str(item.get("summary") or "").strip().lower(),
        )
        for item in file_changes
        if isinstance(item, dict)
    }
    for item in changes or []:
        if not isinstance(item, dict):
            continue
        path = _file_task_change_path(item)
        if not path:
            continue
        key = (
            path.lower(),
            str(item.get("operation") or "").strip().lower(),
            str(item.get("summary") or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        file_changes.append(dict(item))


def _artifact_result_file_changes(artifact_result: dict) -> list[dict]:
    if not isinstance(artifact_result, dict):
        return []
    changes: list[dict] = []
    for artifact in artifact_result.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        path = str(artifact.get("path") or artifact.get("file") or "").strip()
        if not path:
            continue
        changes.append(
            {
                "path": path,
                "operation": artifact.get("operation")
                or artifact.get("type")
                or "artifact",
                "summary": artifact.get("summary")
                or artifact.get("title")
                or f"已生成 {path}",
                "status": artifact.get("status") or "applied",
            }
        )
    for change in artifact_result.get("changes") or []:
        if not isinstance(change, dict):
            continue
        path = str(change.get("file") or change.get("path") or "").strip()
        if not path:
            continue
        item = dict(change)
        item.setdefault("path", path)
        item.setdefault("operation", item.get("kind") or "update")
        item.setdefault("summary", item.get("summary") or f"已更新 {path}")
        changes.append(item)
    return changes


def _collect_file_task_artifact_changes(
    event: dict,
    file_changes: list[dict],
    request_payload=None,
) -> None:
    event_type = str((event or {}).get("type") or "").strip()
    payload = (
        event.get("payload") if isinstance((event or {}).get("payload"), dict) else {}
    )
    if event_type == "file.changed":
        _append_file_task_artifact_changes(file_changes, [payload])
    if isinstance(payload.get("file_changes"), list):
        _append_file_task_artifact_changes(file_changes, payload.get("file_changes"))
    artifact_result = payload.get("artifact_result")
    artifact_identity_matches = True
    if isinstance(artifact_result, dict) and request_payload is not None:
        identity = _file_task_artifact_identity(request_payload, event, payload)
        artifact_identity_matches = _artifact_result_matches_file_task_identity(
            artifact_result,
            identity,
        )
    if isinstance(artifact_result, dict) and artifact_identity_matches:
        _append_file_task_artifact_changes(
            file_changes,
            _artifact_result_file_changes(artifact_result),
        )


def _file_task_artifact_status(event_type: str, event_payload: dict) -> str:
    runtime = (
        event_payload.get("runtime")
        if isinstance(event_payload.get("runtime"), dict)
        else {}
    )
    raw_status = (
        str(
            runtime.get("terminal_status")
            or event_payload.get("terminal_status")
            or event_payload.get("status")
            or ""
        )
        .strip()
        .lower()
    )
    # Old persisted tasks can still contain the retired status name.  Translate
    # at the compatibility boundary so no current artifact result re-emits it.
    if raw_status == "no_file_change":
        return "write_not_performed"
    if raw_status == "needs_attention":
        return "needs_review"
    if raw_status in {
        "awaiting_confirmation",
        "waiting",
        "context_summary_fallback",
        "needs_review",
        "pending",
        "blocked",
        "failed",
        "error",
        "write_blocked",
        "tool_gap",
        "write_not_performed",
        "model_unavailable",
        "model_timeout",
        "model_error",
        "quality_gate_failed",
    }:
        return raw_status
    terminal_status = _file_task_terminal_status(event_type, event_payload)
    if terminal_status:
        return terminal_status
    if event_type == "run.cancelled":
        return "failed"
    return "running"


def _should_attach_file_task_artifact_result(
    event_type: str,
    event_payload: dict,
    file_changes: list[dict],
) -> bool:
    if isinstance(event_payload.get("artifact_result"), dict):
        return False
    if event_type in {"run.finished", "run.cancelled"}:
        return True
    if event_type == "file.changed":
        return True
    if event_type in {"step.result", "check.finished"} and file_changes:
        return True
    if isinstance(event_payload.get("next_action_artifact"), dict):
        return True
    return False


def _merge_file_changes_into_artifact_result(
    artifact_result: dict, file_changes: list[dict]
) -> dict:
    from app.core.artifacts import canonical_artifact_path_key

    result = dict(artifact_result or {})
    existing_changes = []
    seen_changes = set()
    for item in result.get("changes") or []:
        if not isinstance(item, dict):
            continue
        candidate = dict(item)
        key = canonical_artifact_path_key(
            candidate.get("file") or candidate.get("path")
        )
        if key and key in seen_changes:
            continue
        if key:
            seen_changes.add(key)
        existing_changes.append(candidate)
    for change in file_changes or []:
        if not isinstance(change, dict):
            continue
        path = _file_task_change_path(change)
        key = canonical_artifact_path_key(path)
        if not path or key in seen_changes:
            continue
        seen_changes.add(key)
        existing_changes.append(
            {
                "file": path,
                "kind": change.get("kind") or change.get("operation") or "update",
                "summary": change.get("summary") or f"已更新 {path}",
                "status": change.get("status") or "applied",
                "after_preview": change.get("after_preview")
                or change.get("preview")
                or "",
                "metadata": {
                    key: value
                    for key, value in change.items()
                    if key
                    not in {
                        "path",
                        "file",
                        "file_path",
                        "output_path",
                        "target_path",
                        "operation",
                        "kind",
                        "summary",
                        "status",
                        "after_preview",
                        "preview",
                    }
                },
            }
        )
    result["changes"] = existing_changes

    existing_artifacts = []
    seen_artifacts = set()
    for item in result.get("artifacts") or []:
        if not isinstance(item, dict):
            continue
        candidate = dict(item)
        key = canonical_artifact_path_key(
            candidate.get("path") or candidate.get("file")
        )
        if key and key in seen_artifacts:
            continue
        if key:
            seen_artifacts.add(key)
        existing_artifacts.append(candidate)
    for change in file_changes or []:
        if not isinstance(change, dict):
            continue
        path = _file_task_change_path(change)
        key = canonical_artifact_path_key(path)
        if not path or key in seen_artifacts:
            continue
        seen_artifacts.add(key)
        existing_artifacts.append(
            {
                "type": change.get("type") or change.get("file_type") or "data",
                "title": str(path).replace("\\", "/").rsplit("/", 1)[-1] or path,
                "path": path,
                "status": "ready",
                "metadata": {},
            }
        )
    result["artifacts"] = existing_artifacts
    return result


def _file_task_artifact_identity(
    request_payload, event: dict, event_payload: dict
) -> dict[str, str]:
    return {
        "task_id": str(
            event.get("task_id")
            or getattr(request_payload, "task_id", "")
            or event.get("run_id")
            or getattr(request_payload, "run_id", "")
            or ""
        ).strip(),
        "run_id": str(
            event.get("run_id") or getattr(request_payload, "run_id", "") or ""
        ).strip(),
        "target_path": str(
            event_payload.get("target_path")
            or event_payload.get("target")
            or getattr(request_payload, "target_path", "")
            or ""
        ).strip(),
    }


def _artifact_result_matches_file_task_identity(
    artifact_result: dict,
    identity: dict[str, str],
) -> bool:
    from app.core.artifacts import canonical_artifact_path_key

    metadata = artifact_result.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    existing_task_id = str(artifact_result.get("task_id") or "").strip()
    existing_run_id = str(metadata.get("run_id") or "").strip()
    existing_target = str(metadata.get("target_path") or "").strip()
    if (
        existing_task_id
        and identity["task_id"]
        and existing_task_id != identity["task_id"]
    ):
        return False
    if existing_run_id and identity["run_id"] and existing_run_id != identity["run_id"]:
        return False
    if existing_target and identity["target_path"]:
        if canonical_artifact_path_key(existing_target) != canonical_artifact_path_key(
            identity["target_path"]
        ):
            return False
    return True


def _normalize_file_task_artifact_identity(
    artifact_result: dict,
    identity: dict[str, str],
) -> dict:
    result = dict(artifact_result or {})
    if identity["task_id"]:
        result["task_id"] = identity["task_id"]
    metadata = result.get("metadata")
    metadata = dict(metadata) if isinstance(metadata, dict) else {}
    if identity["run_id"]:
        metadata["run_id"] = identity["run_id"]
    if identity["target_path"]:
        metadata["target_path"] = identity["target_path"]
    result["metadata"] = metadata
    return result


def _attach_file_task_artifact_result(
    request_payload, event: dict, file_changes: list[dict]
) -> dict:
    event_type = str((event or {}).get("type") or "").strip()
    event_payload = (
        event.get("payload") if isinstance((event or {}).get("payload"), dict) else {}
    )
    identity = _file_task_artifact_identity(request_payload, event, event_payload)
    incoming_artifact_result = event_payload.get("artifact_result")
    if isinstance(
        incoming_artifact_result, dict
    ) and _artifact_result_matches_file_task_identity(
        incoming_artifact_result,
        identity,
    ):
        outbound_event = dict(event)
        outbound_payload = dict(event_payload)
        outbound_payload["artifact_result"] = _normalize_file_task_artifact_identity(
            _merge_file_changes_into_artifact_result(
                incoming_artifact_result,
                file_changes,
            ),
            identity,
        )
        outbound_event["payload"] = outbound_payload
        return outbound_event
    if isinstance(incoming_artifact_result, dict):
        event_payload = dict(event_payload)
        event_payload.pop("artifact_result", None)
    if not _should_attach_file_task_artifact_result(
        event_type, event_payload, file_changes
    ):
        return event
    try:
        from app.core.artifacts import build_file_task_artifact_result

        task_id = identity["task_id"]
        run_id = identity["run_id"]
        task = str(
            event_payload.get("task") or getattr(request_payload, "task", "") or ""
        ).strip()
        summary = str(
            event_payload.get("summary")
            or event_payload.get("text")
            or event_payload.get("detail")
            or ""
        ).strip()
        target_path = identity["target_path"]
        result = build_file_task_artifact_result(
            task_id=task_id,
            task=task,
            run_id=run_id,
            status=_file_task_artifact_status(event_type, event_payload),
            summary=summary,
            file_changes=file_changes,
            event_payload=event_payload,
            source_files=getattr(request_payload, "files", []) or [],
            current_file=getattr(request_payload, "current_file", None),
            selection_source=str(
                getattr(request_payload, "selection_source", "") or ""
            ),
            target_path=target_path,
        )
        outbound_event = dict(event)
        outbound_payload = dict(event_payload)
        outbound_payload["artifact_result"] = result.to_dict()
        outbound_event["payload"] = outbound_payload
        return outbound_event
    except Exception as exc:
        logger.debug("[FileTaskRuntime] artifact result attachment skipped: %s", exc)
        return event


def _build_file_task_ui_message_sse(
    request_payload, event, *, normalize_event_fn, seq_override=None
):
    try:
        ui_message = normalize_event_fn(event)
    except Exception as exc:
        logger.debug("[FileTaskRuntime] ui stream normalization skipped: %s", exc)
        return None
    if ui_message is None:
        return None
    event_payload = _safe_file_task_event_dict(event)
    return _file_task_event_to_safe_sse(
        {
            "type": "ui.message",
            "task_id": event_payload.get("task_id")
            or getattr(request_payload, "task_id", "")
            or "",
            "run_id": event_payload.get("run_id")
            or request_payload.run_id
            or "file_task",
            "seq": (
                int(seq_override)
                if seq_override is not None
                else event_payload.get("seq", 0)
            ),
            "step_id": event_payload.get("step_id") or "ui",
            "ts": event_payload.get("ts") or time.time(),
            "projection_of": event_payload.get("event_id")
            or f"{event_payload.get('run_id', '')}:{event_payload.get('seq', 0)}",
            "payload": ui_message.to_payload(),
        }
    )


def _build_file_task_orchestrator(*, workspace_root):
    from app.core.agent.file_task_model import FileTaskModelClient
    from app.core.agent.file_task_runtime import FileTaskRuntime
    from app.core.config.workspace_runtime import get_workspace_root

    return FileTaskRuntime(
        workspace_root=workspace_root or get_workspace_root(),
        model_client=FileTaskModelClient(),
        yield_thinking=None,
    )


def _build_file_task_request(
    data: dict,
    *,
    request_cls,
    load_recent_summaries_fn,
    format_summaries_as_context_fn,
):
    payload = _normalize_file_task_payload(data)
    payload = _inject_recent_file_task_summary_context(
        payload,
        load_recent_summaries_fn=load_recent_summaries_fn,
        format_summaries_as_context_fn=format_summaries_as_context_fn,
    )
    return request_cls.from_mapping(payload)


def _build_file_task_request_from_data(data: dict):
    from app.core.agent.file_task_contract import FileTaskRequest
    from app.core.agent.file_task_session_store import (
        format_summaries_as_context,
        load_recent_summaries,
    )

    return _build_file_task_request(
        data,
        request_cls=FileTaskRequest,
        load_recent_summaries_fn=load_recent_summaries,
        format_summaries_as_context_fn=format_summaries_as_context,
    )


@dataclass
class _FileTaskStreamState:
    """Mutable projection state shared across the complete SSE response."""

    outbound_seq: int = 0
    terminal_emitted: bool = False


def _iter_file_task_stream_events(
    request_payload,
    event_iterable,
    *,
    save_task_summary_fn,
    normalize_event_fn,
    persist_progress_fn,
    stream_state: _FileTaskStreamState | None = None,
):
    state = stream_state or _FileTaskStreamState()
    file_changes: list[dict] = []
    source_iter = iter(event_iterable)
    while not state.terminal_emitted:
        try:
            event = next(source_iter)
        except StopIteration:
            return
        except GeneratorExit:
            raise
        except Exception as exc:
            logger.exception(
                "[FileTaskRuntime] event producer failed before terminal: %s",
                exc,
            )
            event = _build_file_task_failed_terminal_event(request_payload, exc)

        safe_event = _safe_file_task_event_dict(event)
        _collect_file_task_artifact_changes(safe_event, file_changes, request_payload)
        safe_event = _attach_file_task_artifact_result(
            request_payload, safe_event, file_changes
        )
        _persist_file_task_summary_event(
            request_payload,
            safe_event,
            save_task_summary_fn=save_task_summary_fn,
        )
        # A persisted event receives its only business sequence before it is
        # published.  Test/embedding callbacks without storage keep a local
        # sequence, while the production callback returns the journal fact.
        persisted_event = persist_progress_fn(request_payload, safe_event)
        if isinstance(persisted_event, dict):
            safe_event = persisted_event
            state.outbound_seq = int(safe_event.get("seq") or state.outbound_seq + 1)
        else:
            state.outbound_seq += 1
            safe_event = {**safe_event, "seq": state.outbound_seq}
        outbound_event = dict(safe_event)
        outbound_event["payload"] = _compact_file_task_stream_payload(
            safe_event.get("payload")
            if isinstance(safe_event.get("payload"), dict)
            else {}
        )
        terminal_event = str(outbound_event.get("type") or "") in {
            "run.finished",
            "run.cancelled",
        }
        outbound_event["seq"] = state.outbound_seq
        raw_sse = _file_task_event_to_safe_sse(outbound_event)
        ui_sse = None
        if not terminal_event:
            ui_sse = _build_file_task_ui_message_sse(
                request_payload,
                safe_event,
                normalize_event_fn=normalize_event_fn,
                seq_override=state.outbound_seq,
            )
        if terminal_event:
            state.terminal_emitted = True
        yield raw_sse
        if terminal_event:
            return
        if ui_sse is not None:
            yield ui_sse


def _build_file_task_failed_terminal_event(request_payload, exc):
    from app.core.agent.file_task_failure import build_failed_run_payload

    detail = _trim_file_task_text(str(exc), 1200) or "文件任务流异常终止。"
    return {
        "type": "run.finished",
        "task_id": getattr(request_payload, "task_id", "") or "",
        "run_id": request_payload.run_id or "file_task",
        "seq": 999999,
        "step_id": "run",
        "ts": time.time(),
        "payload": build_failed_run_payload(
            status="failed",
            code="FILE_TASK_STREAM_FAILED",
            phase="stream_transport",
            summary="文件任务流异常终止，未能完成结果交付。",
            detail=detail,
            remaining=["查看任务执行详情，修复异常后重新执行。"],
        ),
    }


def _fallback_file_task_request_for_error(data: dict):
    return SimpleNamespace(
        task=str((data or {}).get("task") or (data or {}).get("instruction") or ""),
        run_id=str((data or {}).get("run_id") or "file_task"),
        session_id=str((data or {}).get("session_id") or ""),
        target_path=str(
            (data or {}).get("target_path") or (data or {}).get("target") or ""
        ),
    )


def _drain_file_task_stream_output_in_background(
    request_payload,
    stream_iter,
    *,
    stream_state: _FileTaskStreamState,
) -> None:
    task_id = str(getattr(request_payload, "task_id", "") or "").strip()

    def _drain():
        try:
            for _ in stream_iter:
                pass
        except Exception as exc:
            logger.exception(
                "[FileTaskRuntime] background stream drain failed (task_id=%s): %s",
                task_id or "?",
                exc,
            )
            try:
                if stream_state.terminal_emitted:
                    return
                error_event = _build_file_task_failed_terminal_event(
                    request_payload, exc
                )
                for _ in _iter_file_task_stream_output(
                    request_payload,
                    [error_event],
                    stream_state=stream_state,
                ):
                    pass
            except Exception as persist_exc:
                logger.debug(
                    "[FileTaskRuntime] background drain error persistence skipped (task_id=%s): %s",
                    task_id or "?",
                    persist_exc,
                )

    consume = _drain
    try:
        from flask import copy_current_request_context, g, has_request_context

        if has_request_context():
            trusted_request_state = dict(vars(g._get_current_object()))

            @copy_current_request_context
            def consume():
                for key, value in trusted_request_state.items():
                    setattr(g, key, value)
                _drain()

    except ImportError:
        pass

    from app.core.jobs.job_runner import get_job_runner

    get_job_runner().submit_continuation(consume)


def _iter_file_task_stream_output(
    request_payload,
    event_iterable,
    *,
    stream_state: _FileTaskStreamState | None = None,
):
    from app.core.agent.file_task_session_store import save_task_summary
    from app.core.agent.file_task_ui_stream import (
        normalize_event as _ui_normalize_event,
    )

    yield from _iter_file_task_stream_events(
        request_payload,
        event_iterable,
        save_task_summary_fn=save_task_summary,
        normalize_event_fn=_ui_normalize_event,
        persist_progress_fn=_persist_file_task_progress_event,
        stream_state=stream_state,
    )


def stream_file_task_request(
    data: dict,
    *,
    workspace_root: str | None = None,
) -> Iterable[str]:
    """Stream the Koto-native file task event contract as SSE frames."""
    request_payload = None
    stream_state = _FileTaskStreamState()
    try:
        request_payload = _build_file_task_request_from_data(data)
        _ensure_file_task_record(request_payload)
        orchestrator = _build_file_task_orchestrator(workspace_root=workspace_root)
        event_iterable = orchestrator.run(request_payload)
        stream_iter = _iter_file_task_stream_output(
            request_payload,
            event_iterable,
            stream_state=stream_state,
        )
        for frame in stream_iter:
            try:
                yield frame
            except GeneratorExit:
                # Closing a viewer is separate from requesting cancellation.
                # Even a cancelled run must consume its safe-stop and terminal
                # events; abandoning it here would leave the ledger running.
                _drain_file_task_stream_output_in_background(
                    request_payload,
                    stream_iter,
                    stream_state=stream_state,
                )
                raise
    except Exception as exc:
        logger.exception("[FileTaskRuntime] stream failed: %s", exc)
        if stream_state.terminal_emitted:
            return
        if request_payload is None:
            request_payload = _fallback_file_task_request_for_error(data)
        error_event = _build_file_task_failed_terminal_event(request_payload, exc)
        yield from _iter_file_task_stream_output(
            request_payload,
            [error_event],
            stream_state=stream_state,
        )
