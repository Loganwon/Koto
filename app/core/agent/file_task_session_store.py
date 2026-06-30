from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_LOCK = threading.Lock()


def _default_store_path() -> Path:
    return Path(
        os.environ.get(
            "KOTO_FILE_TASK_SUMMARY_PATH",
            Path(__file__).resolve().parents[3] / "config" / "file_task_summaries.json",
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
    if not store_path.exists():
        return []
    try:
        raw = json.loads(store_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _write_records(
    records: List[Dict[str, Any]], path: Optional[str | Path] = None
) -> None:
    store_path = Path(path) if path else _default_store_path()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = store_path.with_suffix(store_path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temp_path.replace(store_path)


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
    with _LOCK:
        records = _load_records(path)
        records.append(record)
        records = records[-500:]
        _write_records(records, path)
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
            Path(__file__).resolve().parents[3] / "config" / "file_task_plans.json",
        )
    )


def save_task_plan(
    *,
    run_id: str,
    recipe_id: str = "",
    task: str = "",
    target_path: str = "",
    source_path: str = "",
    total_steps: int = 0,
    completed_steps: int = 0,
    current_page_start: int = 0,
    current_page_end: int = 0,
    total_pages: int = 0,
    total_paragraphs: int = 0,
    status: str = "in_progress",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Save or update a task plan for cross-step continuity."""
    clean_run_id = str(run_id or "").strip()
    if not clean_run_id:
        return {}

    now = _now_iso()
    plan = {
        "run_id": clean_run_id,
        "recipe_id": str(recipe_id or ""),
        "task": str(task or "")[:500],
        "target_path": _normalize_path(target_path),
        "source_path": _normalize_path(source_path),
        "total_steps": max(0, int(total_steps or 0)),
        "completed_steps": max(0, int(completed_steps or 0)),
        "current_page_start": max(0, int(current_page_start or 0)),
        "current_page_end": max(0, int(current_page_end or 0)),
        "total_pages": max(0, int(total_pages or 0)),
        "total_paragraphs": max(0, int(total_paragraphs or 0)),
        "status": str(status or "in_progress")[:32],
        "extra": dict(extra) if isinstance(extra, dict) else {},
        "created_at": now,
        "updated_at": now,
    }

    store_path = _plan_store_path()
    store_path.parent.mkdir(parents=True, exist_ok=True)

    with _LOCK:
        records = []
        if store_path.exists():
            try:
                records = json.loads(store_path.read_text(encoding="utf-8"))
            except Exception:
                records = []
        if not isinstance(records, list):
            records = []

        # Update existing or append
        found = False
        for i, rec in enumerate(records):
            if isinstance(rec, dict) and rec.get("run_id") == clean_run_id:
                plan["created_at"] = rec.get("created_at", now)
                records[i] = plan
                found = True
                break
        if not found:
            records.append(plan)

        records = records[-200:]
        temp_path = store_path.with_suffix(store_path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp_path.replace(store_path)

    return dict(plan)


def load_task_plan(run_id: str) -> Optional[Dict[str, Any]]:
    """Load a task plan by run_id."""
    clean_run_id = str(run_id or "").strip()
    if not clean_run_id:
        return None

    store_path = _plan_store_path()
    if not store_path.exists():
        return None

    with _LOCK:
        try:
            records = json.loads(store_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    if not isinstance(records, list):
        return None

    for rec in reversed(records):
        if isinstance(rec, dict) and rec.get("run_id") == clean_run_id:
            return dict(rec)
    return None


def load_active_plans(limit: int = 10) -> List[Dict[str, Any]]:
    """Load all active (in_progress) task plans."""
    store_path = _plan_store_path()
    if not store_path.exists():
        return []

    with _LOCK:
        try:
            records = json.loads(store_path.read_text(encoding="utf-8"))
        except Exception:
            return []

    if not isinstance(records, list):
        return []

    active = [
        dict(r)
        for r in records
        if isinstance(r, dict) and r.get("status") == "in_progress"
    ]
    return active[-limit:]


def mark_plan_complete(run_id: str) -> bool:
    """Mark a task plan as completed."""
    return bool(
        save_task_plan(
            run_id=run_id,
            status="completed",
        )
    )


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
