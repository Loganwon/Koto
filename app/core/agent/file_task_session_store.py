from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.core.config.atomic_json_store import (
    load_json_document,
    save_json_document,
    update_json_document,
)

_LOCK = threading.Lock()
_PLAN_MIGRATION_LOCK = threading.Lock()
_PLAN_MIGRATION_DONE = False


def _default_store_path() -> Path:
    return Path(
        os.environ.get(
            "KOTO_FILE_TASK_SUMMARY_PATH",
            Path(__file__).resolve().parents[3] / "data" / "file_task_summaries.json",
        )
    )


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def _safe_str(value: Any, limit: int = 0) -> str:
    text = str(value or "").strip()
    if limit and len(text) > limit:
        return text[:limit]
    return text


def _normalize_path(value: Any) -> str:
    return _safe_str(value, 1000).replace("\\", "/").rstrip("/")


def _path_keys(value: Any) -> set[str]:
    path = _normalize_path(value)
    if not path:
        return set()
    keys = {path.lower()}
    name = path.split("/")[-1]
    if name:
        keys.add(name.lower())
    return keys


def _load_records(path: Optional[str | Path] = None) -> List[Dict[str, Any]]:
    store_path = Path(path) if path else _default_store_path()
    raw = load_json_document(store_path, default=[])
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _write_records(
    records: List[Dict[str, Any]], path: Optional[str | Path] = None
) -> None:
    store_path = Path(path) if path else _default_store_path()
    save_json_document(store_path, records)


def save_task_summary(
    *,
    file_path: str,
    task: str = "",
    outcome: str = "",
    summary: str = "",
    path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    clean_file_path = _normalize_path(file_path)
    clean_summary = _safe_str(summary, 4000)
    if not clean_file_path or not clean_summary:
        return {}

    now = _now_iso()
    record = {
        "id": f"fts_{uuid.uuid4().hex[:12]}",
        "file_path": clean_file_path,
        "task": _safe_str(task, 500),
        "outcome": _safe_str(outcome, 64) or "completed",
        "summary": clean_summary,
        "created_at": now,
        "updated_at": now,
    }
    store_path = Path(path) if path else _default_store_path()

    def _append(current: Any) -> List[Dict[str, Any]]:
        records = (
            [item for item in current if isinstance(item, dict)]
            if isinstance(current, list)
            else []
        )
        records.append(record)
        return records[-500:]

    with _LOCK:
        update_json_document(store_path, _append, default=[])
    return dict(record)


def load_recent_summaries(
    file_paths: Iterable[str],
    *,
    limit: int = 5,
    path: Optional[str | Path] = None,
) -> List[Dict[str, Any]]:
    requested_keys: set[str] = set()
    for file_path in file_paths or []:
        requested_keys.update(_path_keys(file_path))
    if not requested_keys:
        return []

    safe_limit = max(1, min(int(limit or 5), 20))
    with _LOCK:
        records = _load_records(path)
    matches: List[Dict[str, Any]] = []
    for record in reversed(records):
        record_keys = _path_keys(record.get("file_path"))
        if not record_keys.intersection(requested_keys):
            continue
        matches.append(dict(record))
        if len(matches) >= safe_limit:
            break
    return matches


def format_summaries_as_context(summaries: Iterable[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for item in summaries or []:
        if not isinstance(item, dict):
            continue
        file_path = _safe_str(item.get("file_path"), 160)
        task = _safe_str(item.get("task"), 180)
        outcome = _safe_str(item.get("outcome"), 64)
        summary = _safe_str(item.get("summary"), 600)
        if not summary:
            continue
        prefix_parts = [part for part in (file_path, outcome) if part]
        prefix = " / ".join(prefix_parts)
        task_part = f"；任务：{task}" if task else ""
        lines.append(
            f"- {prefix}{task_part}；结果：{summary}" if prefix else f"- {summary}"
        )
    if not lines:
        return ""
    return "最近相关文件任务记录：\n" + "\n".join(lines[:10])


def _plan_store_path() -> Path:
    return Path(
        os.environ.get(
            "KOTO_FILE_TASK_PLAN_PATH",
            Path(__file__).resolve().parents[3] / "data" / "file_task_plans.json",
        )
    )


def _legacy_plan_store_paths() -> List[Path]:
    primary = _plan_store_path()
    paths = [primary]
    if "KOTO_FILE_TASK_PLAN_PATH" not in os.environ:
        old_source_path = (
            Path(__file__).resolve().parents[3] / "config" / "file_task_plans.json"
        )
        if old_source_path != primary:
            paths.append(old_source_path)
    return paths


def _migrate_legacy_plan_store_once() -> None:
    """Import the former JSON plan ledger into SQLite without deleting it."""
    global _PLAN_MIGRATION_DONE
    if _PLAN_MIGRATION_DONE:
        return
    with _PLAN_MIGRATION_LOCK:
        if _PLAN_MIGRATION_DONE:
            return
        for legacy_path in _legacy_plan_store_paths():
            if not legacy_path.exists():
                continue
            records = load_json_document(legacy_path, default=[])
            if not isinstance(records, list):
                raise RuntimeError("legacy file-task plans must be a JSON array")
            from app.core.tasks.task_ledger import get_ledger

            ledger = get_ledger()
            for record in records:
                if not isinstance(record, dict):
                    continue
                run_id = str(record.get("run_id") or "").strip()
                if run_id:
                    ledger.upsert_task_plan(run_id, record)
        _PLAN_MIGRATION_DONE = True


def save_task_plan(
    *,
    run_id: str,
    recipe_id: Optional[str] = None,
    task: Optional[str] = None,
    target_path: Optional[str] = None,
    source_path: Optional[str] = None,
    total_steps: Optional[int] = None,
    completed_steps: Optional[int] = None,
    current_page_start: Optional[int] = None,
    current_page_end: Optional[int] = None,
    total_pages: Optional[int] = None,
    total_paragraphs: Optional[int] = None,
    status: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Save or update a task plan for cross-step continuity."""
    clean_run_id = str(run_id or "").strip()
    if not clean_run_id:
        return {}

    from app.core.tasks.task_ledger import get_ledger

    _migrate_legacy_plan_store_once()

    patch: Dict[str, Any] = {}
    text_fields = {
        "recipe_id": recipe_id,
        "task": task,
        "target_path": target_path,
        "source_path": source_path,
        "status": status,
    }
    for key, value in text_fields.items():
        if value is None:
            continue
        if key in {"target_path", "source_path"}:
            patch[key] = _normalize_path(value)
        elif key == "task":
            patch[key] = str(value or "")[:500]
        elif key == "status":
            patch[key] = str(value or "in_progress")[:32]
        else:
            patch[key] = str(value or "")
    for key, value in {
        "total_steps": total_steps,
        "completed_steps": completed_steps,
        "current_page_start": current_page_start,
        "current_page_end": current_page_end,
        "total_pages": total_pages,
        "total_paragraphs": total_paragraphs,
    }.items():
        if value is not None:
            patch[key] = max(0, int(value or 0))
    if isinstance(extra, dict):
        patch["extra"] = dict(extra)

    existing = get_ledger().get_task_plan(clean_run_id)
    if existing is None:
        defaults = {
            "recipe_id": "",
            "task": "",
            "target_path": "",
            "source_path": "",
            "total_steps": 0,
            "completed_steps": 0,
            "current_page_start": 0,
            "current_page_end": 0,
            "total_pages": 0,
            "total_paragraphs": 0,
            "status": "in_progress",
            "extra": {},
        }
        defaults.update(patch)
        patch = defaults
    return get_ledger().upsert_task_plan(clean_run_id, patch)


def load_task_plan(run_id: str) -> Optional[Dict[str, Any]]:
    """Load a task plan by run_id."""
    clean_run_id = str(run_id or "").strip()
    if not clean_run_id:
        return None

    from app.core.tasks.task_ledger import get_ledger

    _migrate_legacy_plan_store_once()
    return get_ledger().get_task_plan(clean_run_id)


def load_active_plans(limit: int = 10) -> List[Dict[str, Any]]:
    """Load all active (in_progress) task plans."""
    from app.core.tasks.task_ledger import get_ledger

    _migrate_legacy_plan_store_once()
    return get_ledger().list_task_plans(status="in_progress", limit=limit)


def mark_plan_complete(run_id: str) -> bool:
    """Mark a task plan as completed."""
    clean_run_id = str(run_id or "").strip()
    if not clean_run_id:
        return False
    from app.core.tasks.task_ledger import get_ledger

    _migrate_legacy_plan_store_once()
    if get_ledger().get_task_plan(clean_run_id) is None:
        return False
    get_ledger().upsert_task_plan(clean_run_id, {"status": "completed"})
    get_ledger().mark_control_terminal(clean_run_id, "completed")
    return True


def format_plan_as_context(plan: Optional[Dict[str, Any]]) -> str:
    """Format a task plan as context for the next step."""
    if not plan:
        return ""
    parts = [
        f"跨步骤任务计划 (run_id={plan.get('run_id', '')}):",
        f"- 任务: {plan.get('task', '')}",
        f"- 方案: {plan.get('recipe_id', '')}",
        f"- 目标文件: {plan.get('target_path', '')}",
        f"- 源文件: {plan.get('source_path', '')}",
    ]
    if plan.get("total_pages"):
        parts.append(f"- 总页数: {plan['total_pages']}")
    if plan.get("total_steps"):
        parts.append(
            f"- 总步骤: {plan['total_steps']} / 已完成: {plan['completed_steps']}"
        )
    if plan.get("current_page_end"):
        parts.append(
            f"- 当前进度: 第 {plan['current_page_start']}-{plan['current_page_end']} 页已处理"
        )
    if plan.get("total_paragraphs"):
        parts.append(f"- 已写入段落: {plan['total_paragraphs']}")
    if plan.get("extra"):
        for k, v in plan["extra"].items():
            parts.append(f"- {k}: {v}")
    return "\n".join(parts)
