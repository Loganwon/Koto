from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


def _event_type(event: Any) -> str:
    return str(
        getattr(event, "type", "")
        or (event.get("type") if isinstance(event, dict) else "")
        or ""
    ).strip()


def _event_payload(event: Any) -> Dict[str, Any]:
    payload = getattr(event, "payload", None)
    if payload is None and isinstance(event, dict):
        payload = event.get("payload")
    return payload if isinstance(payload, dict) else {}


def _text(value: Any, limit: int = 600) -> str:
    text = str(value or "").strip()
    if limit and len(text) > limit:
        return text[: limit - 3] + "..."
    return text


@dataclass
class FileTaskUiMessage:
    kind: str
    status: str = "info"
    title: str = ""
    detail: str = ""
    raw_type: str = ""

    def to_payload(self) -> Dict[str, Any]:
        payload = {
            "kind": self.kind,
            "status": self.status or "info",
            "raw_type": self.raw_type,
        }
        if self.title:
            payload["title"] = self.title
        if self.detail:
            payload["detail"] = self.detail
        return payload


@dataclass
class FileTaskUiState:
    phase: str
    title: str
    status: str = "running"
    progress: int = 0
    terminal: bool = False
    progress_explicit: bool = False

    def to_payload(self) -> Dict[str, Any]:
        return {
            "phase": self.phase,
            "title": self.title,
            "status": self.status,
            "progress": self.progress,
            "terminal": self.terminal,
            "progress_explicit": self.progress_explicit,
        }


def normalize_ui_state(event: Any) -> Optional[FileTaskUiState]:
    raw_type = _event_type(event)
    payload = _event_payload(event)
    if not raw_type:
        return None

    quick_action_mode = str(payload.get("quick_action_mode") or "").strip().lower()
    is_text_qa = quick_action_mode in {
        "simple",
        "polish",
        "translate",
        "summary",
        "rewrite",
        "continue",
        "check",
    }

    if raw_type == "run.started":
        if is_text_qa:
            return FileTaskUiState("run", "处理中…", "running", 8)
        return FileTaskUiState("run", "执行任务", "running", 4)
    if raw_type == "task.classified":
        if is_text_qa:
            return None
        return FileTaskUiState("plan", "任务识别", "running", 12)
    if raw_type == "plan.checked":
        status = "running" if payload.get("passed") is not False else "warning"
        return FileTaskUiState("plan", "规划检查", status, 20)
    if raw_type == "plan.created":
        if is_text_qa:
            return None
        return FileTaskUiState("plan", "准备计划", "running", 28)
    if raw_type == "step.started":
        if is_text_qa:
            return None
        return FileTaskUiState(
            str(
                event.get("step_id")
                if isinstance(event, dict)
                else getattr(event, "step_id", "")
            )
            or "step",
            _text(payload.get("title") or "执行步骤", 80),
            "running",
            36,
        )
    if raw_type == "tool.started":
        if is_text_qa:
            return None
        return FileTaskUiState(
            "tool", _text(payload.get("tool_name") or "执行工具", 80), "running", 52
        )
    if raw_type in {"tool.finished", "step.finished", "step.result"}:
        if is_text_qa:
            return None
        success = payload.get("success")
        failed = success is False or str(
            payload.get("status") or ""
        ).strip().lower() in {"failed", "error"}
        return FileTaskUiState(
            "execute",
            _text(payload.get("title") or payload.get("tool_name") or "执行任务", 80),
            "failed" if failed else "running",
            68,
        )
    if raw_type in {"check.started", "check.finished"}:
        if is_text_qa:
            return None
        status = "running"
        progress = 84 if raw_type == "check.started" else 92
        if raw_type == "check.finished" and payload.get("passed") is False:
            status = "warning"
        return FileTaskUiState(
            "check", _text(payload.get("title") or "检查结果", 80), status, progress
        )
    if raw_type == "run.finished":
        runtime = (
            payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
        )
        terminal_status = _text(runtime.get("terminal_status"), 80).lower()
        completed = bool(payload.get("completed_task"))
        if terminal_status == "awaiting_confirmation":
            return FileTaskUiState("waiting", "等待确认", "waiting", 100, True, True)
        if is_text_qa and completed:
            return FileTaskUiState("done", "完成", "succeeded", 100, True, True)
        failed = (
            terminal_status in {"failed", "blocked", "write_blocked", "tool_gap"}
            or not completed
        )
        return FileTaskUiState(
            "done",
            "任务完成" if not failed else "任务需要处理",
            "failed" if failed else "succeeded",
            100,
            True,
            True,
        )
    if raw_type == "run.error":
        return FileTaskUiState("error", "任务失败", "failed", 100, True, True)
    if raw_type == "run.cancelled":
        return FileTaskUiState("cancelled", "已取消", "cancelled", 100, True, True)
    return None


def normalize_event(event: Any) -> Optional[FileTaskUiMessage]:
    raw_type = _event_type(event)
    payload = _event_payload(event)
    if not raw_type:
        return None

    if raw_type in {"run.started", "run.finished", "run.error", "run.cancelled"}:
        return None

    if raw_type in {"plan.checked", "plan.created", "plan.proposed"}:
        passed = payload.get("passed")
        if raw_type == "plan.checked" and passed is not False:
            return None
        if raw_type in {"plan.created", "plan.proposed"}:
            return None
        return FileTaskUiMessage(
            kind="intent",
            status="succeeded" if passed is not False else "warning",
            title=_text(payload.get("summary") or "规划检查完成", 160),
            detail=_text(payload.get("routing") or payload.get("status"), 240),
            raw_type=raw_type,
        )

    if raw_type == "plan.gated":
        if payload.get("passed") is not False:
            return None
        return FileTaskUiMessage(
            kind="intent",
            status="warning",
            title=_text(payload.get("summary") or "计划需要调整", 160),
            detail=_text(payload.get("status") or payload.get("violations"), 240),
            raw_type=raw_type,
        )

    if raw_type == "decision.made":
        return None

    if raw_type.startswith("model.call."):
        return None

    if raw_type.startswith("tool."):
        return None

    if raw_type.startswith("file."):
        return None

    if raw_type.startswith("multi_target."):
        return None

    if raw_type.startswith("repair.") or raw_type.startswith("degradation."):
        return FileTaskUiMessage(
            kind="degradation",
            status="warning",
            title=_text(payload.get("summary") or "任务降级处理", 180),
            detail=_text(payload.get("reason") or payload.get("text"), 400),
            raw_type=raw_type,
        )

    return None


__all__ = [
    "FileTaskUiMessage",
    "FileTaskUiState",
    "normalize_event",
    "normalize_ui_state",
]
