"""Keep unresolved write failures visible until a matching committed result."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from app.core.agent.toolkits.foundation.catalog import (
    is_write_tool,
    write_target_for_tool,
)


def _path(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    from app.core.agent.file_task_artifact_transaction import resolved_write_path

    return str(resolved_write_path(text)).replace("\\", "/").rstrip("/").casefold()


def update_mutation_failures(
    failures: list[dict[str, Any]],
    *,
    tool_name: str,
    tool_args: Mapping[str, Any],
    result: Mapping[str, Any],
    changes: list[dict[str, Any]],
    call_id: str = "",
    authorized_target: str = "",
) -> None:
    if not is_write_tool(tool_name):
        return
    operation_hash = hashlib.sha256(
        json.dumps(
            dict(tool_args),
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if result.get("ok") is True:
        committed = {
            _path(change.get("path") or change.get("file_path")) for change in changes
        }

        def unresolved(item):
            denied_other_target = (
                item.get("policy_denied")
                and _path(authorized_target)
                and _path(item.get("target"))
                and _path(item.get("target")) != _path(authorized_target)
                and _path(authorized_target) in committed
            )
            if denied_other_target:
                # A rejected attempt on a protected input is not the task's
                # requested output. Completing the actual bound output can
                # recover that attempt; the rejection remains in the journal.
                return False
            return bool(
                item.get("policy_denied")
                or not _path(item.get("target"))
                or _path(item.get("target")) not in committed
                or item.get("tool_name") != tool_name
                or item.get("operation_hash") != operation_hash
            )

        failures[:] = [item for item in failures if unresolved(item)]
        return
    error = result.get("error")
    error = error if isinstance(error, Mapping) else {}
    code = str(error.get("code") or result.get("error_code") or "execution_error")
    record = {
        "tool_name": tool_name,
        "tool_call_id": call_id,
        "target": write_target_for_tool(tool_name, dict(tool_args)),
        "error_code": code,
        "operation_hash": operation_hash,
        "policy_denied": code.lower().endswith("policy_denied"),
    }
    if not any(item.get("tool_call_id") == call_id for item in failures if call_id):
        failures.append(record)


__all__ = ["update_mutation_failures"]
