from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)

_MAX_HISTORY_TURNS = 20
_TASK_MODEL_NAME = "openclaw-task-runtime"
_PENDING_PLACEHOLDER = "⏳ 处理中..."
_DEFAULT_BACKEND = str(os.getenv("KOTO_FILE_TASK_BACKEND", "doc_agent") or "doc_agent").strip().lower()
_RUNTIME_PHASES = [
    {"id": "decision", "label": "决策"},
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


@dataclass
class TaskRuntimeDecision:
    backend: str
    reason: str
    has_native_check: bool = False


class OpenClawTaskRuntime:
    """Single ai_task entrypoint for request normalization, history, and persistence.

    The underlying execution engine is still TaskAgent / ChunkedTaskRuntime for now,
    but all route-level plumbing lives here so the later planner/executor/checker
    split can replace the backend without touching every caller again.
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
        final_verification: Optional[Dict[str, Any]] = None
        had_error = False
        result_emitted = False
        decision: Optional[TaskRuntimeDecision] = None

        try:
            yield self._emit_phase("decision", "running")
            decision = self._decide_backend(request.task, request.files, options)
            yield self._emit_plan_summary(decision.reason)
            yield self._emit_phase("decision", "done")
            yield self._emit_phase("execution", "running")

            event_stream = self._build_event_stream(decision, request, options)
            backend_event_count = 0
            try:
                for event in event_stream:
                    payload = self._parse_event_payload(event)
                    if isinstance(payload, dict):
                        event_type = str(payload.get("type") or "").strip().lower()
                        if event_type == "result":
                            result_emitted = True
                            result_text = self._extract_result_text(payload)
                            if result_text:
                                final_result = result_text
                        elif event_type == "verification":
                            final_verification = payload
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

                    backend_event_count += 1
                    if isinstance(event, str):
                        yield event
                    else:
                        yield _sse(event)
            except Exception as backend_exc:
                if decision.backend == "doc_agent" and backend_event_count == 0:
                    logger.warning(
                        "[OpenClawTaskRuntime] DocAgent failed before emitting events, falling back to TaskAgent: %s",
                        backend_exc,
                    )
                    yield self._emit_plan_summary("OpenClaw 主链路启动失败，已自动回退到兼容执行器。")
                    decision = TaskRuntimeDecision(
                        backend="task_agent",
                        reason="DocAgent 启动失败，回退到兼容 TaskAgent 执行器。",
                        has_native_check=False,
                    )
                    event_stream = self._build_event_stream(decision, request, options)
                    for event in event_stream:
                        payload = self._parse_event_payload(event)
                        if isinstance(payload, dict):
                            event_type = str(payload.get("type") or "").strip().lower()
                            if event_type == "result":
                                result_emitted = True
                                result_text = self._extract_result_text(payload)
                                if result_text:
                                    final_result = result_text
                            elif event_type == "verification":
                                final_verification = payload
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
                else:
                    raise backend_exc

            yield self._emit_phase("execution", "done")

            if not result_emitted and final_summary:
                final_result = final_result or final_summary
                yield _sse({
                    "type": "result",
                    "output_type": "markdown",
                    "data": final_result,
                    "summary": final_summary or final_result,
                })

            yield self._emit_phase("check", "running")
            if not final_verification:
                final_verification = self._run_check_layer(
                    decision=decision,
                    final_result=final_result,
                    final_summary=final_summary,
                    had_error=had_error,
                )
            if final_verification:
                verification_summary = str(final_verification.get("summary") or "").strip()
                if verification_summary and not final_summary:
                    final_summary = verification_summary
                yield _sse(final_verification)
            yield self._emit_phase("check", "done")
            yield _sse({"type": "done", "summary": final_summary or final_result or ("执行失败" if had_error else "任务完成")})
        except Exception as exc:
            had_error = True
            final_summary = str(exc)
            logger.exception("[OpenClawTaskRuntime] execution failed")
            yield _sse({"type": "error", "text": str(exc)})
            yield _sse({"type": "verification", "status": "failed", "summary": str(exc), "backend": decision.backend if decision else "unknown"})
            yield _sse({"type": "done", "summary": "执行失败"})
        finally:
            self._persist_model_turn(
                session_filename=session_filename,
                final_result=final_result,
                final_summary=final_summary,
                had_error=had_error,
            )

    def _build_event_stream(
        self,
        decision: TaskRuntimeDecision,
        request: TaskRuntimeRequest,
        options: Dict[str, Any],
    ):
        if decision.backend == "chunked":
            from app.core.agent.chunked_task_runtime import ChunkedTaskRuntime

            runtime = ChunkedTaskRuntime(
                socketio=self._socketio,
                model_id=self._model_id,
                api_key=self._api_key,
            )
            return runtime.execute(task=request.task, files=request.files, options=options)

        if decision.backend == "doc_agent":
            return self._execute_doc_agent(request, options)

        from app.core.agent.task_agent import TaskAgent

        agent = TaskAgent(
            socketio=self._socketio,
            model_id=self._model_id,
            api_key=self._api_key,
        )
        return agent.execute(task=request.task, files=request.files, options=options)

    def _decide_backend(
        self,
        task: str,
        files: List[Dict[str, Any]],
        options: Dict[str, Any],
    ) -> TaskRuntimeDecision:
        from app.core.agent.chunked_task_runtime import ChunkedTaskRuntime

        runtime = ChunkedTaskRuntime(
            socketio=self._socketio,
            model_id=self._model_id,
            api_key=self._api_key,
        )
        if runtime.should_handle(task=task, files=files, options=options):
            return TaskRuntimeDecision(
                backend="chunked",
                reason="检测到长文档重写类任务，采用分块执行通路以控制上下文和写入风险。",
                has_native_check=False,
            )

        backend = str(options.get("task_backend") or _DEFAULT_BACKEND).strip().lower()
        if backend in {"task_agent", "legacy"}:
            return TaskRuntimeDecision(
                backend="task_agent",
                reason="根据运行配置，使用兼容 TaskAgent 执行通路。",
                has_native_check=False,
            )

        return TaskRuntimeDecision(
            backend="doc_agent",
            reason="采用智能分析模式：先分析任务并拆解步骤，再分步执行并在结束后统一检查。",
            has_native_check=True,
        )

    def _execute_doc_agent(
        self,
        request: TaskRuntimeRequest,
        options: Dict[str, Any],
    ) -> Generator[str, None, None]:
        from app.core.agent.doc_agent import DocAgent, DocEventType, DocTask, FileHandle

        files: List[FileHandle] = []
        for index, item in enumerate(request.files or []):
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or item.get("name") or f"file_{index}").strip()
            file_type = str(item.get("type") or item.get("file_type") or Path(path).suffix.lstrip(".").lower()).strip()
            content_snapshot = str(
                item.get("content_snapshot")
                or item.get("content_preview")
                or (options.get("current_file_text") if index == 0 else "")
                or ""
            )
            selection = str(item.get("selection") or "").strip() or None
            files.append(
                FileHandle(
                    path=path,
                    file_type=file_type,
                    content_snapshot=content_snapshot,
                    selection=selection,
                )
            )

        if not files and (options.get("current_file") or options.get("current_file_name") or options.get("current_file_text")):
            fallback_path = str(options.get("current_file") or options.get("current_file_name") or "current_document").strip()
            files.append(
                FileHandle(
                    path=fallback_path,
                    file_type=Path(fallback_path).suffix.lstrip(".").lower(),
                    content_snapshot=str(options.get("current_file_text") or ""),
                )
            )

        task = DocTask(
            id=str(options.get("session_id") or "").strip(),
            prompt=request.task,
            files=files,
            permissions={"read", "write", "annotate"},
            session_id=str(options.get("session_id") or "").strip(),
            history=list(options.get("history") or []),
            options=dict(options),
        )

        agent = DocAgent(
            model_id=self._model_id,
            api_key=self._api_key,
        )

        for event in agent.run(task):
            event_type = getattr(event, "event_type", None)
            step_id = str(getattr(event, "step_id", "") or "").strip()
            data = dict(getattr(event, "data", {}) or {})

            if event_type == DocEventType.PLAN_START:
                continue
            if event_type == DocEventType.PLAN_CREATED:
                plan_data = data.get("plan") if isinstance(data.get("plan"), dict) else {}
                yield _sse({"type": "plan", "steps": plan_data.get("steps", [])})
                continue
            if event_type == DocEventType.STEP_START:
                yield _sse({
                    "type": "step_start",
                    "step_id": step_id,
                    "text": str(data.get("description") or data.get("name") or "执行步骤").strip(),
                })
                continue
            if event_type == DocEventType.STEP_PROGRESS:
                detail = str(data.get("detail") or "").strip()
                progress = data.get("progress")
                if not detail and progress is not None:
                    detail = f"进度 {progress}%"
                yield _sse({"type": "step_progress", "step_id": step_id, "detail": detail})
                continue
            if event_type == DocEventType.STEP_DONE:
                yield _sse({
                    "type": "step_done",
                    "step_id": step_id,
                    "text": str(data.get("summary") or data.get("name") or "步骤完成").strip(),
                })
                continue
            if event_type == DocEventType.STEP_ERROR:
                yield _sse({
                    "type": "step_error",
                    "step_id": step_id,
                    "error": str(data.get("error") or data.get("message") or "步骤失败").strip(),
                })
                continue
            if event_type == DocEventType.TOOL_CALL:
                yield _sse({
                    "type": "tool_call",
                    "step_id": step_id,
                    "tool_name": str(data.get("tool_name") or "").strip(),
                    "tool_args": data.get("tool_args") or {},
                })
                continue
            if event_type == DocEventType.TOOL_RESULT:
                yield _sse({
                    "type": "tool_result",
                    "step_id": step_id,
                    "tool_name": str(data.get("tool_name") or "").strip(),
                    "result_preview": str(data.get("result_preview") or "").strip()[:500],
                })
                continue
            if event_type == DocEventType.FILE_CHANGE:
                file_path = str(data.get("file_path") or data.get("path") or "").strip()
                modified_preview = str(data.get("modified") or data.get("preview") or "").strip()
                yield _sse({
                    "type": "file_change",
                    "path": file_path,
                    "file_type": Path(file_path).suffix.lstrip(".").lower(),
                    "operation": str(data.get("operation") or "").strip(),
                    "summary": str(data.get("summary") or "").strip(),
                    "preview": modified_preview[:500],
                    "change_type": str(data.get("change_type") or "modify").strip(),
                    "focus": bool(data.get("focus", False)),
                })
                continue
            if event_type == DocEventType.THOUGHT:
                yield _sse({"type": "thought", "text": str(data.get("text") or "").strip()})
                continue
            if event_type == DocEventType.STREAM_CHUNK:
                chunk = str(data.get("chunk") or "").strip()
                if chunk:
                    yield _sse({"type": "thought", "text": chunk})
                continue
            if event_type == DocEventType.VERIFICATION:
                yield _sse({
                    "type": "verification",
                    "status": str(data.get("status") or "unknown").strip(),
                    "summary": str(data.get("summary") or "").strip(),
                    "backend": "doc_agent",
                })
                continue
            if event_type == DocEventType.TASK_COMPLETE:
                summary = str(data.get("summary") or "任务完成").strip()
                yield _sse({
                    "type": "result",
                    "output_type": "markdown",
                    "data": summary,
                    "summary": summary,
                })
                continue
            if event_type == DocEventType.ERROR:
                message = str(data.get("message") or data.get("error") or "执行失败").strip()
                yield _sse({"type": "error", "text": message})

    def _run_check_layer(
        self,
        decision: Optional[TaskRuntimeDecision],
        final_result: str,
        final_summary: str,
        had_error: bool,
    ) -> Dict[str, Any]:
        status = "failed" if had_error else "completed"
        summary = final_summary.strip() or final_result.strip()
        if not summary:
            summary = "执行失败" if had_error else "任务执行完成"
        if not had_error and not final_result and not final_summary:
            status = "partial"
        return {
            "type": "verification",
            "status": status,
            "summary": summary,
            "backend": decision.backend if decision else "unknown",
        }

    @staticmethod
    def _emit_phase(current: str, status: str) -> str:
        return _sse({"type": "phase", "phases": _RUNTIME_PHASES, "current": current, "status": status})

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
            logger.debug("[OpenClawTaskRuntime] update_last_model_response skipped: %s", exc)