"""Serializable continuation receipts for the existing file-task adapter."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, Mapping

from app.core.agent.toolkits.foundation.catalog import (
    is_write_tool,
    tool_result_preview,
)


class FileTaskCheckpointConflict(RuntimeError):
    """A saved file version changed; continuing needs explicit reconciliation."""


def _change_path(change: Mapping[str, Any]) -> str:
    return next(
        (
            str(change.get(key) or "")
            for key in (
                "path",
                "file_path",
                "output_path",
                "target_path",
                "destination",
                "revised_file",
            )
            if change.get(key)
        ),
        "",
    )


def _resolved_file(path: str, workspace_root: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate.resolve()
    root = Path(workspace_root).resolve()
    parts = candidate.parts
    if parts and parts[0].lower() == "workspace" and root.name.lower() == "workspace":
        candidate = Path(*parts[1:])
    return (root / candidate).resolve()


def _fingerprint(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"exists": False}
    if path.is_dir():
        return {
            "exists": True,
            "directory": True,
            "modified_ns": path.stat().st_mtime_ns,
        }
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"exists": True, "size": path.stat().st_size, "sha256": digest.hexdigest()}


def _request_snapshot(request: Any) -> Dict[str, Any]:
    # Drop a saved continuation before asdict/deepcopy to avoid recursively
    # embedding every previous checkpoint in the next one.
    options = dict(getattr(request, "options", None) or {})
    clean_options = {
        key: value
        for key, value in options.items()
        if key
        not in {"_kernel_resume_state", "_checkpoint_owner", "_checkpoint_callback"}
    }
    if is_dataclass(request):
        from dataclasses import replace

        result = asdict(replace(request, options=clean_options))
    else:
        result = {
            key: value for key, value in vars(request).items() if key != "options"
        }
        result["options"] = clean_options
    return result


def _tool_observations(messages):
    calls: Dict[str, Dict[str, Any]] = {}
    for message in messages or []:
        if not isinstance(message, Mapping):
            continue
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                if not isinstance(call, Mapping):
                    continue
                function = (
                    call.get("function")
                    if isinstance(call.get("function"), Mapping)
                    else {}
                )
                args = call.get(
                    "args", call.get("arguments", function.get("arguments", {}))
                )
                if isinstance(args, str):
                    args = json.loads(args)
                calls[str(call.get("id") or call.get("call_id") or "")] = {
                    "name": str(call.get("name") or function.get("name") or ""),
                    "args": dict(args or {}),
                }
        elif message.get("role") == "tool":
            result = message.get("content")
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except ValueError:
                    continue
            if isinstance(result, Mapping):
                call_id = str(
                    message.get("tool_call_id") or result.get("call_id") or ""
                )
                call = calls.get(call_id, {})
                yield call_id, str(
                    result.get("tool_name")
                    or call.get("name")
                    or message.get("name")
                    or ""
                ), call.get("args") or {}, dict(result)


def build_file_task_checkpoint(
    state: Mapping[str, Any],
    *,
    request: Any,
    workspace_root: str,
    runtime: Any,
    receipts: Mapping[str, Any],
    raw_results: Mapping[str, Any] | None = None,
    actual_args: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Include a tool result even before its adapter event has been yielded.

    Kernel writes a tool_complete checkpoint before yielding TOOL_RESULT.
    Rebuilding receipts from the full paired transcript closes that crash
    window without running a committed tool again.
    """
    snapshot = copy.deepcopy(dict(state))
    previous = (
        dict((request.options or {}).get("_kernel_resume_state") or {})
        if hasattr(request, "options")
        else {}
    )
    saved = (
        previous.get("adapter_receipts")
        if isinstance(previous.get("adapter_receipts"), dict)
        else {}
    )
    combined = copy.deepcopy(saved)
    combined.update(copy.deepcopy(dict(receipts or {})))
    for key in (
        "file_changes",
        "generated_artifacts",
        "readonly_tool_outputs",
        "mutation_failures",
    ):
        combined[key] = list(combined.get(key) or [])
    observed = set(combined.get("observed_call_ids") or [])
    # Adapter lists already contain older results, but the current result may
    # still be waiting for its public event.  Prefer actual resolved arguments.
    raw_results = raw_results or {}
    actual_args = actual_args or {}
    newly_committed_paths = set()
    for call_id, tool_name, args, result in _tool_observations(
        snapshot.get("messages")
    ):
        if not call_id or call_id in observed:
            continue
        observed.add(call_id)
        args = dict(actual_args.get(call_id) or args)
        value = raw_results.get(
            call_id,
            result.get("value") if result.get("ok") else {"error": result.get("error")},
        )
        changes = (
            runtime._extract_file_changes(tool_name, args, value)
            if result.get("ok")
            else []
        )
        from app.core.agent.file_task_mutation_evidence import update_mutation_failures

        update_mutation_failures(
            combined["mutation_failures"],
            tool_name=tool_name,
            tool_args=args,
            result=result,
            changes=changes,
            call_id=call_id,
            authorized_target=str(combined.get("authorized_write_target") or ""),
        )
        existing = {
            (str(_change_path(change)), str(change.get("operation") or ""))
            for change in combined["file_changes"]
        }
        for change in changes or []:
            change = {**change, "tool_call_id": change.get("tool_call_id") or call_id}
            key = (str(_change_path(change)), str(change.get("operation") or ""))
            newly_committed_paths.add(str(_change_path(change)))
            if key not in existing:
                combined["file_changes"].append(dict(change))
                existing.add(key)
        artifacts = runtime._tool_artifacts(tool_name, value)
        runtime._remember_generated_artifacts(
            combined["generated_artifacts"], artifacts
        )
        outcome = runtime._extract_tool_runtime_outcome(value)
        if outcome:
            combined["tool_runtime_outcome"] = outcome
        if not is_write_tool(tool_name):
            if not any(
                item.get("tool_call_id") == call_id
                or (item.get("tool_name") == tool_name and item.get("args") == args)
                for item in combined["readonly_tool_outputs"]
            ):
                combined["readonly_tool_outputs"].append(
                    {
                        "tool_call_id": call_id,
                        "tool_name": tool_name,
                        "args": args,
                        "result": value,
                        "preview": tool_result_preview(tool_name, value, 1200),
                    }
                )
    combined["observed_call_ids"] = sorted(observed)
    old_versions = {
        str(item.get("path") or ""): item
        for item in (
            receipts.get("file_versions") or previous.get("file_versions") or []
        )
        if isinstance(item, Mapping)
    }
    versions = []
    for change in combined["file_changes"]:
        path = _change_path(change)
        if path:
            if path in old_versions and path not in newly_committed_paths:
                versions.append(copy.deepcopy(old_versions[path]))
                continue
            resolved = _resolved_file(path, workspace_root)
            versions.append(
                {
                    "path": path,
                    "resolved_path": str(resolved),
                    "fingerprint": _fingerprint(resolved),
                }
            )
    snapshot.update(
        {
            "runtime_adapter": "file_task",
            "file_task_request": _request_snapshot(request),
            "workspace_root": str(workspace_root),
            "adapter_receipts": combined,
            "file_versions": versions,
        }
    )
    return snapshot


def restore_file_task_receipts(state: Mapping[str, Any]) -> Dict[str, Any]:
    """Verify committed file versions before entering any resumed tool call."""
    if not state:
        return {}
    if state.get("runtime_adapter") != "file_task" or not isinstance(
        state.get("file_task_request"), Mapping
    ):
        raise FileTaskCheckpointConflict("文件任务检查点缺少原始请求，无法安全重建")
    for version in state.get("file_versions") or []:
        path = Path(str(version.get("resolved_path") or ""))
        if not str(version.get("resolved_path") or "") or _fingerprint(
            path
        ) != version.get("fingerprint"):
            raise FileTaskCheckpointConflict(
                f"已提交文件在中断后发生变化，需要核对：{version.get('path') or path.name}"
            )
    receipts = state.get("adapter_receipts")
    if not isinstance(receipts, Mapping):
        raise FileTaskCheckpointConflict("文件任务检查点缺少执行回执")
    return copy.deepcopy(dict(receipts))
