"""Production Agent facade backed exclusively by the reusable Kernel Runtime."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Generator, List, Mapping, Optional, Sequence

from app.core.agent.base import Agent
from app.core.agent.kernel import (
    AgentRequest,
    EventType,
    KernelRuntime,
    KernelRuntimeConfig,
)
from app.core.agent.kernel_output_validator import KotoOutputValidator
from app.core.agent.provider_model_gateway import ProviderModelGateway
from app.core.agent.tool_registry import ToolRegistry
from app.core.agent.types import AgentAction, AgentStep, AgentStepType

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_INSTRUCTION = (
    "你是 Koto，一个可靠的通用任务处理 Agent。"
    "先理解目标和已有上下文，再使用完成当前任务所需的最少工具。"
    "不得猜测文件内容、工具结果或执行状态。"
)


class KernelAgent(Agent):
    """Compatibility facade that makes KernelRuntime the production loop.

    The facade owns request preparation and maps canonical Kernel events to the
    existing ``AgentStep`` API. It does not implement another model/tool loop.
    """

    def __init__(
        self,
        llm_provider: Any,
        tool_registry: Optional[ToolRegistry] = None,
        model_id: str = "deepseek-chat",
        system_instruction: Optional[str] = None,
        *,
        enable_pii_filter: bool = True,
        enable_output_validation: bool = True,
        use_tool_router: bool = True,
        tool_router_max: int = 20,
        task_type: str = "AGENT",
        allow_model_fallback: bool = True,
    ) -> None:
        super().__init__(llm_provider)
        self.registry = tool_registry or ToolRegistry()
        self.model_id = str(model_id or "")
        self.base_system_instruction = (
            str(system_instruction or "").strip() or _DEFAULT_SYSTEM_INSTRUCTION
        )
        self.enable_pii_filter = bool(enable_pii_filter)
        self.enable_output_validation = bool(enable_output_validation)
        self.task_type = str(task_type or "AGENT")
        self._gateway = ProviderModelGateway(
            llm_provider,
            task_type=self.task_type,
            allow_fallback=allow_model_fallback,
        )
        self._tool_router = None
        if use_tool_router:
            try:
                from app.core.routing.tool_router import get_tool_router

                self._tool_router = get_tool_router(max_tools=tool_router_max)
            except Exception as exc:
                logger.warning("[KernelAgent] ToolRouter unavailable: %s", exc)

    def run(
        self,
        input_text: str,
        history: Optional[List[Dict]] = None,
        session_id: Optional[str] = None,
        task_type: Optional[str] = None,
        system_context: Optional[str] = None,
        addon_tool_names: Optional[Sequence[str]] = None,
        addon_plan: Optional[Mapping[str, Any]] = None,
        addon_invocation_context: Any = None,
        record_task: bool = True,
        task_id: Optional[str] = None,
        run_id: Optional[str] = None,
        resume_state: Optional[Mapping[str, Any]] = None,
        checkpoint_callback: Any = None,
        stream_events: bool = False,
        task_ledger: Any = None,
    ) -> Generator[AgentStep, None, None]:
        active_task_type = str(task_type or self.task_type or "AGENT")
        active_session = str(session_id or "")
        task_id, ledger = self._start_ledger(
            input_text=input_text,
            session_id=active_session,
            task_type=active_task_type,
            enabled=record_task,
            task_id=task_id,
            task_ledger=task_ledger,
        )
        active_run_id = str(
            run_id or (resume_state or {}).get("run_id") or uuid.uuid4().hex[:12]
        )
        if addon_invocation_context is not None:
            from app.core.agent.frontend_observability import bind_frontend_run_context

            addon_invocation_context = bind_frontend_run_context(
                addon_invocation_context, task_id=task_id, run_id=active_run_id
            )
        checkpoint_owner = uuid.uuid4().hex
        external_checkpoint = checkpoint_callback
        if (
            checkpoint_callback is None
            and ledger is not None
            and callable(getattr(ledger, "save_kernel_checkpoint", None))
        ):

            def checkpoint_callback(state):
                state = dict(state)
                state["model_mode"] = (
                    "local"
                    if getattr(self.llm, "streaming_tool_calls", None) is False
                    else "cloud"
                )
                state["requires_authorization"] = bool(addon_invocation_context)
                ledger.save_kernel_checkpoint(
                    task_id,
                    active_run_id,
                    state,
                    resumable=not bool(addon_invocation_context),
                    owner_id=checkpoint_owner,
                )
                ledger.renew_kernel_lease(
                    task_id, active_run_id, checkpoint_owner, lease_seconds=900
                )

        safe_input, mask_result = self._mask_input(input_text)
        system, explicit_allowlist = self._build_system_instruction(
            user_input=safe_input,
            task_type=active_task_type,
            system_context=system_context,
        )
        normalized_addon_tools = tuple(
            dict.fromkeys(
                str(name).strip()
                for name in (addon_tool_names or ())
                if str(name).strip()
            )
        )
        if normalized_addon_tools:
            system += self._addon_instruction(normalized_addon_tools, addon_plan)
        tool_allowlist = self._select_tools(
            user_input=safe_input,
            explicit_allowlist=explicit_allowlist,
        )
        tool_allowlist = self._merge_tool_allowlist(
            tool_allowlist,
            normalized_addon_tools,
        )
        frontend_scope = getattr(
            addon_invocation_context, "frontend_document_scope", None
        )
        frontend_tool_names = {
            "ui_read_context",
            "ui_action_status",
            "ui_apply_edit",
            "ui_save",
        }
        tool_allowlist = tuple(
            name for name in tool_allowlist if name not in frontend_tool_names
        )
        if isinstance(frontend_scope, Mapping):
            operations = frontend_scope.get("allowed_operations", ())
            frontend_names = tuple(
                name
                for operation, name in (
                    ("read", "ui_read_context"),
                    ("read", "ui_action_status"),
                    ("edit", "ui_apply_edit"),
                    ("save", "ui_save"),
                )
                if operation in operations
                and self.registry.catalog.get(name) is not None
            )
            tool_allowlist = self._merge_tool_allowlist(tool_allowlist, frontend_names)
        validator = KotoOutputValidator() if self.enable_output_validation else None
        runtime = KernelRuntime(
            gateway=self._gateway,
            catalog=self.registry.catalog,
            validator=validator,
        )
        request = AgentRequest(
            prompt=safe_input,
            session_id=active_session,
            history=list(history or []),
            extra={
                "task_id": task_id,
                "run_id": active_run_id,
                "task_type": active_task_type,
                "addon_ids": list((addon_plan or {}).get("addon_ids") or []),
            },
        )
        config = KernelRuntimeConfig(
            system_instruction=system,
            model_id=self.model_id,
            tool_allowlist=tool_allowlist,
            options={
                "task_type": active_task_type,
                "session_id": active_session,
                "addon_tool_names": list(normalized_addon_tools),
            },
            checkpoint_callback=checkpoint_callback,
            resume_state=resume_state,
        )

        pending_text = ""
        validation_metadata: Dict[str, Any] = {}
        terminal_seen = False

        for event in runtime.iter_events(
            request,
            config=config,
            cancel_check=self._cancel_check(ledger, task_id),
            invocation_context=addon_invocation_context,
        ):
            stream_name = {
                EventType.LIFECYCLE_START: "run.started",
                EventType.MESSAGE_STARTED: "message.started",
                EventType.STREAM_CHUNK: "message.delta",
                EventType.MESSAGE_FINISHED: "message.finished",
                EventType.TOOL_PROGRESS: "tool.progress",
                EventType.LIFECYCLE_END: "run.finished",
                EventType.STATUS_MESSAGE: str(
                    event.data.get("event_type") or "run.progress"
                ),
            }.get(event.type)
            if stream_name:
                payload = dict(event.data)
                payload.update(
                    {
                        "task_id": task_id,
                        "run_id": active_run_id,
                        "event_type": stream_name,
                    }
                )
                text = str(payload.get("delta") or payload.get("chunk") or "")
                if event.type is EventType.MESSAGE_FINISHED:
                    text = self._restore_output(
                        str(payload.get("text") or ""), mask_result
                    )
                    payload["text"] = text
                if (
                    event.type is EventType.LIFECYCLE_END
                    and external_checkpoint is None
                    and ledger is not None
                ):
                    release = getattr(ledger, "release_kernel_checkpoint", None)
                    if callable(release):
                        release(task_id, active_run_id, checkpoint_owner)
                if stream_events and event.type is not EventType.LIFECYCLE_END:
                    yield AgentStep(AgentStepType.STREAM, text, metadata=payload)
                continue
            if event.type is EventType.STREAM_BLOCK:
                pending_text = str(event.data.get("text") or "")
                continue

            if event.type is EventType.TOOL_CALL:
                if pending_text:
                    thought = self._safe_visible_text(
                        pending_text,
                        fallback="正在执行下一步。",
                    )
                    if thought:
                        yield AgentStep(AgentStepType.THOUGHT, thought)
                    pending_text = ""
                call = dict(event.data.get("tool_call") or {})
                action = AgentAction(
                    tool_name=str(call.get("name") or ""),
                    tool_args=dict(call.get("args") or {}),
                    tool_call_id=str(call.get("id") or "") or None,
                )
                yield AgentStep(
                    AgentStepType.ACTION,
                    f"Calling tool: {action.tool_name}",
                    action=action,
                    metadata={"task_id": task_id},
                )
                continue

            if event.type is EventType.TOOL_RESULT:
                observation = str(event.data.get("result_preview") or "")
                yield AgentStep(
                    AgentStepType.OBSERVATION,
                    observation,
                    observation=observation,
                    metadata={
                        "task_id": task_id,
                        "tool_name": event.data.get("tool_name"),
                        "tool_call_id": event.data.get("call_id"),
                        "result": event.data.get("result"),
                    },
                )
                continue

            if event.type is EventType.VALIDATION:
                validation_metadata = dict(event.data)
                if event.data.get("retrying"):
                    yield AgentStep(
                        AgentStepType.THOUGHT,
                        "输出未通过验收，正在修正。",
                        metadata={"phase": "validation", **validation_metadata},
                    )
                continue

            if event.type is EventType.TASK_COMPLETE:
                terminal_seen = True
                error = str(event.data.get("error") or "")
                if error:
                    state = "cancelled" if "cancel" in error.lower() else "failed"
                    self._finish_ledger(ledger, task_id, state=state, error=error)
                    display_error = str(event.data.get("result") or error)
                    yield AgentStep(
                        AgentStepType.ERROR,
                        self._safe_visible_text(
                            display_error,
                            fallback="任务执行失败，请稍后重试。",
                            treat_as_error=True,
                        ),
                        metadata={
                            "task_id": task_id,
                            "run_id": active_run_id,
                            "state": state,
                            "error_code": event.data.get("error_code"),
                            "blocked": bool(event.data.get("blocked")),
                            "validation": event.data.get("validation")
                            or validation_metadata
                            or None,
                        },
                    )
                    pending_text = ""
                    continue

                answer = str(event.data.get("result") or pending_text or "")
                answer = self._restore_output(answer, mask_result)
                self._finish_ledger(
                    ledger,
                    task_id,
                    state="completed",
                    result=answer,
                )
                yield AgentStep(
                    AgentStepType.ANSWER,
                    answer,
                    metadata={
                        "task_id": task_id,
                        "session_id": active_session,
                        "task_type": active_task_type,
                        "runtime": "kernel",
                        "pii_masked": bool(
                            mask_result and getattr(mask_result, "has_pii", False)
                        ),
                        "validation": validation_metadata or None,
                    },
                )
                pending_text = ""

        if not terminal_seen:
            self._finish_ledger(
                ledger,
                task_id,
                state="failed",
                error="kernel runtime ended without terminal event",
            )
            yield AgentStep(
                AgentStepType.ERROR,
                "任务运行异常结束，请重试。",
                metadata={"task_id": task_id, "runtime": "kernel"},
            )

    def _build_system_instruction(
        self,
        *,
        user_input: str,
        task_type: str,
        system_context: Optional[str],
    ) -> tuple[str, Optional[tuple[str, ...]]]:
        now = self._now()
        weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][
            now.weekday()
        ]
        parts = [
            f"当前本地时间：{now.strftime('%Y年%m月%d日 %H:%M')}（{weekday}）",
            self.base_system_instruction,
        ]
        allowlist: Optional[tuple[str, ...]] = None

        try:
            from app.core.context.context_provider import get_context_provider

            base = "\n\n".join(part for part in parts if part)
            injected = get_context_provider().inject_into_prompt(
                base,
                task_type=task_type,
            )
            parts = [injected]
        except Exception as exc:
            logger.debug("[KernelAgent] context provider skipped: %s", exc)

        if system_context and system_context.strip():
            parts.append(system_context.strip())
        return "\n\n".join(part for part in parts if part), allowlist

    @staticmethod
    def _now() -> datetime:
        """Clock seam for deterministic request-context tests."""

        return datetime.now()

    def _select_tools(
        self,
        *,
        user_input: str,
        explicit_allowlist: Optional[tuple[str, ...]],
    ) -> tuple[str, ...]:
        definitions = self.registry.get_definitions()
        if explicit_allowlist is not None:
            allowed = set(explicit_allowlist)
            return tuple(
                str(item.get("name") or "")
                for item in definitions
                if str(item.get("name") or "") in allowed
            )
        if self._tool_router is not None and definitions:
            selected = self._tool_router.select(definitions, user_input)
            return tuple(
                str(item.get("name") or "")
                for item in selected
                if str(item.get("name") or "")
            )
        return tuple(
            str(item.get("name") or "")
            for item in definitions
            if str(item.get("name") or "")
        )

    def _merge_tool_allowlist(
        self,
        selected: Sequence[str],
        addon_tool_names: Sequence[str],
    ) -> tuple[str, ...]:
        available = {
            str(item.get("name") or "") for item in self.registry.get_definitions()
        }
        missing = [name for name in addon_tool_names if name not in available]
        if missing:
            raise ValueError(
                "planned Add-on tools are not registered: " + ", ".join(missing)
            )
        return tuple(dict.fromkeys((*selected, *addon_tool_names)))

    @staticmethod
    def _addon_instruction(
        tool_names: Sequence[str],
        addon_plan: Optional[Mapping[str, Any]],
    ) -> str:
        plan = dict(addon_plan or {})
        addon_ids = ", ".join(str(item) for item in plan.get("addon_ids") or [])
        capabilities = ", ".join(str(item) for item in plan.get("capabilities") or [])
        lines = [
            "\n\n## 本轮 Add-on 能力边界",
            "仅在确有需要时调用已准入的 Add-on 工具：" + ", ".join(tool_names),
            "不得调用未列出的外部能力，也不得假设工具执行成功。",
        ]
        if addon_ids:
            lines.append("已匹配 Add-on：" + addon_ids)
        if capabilities:
            lines.append("声明能力：" + capabilities)
        return "\n".join(lines)

    def _mask_input(self, text: str) -> tuple[str, Any]:
        if not self.enable_pii_filter:
            return text, None
        try:
            from app.core.security.pii_filter import PIIFilter

            result = PIIFilter.mask(text)
            return (result.masked_text if result.has_pii else text), result
        except Exception as exc:
            logger.warning("[KernelAgent] PII mask skipped: %s", exc)
            return text, None

    @staticmethod
    def _restore_output(text: str, mask_result: Any) -> str:
        if mask_result is None or not getattr(mask_result, "has_pii", False):
            return text
        try:
            return str(mask_result.restore(text))
        except Exception as exc:
            logger.warning("[KernelAgent] PII restore skipped: %s", exc)
            return text

    @staticmethod
    def _safe_visible_text(
        text: str,
        *,
        fallback: str,
        treat_as_error: bool = False,
    ) -> str:
        try:
            from app.core.security.output_validator import sanitize_user_visible_text

            return sanitize_user_visible_text(
                text,
                fallback=fallback,
                treat_as_error=treat_as_error,
            )
        except Exception:
            return fallback if treat_as_error else str(text or "")

    @staticmethod
    def _start_ledger(
        *,
        input_text: str,
        session_id: str,
        task_type: str,
        enabled: bool,
        task_id: Optional[str] = None,
        task_ledger: Any = None,
    ) -> tuple[str, Any]:
        fallback_id = str(task_id or uuid.uuid4())
        if not enabled:
            return fallback_id, task_ledger
        try:
            from app.core.tasks.task_ledger import get_ledger

            ledger = task_ledger if task_ledger is not None else get_ledger()
            record = ledger.get(task_id) if task_id else None
            if record is None:
                record = ledger.create(
                    session_id=session_id,
                    user_input=input_text,
                    task_type=task_type,
                    source="kernel_agent",
                    task_id=task_id,
                )
            ledger.mark_running(record.task_id)
            return record.task_id, ledger
        except Exception as exc:
            if task_id:
                raise
            logger.debug("[KernelAgent] task ledger skipped: %s", exc)
            return fallback_id, None

    @staticmethod
    def _cancel_check(ledger: Any, task_id: str):
        if ledger is None:
            return None

        def _check() -> bool:
            try:
                return bool(ledger.is_cancel_requested(task_id))
            except Exception:
                return False

        return _check

    @staticmethod
    def _finish_ledger(
        ledger: Any,
        task_id: str,
        *,
        state: str,
        result: str = "",
        error: str = "",
    ) -> None:
        if ledger is None:
            return
        try:
            if state == "completed":
                ledger.mark_completed(task_id, result_summary=result[:500])
            elif state == "cancelled":
                ledger.mark_cancelled(task_id)
            else:
                ledger.mark_failed(task_id, error=error[:500])
        except Exception as exc:
            logger.debug("[KernelAgent] ledger finalization skipped: %s", exc)


__all__ = ["KernelAgent"]
