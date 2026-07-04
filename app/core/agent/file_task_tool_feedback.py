# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern

from app.core.agent.file_task_runtime_utils import _json_payload, _preview
from app.core.agent.file_task_tool_catalog import (
    extract_koto_paths,
    extract_sandbox_artifacts,
    parse_file_change,
    stringify_result,
)


def tool_result_for_model(
    tool_name: str,
    result: Any,
    *,
    created_marker: str,
    modified_marker: str,
) -> Any:
    if tool_name != "run_python_code" or not isinstance(result, dict):
        return result

    sanitized: Dict[str, Any] = {}
    summary = str(result.get("summary") or "").strip()
    stdout = str(result.get("stdout") or "").strip()
    stderr = str(result.get("stderr") or "").strip()
    error = str(result.get("error") or "").strip()
    if summary:
        sanitized["summary"] = summary
    if stdout:
        sanitized["stdout"] = stdout
    if stderr:
        sanitized["stderr"] = stderr
    if error:
        sanitized["error"] = error

    created = extract_koto_paths(result, created_marker)
    modified = extract_koto_paths(result, modified_marker)
    if created:
        sanitized["created_paths"] = created
    if modified:
        sanitized["modified_paths"] = modified

    artifacts = extract_sandbox_artifacts(result)
    if artifacts:
        sanitized["generated_files"] = [
            {
                "name": artifact.get("name"),
                "path": artifact.get("path"),
            }
            for artifact in artifacts
        ]
        sanitized["generated_file_count"] = len(artifacts)
    return sanitized or {"summary": "(no output)"}


def _run_python_write_metrics(result: Any) -> Dict[str, int]:
    text = stringify_result(result)
    metrics: Dict[str, int] = {}
    cells_patterns = (
        r"(?:total\s+)?cells?\s+written\s*[:：]\s*(\d+)",
        r"(?:已写入|写入)\s*(\d+)\s*个?单元格",
        r"单元格(?:/行)?指标合计\s*[:：]?\s*(\d+)",
    )
    rows_patterns = (
        r"(?:data\s+)?rows?\s+written\s*[:：]\s*(\d+)",
        r"(?:已写入|写入)\s*(\d+)\s*行",
        r"(\d+)\s*(?:data\s+)?rows?",
    )
    for pattern in cells_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            metrics["cells_written"] = int(match.group(1))
            break
    for pattern in rows_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            metrics["rows_written"] = int(match.group(1))
            break
    return metrics


def extract_file_changes(
    tool_name: str,
    tool_args: Dict[str, Any],
    result: Any,
    *,
    created_marker: str,
    modified_marker: str,
) -> List[Dict[str, Any]]:
    changes: List[Dict[str, Any]] = []
    structured = parse_file_change(tool_name, tool_args, result)
    if structured:
        changes.append(structured)
    if tool_name == "run_python_code":
        metrics = _run_python_write_metrics(result)
        for path in extract_koto_paths(result, created_marker):
            change = {
                "path": path,
                "file_type": Path(path).suffix.lstrip(".").lower(),
                "operation": "run_python_code",
                "summary": f"Python 代码创建了 {Path(path).name}",
                "preview": "",
                "change_type": "create",
                "focus": True,
            }
            change.update(metrics)
            changes.append(change)
        for path in extract_koto_paths(result, modified_marker):
            change = {
                "path": path,
                "file_type": Path(path).suffix.lstrip(".").lower(),
                "operation": "run_python_code",
                "summary": f"Python 代码更新了 {Path(path).name}",
                "preview": "",
                "change_type": "modify",
                "focus": True,
            }
            change.update(metrics)
            changes.append(change)
    return changes


def truncate_tool_feedback_value(value: Any, *, depth: int = 0) -> Any:
    if isinstance(value, str):
        return _preview(value, 2400 if depth == 0 else 1600)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if depth >= 2:
        try:
            return _preview(json.dumps(value, ensure_ascii=False, default=str), 1600)
        except Exception:
            return _preview(str(value), 1600)
    if isinstance(value, dict):
        trimmed: Dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 20:
                trimmed["__truncated__"] = True
                break
            trimmed[str(key)] = truncate_tool_feedback_value(item, depth=depth + 1)
        return trimmed
    if isinstance(value, (list, tuple)):
        items = [
            truncate_tool_feedback_value(item, depth=depth + 1)
            for item in list(value)[:20]
        ]
        if len(value) > 20:
            items.append("__truncated__")
        return items
    return _preview(str(value), 1600)


def tool_feedback_for_model(
    tool_name: str,
    tool_args: Dict[str, Any],
    model_result: Any,
    *,
    success: bool,
    blocked: bool = False,
    skipped: bool = False,
    invalid: bool = False,
) -> str:
    if success and not blocked and not skipped and not invalid:
        return _preview(stringify_result(model_result), 6000)

    if invalid:
        failure_reason = "invalid_tool"
        next_action = (
            "这个工具当前不在 Koto 文件任务 allowlist 中。"
            "请改用现有 allowlist 工具，或在确实缺原生能力时返回 tool_gap；"
            "不要重复调用同一个无效工具。"
        )
    elif blocked:
        failure_reason = "blocked"
        next_action = (
            "这次调用被运行时拦截。请根据 error 或 summary 改用允许的原生工具或修改方案；"
            "不要重复完全相同的调用。"
        )
    elif skipped:
        failure_reason = "skipped"
        next_action = "这次调用被运行时跳过。请先理解跳过原因，再修改目标或方案；不要原样重复同一个调用。"
    else:
        failure_reason = "execution_failed"
        next_action = (
            "上一个工具调用执行失败。请先根据 error、stderr、stdout 和 summary 判断错在哪；"
            "只有在参数、代码或方案已经改变时才允许再次调用，不要重复完全相同的调用。"
        )

    payload = {
        "tool_name": tool_name,
        "tool_args": truncate_tool_feedback_value(tool_args),
        "success": bool(success),
        "blocked": bool(blocked),
        "skipped": bool(skipped),
        "invalid_tool": bool(invalid),
        "failure_reason": failure_reason,
        "retry_same_call_allowed": False,
        "result": truncate_tool_feedback_value(model_result),
        "next_action": next_action,
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def readonly_write_tool_block_message(
    *,
    tool_name: str,
    task: str,
    mode_label: str,
) -> str:
    return (
        f"当前任务模式是“{mode_label}”，用户没有授权写入文件；已拦截写入工具 {tool_name}。"
        f"请不要再调用写入工具，直接基于已读取内容回答用户任务：{task}"
    )


def readonly_run_python_write_block_message(
    *,
    tool_args: Dict[str, Any],
    task: str,
    mode_label: str,
    explicit_readonly: bool,
    strong_write_patterns: tuple[Pattern[str], ...],
    artifact_write_patterns: tuple[Pattern[str], ...],
) -> str:
    code = str((tool_args or {}).get("code") or "")
    if not code.strip():
        return ""
    has_strong_write = any(pattern.search(code) for pattern in strong_write_patterns)
    has_artifact_write = any(
        pattern.search(code) for pattern in artifact_write_patterns
    )
    if not has_strong_write and not (explicit_readonly and has_artifact_write):
        return ""
    return (
        f"当前任务模式是“{mode_label}”，用户没有授权写入文件；已拦截 run_python_code 中的文件写入/保存代码。"
        f"请只用 Python 读取、计算和汇总，或直接输出分析结论；不要创建、保存、覆盖或移动文件。用户任务：{task}"
    )


def extract_tool_runtime_outcome(result: Any) -> Optional[Dict[str, Any]]:
    payload = result if isinstance(result, dict) else _json_payload(result)
    if not isinstance(payload, dict):
        return None

    raw_status = str(payload.get("status") or "").strip().lower()
    awaiting_confirmation = (
        bool(payload.get("awaiting_confirmation"))
        or raw_status == "awaiting_confirmation"
    )
    artifact = (
        payload.get("next_action_artifact")
        if isinstance(payload.get("next_action_artifact"), dict)
        else None
    )
    summary = str(payload.get("summary") or payload.get("error") or "").strip()
    suggested_next_step = str(payload.get("suggested_next_step") or "").strip()
    status = "awaiting_confirmation" if awaiting_confirmation else raw_status
    if not status and artifact is None:
        return None

    outcome: Dict[str, Any] = {
        "status": status or "needs_attention",
        "summary": summary,
    }
    if suggested_next_step:
        outcome["suggested_next_step"] = suggested_next_step
    if artifact is not None:
        outcome["next_action_artifact"] = artifact
    return outcome


def tool_runtime_status(tool_runtime_outcome: Optional[Dict[str, Any]]) -> str:
    if not isinstance(tool_runtime_outcome, dict):
        return ""
    return str(tool_runtime_outcome.get("status") or "").strip().lower()


def tool_artifacts(tool_name: str, result: Any) -> List[Dict[str, Any]]:
    if tool_name != "run_python_code":
        return []
    return extract_sandbox_artifacts(result)


def code_output_preview(tool_name: str, result: Any, result_text: str) -> str:
    if tool_name != "run_python_code" or not isinstance(result, dict):
        return _preview(result_text, 2000)

    parts: List[str] = []
    stdout = str(result.get("stdout") or "").strip()
    stderr = str(result.get("stderr") or "").strip()
    summary = str(result.get("summary") or "").strip()
    if stdout:
        parts.append(stdout)
    if stderr:
        parts.append(f"[stderr] {stderr}")
    if not parts and summary:
        parts.append(summary)
    return _preview("\n".join(parts) if parts else result_text, 2000)
