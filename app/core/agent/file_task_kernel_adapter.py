# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""File-task policy and event adapter around the canonical Agent Kernel."""

from __future__ import annotations

import copy
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from app.core.agent._file_task_stepwise_helpers import stepwise_docx_wait_artifact
from app.core.agent.file_task_checkpoint import (
    FileTaskCheckpointConflict,
    build_file_task_checkpoint,
    restore_file_task_receipts,
)
from app.core.agent.file_task_contract import (
    FileTaskEvent,
    FileTaskToolStreamChunk,
    FileTaskToolStreamResult,
)
from app.core.agent.file_task_evidence_guard import sanitize_unverified_readonly_quotes
from app.core.agent.file_task_failure import (
    build_execution_failure,
    build_model_execution_failure,
)
from app.core.agent.file_task_kernel_validation import FileTaskKernelValidator
from app.core.agent.file_task_mutation_evidence import update_mutation_failures
from app.core.agent.file_task_runtime_utils import _preview
from app.core.agent.file_task_step_verification import (
    build_supervisor_step_verification_payload,
)
from app.core.agent.file_task_workflow_state import supervisor_status_payload
from app.core.agent.kernel import (
    AgentEvent,
    AgentRequest,
    AgentRunLimits,
    EventType,
    KernelRuntime,
    KernelRuntimeConfig,
    ModelResponse,
    ToolCall,
    ToolErrorCode,
    ToolResult,
)
from app.core.agent.kernel.model import iter_model_stream
from app.core.agent.tool_design_protocol import (
    build_next_action_artifact,
    extract_tool_gap_from_response,
    merge_tool_gaps,
)
from app.core.agent.toolkits.foundation.catalog import (
    is_write_tool,
    tool_result_preview,
)


@dataclass
class FileTaskExecutionResult:
    cancelled: bool
    execute_step_id: str
    file_changes: List[Dict[str, Any]]
    final_summary: str
    completed_task: bool
    model_failed: bool
    execution_failure: Optional[Dict[str, Any]]
    readonly_fallback_used: bool
    planner_runtime_payload: Dict[str, Any]
    last_check_payload: Optional[Dict[str, Any]]
    tool_gap: Optional[Dict[str, Any]]
    next_action_artifact: Optional[Dict[str, Any]]
    tool_runtime_outcome: Optional[Dict[str, Any]]
    generated_artifacts: List[Dict[str, Any]]
    readonly_tool_outputs: List[Dict[str, Any]]


class _RuntimeModelGateway:
    """Keep legacy model-client injection behind the Kernel ModelGateway port."""

    def __init__(self, runtime: Any, request: Any) -> None:
        self._runtime = runtime
        self._request = request
        self.last_tool_gap: Optional[Dict[str, Any]] = None

    def context_options(self, options=None):
        client = getattr(self._runtime, "_model_client", None)
        resolve = getattr(client, "context_options", None)
        return (
            resolve(self._request, options)
            if callable(resolve)
            else dict(options or {})
        )

    def generate(
        self,
        *,
        messages: Sequence[Dict[str, Any]],
        system: str,
        tools: Sequence[Dict[str, Any]],
        model_id: str = "",
        options: Any = None,
    ) -> ModelResponse:
        response = self._runtime._call_model(
            request=self._request,
            messages=list(messages),
            system=system,
            tools=list(tools),
        )
        extracted_gap = extract_tool_gap_from_response(response)
        if extracted_gap:
            self.last_tool_gap = merge_tool_gaps(
                extracted_gap,
                self.last_tool_gap,
            )
        return ModelResponse.from_raw(response, strict=False)

    def generate_stream(self, *, messages, system, tools, model_id="", options=None):
        from app.core.agent.runtime.verify_phase import _FileTaskRuntimePart4

        client = getattr(self._runtime, "_model_client", None)
        stream_call = getattr(client, "stream_call", None)
        native_call = (
            getattr(self._runtime._call_model, "__func__", None)
            is _FileTaskRuntimePart4._call_model
        )
        if not native_call or not callable(stream_call):
            yield from iter_model_stream(
                self.generate(
                    messages=messages,
                    system=system,
                    tools=tools,
                    model_id=model_id,
                    options=options,
                )
            )
            return
        for chunk in iter_model_stream(
            stream_call(
                request=self._request,
                messages=list(messages),
                system=system,
                tools=list(tools),
                cancel_check=(options or {}).get("_cancel_check"),
            )
        ):
            if chunk.response is not None:
                gap = extract_tool_gap_from_response(chunk.response.to_mapping())
                if gap:
                    self.last_tool_gap = merge_tool_gaps(gap, self.last_tool_gap)
            yield chunk


class _FileTaskToolExecutor:
    """Adapt the transactional FileTaskToolGateway to Kernel ToolResult values."""

    def __init__(
        self,
        gateway: Any,
        *,
        runtime: Any,
        request: Any,
        context_files: List[Any],
        generated_artifacts: List[Dict[str, Any]],
    ) -> None:
        self._gateway = gateway
        self._runtime = runtime
        self._request = request
        self._context_files = context_files
        self._generated_artifacts = generated_artifacts
        self._stream_events: Dict[str, List[tuple[str, Dict[str, Any]]]] = {}
        self._actual_args: Dict[str, Dict[str, Any]] = {}
        self._raw_results: Dict[str, Any] = {}

    def invoke_many(
        self,
        calls: Sequence[ToolCall],
        *,
        max_workers: int = 1,
        invocation_context: Any = None,
    ) -> List[ToolResult]:
        # File mutations are deliberately serialized. Read-only parallelism is
        # an execution policy of the generic Kernel executor, not this adapter.
        return [self._invoke(call) for call in calls]

    def pop_stream_events(self, call_id: str) -> List[tuple[str, Dict[str, Any]]]:
        return self._stream_events.pop(call_id, [])

    def pop_actual_args(self, call_id: str, fallback: Any) -> Dict[str, Any]:
        return self._actual_args.pop(call_id, dict(fallback or {}))

    def pop_raw_result(self, call_id: str, fallback: Any) -> Any:
        """Return the domain result even when Kernel reports tool failure."""

        return self._raw_results.pop(call_id, fallback)

    def _invoke(self, call: ToolCall) -> ToolResult:
        result = None
        for item in self.iter_invoke(call):
            if isinstance(item, ToolResult):
                result = item
            elif item.type is EventType.TOOL_PROGRESS:
                self._stream_events.setdefault(call.call_id, []).append(
                    (
                        item.data["event_type"],
                        item.data["payload"],
                    )
                )
        return result

    def iter_invoke(self, call: ToolCall, *, invocation_context=None):
        try:
            actual_args = self._runtime._repair_tool_args_for_context(
                call.name,
                dict(call.arguments),
                self._request,
                self._context_files,
                generated_artifacts=self._generated_artifacts,
            )
            self._actual_args[call.call_id] = actual_args
            source_block = self._runtime._protected_source_write_block_message(
                call.name,
                actual_args,
                self._request,
                self._context_files,
            )
            if source_block:
                value = {
                    "error": source_block,
                    "status": "policy_denied",
                    "summary": source_block,
                }
                self._raw_results[call.call_id] = value
                yield ToolResult(
                    call_id=call.call_id,
                    tool_name=call.name,
                    ok=False,
                    error_code=ToolErrorCode.POLICY_DENIED,
                    error_message=source_block,
                )
                return
            value = self._gateway.execute(call.name, actual_args)
            if isinstance(value, FileTaskToolStreamResult):
                final_result = None
                completed = False
                source = iter(value.chunks)
                try:
                    for chunk in source:
                        if not isinstance(chunk, FileTaskToolStreamChunk):
                            continue
                        if chunk.kind == "result":
                            final_result = chunk.payload
                            completed = True
                        elif chunk.kind == "event" and chunk.event_type:
                            progress_payload = dict(chunk.payload or {})
                            progress_payload.update({"draft": True, "committed": False})
                            yield AgentEvent(
                                EventType.TOOL_PROGRESS,
                                {
                                    "tool_name": call.name,
                                    "tool_call_id": call.call_id,
                                    "event_type": chunk.event_type,
                                    "payload": progress_payload,
                                },
                            )
                finally:
                    close = getattr(source, "close", None)
                    if callable(close):
                        close()
                if not completed:
                    raise RuntimeError(
                        "Tool stream ended without a final execution result"
                    )
                value = final_result
            self._raw_results[call.call_id] = value
            if self._reports_error(value):
                yield ToolResult(
                    call_id=call.call_id,
                    tool_name=call.name,
                    ok=False,
                    error_code=ToolErrorCode.EXECUTION_ERROR,
                    error_message=self._error_text(value),
                )
                return
            yield ToolResult(
                call_id=call.call_id,
                tool_name=call.name,
                ok=True,
                value=value,
            )
        except Exception as exc:
            yield ToolResult(
                call_id=call.call_id,
                tool_name=call.name,
                ok=False,
                error_code=ToolErrorCode.EXECUTION_ERROR,
                error_message=str(exc),
            )

    def _consume_stream(self, call_id: str, value: Any) -> Any:
        if not isinstance(value, FileTaskToolStreamResult):
            return value
        final_result: Any = None
        events: List[tuple[str, Dict[str, Any]]] = []
        for chunk in value.chunks:
            if not isinstance(chunk, FileTaskToolStreamChunk):
                continue
            kind = str(chunk.kind or "").strip().lower()
            if kind == "event" and str(chunk.event_type or "").strip():
                payload = dict(chunk.payload) if isinstance(chunk.payload, dict) else {}
                events.append((str(chunk.event_type).strip(), payload))
            elif kind == "result":
                final_result = chunk.payload
        if events:
            self._stream_events[call_id] = events
        return final_result

    @staticmethod
    def _reports_error(value: Any) -> bool:
        payload = _FileTaskToolExecutor._result_payload(value)
        return isinstance(payload, dict) and bool(payload.get("error"))

    @staticmethod
    def _error_text(value: Any) -> str:
        payload = _FileTaskToolExecutor._result_payload(value)
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                return str(error.get("message") or error)
            return str(error or payload)
        return str(value)

    @staticmethod
    def _result_payload(value: Any) -> Any:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (TypeError, ValueError):
                return value
        return value


class FileTaskKernelAdapter:
    """Run a file request through ``KernelRuntime`` and map domain events.

    Classification, recipes, Office/PDF tools, transactions, and terminal
    quality gates stay in the file-task domain. Model/tool progression has one
    owner only: ``KernelRuntime``.
    """

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    def stream(
        self,
        *,
        ledger: Any,
        request: Any,
        snippets: List[Dict[str, Any]],
        context_files: List[Any],
        known_tool_gap: Optional[Dict[str, Any]],
        classification: Any,
        intent_plan: Any,
        execution_context: Any,
        recipe_skeleton: Dict[str, Any],
        tool_defs: List[Dict[str, Any]],
        tool_gateway: Any,
        workflow_state: Dict[str, Any],
        completion_criteria: List[str],
        write_authorized: bool,
        write_required: bool,
        executor: Any,
    ) -> Iterable[FileTaskEvent]:
        runtime = self._runtime
        options = dict(getattr(request, "options", None) or {})
        resume_state = copy.deepcopy(dict(options.get("_kernel_resume_state") or {}))
        restored_receipts = restore_file_task_receipts(resume_state)
        workspace_root = str(getattr(runtime, "_workspace_root", "") or "")
        if not workspace_root:
            from app.core.config.workspace_runtime import get_workspace_root

            workspace_root = str(get_workspace_root())
        if resume_state:
            if (
                str(Path(resume_state.get("workspace_root") or "").resolve()).casefold()
                != str(Path(workspace_root).resolve()).casefold()
            ):
                raise FileTaskCheckpointConflict("文件任务工作区已改变，需要核对后继续")
            if str(resume_state.get("run_id") or "") != str(request.run_id or ""):
                raise FileTaskCheckpointConflict("文件任务运行标识与检查点不一致")
            if resume_state.get("task_id") and str(resume_state["task_id"]) != str(
                getattr(request, "task_id", "") or ""
            ):
                raise FileTaskCheckpointConflict("文件任务标识与检查点不一致")
        execute_step_id = "execute"
        yield ledger.event(
            "step.started",
            {
                "title": "Kernel 执行文件任务",
                "detail": "模型与 Koto 文件工具由统一 KernelRuntime 调度。",
                "max_rounds": runtime._max_rounds,
            },
            step_id=execute_step_id,
        )
        yield ledger.event(
            "supervisor.status",
            supervisor_status_payload(
                workflow_state,
                stage="analyzing",
                summary="Kernel 正在选择并执行 Koto 文件工具。",
                active_step_id="model_reasoning",
                completed_step_ids=["read_context"],
            ),
            step_id=execute_step_id,
        )

        messages = runtime._build_messages(
            request,
            snippets,
            context_files,
            known_tool_gap,
            classification,
            intent_plan,
            execution_context=execution_context,
            recipe_skeleton=recipe_skeleton,
        )
        system = runtime._build_system_prompt(
            request,
            context_files,
            known_tool_gap,
            classification,
            intent_plan,
            execution_context=execution_context,
            recipe_skeleton=recipe_skeleton,
            tool_definitions=tool_defs,
        )
        kernel_request = self._kernel_request(request, messages)
        allowlist = tuple(
            str(item.get("name") or "").strip()
            for item in tool_defs
            if str(item.get("name") or "").strip()
            and (
                write_authorized
                or (
                    not is_write_tool(str(item.get("name") or "").strip())
                    and str(item.get("name") or "").strip() != "run_python_code"
                )
            )
        )
        if resume_state:
            # The Kernel restores its saved allowlist. Intersect it with the
            # current domain authorization before handing it to that owner.
            saved_names = resume_state.get("tool_allowlist")
            resumed_names = tuple(
                name
                for name in (saved_names if saved_names is not None else allowlist)
                if name in allowlist
            )
            if any(
                str(call.get("name") or "") not in resumed_names
                for call in resume_state.get("pending_tool_calls") or []
            ):
                raise FileTaskCheckpointConflict(
                    "检查点中的待执行工具已不在当前授权范围内"
                )
            for call in resume_state.get("pending_tool_calls") or []:
                spec = tool_gateway.catalog.get(str(call.get("name") or ""))
                if spec is None or spec.read_only is not True:
                    raise FileTaskCheckpointConflict(
                        "待恢复工具当前不再是明确只读操作，需要核对执行状态"
                    )
            resume_state["tool_allowlist"] = list(resumed_names)
        generated_artifacts: List[Dict[str, Any]] = list(
            restored_receipts.get("generated_artifacts") or []
        )
        readonly_tool_outputs: List[Dict[str, Any]] = list(
            restored_receipts.get("readonly_tool_outputs") or []
        )
        file_changes: List[Dict[str, Any]] = list(
            restored_receipts.get("file_changes") or []
        )
        mutation_failures = list(restored_receipts.get("mutation_failures") or [])
        observed_call_ids = set(restored_receipts.get("observed_call_ids") or [])
        last_file_versions = copy.deepcopy(resume_state.get("file_versions") or [])
        for change in file_changes:
            # A tool_complete checkpoint precedes its public TOOL_RESULT. On
            # recovery the committed edit must become visible even if that
            # earlier process died before publishing file.changed.
            yield ledger.event(
                "file.changed",
                {**change, "recovered": True, "committed": True},
                step_id=execute_step_id,
            )
        validator = FileTaskKernelValidator(
            task=request.task,
            files=context_files,
            readonly_tool_outputs=readonly_tool_outputs,
            write_required=write_required,
            file_changes=file_changes,
            write_tool_names=tuple(name for name in allowlist if is_write_tool(name)),
            mutation_failures=mutation_failures,
        )
        kernel_executor = _FileTaskToolExecutor(
            tool_gateway,
            runtime=runtime,
            request=request,
            context_files=context_files,
            generated_artifacts=generated_artifacts,
        )
        model_gateway = _RuntimeModelGateway(runtime, request)
        kernel = KernelRuntime(
            gateway=model_gateway,
            catalog=tool_gateway.catalog,
            executor=kernel_executor,
            validator=validator,
            limits=AgentRunLimits(
                max_steps=runtime._max_rounds + 1,
                max_tool_calls=max(8, runtime._max_rounds * 8),
                max_repeated_batches=1,
                max_seconds=600.0,
            ),
        )

        call_by_id: Dict[str, Dict[str, Any]] = {}
        final_summary = ""
        kernel_error = ""
        kernel_error_code = ""
        kernel_validation = {}
        last_result_preview = str(restored_receipts.get("last_result_preview") or "")
        tool_runtime_outcome: Optional[Dict[str, Any]] = restored_receipts.get(
            "tool_runtime_outcome"
        )
        task_id = str(getattr(request, "task_id", "") or "")
        checkpoint_owner = str(options.get("_checkpoint_owner") or uuid.uuid4().hex)
        external_checkpoint = options.get("_checkpoint_callback")

        def checkpoint(state):
            nonlocal last_file_versions
            snapshot = build_file_task_checkpoint(
                state,
                request=request,
                workspace_root=workspace_root,
                runtime=runtime,
                receipts={
                    "file_changes": file_changes,
                    "readonly_tool_outputs": readonly_tool_outputs,
                    "mutation_failures": mutation_failures,
                    "authorized_write_target": (
                        str(request.target_path or "") if write_authorized else ""
                    ),
                    "generated_artifacts": generated_artifacts,
                    "observed_call_ids": sorted(observed_call_ids),
                    "tool_runtime_outcome": tool_runtime_outcome,
                    "last_result_preview": last_result_preview,
                    "file_versions": last_file_versions,
                },
                raw_results=kernel_executor._raw_results,
                actual_args=kernel_executor._actual_args,
            )
            last_file_versions = copy.deepcopy(snapshot.get("file_versions") or [])
            if task_id:
                from app.core.tasks.task_ledger import get_ledger

                task_ledger = get_ledger()
                task_ledger.save_kernel_checkpoint(
                    task_id,
                    str(request.run_id or ""),
                    snapshot,
                    owner_id=checkpoint_owner,
                )
                task_ledger.renew_kernel_lease(
                    task_id,
                    str(request.run_id or ""),
                    checkpoint_owner,
                    lease_seconds=900,
                )
            if callable(external_checkpoint):
                external_checkpoint(snapshot)

        if resume_state and runtime._tool_runtime_status(tool_runtime_outcome) in {
            "blocked",
            "write_blocked",
        }:
            # A committed domain blocking result goes directly through the
            # original finalization policy, rather than selecting another tool.
            resume_state.update(
                phase="completed",
                pending_tool_calls=[],
                terminal_result=str(
                    (tool_runtime_outcome or {}).get("summary") or last_result_preview
                ),
            )
        model_options = {
            key: options[key]
            for key in (
                "context_window_tokens",
                "context_window",
                "num_ctx",
                "reserved_output_tokens",
                "max_output_tokens",
                "max_tokens",
            )
            if key in options
        }
        nested_options = options.get("options")
        if isinstance(nested_options, dict):
            model_options["options"] = {
                key: nested_options[key]
                for key in ("num_ctx", "num_predict")
                if key in nested_options
            }
        model_options["task_type"] = "FILE_TASK"

        for event in kernel.iter_events(
            kernel_request,
            config=KernelRuntimeConfig(
                system_instruction=system,
                model_id=str(request.model_id or ""),
                tool_allowlist=allowlist,
                options=model_options,
                parallel_tool_workers=1,
                max_validation_retries=max(1, runtime._max_rounds),
                checkpoint_callback=(
                    checkpoint if task_id or callable(external_checkpoint) else None
                ),
                resume_state=resume_state or None,
            ),
            cancel_check=lambda: runtime._is_cancelled(request),
        ):
            message_event = {
                EventType.MESSAGE_STARTED: "message.started",
                EventType.STREAM_CHUNK: "message.delta",
                EventType.MESSAGE_FINISHED: "message.finished",
            }.get(event.type)
            if message_event:
                yield ledger.event(
                    message_event, dict(event.data), step_id=execute_step_id
                )
                continue
            if event.type is EventType.TOOL_PROGRESS:
                payload = dict(event.data.get("payload") or {})
                payload.update(
                    {
                        "tool_name": event.data.get("tool_name"),
                        "tool_call_id": event.data.get("tool_call_id"),
                    }
                )
                yield ledger.event("tool.progress", payload, step_id=execute_step_id)
                event_type = str(event.data.get("event_type") or "")
                if event_type and event_type != "tool.progress":
                    yield ledger.event(event_type, payload, step_id=execute_step_id)
                continue
            if event.type is EventType.STATUS_MESSAGE:
                yield ledger.event(
                    str(event.data.get("event_type") or "run.progress"),
                    dict(event.data),
                    step_id=execute_step_id,
                )
                continue
            if event.type is EventType.TOOL_CALL:
                call = dict(event.data.get("tool_call") or {})
                call_id = str(call.get("id") or "")
                call_by_id[call_id] = call
                yield ledger.event(
                    "tool.started",
                    {
                        "tool_name": str(call.get("name") or ""),
                        "args": dict(call.get("args") or {}),
                        "tool_call_id": call_id,
                    },
                    step_id=execute_step_id,
                )
                continue

            if event.type is EventType.VALIDATION and not event.data.get("accepted"):
                yield ledger.event(
                    "tool.finished",
                    {
                        "tool_name": "kernel_evidence_guard",
                        "success": False,
                        "result_preview": validator.last_instruction,
                        "reasons": list(event.data.get("reasons") or []),
                    },
                    step_id=execute_step_id,
                )
                continue

            if event.type is EventType.TOOL_RESULT:
                payload = dict(event.data.get("result") or {})
                call_id = str(event.data.get("call_id") or payload.get("call_id") or "")
                call = call_by_id.get(call_id, {})
                tool_name = str(event.data.get("tool_name") or call.get("name") or "")
                tool_args = kernel_executor.pop_actual_args(
                    call_id, call.get("args") or {}
                )
                for event_type, stream_payload in kernel_executor.pop_stream_events(
                    call_id
                ):
                    yield ledger.event(
                        event_type, stream_payload, step_id=execute_step_id
                    )

                success = bool(payload.get("ok"))
                kernel_result = (
                    payload.get("value")
                    if success
                    else {"error": dict(payload.get("error") or {})}
                )
                model_result = kernel_executor.pop_raw_result(call_id, kernel_result)
                extracted_changes = runtime._extract_file_changes(
                    tool_name, tool_args, model_result
                )
                for change in extracted_changes:
                    change.setdefault("tool_call_id", call_id)
                update_mutation_failures(
                    mutation_failures,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    result=payload,
                    changes=extracted_changes,
                    call_id=call_id,
                    authorized_target=(
                        str(request.target_path or "") if write_authorized else ""
                    ),
                )
                file_changes.extend(extracted_changes)
                for change in extracted_changes:
                    yield ledger.event("file.changed", change, step_id=execute_step_id)

                artifacts = runtime._tool_artifacts(tool_name, model_result)
                runtime._remember_generated_artifacts(generated_artifacts, artifacts)
                outcome = runtime._extract_tool_runtime_outcome(model_result)
                if outcome:
                    tool_runtime_outcome = outcome
                runtime_status = runtime._tool_runtime_status(outcome)
                blocked = runtime_status in {"blocked", "write_blocked"}
                policy_blocked = runtime_status == "policy_denied"
                if not is_write_tool(tool_name):
                    readonly_tool_outputs.append(
                        {
                            "tool_name": tool_name,
                            "args": tool_args,
                            "result": model_result,
                            "preview": tool_result_preview(
                                tool_name, model_result, 1200
                            ),
                        }
                    )
                last_result_preview = tool_result_preview(tool_name, model_result, 1200)
                observed_call_ids.add(call_id)
                yield ledger.event(
                    "tool.finished",
                    {
                        "tool_name": tool_name,
                        "success": success,
                        "result_preview": last_result_preview,
                        "tool_call_id": call_id,
                        "artifacts": artifacts,
                        "blocked": blocked or policy_blocked,
                    },
                    step_id=execute_step_id,
                )
                yield ledger.event(
                    "supervisor.step_verified",
                    build_supervisor_step_verification_payload(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        success=success,
                        blocked=blocked or policy_blocked,
                        summary=last_result_preview,
                        round_index=0,
                        tool_index=0,
                        file_changes=extracted_changes,
                        artifacts=artifacts,
                    ),
                    step_id=execute_step_id,
                )
                if blocked:
                    final_summary = str(
                        (outcome or {}).get("summary") or last_result_preview
                    ).strip()
                    break
                continue

            if event.type is EventType.TASK_COMPLETE:
                final_summary = str(event.data.get("result") or "").strip()
                kernel_error = str(event.data.get("error") or "").strip()
                kernel_error_code = str(event.data.get("error_code") or "")
                kernel_validation = dict(event.data.get("validation") or {})

        if runtime._is_cancelled(request) or "cancelled" in kernel_error.lower():
            yield runtime._cancelled_event(ledger, request)
            return self._result(execute_step_id=execute_step_id, cancelled=True)

        readonly_fallback_used = False
        validation_failed = kernel_error_code in {
            "validation_blocked",
            "validation_exhausted",
        }
        if file_changes and not final_summary:
            final_summary = last_result_preview or "文件工具已完成写入。"
            if not validation_failed:
                kernel_error = ""
        if (
            write_required
            and not file_changes
            and validator.last_instruction
            and kernel_error == "agent step limit exceeded"
        ):
            # The model responded but repeatedly declined to perform the
            # required write. This is a write-evidence failure, not a model
            # transport failure.
            kernel_error = ""
        # A successful mutating tool is an observable completion fact even if
        # the model omits its final prose turn or exhausts the round budget.
        model_failed = bool(kernel_error and not file_changes and not validation_failed)
        execution_failure: Optional[Dict[str, Any]] = None
        last_check_payload = None
        domain_evidence_rejection = not file_changes and (
            (
                write_required
                and "write_evidence_missing" in kernel_validation.get("reasons", [])
            )
            or "readonly_source_coverage_missing"
            in kernel_validation.get("reasons", [])
        )
        if validation_failed and not domain_evidence_rejection:
            execution_failure = build_execution_failure(
                status=kernel_error_code,
                code=kernel_error_code.upper(),
                phase="validation",
                summary=kernel_error or final_summary,
                detail=kernel_error,
                validation=kernel_validation,
                remaining=["修正未通过的验收条件后重试。"],
            )
            if file_changes:
                # A committed write remains a visible fact, while rejected
                # validation can never be promoted to task success by it.
                last_check_payload = {
                    "passed": False,
                    "status": kernel_error_code,
                    "summary": execution_failure["summary"],
                    "failure": execution_failure,
                    "remaining": execution_failure["remaining"],
                    "criteria_results": [
                        {
                            "criterion": "kernel_validation",
                            "passed": False,
                            "detail": kernel_error,
                            "priority": "critical",
                        }
                    ],
                }
        elif model_failed:
            execution_failure = build_model_execution_failure(
                RuntimeError(kernel_error or "Kernel 执行失败。"),
                round_index=1,
                model_mode=str(request.model_mode or ""),
                model_id=str(request.model_id or ""),
            )
        # Known missing-write/source evidence stays with the original domain
        # gates, preserving write_not_performed / analysis_incomplete instead
        # of misclassifying a returned model response as a provider failure.

        if not write_required:
            final_summary = sanitize_unverified_readonly_quotes(
                task=request.task,
                text=final_summary,
            )
        tool_gap = merge_tool_gaps(model_gateway.last_tool_gap, known_tool_gap)
        next_action_artifact = None
        if tool_gap:
            gap_runtime = runtime._build_runtime_metadata(
                terminal_status="tool_gap",
                readonly_fallback_used=readonly_fallback_used,
                model_failed=model_failed,
                planner_payload={
                    "backend": "kernel",
                    "source": "kernel",
                    "policy": "kernel_only",
                    "transport": "native",
                    "reason": "single_model_tool_loop",
                },
            )
            next_action_artifact = runtime._with_runtime_context(
                build_next_action_artifact(request, tool_gap),
                gap_runtime,
            )
            yield ledger.event(
                "tool.missing",
                {
                    "summary": str(tool_gap.get("summary") or ""),
                    "missing_capability": str(tool_gap.get("missing_capability") or ""),
                    "why_missing": str(tool_gap.get("why_missing") or ""),
                    "suggested_next_step": str(
                        tool_gap.get("suggested_next_step") or ""
                    ),
                    "proposed_tool": (
                        tool_gap.get("proposed_tool")
                        if isinstance(tool_gap.get("proposed_tool"), dict)
                        else None
                    ),
                    "next_action_artifact": next_action_artifact,
                    "runtime": gap_runtime,
                },
                step_id=execute_step_id,
            )
        elif file_changes:
            next_action_artifact = stepwise_docx_wait_artifact(
                request=request,
                files=context_files,
                snippets=snippets,
                file_changes=file_changes,
                recipe_skeleton=recipe_skeleton,
                target_path_fallback=str(request.target_path or ""),
            )
            if next_action_artifact:
                tool_runtime_outcome = {
                    "status": "awaiting_confirmation",
                    "summary": str(next_action_artifact.get("summary") or ""),
                    "next_action_artifact": next_action_artifact,
                }
        if (
            mutation_failures
            and execution_failure is None
            and runtime._tool_runtime_status(tool_runtime_outcome)
            not in {"blocked", "write_blocked"}
        ):
            denied = any(item.get("policy_denied") for item in mutation_failures)
            runtime_failure_status = runtime._tool_runtime_status(tool_runtime_outcome)
            failure_status = (
                runtime_failure_status
                if runtime_failure_status
                in {"blocked", "write_blocked", "policy_denied"}
                else (
                    "policy_denied"
                    if denied
                    else (
                        "quality_gate_failed" if file_changes else "write_not_performed"
                    )
                )
            )
            execution_failure = build_execution_failure(
                status=failure_status,
                code=failure_status.upper(),
                phase="tools",
                summary=(
                    "文件写入被授权范围阻止。"
                    if denied
                    else "文件写入失败，尚未核实成功提交。"
                ),
                detail="失败的写入不能通过模型的完成文字升级为成功。",
                remaining=["核对失败操作与目标文件，修正原因后继续处理。"],
            )
            last_check_payload = {
                "passed": False,
                "status": failure_status,
                "summary": execution_failure["summary"],
                "failure": execution_failure,
                "remaining": execution_failure["remaining"],
                "criteria_results": [
                    {
                        "criterion": "mutation_committed",
                        "passed": False,
                        "detail": execution_failure["summary"],
                        "priority": "critical",
                    }
                ],
            }
        completion_evidence = (
            bool(file_changes)
            if write_required
            else bool(file_changes or final_summary)
        )
        completed_task = completion_evidence and not (
            validation_failed or model_failed or mutation_failures
        )
        status = "completed" if completed_task and not model_failed else "failed"
        summary = final_summary or kernel_error or "Kernel 未返回可用结果。"
        yield ledger.event(
            "tool.finished",
            {
                "tool_name": "model_message",
                "success": not (model_failed or validation_failed or mutation_failures),
                "result_preview": _preview(summary, 600),
            },
            step_id=execute_step_id,
        )
        yield ledger.event(
            "step.result",
            runtime._build_step_result_payload(
                title="Kernel 执行文件任务",
                summary=summary,
                status=status,
                file_changes=file_changes,
            ),
            step_id=execute_step_id,
        )
        return FileTaskExecutionResult(
            cancelled=False,
            execute_step_id=execute_step_id,
            file_changes=file_changes,
            final_summary=final_summary,
            completed_task=completed_task,
            model_failed=model_failed,
            execution_failure=execution_failure,
            readonly_fallback_used=readonly_fallback_used,
            planner_runtime_payload={
                "backend": "kernel",
                "source": "kernel",
                "policy": "kernel_only",
                "transport": "native",
                "reason": "single_model_tool_loop",
            },
            last_check_payload=last_check_payload,
            tool_gap=tool_gap,
            next_action_artifact=next_action_artifact,
            tool_runtime_outcome=tool_runtime_outcome,
            generated_artifacts=generated_artifacts,
            readonly_tool_outputs=readonly_tool_outputs,
        )

    @staticmethod
    def _kernel_request(request: Any, messages: List[Dict[str, Any]]) -> AgentRequest:
        prepared = list(messages)
        prompt = str(request.task or "")
        history = prepared
        if prepared and str(prepared[-1].get("role") or "").lower() == "user":
            prompt = str(prepared[-1].get("content") or prompt)
            history = prepared[:-1]
        return AgentRequest(
            prompt=prompt,
            session_id=str(request.session_id or ""),
            file_name=str(request.target_path or ""),
            selection=str(request.selection or ""),
            has_selection=bool(request.selection),
            history=history,
            model_mode=str(request.model_mode or "auto"),
            action_type="file_task",
            extra={"run_id": str(request.run_id or "")},
        )

    @staticmethod
    def _result(*, execute_step_id: str, cancelled: bool) -> FileTaskExecutionResult:
        return FileTaskExecutionResult(
            cancelled=cancelled,
            execute_step_id=execute_step_id,
            file_changes=[],
            final_summary="",
            completed_task=False,
            model_failed=False,
            execution_failure=None,
            readonly_fallback_used=False,
            planner_runtime_payload={},
            last_check_payload=None,
            tool_gap=None,
            next_action_artifact=None,
            tool_runtime_outcome=None,
            generated_artifacts=[],
            readonly_tool_outputs=[],
        )


__all__ = ["FileTaskExecutionResult", "FileTaskKernelAdapter"]
