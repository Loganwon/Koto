"""Provider- and transport-neutral model/tool execution loop."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterator, Mapping, Optional, Sequence

from .catalog import ToolCatalog
from .context_budget import prepare_model_messages
from .contracts import AgentRunLimits, ToolCall, ToolErrorCode, ToolResult
from .execution import ToolExecutor
from .guard import RunGuard, RunLimitExceeded
from .instructions import build_tool_usage_instruction
from .lifecycle import (
    AgentEvent,
    AgentRequest,
    EventType,
    RunMetadata,
    RunState,
    evt_lifecycle_end,
    evt_lifecycle_error,
    evt_lifecycle_start,
    evt_stream_block,
    evt_task_complete,
    evt_tool_call,
    evt_tool_result,
    evt_validation,
)
from .model import ModelGateway, ModelResponse, iter_model_stream
from .model_metrics import ModelTurnMetrics
from .validation import ResponseValidator


@dataclass(frozen=True)
class KernelRuntimeConfig:
    """Immutable configuration for one stable Agent runtime surface."""

    system_instruction: str = ""
    model_id: str = ""
    tool_allowlist: Optional[tuple[str, ...]] = None
    options: Mapping[str, Any] = field(default_factory=dict)
    max_validation_retries: int = 1
    parallel_tool_workers: int = 6
    checkpoint_callback: Optional[Callable[[dict[str, Any]], None]] = None
    resume_state: Optional[Mapping[str, Any]] = None

    def __post_init__(self) -> None:
        if self.tool_allowlist is not None:
            normalized = tuple(
                dict.fromkeys(
                    str(name).strip()
                    for name in self.tool_allowlist
                    if str(name).strip()
                )
            )
            object.__setattr__(self, "tool_allowlist", normalized)
        object.__setattr__(self, "options", copy.deepcopy(dict(self.options)))
        if self.max_validation_retries < 0:
            raise ValueError("max_validation_retries cannot be negative")
        if self.parallel_tool_workers < 1:
            raise ValueError("parallel_tool_workers must be positive")


class _RunCancelled(RuntimeError):
    pass


class KernelRuntime:
    """The single reusable model → tool → model loop.

    UI transports and file-format policies belong in adapters around this
    class. The runtime only owns message progression, fixed tool exposure,
    deterministic budgets, structured execution results, and lifecycle events.
    """

    def __init__(
        self,
        *,
        gateway: ModelGateway,
        catalog: ToolCatalog,
        executor: Optional[ToolExecutor] = None,
        limits: Optional[AgentRunLimits] = None,
        validator: Optional[ResponseValidator] = None,
    ) -> None:
        self._gateway = gateway
        self._catalog = catalog
        self._executor = executor or ToolExecutor(catalog)
        self._limits = limits or AgentRunLimits()
        self._validator = validator

    def iter_events(
        self,
        request: AgentRequest,
        *,
        config: Optional[KernelRuntimeConfig] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        invocation_context: Any = None,
    ) -> Iterator[AgentEvent]:
        """Run one request and emit only canonical Kernel events."""

        active = config or KernelRuntimeConfig()
        restored = dict(active.resume_state or {})
        if restored:
            active = replace(
                active,
                system_instruction=str(
                    restored.get("system_instruction")
                    or restored.get("system")
                    or active.system_instruction
                ),
                model_id=str(restored.get("model_id") or active.model_id),
                tool_allowlist=(
                    tuple(restored["tool_allowlist"])
                    if restored.get("tool_allowlist") is not None
                    else active.tool_allowlist
                ),
                options=restored.get("options") or active.options,
            )
        metadata = RunMetadata(session_id=request.session_id, model=active.model_id)
        metadata.run_id = str(
            request.extra.get("run_id") or restored.get("run_id") or metadata.run_id
        )
        metadata.start()
        yield evt_lifecycle_start(metadata.run_id, metadata.session_id)

        try:
            tool_definitions = self._tool_definitions(active.tool_allowlist)
            exposed_tool_names = {
                str(item.get("name") or "").strip()
                for item in tool_definitions
                if str(item.get("name") or "").strip()
            }
            system = self._build_system_instruction(
                active.system_instruction, tool_definitions
            )
            messages = copy.deepcopy(
                restored.get("messages") or self._request_messages(request)
            )
            guard = RunGuard(self._limits)
            step_index = int(restored.get("step_index") or 0)
            validation_retries = 0
            resumed_response = None
            resumed_tools = False
            pending = list(restored.get("pending_tool_calls") or [])
            if pending:
                if any(call.get("read_only") is not True for call in pending):
                    raise RuntimeError(
                        "Cannot automatically resume a tool with an unknown write outcome"
                    )
                resumed_response = ModelResponse.from_raw({"tool_calls": pending})
                resumed_tools = True
            elif restored.get("phase") == "model_complete" and restored.get("response"):
                resumed_response = ModelResponse.from_raw(restored["response"])
            if restored.get("phase") == "completed":
                metadata.finish(RunState.SUCCEEDED)
                yield evt_task_complete(
                    result=str(restored.get("terminal_result") or "")
                )
                yield evt_lifecycle_end(metadata.run_id, RunState.SUCCEEDED)
                return
            if restored.get("phase") in {"failed", "cancelled"}:
                restored_state = (
                    RunState.CANCELLED
                    if restored["phase"] == "cancelled"
                    else RunState.FAILED
                )
                error = str(restored.get("error") or f"agent run {restored['phase']}")
                metadata.finish(restored_state, error=error)
                yield evt_task_complete(
                    result=str(restored.get("terminal_result") or ""),
                    error=error,
                    state=restored_state.value,
                    error_code=restored.get("error_code"),
                    validation=restored.get("validation") or {},
                )
                yield evt_lifecycle_end(metadata.run_id, restored_state)
                return
            if not restored:
                self._checkpoint(active, metadata, "started", messages, step_index)

            while True:
                if cancel_check is not None and cancel_check():
                    raise _RunCancelled()

                step_index += 1
                guard.begin_step()
                context_options = getattr(self._gateway, "context_options", None)
                if callable(context_options):
                    active = replace(active, options=context_options(active.options))
                budgeted = prepare_model_messages(
                    messages,
                    system=system,
                    tools=tool_definitions,
                    options=active.options,
                    prompt=request.prompt,
                )
                if budgeted.compacted:
                    yield AgentEvent(
                        EventType.STATUS_MESSAGE,
                        {
                            "event_type": "context.compacted",
                            "run_id": metadata.run_id,
                            "estimated_tokens": budgeted.estimated_tokens,
                            "input_budget": budgeted.input_budget,
                            "text": "已压缩较早的上下文，保留当前任务与工具调用关系。",
                        },
                    )
                message_id = f"{metadata.run_id}:message:{step_index}"
                streamed = False
                if resumed_response is not None:
                    response, resumed_response = resumed_response, None
                else:
                    response, streamed = yield from self._generate_turn(
                        messages=budgeted.messages,
                        system=system,
                        tools=tool_definitions,
                        active=active,
                        message_id=message_id,
                        run_id=metadata.run_id,
                        cancel_check=cancel_check,
                        budgeted=budgeted,
                    )
                if not resumed_tools:
                    self._checkpoint(
                        active,
                        metadata,
                        "model_complete",
                        messages,
                        step_index,
                        response=response.to_mapping(),
                    )
                if response.model:
                    metadata.model = response.model

                if not response.tool_calls:
                    final_content = response.content
                    validation_error_code = ""
                    validation_failure = {}
                    if self._validator is not None:
                        outcome = self._validator.validate(final_content, request)
                        if outcome.blocked:
                            yield evt_validation(
                                accepted=False,
                                blocked=True,
                                reasons=list(outcome.reasons),
                            )
                            final_content = outcome.content
                            validation_error_code = "validation_blocked"
                            validation_failure = {
                                "accepted": False,
                                "blocked": True,
                                "reasons": list(outcome.reasons),
                            }
                        elif not outcome.accepted:
                            can_retry = (
                                bool(outcome.retry_instruction)
                                and validation_retries < active.max_validation_retries
                            )
                            yield evt_validation(
                                accepted=False,
                                retrying=can_retry,
                                reasons=list(outcome.reasons),
                            )
                            if can_retry:
                                if streamed:
                                    yield self._message_finished(
                                        message_id,
                                        metadata.run_id,
                                        response.content,
                                        "retrying",
                                    )
                                validation_retries += 1
                                messages.append(
                                    {"role": "assistant", "content": response.content}
                                )
                                messages.append(
                                    {
                                        "role": "user",
                                        "content": outcome.retry_instruction,
                                    }
                                )
                                continue
                            final_content = (
                                "输出未通过验收，自动修正未能完成。请调整要求后重试。"
                            )
                            validation_error_code = "validation_exhausted"
                            validation_failure = {
                                "accepted": False,
                                "blocked": False,
                                "exhausted": True,
                                "reasons": list(outcome.reasons),
                            }
                        else:
                            final_content = outcome.content
                            yield evt_validation(
                                accepted=True,
                                reasons=list(outcome.reasons),
                            )

                    if streamed:
                        status = "completed"
                        if validation_error_code:
                            status = (
                                "blocked"
                                if validation_failure.get("blocked")
                                else "failed"
                            )
                        yield self._message_finished(
                            message_id, metadata.run_id, final_content, status
                        )
                    if final_content:
                        yield evt_stream_block(final_content)
                    if validation_error_code:
                        error = (
                            "output validation blocked"
                            if validation_failure.get("blocked")
                            else "output validation failed after repair attempts"
                        )
                        metadata.finish(RunState.FAILED, error=error)
                        self._checkpoint(
                            active,
                            metadata,
                            "failed",
                            messages,
                            step_index,
                            terminal_result=final_content,
                            error=error,
                            error_code=validation_error_code,
                            validation=validation_failure,
                        )
                        yield evt_lifecycle_error(
                            metadata.run_id, error, RunState.FAILED
                        )
                        yield evt_task_complete(
                            result=final_content,
                            error=error,
                            state="failed",
                            error_code=validation_error_code,
                            validation=validation_failure,
                            blocked=bool(validation_failure.get("blocked")),
                        )
                        yield evt_lifecycle_end(metadata.run_id, RunState.FAILED)
                        return
                    self._checkpoint(
                        active,
                        metadata,
                        "completed",
                        messages,
                        step_index,
                        terminal_result=final_content,
                    )
                    metadata.finish(RunState.SUCCEEDED)
                    yield evt_task_complete(result=final_content)
                    yield evt_lifecycle_end(metadata.run_id, RunState.SUCCEEDED)
                    return

                calls = [
                    ToolCall(
                        name=item.name,
                        arguments=item.arguments,
                        call_id=item.call_id or f"step-{step_index}-call-{index + 1}",
                    )
                    for index, item in enumerate(response.tool_calls)
                ]
                nonrepeatable_names = {
                    call.name
                    for call in calls
                    if (spec := self._catalog.get(call.name)) is not None
                    and spec.read_only is False
                }
                guard.accept_tool_batch(
                    calls,
                    nonrepeatable_names=nonrepeatable_names,
                )
                if streamed:
                    yield self._message_finished(
                        message_id, metadata.run_id, response.content, "tool_call"
                    )
                if response.content:
                    yield evt_stream_block(response.content)
                if not resumed_tools:
                    messages.append(self._assistant_tool_message(response, calls))
                resumed_tools = False

                for call in calls:
                    if cancel_check is not None and cancel_check():
                        raise _RunCancelled()

                    yield evt_tool_call(
                        {
                            "id": call.call_id,
                            "name": call.name,
                            "args": copy.deepcopy(dict(call.arguments)),
                        }
                    )

                self._checkpoint(
                    active,
                    metadata,
                    "tool_pending",
                    messages,
                    step_index,
                    pending_tool_calls=self._pending_calls(calls),
                )
                completed_results = []
                for item in self._invoke_calls(
                    calls, exposed_tool_names, active, invocation_context, cancel_check
                ):
                    if isinstance(item, AgentEvent):
                        yield item
                        continue
                    call, result = item
                    result_payload = result.to_payload()
                    result_text = json.dumps(
                        result_payload,
                        ensure_ascii=False,
                        default=str,
                        separators=(",", ":"),
                    )
                    messages.append(self._tool_result_message(call, result_text))
                    completed_results.append(result_payload)
                    remaining = calls[len(completed_results) :]
                    self._checkpoint(
                        active,
                        metadata,
                        "tool_complete",
                        messages,
                        step_index,
                        pending_tool_calls=self._pending_calls(remaining),
                        completed_tool_results=completed_results,
                    )
                    yield evt_tool_result(
                        call.name,
                        result_text,
                        call_id=call.call_id,
                        result=result_payload,
                    )

        except _RunCancelled:
            metadata.finish(RunState.CANCELLED)
            self._terminal_checkpoint(
                active,
                metadata,
                "cancelled",
                locals().get("messages", []),
                locals().get("step_index", 0),
                "agent run cancelled",
            )
            yield evt_task_complete(error="agent run cancelled")
            yield evt_lifecycle_end(metadata.run_id, RunState.CANCELLED)
        except RunLimitExceeded as exc:
            self._finish_with_error(metadata, str(exc))
            self._terminal_checkpoint(
                active,
                metadata,
                "failed",
                locals().get("messages", []),
                locals().get("step_index", 0),
                str(exc),
            )
            yield evt_lifecycle_error(metadata.run_id, str(exc), metadata.state)
            yield evt_task_complete(error=str(exc))
            yield evt_lifecycle_end(metadata.run_id, metadata.state)
        except Exception as exc:
            self._finish_with_error(metadata, str(exc))
            self._terminal_checkpoint(
                active,
                metadata,
                "failed",
                locals().get("messages", []),
                locals().get("step_index", 0),
                str(exc),
            )
            yield evt_lifecycle_error(metadata.run_id, str(exc), metadata.state)
            yield evt_task_complete(error=str(exc))
            yield evt_lifecycle_end(metadata.run_id, metadata.state)

    def _generate_turn(
        self,
        *,
        messages,
        system,
        tools,
        active,
        message_id,
        run_id,
        cancel_check,
        budgeted=None,
    ):
        metrics = ModelTurnMetrics(
            run_id=run_id,
            message_id=message_id,
            model=active.model_id,
            estimated_input_tokens=getattr(budgeted, "estimated_tokens", None),
            input_budget=getattr(budgeted, "input_budget", None),
            compacted=bool(getattr(budgeted, "compacted", False)),
        )
        try:
            response, streamed = yield from self._generate_turn_body(
                messages=messages,
                system=system,
                tools=tools,
                active=active,
                message_id=message_id,
                run_id=run_id,
                cancel_check=cancel_check,
                metrics=metrics,
            )
        except Exception as exc:
            yield metrics.event(
                status="cancelled" if isinstance(exc, _RunCancelled) else "failed",
                error_type=type(exc).__name__,
            )
            raise
        yield metrics.event(status="completed", response=response)
        return response, streamed

    def _generate_turn_body(
        self,
        *,
        messages,
        system,
        tools,
        active,
        message_id,
        run_id,
        cancel_check,
        metrics,
    ):
        stream_method = getattr(self._gateway, "generate_stream", None)
        if not callable(stream_method):
            metrics.start_call()
            response = self._gateway.generate(
                messages=messages,
                system=system,
                tools=tools,
                model_id=active.model_id,
                options=active.options,
            )
            if cancel_check is not None and cancel_check():
                raise _RunCancelled()
            return ModelResponse.from_raw(response), False
        yield AgentEvent(
            EventType.MESSAGE_STARTED,
            {
                "message_id": message_id,
                "attempt_id": message_id,
                "run_id": run_id,
                "draft": True,
                "status": "generating",
            },
        )
        final = None
        metrics.start_call()
        source = iter_model_stream(
            stream_method(
                messages=messages,
                system=system,
                tools=tools,
                model_id=active.model_id,
                options={**dict(active.options), "_cancel_check": cancel_check},
            )
        )
        try:
            for chunk in source:
                if cancel_check is not None and cancel_check():
                    raise _RunCancelled()
                if chunk.delta:
                    metrics.first_text()
                    yield AgentEvent(
                        EventType.STREAM_CHUNK,
                        {
                            "chunk": chunk.delta,
                            "delta": chunk.delta,
                            "message_id": message_id,
                            "attempt_id": message_id,
                            "run_id": run_id,
                            "draft": True,
                        },
                    )
                if chunk.response is not None:
                    final = chunk.response
        except Exception:
            if cancel_check is not None and cancel_check():
                raise _RunCancelled()
            raise
        finally:
            source.close()
        if final is None:
            raise RuntimeError("Model stream ended without a complete response")
        return final, True

    @staticmethod
    def _message_finished(message_id, run_id, text, status):
        return AgentEvent(
            EventType.MESSAGE_FINISHED,
            {
                "message_id": message_id,
                "attempt_id": message_id,
                "run_id": run_id,
                "text": text,
                "status": status,
                "draft": status == "retrying",
            },
        )

    def _pending_calls(self, calls):
        return [
            {
                "id": call.call_id,
                "name": call.name,
                "args": copy.deepcopy(dict(call.arguments)),
                "read_only": (
                    self._catalog.get(call.name).read_only
                    if self._catalog.get(call.name) is not None
                    else False
                ),
            }
            for call in calls
        ]

    @staticmethod
    def _checkpoint(active, metadata, phase, messages, step_index, **extra):
        if active.checkpoint_callback is None:
            return
        active.checkpoint_callback(
            {
                "run_id": metadata.run_id,
                "phase": phase,
                "messages": copy.deepcopy(messages),
                "step_index": step_index,
                "system_instruction": active.system_instruction,
                "model_id": active.model_id,
                "tool_allowlist": (
                    list(active.tool_allowlist)
                    if active.tool_allowlist is not None
                    else None
                ),
                "options": copy.deepcopy(dict(active.options)),
                "pending_tool_calls": [],
                "completed_tool_results": [],
                **extra,
            }
        )

    def _terminal_checkpoint(
        self, active, metadata, phase, messages, step_index, error
    ):
        try:
            self._checkpoint(active, metadata, phase, messages, step_index, error=error)
        except Exception:
            # A failed checkpoint store must not suppress the actual terminal
            # error. The ledger's terminal task state also forbids resumption.
            pass

    def _invoke_calls(self, calls, exposed, active, invocation_context, cancel_check):
        stream_invoke = getattr(self._executor, "iter_invoke", None)
        specs = [self._catalog.get(call.name) for call in calls]
        parallel = not callable(stream_invoke) and all(
            call.name in exposed and spec is not None and spec.read_only is True
            for call, spec in zip(calls, specs)
        )
        if parallel:
            results = self._executor.invoke_many(
                calls,
                max_workers=active.parallel_tool_workers,
                invocation_context=invocation_context,
            )
            yield from zip(calls, results)
            return
        for call in calls:
            if cancel_check is not None and cancel_check():
                raise _RunCancelled()
            if call.name not in exposed:
                yield call, ToolResult(
                    call_id=call.call_id,
                    tool_name=call.name,
                    ok=False,
                    error_code=ToolErrorCode.POLICY_DENIED,
                    error_message=f"Tool '{call.name}' is not exposed for this run.",
                )
            elif callable(stream_invoke):
                source = stream_invoke(call, invocation_context=invocation_context)
                try:
                    for event in source:
                        if isinstance(event, ToolResult):
                            yield call, event
                        else:
                            yield event
                finally:
                    close = getattr(source, "close", None)
                    if callable(close):
                        close()
            else:
                result = self._executor.invoke_many(
                    [call],
                    max_workers=1,
                    invocation_context=invocation_context,
                )[0]
                yield call, result

    def _tool_definitions(
        self, allowlist: Optional[Sequence[str]]
    ) -> list[dict[str, Any]]:
        if allowlist is not None:
            missing = [name for name in allowlist if self._catalog.get(name) is None]
            if missing:
                raise ValueError(
                    "runtime tool allowlist contains unknown tools: "
                    + ", ".join(sorted(missing))
                )
        return self._catalog.definitions(allowlist=allowlist)

    @staticmethod
    def _build_system_instruction(
        base_instruction: str, tool_definitions: Sequence[Mapping[str, Any]]
    ) -> str:
        fixed_instruction = build_tool_usage_instruction(tool_definitions)
        base = str(base_instruction or "").strip()
        return f"{base}\n\n{fixed_instruction}" if base else fixed_instruction

    @staticmethod
    def _request_messages(request: AgentRequest) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = copy.deepcopy(list(request.history))
        if request.context:
            messages.append({"role": "user", "content": f"Context:\n{request.context}"})
        messages.append({"role": "user", "content": request.prompt})
        return messages

    @staticmethod
    def _assistant_tool_message(
        response: ModelResponse, calls: Sequence[ToolCall]
    ) -> dict[str, Any]:
        message: dict[str, Any] = {
            "role": "assistant",
            "content": response.content,
            "tool_calls": [
                {
                    "id": call.call_id,
                    "name": call.name,
                    "args": copy.deepcopy(dict(call.arguments)),
                }
                for call in calls
            ],
        }
        if response.reasoning:
            message["reasoning_content"] = response.reasoning
        return message

    @staticmethod
    def _tool_result_message(call: ToolCall, result_text: str) -> dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": call.call_id,
            "name": call.name,
            "content": result_text,
        }

    @staticmethod
    def _finish_with_error(metadata: RunMetadata, error: str) -> None:
        state = (
            RunState.TIMED_OUT if "runtime limit" in error.lower() else RunState.FAILED
        )
        metadata.finish(state, error=error)


__all__ = ["KernelRuntime", "KernelRuntimeConfig"]
