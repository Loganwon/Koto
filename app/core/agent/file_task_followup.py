from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_ALLOWED_STATUSES = {"open", "accepted", "done", "dismissed"}


def _default_store_path() -> Path:
    return Path(
        os.environ.get(
            "KOTO_FILE_TASK_FOLLOWUP_PATH",
            Path(__file__).resolve().parents[3] / "config" / "file_task_followups.json",
        )
    )


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def _safe_str(value: Any, limit: int = 0) -> str:
    text = str(value or "").strip()
    if limit and len(text) > limit:
        return text[:limit]
    return text


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")
    )


def _record_id_for(artifact: Dict[str, Any]) -> str:
    proposed_tool = (
        artifact.get("proposed_tool")
        if isinstance(artifact.get("proposed_tool"), dict)
        else {}
    )
    identity = {
        "artifact_type": artifact.get("artifact_type"),
        "category": artifact.get("category"),
        "missing_capability": artifact.get("missing_capability"),
        "source_task": artifact.get("source_task"),
        "target_path": artifact.get("target_path"),
        "proposed_tool_name": proposed_tool.get("name"),
    }
    digest = hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()[:16]
    return f"ftf_{digest}"


def _public_record(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": _safe_str(record.get("id")),
        "status": _safe_str(record.get("status")) or "open",
        "created_at": _safe_str(record.get("created_at")),
        "updated_at": _safe_str(record.get("updated_at")),
        "run_id": _safe_str(record.get("run_id")),
        "session_id": _safe_str(record.get("session_id")),
        "source": _safe_str(record.get("source")) or "file_task_runtime",
        "occurrences": int(record.get("occurrences") or 1),
        "artifact": (
            record.get("artifact") if isinstance(record.get("artifact"), dict) else {}
        ),
    }


class FileTaskFollowupStore:
    def __init__(self, path: Optional[str | Path] = None):
        self.path = Path(path) if path else _default_store_path()
        self._lock = threading.Lock()

    def list(self, *, status: str = "", limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            records = self._load_unlocked()
        if status:
            records = [
                item for item in records if str(item.get("status") or "") == status
            ]
        records.sort(
            key=lambda item: str(
                item.get("updated_at") or item.get("created_at") or ""
            ),
            reverse=True,
        )
        safe_limit = max(1, min(int(limit or 100), 500))
        return [_public_record(item) for item in records[:safe_limit]]

    def upsert(
        self,
        artifact: Dict[str, Any],
        *,
        run_id: str = "",
        session_id: str = "",
        source: str = "file_task_runtime",
    ) -> Dict[str, Any]:
        if not isinstance(artifact, dict) or not artifact:
            raise ValueError("next_action_artifact must be a non-empty object")

        now = _now_iso()
        record_id = _record_id_for(artifact)
        with self._lock:
            records = self._load_unlocked()
            for item in records:
                if item.get("id") != record_id:
                    continue
                item["artifact"] = dict(artifact)
                item["run_id"] = _safe_str(run_id, 128) or _safe_str(
                    item.get("run_id"), 128
                )
                item["session_id"] = _safe_str(session_id, 128) or _safe_str(
                    item.get("session_id"), 128
                )
                item["source"] = _safe_str(source, 64) or "file_task_runtime"
                item["updated_at"] = now
                item["occurrences"] = int(item.get("occurrences") or 1) + 1
                self._write_unlocked(records)
                return _public_record(item)

            record = {
                "id": record_id,
                "status": "open",
                "created_at": now,
                "updated_at": now,
                "run_id": _safe_str(run_id, 128),
                "session_id": _safe_str(session_id, 128),
                "source": _safe_str(source, 64) or "file_task_runtime",
                "occurrences": 1,
                "artifact": dict(artifact),
            }
            records.append(record)
            self._write_unlocked(records)
            return _public_record(record)

    def update_status(self, record_id: str, status: str) -> Dict[str, Any]:
        clean_id = _safe_str(record_id, 64)
        clean_status = _safe_str(status, 32)
        if clean_status not in _ALLOWED_STATUSES:
            raise ValueError(f"unsupported follow-up status: {clean_status}")

        with self._lock:
            records = self._load_unlocked()
            for item in records:
                if item.get("id") != clean_id:
                    continue
                item["status"] = clean_status
                item["updated_at"] = _now_iso()
                self._write_unlocked(records)
                return _public_record(item)
        raise KeyError(clean_id)

    def _load_unlocked(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict)]

    def _write_unlocked(self, records: List[Dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp_path.replace(self.path)


def get_file_task_followup_store(
    path: Optional[str | Path] = None,
) -> FileTaskFollowupStore:
    return FileTaskFollowupStore(path)
