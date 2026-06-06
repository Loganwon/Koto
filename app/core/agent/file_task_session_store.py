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


def _write_records(records: List[Dict[str, Any]], path: Optional[str | Path] = None) -> None:
    store_path = Path(path) if path else _default_store_path()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = store_path.with_suffix(store_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
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
        lines.append(f"- {prefix}{task_part}；结果：{summary}" if prefix else f"- {summary}")
    if not lines:
        return ""
    return "最近相关文件任务记录：\n" + "\n".join(lines[:10])
