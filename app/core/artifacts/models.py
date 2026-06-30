# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Canonical artifact result objects shared by Agent and workspace UI."""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Optional

_FILE_EXT_TO_TYPE = {
    ".doc": "docx",
    ".docx": "docx",
    ".ppt": "pptx",
    ".pptx": "pptx",
    ".xls": "xlsx",
    ".xlsx": "xlsx",
    ".csv": "xlsx",
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".bmp": "image",
    ".webp": "image",
    ".svg": "image",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".json": "data",
}

_WORKSPACE_PATH_RE = re.compile(
    r"(?P<path>(?:workspace/|\.?/)?[^\s`'\"<>|]+?\."
    r"(?:docx|doc|pptx|ppt|xlsx|xls|csv|pdf|png|jpe?g|gif|bmp|webp|svg|md|markdown|txt|json))",
    re.IGNORECASE,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now() -> float:
    return time.time()


def _clean_text(value: Any, limit: int = 1000) -> str:
    text = str(value or "").strip()
    if limit > 0 and len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def _clean_path(value: Any) -> str:
    path = str(value or "").strip().strip("`'\"")
    if not path:
        return ""
    path = path.replace("\\", "/")
    workspace_idx = path.lower().find("workspace/")
    if workspace_idx > 0:
        path = path[workspace_idx:]
    if path.startswith("./"):
        path = path[2:]
    return path


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _artifact_type_from_path(path: str) -> str:
    ext = PurePosixPath(path).suffix.lower()
    return _FILE_EXT_TO_TYPE.get(ext, "file")


def _preview_url_for_path(path: str) -> str:
    if not path:
        return ""
    if path.startswith(("http://", "https://", "/")):
        return path
    return ""


def _iter_unique_paths(texts: Iterable[str]) -> List[str]:
    seen = set()
    paths: List[str] = []
    for text in texts:
        for match in _WORKSPACE_PATH_RE.finditer(str(text or "")):
            path = _clean_path(match.group("path"))
            key = path.lower()
            if path and key not in seen:
                seen.add(key)
                paths.append(path)
    return paths


@dataclass
class Artifact:
    id: str = field(default_factory=lambda: _new_id("artifact"))
    type: str = "file"
    title: str = ""
    path: str = ""
    preview_url: str = ""
    source_path: str = ""
    status: str = "ready"
    created_at: float = field(default_factory=_now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.path = _clean_path(self.path)
        self.source_path = _clean_path(self.source_path)
        if not self.type or self.type == "file":
            self.type = _artifact_type_from_path(self.path)
        if not self.title:
            self.title = PurePosixPath(self.path).name or "任务产物"
        if not self.preview_url:
            self.preview_url = _preview_url_for_path(self.path)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "path": self.path,
            "preview_url": self.preview_url,
            "source_path": self.source_path,
            "status": self.status,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


@dataclass
class FileChange:
    id: str = field(default_factory=lambda: _new_id("change"))
    file: str = ""
    kind: str = "update"
    summary: str = ""
    status: str = "applied"
    before_preview: str = ""
    after_preview: str = ""
    created_at: float = field(default_factory=_now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.file = _clean_path(self.file)
        self.summary = _clean_text(self.summary, 500)
        self.before_preview = _clean_text(self.before_preview, 1000)
        self.after_preview = _clean_text(self.after_preview, 1000)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "file": self.file,
            "kind": self.kind,
            "summary": self.summary,
            "status": self.status,
            "before_preview": self.before_preview,
            "after_preview": self.after_preview,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


@dataclass
class SourceRef:
    id: str = field(default_factory=lambda: _new_id("source"))
    title: str = ""
    file: str = ""
    locator: str = ""
    url: str = ""
    snippet: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.file = _clean_path(self.file)
        self.title = _clean_text(self.title or self.file or self.url or "来源", 200)
        self.snippet = _clean_text(self.snippet, 800)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "file": self.file,
            "locator": self.locator,
            "url": self.url,
            "snippet": self.snippet,
            "metadata": self.metadata,
        }


@dataclass
class ExecutionLog:
    level: str = "info"
    message: str = ""
    ts: float = field(default_factory=_now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.level = (
            self.level if self.level in {"debug", "info", "warn", "error"} else "info"
        )
        self.message = _clean_text(self.message, 800)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "message": self.message,
            "ts": self.ts,
            "metadata": self.metadata,
        }


@dataclass
class ArtifactResult:
    task_id: str
    title: str = ""
    status: str = "running"
    summary: str = ""
    artifacts: List[Artifact] = field(default_factory=list)
    changes: List[FileChange] = field(default_factory=list)
    sources: List[SourceRef] = field(default_factory=list)
    logs: List[ExecutionLog] = field(default_factory=list)
    actions: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.title = _clean_text(self.title or "Koto 任务结果", 200)
        self.summary = _clean_text(self.summary, 2000)
        if not self.actions:
            self.actions = self.default_actions()

    def default_actions(self) -> List[str]:
        actions = ["continue_editing"]
        if self.artifacts:
            actions = ["open", "download", "continue_editing"]
        if self.changes:
            actions.extend(["review_changes", "revert"])
        return list(dict.fromkeys(actions))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "status": self.status,
            "summary": self.summary,
            "artifacts": [item.to_dict() for item in self.artifacts],
            "changes": [item.to_dict() for item in self.changes],
            "sources": [item.to_dict() for item in self.sources],
            "logs": [item.to_dict() for item in self.logs],
            "actions": self.actions,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }


def _result_status_from_phase(phase: str, error: str = "") -> str:
    if error:
        return "failed"
    phase_value = str(phase or "").lower()
    if phase_value in {"done", "completed", "success"}:
        return "completed"
    if phase_value in {"review", "needs_review", "waiting"}:
        return "needs_review"
    if phase_value in {"failed", "error", "cancelled"}:
        return "failed"
    return "running"


def _change_kind_from_step(step: Any) -> str:
    hint = str(getattr(step, "tool_hint", "") or "").lower()
    text = " ".join(
        [
            str(getattr(step, "title", "") or ""),
            str(getattr(step, "description", "") or ""),
        ]
    ).lower()
    if "convert" in hint or "转换" in text:
        return "convert"
    if "write" in hint or "save" in hint or "写" in text or "保存" in text:
        return "update"
    if "annotate" in hint or "批注" in text:
        return "comment"
    return "step"


def _field_value(item: Any, *keys: str) -> Any:
    if isinstance(item, Mapping):
        for key in keys:
            if item.get(key) not in (None, "", [], {}):
                return item.get(key)
    for key in keys:
        value = getattr(item, key, None)
        if value not in (None, "", [], {}):
            return value
    return ""


def _public_file_info(item: Any) -> Dict[str, Any]:
    if item is None:
        return {}
    if hasattr(item, "public_dict"):
        try:
            payload = item.public_dict()
        except Exception:
            payload = {}
        return dict(payload) if isinstance(payload, Mapping) else {}
    if isinstance(item, Mapping):
        return dict(item)
    payload: Dict[str, Any] = {}
    for key in ("path", "name", "type", "target"):
        value = getattr(item, key, None)
        if value not in (None, "", [], {}):
            payload[key] = value
    return payload


def _compact_metadata(payload: Mapping[str, Any], *, limit: int = 28) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    skipped = {
        "artifact_result",
        "context",
        "diff",
        "file_changes",
        "original_selection",
        "preview",
        "result_preview",
        "workflow_state",
    }
    for key, value in payload.items():
        if len(metadata) >= limit:
            break
        key_text = str(key or "").strip()
        if not key_text or key_text in skipped or value in (None, "", [], {}):
            continue
        if isinstance(value, (str, int, float, bool)):
            metadata[key_text] = (
                _clean_text(value, 400) if isinstance(value, str) else value
            )
        elif isinstance(value, list):
            cleaned = [
                _clean_text(item, 200) if isinstance(item, str) else item
                for item in value[:8]
                if item not in (None, "", [], {})
            ]
            if cleaned:
                metadata[key_text] = cleaned
        elif isinstance(value, Mapping):
            cleaned_map: Dict[str, Any] = {}
            for sub_key, sub_value in list(value.items())[:8]:
                if sub_value in (None, "", [], {}):
                    continue
                if isinstance(sub_value, (str, int, float, bool)):
                    cleaned_map[str(sub_key)] = (
                        _clean_text(sub_value, 200)
                        if isinstance(sub_value, str)
                        else sub_value
                    )
            if cleaned_map:
                metadata[key_text] = cleaned_map
    return metadata


def _file_task_output_path(change: Mapping[str, Any]) -> str:
    return _clean_path(
        _field_value(
            change,
            "path",
            "file_path",
            "output_path",
            "target_path",
            "destination",
            "revised_file",
        )
    )


def _file_task_source_path(change: Mapping[str, Any]) -> str:
    return _clean_path(
        _field_value(
            change,
            "source_path",
            "compare_path",
            "original_target_path",
            "input_path",
            "source",
        )
    )


def _file_task_change_key(change: Mapping[str, Any]) -> str:
    path = _file_task_output_path(change).lower()
    operation = (
        str(_field_value(change, "operation", "tool_name") or "").strip().lower()
    )
    summary = _clean_text(
        _field_value(change, "summary", "title", "message"), 160
    ).lower()
    return "|".join([path, operation, summary])


def _merge_file_task_changes(*change_groups: Iterable[Any]) -> List[Dict[str, Any]]:
    seen = set()
    changes: List[Dict[str, Any]] = []
    for group in change_groups:
        for item in group or []:
            if not isinstance(item, Mapping):
                continue
            change = dict(item)
            path = _file_task_output_path(change)
            if not path:
                continue
            key = _file_task_change_key(change)
            if key in seen:
                continue
            seen.add(key)
            changes.append(change)
    return changes


def _file_task_change_kind(change: Mapping[str, Any]) -> str:
    change_type = str(_field_value(change, "change_type") or "").strip().lower()
    operation = (
        str(_field_value(change, "operation", "tool_name") or "").strip().lower()
    )
    text = " ".join(
        [
            operation,
            str(_field_value(change, "summary", "title", "message") or ""),
        ]
    ).lower()
    if change_type in {"create", "created", "new"}:
        return "create"
    if "convert" in text or "export" in text or "转换" in text or "导出" in text:
        return "convert"
    if (
        "annotate" in text
        or "comment" in text
        or "review" in text
        or "批注" in text
        or "修订" in text
        or _safe_int(_field_value(change, "annotations_added")) > 0
    ):
        return "comment"
    if (
        "design" in text
        or "theme" in text
        or "layout" in text
        or "style" in text
        or "版式" in text
        or "主题" in text
    ):
        return "format"
    if "copy" in text or "复制" in text:
        return "create"
    if "remove" in text or "clear" in text or "删除" in text or "清除" in text:
        return "update"
    return "update"


def _file_task_change_status(change: Mapping[str, Any]) -> str:
    raw_status = str(_field_value(change, "status") or "").strip().lower()
    if raw_status in {"blocked", "write_blocked", "unsupported"}:
        return raw_status
    if change.get("supported") is False:
        return "unsupported"
    if change.get("fallback_copy") or change.get("blocked_reason"):
        return "needs_review"
    return "applied"


def _file_task_change_summary(change: Mapping[str, Any]) -> str:
    summary = _clean_text(_field_value(change, "summary", "title", "message"), 500)
    if summary:
        return summary
    path = _file_task_output_path(change)
    name = PurePosixPath(path).name or "文件"
    operation = str(_field_value(change, "operation") or "").strip()
    if _safe_int(_field_value(change, "annotations_added")) > 0:
        return f"已为 {name} 添加批注"
    if _safe_int(_field_value(change, "rows_written")) > 0:
        return f"已更新 {name} 的表格数据"
    if _safe_int(_field_value(change, "slides_designed")) > 0:
        return f"已更新 {name} 的幻灯片设计"
    if operation:
        return f"{name} 已完成 {operation}"
    return f"{name} 已更新"


def _file_task_result_status(status: str) -> str:
    value = str(status or "").strip().lower()
    if value in {"completed", "done", "success", "succeeded", "verified"}:
        return "completed"
    if value in {
        "waiting",
        "awaiting_confirmation",
        "needs_review",
        "needs_attention",
        "pending",
    }:
        return "needs_review"
    if value in {
        "failed",
        "error",
        "cancelled",
        "canceled",
        "write_blocked",
        "tool_gap",
    }:
        return "failed"
    return "running"


def _source_refs_from_files(
    *,
    source_files: Optional[Iterable[Any]] = None,
    current_file: Any = None,
    selection_source: str = "",
) -> List[SourceRef]:
    refs: List[SourceRef] = []
    seen = set()

    def add_ref(
        path: Any,
        title: Any = "",
        snippet: Any = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        clean_path = _clean_path(path)
        clean_title = _clean_text(
            title or PurePosixPath(clean_path).name or path or "来源", 200
        )
        key = (clean_path or clean_title).lower()
        if not key or key in seen:
            return
        seen.add(key)
        refs.append(
            SourceRef(
                title=clean_title,
                file=clean_path,
                snippet=_clean_text(snippet, 800),
                metadata=metadata or {},
            )
        )

    for raw_file in source_files or []:
        file_info = _public_file_info(raw_file)
        add_ref(
            file_info.get("path") or file_info.get("name"),
            file_info.get("name") or file_info.get("path"),
            metadata={
                "type": file_info.get("type", ""),
                "target": bool(file_info.get("target")),
            },
        )
    current_info = _public_file_info(current_file)
    if current_info:
        add_ref(
            current_info.get("path") or current_info.get("name"),
            current_info.get("name") or current_info.get("path"),
            metadata={"current": True, "type": current_info.get("type", "")},
        )
    if selection_source:
        add_ref(selection_source, selection_source, metadata={"selection_source": True})
    return refs


def _source_refs_from_event_payload(
    event_payload: Mapping[str, Any],
) -> List[SourceRef]:
    refs: List[SourceRef] = []
    seen = set()

    def add_ref(
        path: Any, title: Any = "", snippet: Any = "", locator: str = ""
    ) -> None:
        clean_path = _clean_path(path)
        clean_title = _clean_text(
            title or PurePosixPath(clean_path).name or path or "来源", 200
        )
        key = (clean_path or clean_title).lower()
        if not key or key in seen:
            return
        seen.add(key)
        refs.append(
            SourceRef(
                title=clean_title,
                file=clean_path,
                locator=_clean_text(locator, 120),
                snippet=_clean_text(snippet, 800),
            )
        )

    for key in ("source_path", "compare_path", "original_target_path"):
        value = event_payload.get(key)
        if value:
            add_ref(value, value)

    for item in event_payload.get("context") or []:
        if not isinstance(item, Mapping):
            continue
        add_ref(
            item.get("path") or item.get("source") or item.get("file"),
            item.get("source") or item.get("title") or item.get("path"),
            item.get("preview") or item.get("snippet") or item.get("summary"),
            str(item.get("locator") or item.get("page") or ""),
        )
    for item in event_payload.get("sources") or []:
        if not isinstance(item, Mapping):
            continue
        add_ref(
            item.get("file") or item.get("path") or item.get("url"),
            item.get("title")
            or item.get("file")
            or item.get("path")
            or item.get("url"),
            item.get("snippet") or item.get("preview"),
            str(item.get("locator") or ""),
        )
    return refs


def _dedupe_source_refs(*groups: Iterable[SourceRef]) -> List[SourceRef]:
    seen = set()
    refs: List[SourceRef] = []
    for group in groups:
        for ref in group or []:
            key = (ref.file or ref.url or ref.title).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            refs.append(ref)
    return refs


def build_file_task_artifact_result(
    *,
    task_id: str,
    task: str,
    run_id: str = "",
    status: str = "running",
    summary: str = "",
    file_changes: Optional[Iterable[Mapping[str, Any]]] = None,
    event_payload: Optional[Mapping[str, Any]] = None,
    source_files: Optional[Iterable[Any]] = None,
    current_file: Any = None,
    selection_source: str = "",
    target_path: str = "",
) -> ArtifactResult:
    """Create an ArtifactResult view from file-task stream state."""
    payload = dict(event_payload or {})
    event_changes = (
        payload.get("file_changes")
        if isinstance(payload.get("file_changes"), list)
        else []
    )
    changes_payload = _merge_file_task_changes(file_changes or [], event_changes)
    result_status = _file_task_result_status(status)
    title = _clean_text(task, 200) or "文件任务结果"
    result_summary = _clean_text(
        summary or payload.get("summary") or payload.get("text") or task, 2000
    )

    artifacts: List[Artifact] = []
    seen_artifacts = set()
    for change in changes_payload:
        path = _file_task_output_path(change)
        key = path.lower()
        if not path or key in seen_artifacts:
            continue
        seen_artifacts.add(key)
        change_status = _file_task_change_status(change)
        artifacts.append(
            Artifact(
                type=_artifact_type_from_path(path),
                title=PurePosixPath(path).name,
                path=path,
                source_path=_file_task_source_path(change),
                status="ready" if change_status == "applied" else change_status,
                metadata=_compact_metadata(change),
            )
        )

    next_action = payload.get("next_action_artifact")
    if isinstance(next_action, Mapping) and next_action:
        artifacts.append(
            Artifact(
                type="data",
                title=_clean_text(next_action.get("title") or "下一步行动", 200),
                path=_clean_path(next_action.get("target_path") or target_path),
                status="needs_review",
                metadata=_compact_metadata(next_action),
            )
        )

    changes = [
        FileChange(
            file=_file_task_output_path(change),
            kind=_file_task_change_kind(change),
            summary=_file_task_change_summary(change),
            status=_file_task_change_status(change),
            after_preview=_clean_text(
                _field_value(change, "preview", "after_preview", "warning", "summary"),
                1000,
            ),
            metadata=_compact_metadata(change),
        )
        for change in changes_payload
    ]

    source_refs = _source_refs_from_files(
        source_files=source_files,
        current_file=current_file,
        selection_source=selection_source,
    )
    change_source_refs = [
        SourceRef(
            title=PurePosixPath(source_path).name or source_path,
            file=source_path,
            metadata={"from_change": True},
        )
        for source_path in dict.fromkeys(
            _file_task_source_path(change)
            for change in changes_payload
            if _file_task_source_path(change)
        )
    ]
    sources = _dedupe_source_refs(
        source_refs,
        change_source_refs,
        _source_refs_from_event_payload(payload),
    )

    log_level = (
        "error"
        if result_status == "failed"
        else ("warn" if result_status == "needs_review" else "info")
    )
    logs = [
        ExecutionLog(
            level=log_level,
            message=result_summary or f"文件任务状态：{result_status}",
            metadata={
                "run_id": run_id,
                "file_change_count": len(changes_payload),
            },
        )
    ]
    if changes_payload:
        logs.append(ExecutionLog(message=f"已记录 {len(changes_payload)} 个文件变更。"))
    if isinstance(next_action, Mapping) and next_action:
        next_message = _clean_text(
            next_action.get("summary")
            or next_action.get("suggested_next_step")
            or "需要下一步处理。",
            800,
        )
        logs.append(ExecutionLog(level="warn", message=next_message))

    result = ArtifactResult(
        task_id=task_id or run_id or _new_id("file_task"),
        title=title,
        status=result_status,
        summary=result_summary,
        artifacts=artifacts,
        changes=changes,
        sources=sources,
        logs=logs,
        metadata={
            "producer": "file_task",
            "run_id": run_id,
            "target_path": _clean_path(target_path),
            "terminal_status": status,
        },
    )
    result.actions = result.default_actions()
    return result


def build_background_artifact_result(
    *,
    task_id: str,
    goal: str,
    phase: str,
    final_report: str = "",
    error: str = "",
    steps: Optional[Iterable[Any]] = None,
) -> ArtifactResult:
    """Create an ArtifactResult view from a BackgroundAgent status."""
    step_list = list(steps or [])
    status = _result_status_from_phase(phase, error)
    report = _clean_text(final_report or error, 2000)
    summary = report or _clean_text(goal, 500)
    texts = [goal, final_report, error]
    texts.extend(str(getattr(step, "result", "") or "") for step in step_list)
    paths = _iter_unique_paths(texts)
    artifacts = [
        Artifact(
            type=_artifact_type_from_path(path),
            title=PurePosixPath(path).name,
            path=path,
        )
        for path in paths
    ]
    changes = []
    for step in step_list:
        step_result = str(getattr(step, "result", "") or "").strip()
        if not step_result:
            continue
        step_paths = _iter_unique_paths(
            [
                str(getattr(step, "description", "") or ""),
                step_result,
            ]
        )
        for path in step_paths:
            changes.append(
                FileChange(
                    file=path,
                    kind=_change_kind_from_step(step),
                    summary=str(getattr(step, "title", "") or "文件处理完成"),
                    status="applied",
                    after_preview=step_result[:1000],
                )
            )
    logs = [
        ExecutionLog(
            level="error" if error else "info",
            message=error or f"后台任务状态：{phase or 'running'}",
        )
    ]
    for index, step in enumerate(step_list, start=1):
        title = str(getattr(step, "title", "") or f"步骤 {index}")
        step_status = getattr(step, "status", "")
        status_value = getattr(step_status, "value", step_status)
        logs.append(
            ExecutionLog(
                level="info" if str(status_value).lower() != "failed" else "error",
                message=f"{index}. {title}：{status_value or 'pending'}",
                metadata={"step_id": getattr(step, "step_id", "")},
            )
        )
    result = ArtifactResult(
        task_id=task_id,
        title=_clean_text(goal, 200) or "后台任务",
        status=status,
        summary=summary,
        artifacts=artifacts,
        changes=changes,
        logs=logs,
        metadata={"phase": phase},
    )
    result.actions = result.default_actions()
    return result
