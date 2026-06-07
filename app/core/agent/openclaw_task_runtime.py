from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)

_MAX_HISTORY_TURNS = 20
_TASK_MODEL_NAME = "koto-task-agent"
_PENDING_PLACEHOLDER = "⏳ 处理中..."
_RUNTIME_PHASES = [
    {"id": "analysis", "label": "分析"},
    {"id": "execution", "label": "执行"},
    {"id": "check", "label": "检查"},
]


def _sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@dataclass
class TaskRuntimeRequest:
    task: str
    files: List[Dict[str, Any]] = field(default_factory=list)
    options: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)


class OpenClawTaskRuntime:
    """AI task entrypoint — pure ReAct agent loop.

    Receives a task + file context, delegates to TaskAgent which lets the
    LLM freely plan and call tools until the task is done. No pre-routing,
    no separate planning phase — the model decides everything.
    """

    def __init__(
        self,
        socketio=None,
        model_id: str = "",
        api_key: Optional[str] = None,
        session_store: Any = None,
    ):
        self._socketio = socketio
        self._model_id = model_id
        self._api_key = api_key
        self._session_store = session_store

    def execute(self, request: TaskRuntimeRequest) -> Generator[str, None, None]:
        options = dict(request.options or {})
        session_id = str(options.get("session_id") or "").strip()
        merged_history = self._merge_history(request.history, session_id)
        if merged_history:
            options["history"] = merged_history

        session_filename = self._session_filename(session_id)
        self._persist_user_turn(session_filename, request.task)

        final_result = ""
        final_summary = ""
        had_error = False
        result_emitted = False

        try:
            yield self._emit_phase("analysis", "running")
            yield self._emit_plan_summary("正在分析任务...")
            yield self._emit_phase("analysis", "done")
            yield self._emit_phase("execution", "running")

            from app.core.agent.task_agent import TaskAgent

            agent = TaskAgent(
                socketio=self._socketio,
                model_id=self._model_id,
                api_key=self._api_key,
            )
            for event in agent.execute(
                task=request.task, files=request.files, options=options
            ):
                payload = self._parse_event_payload(event)
                if isinstance(payload, dict):
                    event_type = str(payload.get("type") or "").strip().lower()
                    if event_type == "result":
                        result_emitted = True
                        result_text = self._extract_result_text(payload)
                        if result_text:
                            final_result = result_text
                    elif event_type == "done":
                        summary = str(payload.get("summary") or "").strip()
                        if summary:
                            final_summary = summary
                        continue
                    elif event_type == "error":
                        had_error = True
                        error_text = str(payload.get("text") or "").strip()
                        if error_text:
                            final_summary = error_text

                if isinstance(event, str):
                    yield event
                else:
                    yield _sse(event)

            yield self._emit_phase("execution", "done")

            if not result_emitted and final_summary:
                final_result = final_result or final_summary
                yield _sse(
                    {
                        "type": "result",
                        "output_type": "markdown",
                        "data": final_result,
                        "summary": final_summary or final_result,
                    }
                )

            yield self._emit_phase("check", "running")
            status = "failed" if had_error else "completed"
            summary = (
                final_summary.strip()
                or final_result.strip()
                or ("执行失败" if had_error else "任务执行完成")
            )
            yield _sse(
                {
                    "type": "verification",
                    "status": status,
                    "summary": summary,
                    "backend": "task_agent",
                }
            )
            yield self._emit_phase("check", "done")
            yield _sse(
                {
                    "type": "done",
                    "summary": final_summary
                    or final_result
                    or ("执行失败" if had_error else "任务完成"),
                }
            )
        except Exception as exc:
            had_error = True
            final_summary = str(exc)
            logger.exception("[OpenClawTaskRuntime] execution failed")
            yield _sse({"type": "error", "text": str(exc)})
            yield _sse(
                {
                    "type": "verification",
                    "status": "failed",
                    "summary": str(exc),
                    "backend": "task_agent",
                }
            )
            yield _sse({"type": "done", "summary": "执行失败"})
        finally:
            self._persist_model_turn(
                session_filename=session_filename,
                final_result=final_result,
                final_summary=final_summary,
                had_error=had_error,
            )

    @staticmethod
    def _emit_phase(current: str, status: str) -> str:
        return _sse(
            {
                "type": "phase",
                "phases": _RUNTIME_PHASES,
                "current": current,
                "status": status,
            }
        )

    @staticmethod
    def _emit_plan_summary(text: str) -> str:
        return _sse({"type": "plan_summary", "text": text})

    def _merge_history(
        self,
        incoming_history: List[Dict[str, Any]],
        session_id: str,
    ) -> List[Dict[str, str]]:
        stored_history = self._load_session_history(session_id)
        current_history = self._normalize_history(incoming_history)
        if not stored_history:
            return current_history
        if not current_history:
            return stored_history

        overlap = 0
        max_overlap = min(len(stored_history), len(current_history))
        for size in range(max_overlap, 0, -1):
            if stored_history[-size:] == current_history[:size]:
                overlap = size
                break

        merged = stored_history + current_history[overlap:]
        compacted: List[Dict[str, str]] = []
        for item in merged:
            if compacted and compacted[-1] == item:
                continue
            compacted.append(item)
        return compacted[-_MAX_HISTORY_TURNS:]

    def _load_session_history(self, session_id: str) -> List[Dict[str, str]]:
        filename = self._session_filename(session_id)
        if not filename or self._session_store is None:
            return []

        try:
            loader = getattr(self._session_store, "load", None)
            if not callable(loader):
                return []
            records = loader(filename) or []
        except Exception as exc:
            logger.debug("[OpenClawTaskRuntime] session load skipped: %s", exc)
            return []

        history = self._normalize_history(records)
        return [item for item in history if item.get("content") != _PENDING_PLACEHOLDER]

    def _normalize_history(self, history: Any) -> List[Dict[str, str]]:
        normalized: List[Dict[str, str]] = []
        for item in history or []:
            if not isinstance(item, dict):
                continue

            role = str(item.get("role") or "").strip().lower()
            if role == "assistant":
                role = "model"
            if role not in {"user", "model"}:
                continue

            content = item.get("content")
            if content is None:
                parts = item.get("parts")
                if isinstance(parts, list) and parts:
                    content = parts[0]
            text = str(content or "").strip()
            if not text:
                continue

            normalized.append({"role": role, "content": text})
        return normalized[-_MAX_HISTORY_TURNS:]

    @staticmethod
    def _parse_event_payload(event: Any) -> Optional[Dict[str, Any]]:
        if isinstance(event, dict):
            return event
        if not isinstance(event, str):
            return None

        for line in event.splitlines():
            if not line.startswith("data: "):
                continue
            try:
                payload = json.loads(line[6:])
            except Exception:
                continue
            if isinstance(payload, dict):
                return payload
        return None

    @staticmethod
    def _extract_result_text(payload: Dict[str, Any]) -> str:
        data = payload.get("data")
        if isinstance(data, str):
            return data.strip()
        if isinstance(data, dict):
            return str(data.get("text") or data.get("content") or "").strip()
        return ""

    @staticmethod
    def _session_filename(session_id: str) -> str:
        session_id = str(session_id or "").strip()
        return f"{session_id}.json" if session_id else ""

    def _persist_user_turn(self, session_filename: str, task: str) -> None:
        if not session_filename or self._session_store is None:
            return
        append_early = getattr(self._session_store, "append_user_early", None)
        if not callable(append_early):
            return
        try:
            append_early(session_filename, task)
        except Exception as exc:
            logger.debug("[OpenClawTaskRuntime] append_user_early skipped: %s", exc)

    def _persist_model_turn(
        self,
        session_filename: str,
        final_result: str,
        final_summary: str,
        had_error: bool,
    ) -> None:
        if not session_filename or self._session_store is None:
            return
        updater = getattr(self._session_store, "update_last_model_response", None)
        if not callable(updater):
            return

        persisted_text = final_result.strip() or final_summary.strip()
        if not persisted_text:
            persisted_text = "执行失败" if had_error else "任务完成"

        try:
            updater(
                session_filename,
                persisted_text,
                task="FILE_TASK",
                model_name=_TASK_MODEL_NAME,
                error=had_error,
            )
        except Exception as exc:
            logger.debug(
                "[OpenClawTaskRuntime] update_last_model_response skipped: %s", exc
            )
