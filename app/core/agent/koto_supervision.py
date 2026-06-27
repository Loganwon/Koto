# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Read-mostly supervision helpers exposed through Koto's MCP endpoint.

The functions here are intentionally conservative: paths are constrained to the
project root, code search uses bounded output, and test execution is limited to
pytest targets inside the repository.
"""

from __future__ import annotations

import os
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List


_LAST_TEST_RUN: Dict[str, Any] = {}
_TEST_LOCK = threading.Lock()


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _commonpath(a: Path, b: Path) -> str:
    return os.path.commonpath([str(a.resolve()), str(b.resolve())])


def resolve_project_path(path: str | None = ".") -> Path:
    root = project_root().resolve()
    raw = path or "."
    candidate = (root / raw).resolve()
    if _commonpath(root, candidate) != str(root):
        raise ValueError(f"path is outside project root: {raw}")
    return candidate


def _run(command: List[str], timeout: int = 20) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault("HF_HUB_OFFLINE", "1")
    env.setdefault("TRANSFORMERS_OFFLINE", "1")
    env.setdefault("HF_DATASETS_OFFLINE", "1")
    env.setdefault("TOKENIZERS_PARALLELISM", "false")
    return subprocess.run(
        command,
        cwd=str(project_root()),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
        env=env,
    )


def _tail(text: str, max_chars: int = 12000) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _coerce_limit(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(parsed, maximum))


def recent_file_changes(limit: int = 100, **_: Any) -> Dict[str, Any]:
    """Return current git status for supervision and change attribution."""

    limit = _coerce_limit(limit, 100, 1, 500)
    try:
        proc = _run(["git", "status", "--short"], timeout=10)
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        changes = []
        for line in lines[:limit]:
            status = line[:2].strip()
            path = line[3:].strip() if len(line) > 3 else ""
            changes.append({"status": status, "path": path, "raw": line})
        return {
            "success": proc.returncode == 0,
            "count": len(lines),
            "returned": len(changes),
            "changes": changes,
            "stderr": _tail(proc.stderr, 2000),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "changes": []}


def read_file_snippet(
    path: str,
    start_line: int = 1,
    max_chars: int = 4000,
    **_: Any,
) -> Dict[str, Any]:
    """Read a bounded text snippet from a file inside the Koto project."""

    target = resolve_project_path(path)
    if not target.exists() or not target.is_file():
        raise ValueError(f"file not found: {path}")
    start_line = _coerce_limit(start_line, 1, 1, 1_000_000)
    max_chars = _coerce_limit(max_chars, 4000, 200, 20000)
    text = target.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    selected: List[str] = []
    char_count = 0
    for idx in range(start_line - 1, len(lines)):
        rendered = f"{idx + 1}: {lines[idx]}"
        selected.append(rendered)
        char_count += len(rendered) + 1
        if char_count >= max_chars:
            break
    return {
        "path": str(target.relative_to(project_root())),
        "start_line": start_line,
        "total_lines": len(lines),
        "snippet": "\n".join(selected),
    }


def search_code(
    pattern: str,
    path: str = ".",
    max_results: int = 50,
    **_: Any,
) -> Dict[str, Any]:
    """Search source text with ripgrep, constrained to the project root."""

    if not pattern or not str(pattern).strip():
        raise ValueError("pattern is required")
    if len(pattern) > 200:
        raise ValueError("pattern is too long")
    target = resolve_project_path(path)
    max_results = _coerce_limit(max_results, 50, 1, 200)
    rel = str(target.relative_to(project_root()))
    command = [
        "rg",
        "--line-number",
        "--column",
        "--smart-case",
        "--glob",
        "!dist/**",
        "--glob",
        "!build/**",
        "--glob",
        "!web/static/vendor/**",
        str(pattern),
        rel,
    ]
    try:
        proc = _run(command, timeout=15)
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        return {
            "success": proc.returncode in (0, 1),
            "count": len(lines),
            "returned": min(len(lines), max_results),
            "matches": lines[:max_results],
            "stderr": _tail(proc.stderr, 2000),
        }
    except FileNotFoundError:
        return {"success": False, "error": "ripgrep (rg) is not installed", "matches": []}


def recent_events(limit: int = 30, **_: Any) -> Dict[str, Any]:
    """Return recent log tails from Koto's logs directory."""

    root = project_root()
    logs_dir = root / "logs"
    limit = _coerce_limit(limit, 30, 1, 100)
    if not logs_dir.exists():
        return {"success": True, "events": [], "message": "logs directory not found"}
    files = [
        p
        for p in logs_dir.iterdir()
        if p.is_file() and p.suffix.lower() in {".log", ".txt", ".jsonl"}
    ]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    events = []
    for path in files[: min(5, len(files))]:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = [line for line in text.splitlines() if line.strip()]
        for line in lines[-limit:]:
            events.append(
                {
                    "file": str(path.relative_to(root)),
                    "mtime": path.stat().st_mtime,
                    "text": line[-1000:],
                }
            )
    events.sort(key=lambda item: item["mtime"], reverse=True)
    return {"success": True, "count": len(events), "events": events[:limit]}


def route_map(limit: int = 300, **_: Any) -> Dict[str, Any]:
    """Return Flask routes visible in the current application context."""

    from flask import current_app

    limit = _coerce_limit(limit, 300, 1, 1000)
    rules = []
    for rule in sorted(current_app.url_map.iter_rules(), key=lambda r: str(r.rule)):
        rules.append(
            {
                "rule": str(rule.rule),
                "endpoint": rule.endpoint,
                "methods": sorted(m for m in rule.methods if m not in {"HEAD", "OPTIONS"}),
            }
        )
    return {"count": len(rules), "returned": min(len(rules), limit), "routes": rules[:limit]}


def agent_tool_inventory(full: bool = False, limit: int = 300, **_: Any) -> Dict[str, Any]:
    """Build a Koto agent tool registry and return available tool definitions."""

    from app.core.agent.factory import _build_registry

    limit = _coerce_limit(limit, 300, 1, 1000)
    registry = _build_registry(api_key=None, full=bool(full))
    tools = registry.get_definitions()
    compact = [
        {
            "name": item.get("name"),
            "description": item.get("description", ""),
            "parameters": item.get("parameters", {}),
        }
        for item in tools[:limit]
    ]
    return {"count": len(tools), "returned": len(compact), "tools": compact}


def _task_ledger():
    from app.core.tasks.task_ledger import get_ledger

    return get_ledger()


def _progress_bus():
    from app.core.tasks.progress_bus import get_progress_bus

    return get_progress_bus()


def _parse_json_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def _step_to_dict(step: Any) -> Dict[str, Any]:
    data = step.to_dict() if hasattr(step, "to_dict") else dict(step)
    data["tool_args"] = _parse_json_text(data.get("tool_args"))
    return data


def _task_to_dict(task: Any, include_steps: bool = False) -> Dict[str, Any]:
    data = task.to_dict() if hasattr(task, "to_dict") else dict(task)
    data["metadata"] = _parse_json_text(data.get("metadata"))
    if include_steps:
        data["steps"] = [_step_to_dict(step) for step in getattr(task, "steps", [])]
    return data


def recent_tasks(
    session_id: str = "",
    source: str = "",
    status: str = "",
    limit: int = 20,
    include_steps: bool = False,
    **_: Any,
) -> Dict[str, Any]:
    """Return recent tasks from the persistent task ledger."""

    from app.core.tasks.task_ledger import TaskStatus

    limit = _coerce_limit(limit, 20, 1, 100)
    status_value = TaskStatus(status) if status else None
    tasks = _task_ledger().list_tasks(
        session_id=session_id or None,
        source=source or None,
        status=status_value,
        limit=limit,
    )
    if include_steps:
        ledger = _task_ledger()
        for task in tasks:
            task.steps = ledger.get_steps(task.task_id)
    return {
        "success": True,
        "count": len(tasks),
        "tasks": [_task_to_dict(task, include_steps=include_steps) for task in tasks],
    }


def task_progress_history(task_id: str, **_: Any) -> Dict[str, Any]:
    """Return in-memory progress events for a task."""

    events = [event.to_dict() for event in _progress_bus().get_history(task_id)]
    return {"success": True, "task_id": task_id, "count": len(events), "events": events}


def task_status(task_id: str, include_steps: bool = True, **_: Any) -> Dict[str, Any]:
    """Return task ledger status plus recent progress events."""

    ledger = _task_ledger()
    task = ledger.get(task_id, include_steps=include_steps)
    if not task:
        return {"success": False, "error": f"task not found: {task_id}"}
    progress = task_progress_history(task_id)
    latest = progress["events"][-1] if progress["events"] else {}
    data = _task_to_dict(task, include_steps=include_steps)
    if latest:
        data.update(
            {
                "progress": latest.get("progress"),
                "step_type": latest.get("step_type"),
                "latest_event": latest,
            }
        )
    return {"success": True, "task": data}


def _normalize_test_targets(targets: Any) -> List[str]:
    if targets in (None, "", []):
        return ["tests/unit/test_mcp_integration.py"]
    if isinstance(targets, str):
        raw_targets: Iterable[str] = [targets]
    elif isinstance(targets, list):
        raw_targets = [str(item) for item in targets]
    else:
        raise ValueError("targets must be a string or list of strings")

    normalized: List[str] = []
    root = project_root().resolve()
    for raw in raw_targets:
        value = raw.strip()
        if not value or value.startswith("-"):
            raise ValueError(f"invalid pytest target: {raw}")
        path_part, sep, node_part = value.partition("::")
        target_path = resolve_project_path(path_part)
        if _commonpath(root / "tests", target_path) != str((root / "tests").resolve()):
            raise ValueError(f"pytest target must be under tests/: {raw}")
        if not target_path.exists():
            raise ValueError(f"pytest target not found: {raw}")
        normalized.append(str(target_path.relative_to(root)) + (sep + node_part if sep else ""))
    return normalized


def run_tests(targets: Any = None, timeout: int = 120, **_: Any) -> Dict[str, Any]:
    """Run a constrained pytest command and remember the latest result."""

    timeout = _coerce_limit(timeout, 120, 5, 300)
    test_targets = _normalize_test_targets(targets)
    command = [sys.executable, "-m", "pytest", "-q", *test_targets]
    started = time.time()
    with _TEST_LOCK:
        try:
            proc = _run(command, timeout=timeout)
            result = {
                "success": proc.returncode == 0,
                "exit_code": proc.returncode,
                "duration_seconds": round(time.time() - started, 3),
                "command": command,
                "stdout_tail": _tail(proc.stdout),
                "stderr_tail": _tail(proc.stderr),
                "targets": test_targets,
                "timestamp": started,
            }
        except subprocess.TimeoutExpired as exc:
            result = {
                "success": False,
                "exit_code": None,
                "duration_seconds": round(time.time() - started, 3),
                "command": command,
                "stdout_tail": _tail(exc.stdout or ""),
                "stderr_tail": _tail(exc.stderr or ""),
                "targets": test_targets,
                "timestamp": started,
                "error": f"pytest timed out after {timeout}s",
            }
        _LAST_TEST_RUN.clear()
        _LAST_TEST_RUN.update(result)
        return dict(result)


def test_status(**_: Any) -> Dict[str, Any]:
    """Return the latest pytest result triggered via koto_run_tests."""

    if not _LAST_TEST_RUN:
        return {"has_result": False}
    return {"has_result": True, **dict(_LAST_TEST_RUN)}
