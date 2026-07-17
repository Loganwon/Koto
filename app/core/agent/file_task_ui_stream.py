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


def _tool_activity_title(payload: Dict[str, Any], *, finished: bool = False) -> str:
    tool_name = _text(payload.get("tool_name") or payload.get("tool"), 120).lower()
    explicit_title = _text(payload.get("tool_title"), 120)
    if explicit_title:
        return f"已完成{explicit_title}" if finished else f"正在{explicit_title}"
    if any(token in tool_name for token in ("read", "parse", "inspect", "audit")):
        return "已完成文件读取与分析" if finished else "正在读取并分析文件"
    if any(token in tool_name for token in ("write", "create", "insert", "replace", "convert", "copy")):
        return "已完成结果写入" if finished else "正在写入任务结果"
    if any(token in tool_name for token in ("verify", "check", "guard")):
        return "已完成当前核验步骤" if finished else "正在核验处理结果"
    return "已完成当前处理步骤" if finished else "正在执行处理步骤"


def _terminal_status(payload: Dict[str, Any]) -> str:
    runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
    return _text(
        runtime.get("terminal_status")
        or payload.get("terminal_status")
        or payload.get("status"),
        80,
    ).lower()


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
            return FileTaskUiState("execute", "正在处理请求", "running", 8)
        return FileTaskUiState("route", "正在建立任务上下文", "running", 5)
    if raw_type == "task.classified":
        if is_text_qa:
            return None
        return FileTaskUiState("route", "已识别任务目标", "succeeded", 16)
    if raw_type in {"plan.checked", "plan.gated"}:
        passed = payload.get("passed") is not False and str(
            payload.get("status") or ""
        ).strip().lower() != "failed"
        return FileTaskUiState(
            "plan",
            "执行边界检查通过" if passed else "执行方案需要调整",
            "running" if passed else "warning",
            24,
        )
    if raw_type in {"plan.created", "plan.proposed"}:
        if is_text_qa:
            return None
        plan_title = _text(
            payload.get("plan_summary")
            or payload.get("summary")
            or payload.get("goal")
            or "已生成执行方案",
            120,
        )
        return FileTaskUiState("plan", plan_title, "running", 32)
    if raw_type == "workflow.state":
        return FileTaskUiState("plan", "正在准备执行环境", "running", 30)
    if raw_type == "supervisor.intervention":
        return FileTaskUiState("plan", "执行方案正在调整", "warning", 26)
    if raw_type == "supervisor.status":
        stage = str(payload.get("stage") or "").strip().lower()
        if stage in {"verifying", "completed", "repairing"}:
            return FileTaskUiState("check", "正在复核任务结果", "running", 90)
        if stage in {"executing", "running"}:
            return FileTaskUiState("execute", "正在监管执行过程", "running", 64)
        return FileTaskUiState("plan", "正在检查执行方案", "running", 22)
    if raw_type == "decision.made":
        return FileTaskUiState("execute", "已确定下一步处理方式", "running", 40)
    if raw_type in {"plan.step_started", "plan.step_finished"}:
        return FileTaskUiState(
            "execute",
            _text(
                payload.get("title")
                or payload.get("summary")
                or (
                    "正在执行计划步骤"
                    if raw_type == "plan.step_started"
                    else "已完成当前计划步骤"
                ),
                80,
            ),
            "running",
            42 if raw_type == "plan.step_started" else 48,
        )
    if raw_type == "model.call.started":
        return FileTaskUiState("execute", "AI 正在分析内容", "running", 44)
    if raw_type == "model.call.finished":
        return FileTaskUiState(
            "execute",
            "AI 分析完成，正在执行处理"
            if payload.get("success") is not False
            else "AI 分析暂时失败，正在尝试备用处理",
            "running" if payload.get("success") is not False else "warning",
            50,
        )
    if raw_type == "step.started":
        if is_text_qa:
            return None
        return FileTaskUiState(
            "execute",
            _text(payload.get("title") or "正在执行计划步骤", 80),
            "running",
            42,
        )
    if raw_type == "tool.started":
        if is_text_qa:
            return None
        return FileTaskUiState("execute", _tool_activity_title(payload), "running", 58)
    if raw_type == "tool.finished":
        if is_text_qa:
            return None
        success = payload.get("success")
        failed = success is False or str(
            payload.get("status") or ""
        ).strip().lower() in {"failed", "error"}
        return FileTaskUiState(
            "execute",
            _tool_activity_title(payload, finished=not failed),
            "failed" if failed else ("waiting" if payload.get("blocked") else "running"),
            70,
        )
    if raw_type in {"step.finished", "step.result"}:
        if is_text_qa:
            return None
        failed = payload.get("success") is False or str(
            payload.get("status") or ""
        ).strip().lower() in {"failed", "error"}
        return FileTaskUiState(
            "execute",
            _text(
                payload.get("title")
                or payload.get("summary")
                or ("计划步骤未完成" if failed else "已完成计划步骤"),
                80,
            ),
            "failed" if failed else "running",
            80,
        )
    if raw_type in {"file.changed", "code_summary"}:
        return FileTaskUiState("execute", "已写入任务变更", "running", 78)
    if raw_type == "read.changed":
        return FileTaskUiState(
            "execute", "正在读取并整理文件内容", "running", 54
        )
    if raw_type == "supervisor.step_verified":
        passed = payload.get("passed") is not False and str(
            payload.get("outcome") or payload.get("status") or ""
        ).strip().lower() != "failed"
        return FileTaskUiState(
            "execute",
            "当前处理步骤已通过核验"
            if passed
            else "当前处理步骤核验未通过",
            "running" if passed else "failed",
            76,
        )
    if raw_type.startswith("repair.") or raw_type.startswith("degradation."):
        return FileTaskUiState("execute", "正在调整处理方式", "warning", 66)
    if raw_type in {"check.started", "check.finished"}:
        if is_text_qa:
            return None
        passed = payload.get("passed") is not False
        status = "running" if raw_type == "check.started" else (
            "succeeded" if passed else "failed"
        )
        progress = 86 if raw_type == "check.started" else 94
        return FileTaskUiState(
            "check",
            _text(
                payload.get("title")
                or (
                    "正在核验结果与文件变更"
                    if raw_type == "check.started"
                    else ("结果核验通过" if passed else "结果核验未通过")
                ),
                80,
            ),
            status,
            progress,
        )
    if raw_type == "run.finished":
        terminal_status = _terminal_status(payload)
        completed = bool(payload.get("completed_task"))
        if terminal_status in {
            "awaiting_confirmation",
            "waiting",
            "needs_review",
            "context_summary_fallback",
        }:
            return FileTaskUiState(
                "deliver",
                "已整理当前结果，等待确认",
                "waiting",
                100,
                True,
                True,
            )
        if is_text_qa and completed:
            return FileTaskUiState(
                "deliver", "结果已整理完成", "succeeded", 100, True, True
            )
        failed = (
            terminal_status
            in {
                "failed",
                "blocked",
                "write_blocked",
                "tool_gap",
                "quality_gate_failed",
            }
            or not completed
        )
        return FileTaskUiState(
            "deliver",
            "结果与产物已整理完成"
            if not failed
            else "任务未完成，已保留诊断信息",
            "failed" if failed else "succeeded",
            100,
            True,
            True,
        )
    if raw_type == "run.cancelled":
        return FileTaskUiState(
            "deliver", "任务已取消", "cancelled", 100, True, True
        )
    return None


def normalize_event(event: Any) -> Optional[FileTaskUiMessage]:
    raw_type = _event_type(event)
    payload = _event_payload(event)
    if not raw_type:
        return None

    if raw_type in {"run.started", "run.finished", "run.cancelled"}:
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
