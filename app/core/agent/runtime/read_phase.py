from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.core.agent.file_task_builtin_tool_runner import (
    run_builtin_tool as _builtin_tool_runner_run_builtin_tool,
)
from app.core.agent.file_task_cancel import is_cancel_requested
from app.core.agent.file_task_context_read import FileTaskContextReadPhase
from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskEvent,
    FileTaskFile,
    FileTaskLedger,
    FileTaskRequest,
    FileTaskToolStreamChunk,
    FileTaskToolStreamResult,
)
from app.core.agent.file_task_file_facts import request_has_file_type
from app.core.agent.file_task_finalization import FileTaskFinalizationPhase
from app.core.agent.file_task_intent_predicates import (
    explicit_output_mode as _intent_explicit_output_mode,
)
from app.core.agent.file_task_intent_predicates import (
    has_artifact_creation_intent as _intent_has_artifact_creation_intent,
)
from app.core.agent.file_task_intent_predicates import (
    has_explicit_write_intent as _intent_has_explicit_write_intent,
)
from app.core.agent.file_task_intent_predicates import (
    has_global_readonly_write_negation as _intent_has_global_readonly_write_negation,
)
from app.core.agent.file_task_intent_predicates import (
    has_readonly_write_negation as _intent_has_readonly_write_negation,
)
from app.core.agent.file_task_intent_predicates import (
    has_source_scoped_write_negation as _intent_has_source_scoped_write_negation,
)
from app.core.agent.file_task_intent_predicates import (
    has_write_intent as _intent_has_write_intent,
)
from app.core.agent.file_task_intent_predicates import (
    quick_action_mode as _intent_quick_action_mode,
)
from app.core.agent.file_task_kernel_adapter import FileTaskKernelAdapter
from app.core.agent.file_task_planning import FileTaskPlanningPhase
from app.core.agent.file_task_runtime_patterns import _READ_LIMIT
from app.core.agent.file_task_step_payload import (
    build_runtime_metadata as _step_payload_build_runtime_metadata,
)
from app.core.agent.file_task_step_payload import (
    build_step_result_payload as _step_payload_build_step_result_payload,
)
from app.core.agent.file_task_step_payload import (
    check_step_result_status as _step_payload_check_step_result_status,
)
from app.core.agent.file_task_step_payload import (
    execute_step_result_status as _step_payload_execute_step_result_status,
)
from app.core.agent.file_task_step_payload import (
    execute_step_summary as _step_payload_execute_step_summary,
)
from app.core.agent.file_task_step_payload import (
    public_context_snippets as _step_payload_public_context_snippets,
)
from app.core.agent.file_task_step_payload import (
    step_result_file_changes as _step_payload_step_result_file_changes,
)
from app.core.agent.file_task_step_payload import (
    with_runtime_context as _step_payload_with_runtime_context,
)
from app.core.agent.file_task_targeting import context_files as _targeting_context_files
from app.core.agent.file_task_targeting import (
    explicit_output_path_from_task as _targeting_explicit_output_path_from_task,
)
from app.core.agent.file_task_targeting import (
    explicit_write_target_path_from_task as _targeting_explicit_write_target_path_from_task,
)
from app.core.agent.file_task_targeting import (
    files_explicitly_mentioned_in_task as _targeting_files_explicitly_mentioned_in_task,
)
from app.core.agent.file_task_targeting import (
    protected_source_write_block_message as _targeting_protected_source_write_block_message,
)
from app.core.agent.file_task_targeting import (
    request_target_points_to_source as _targeting_request_target_points_to_source,
)
from app.core.agent.file_task_targeting import (
    request_with_target_path as _targeting_request_with_target_path,
)
from app.core.agent.file_task_targeting import (
    resolve_explicit_output_against_request_target as _targeting_resolve_explicit_output_against_request_target,
)
from app.core.agent.file_task_targeting import (
    resolved_workspace_root as _targeting_resolved_workspace_root,
)
from app.core.agent.file_task_targeting import (
    same_task_path as _targeting_same_task_path,
)
from app.core.agent.file_task_targeting import (
    should_skip_uncreated_target_context as _targeting_should_skip_uncreated_target_context,
)
from app.core.agent.file_task_targeting import (
    target_path_with_file_alias as _targeting_target_path_with_file_alias,
)
from app.core.agent.file_task_targeting import (
    task_text_mentions_path as _targeting_task_text_mentions_path,
)
from app.core.agent.file_task_tool_gateway import (
    FileTaskToolContext,
    FileTaskToolGateway,
    ToolExecutor,
)
from app.core.agent.file_task_workflow_state import request_with_workflow_checkpoint


class _FileTaskRuntimePart1:
    def run(self, request: FileTaskRequest) -> Iterable[FileTaskEvent]:
        run_started_at = time.perf_counter()
        phase_started_at = run_started_at
        performance: Dict[str, Any] = {}

        def _mark_phase(name: str) -> None:
            nonlocal phase_started_at
            now = time.perf_counter()
            performance[f"{name}_ms"] = round((now - phase_started_at) * 1000, 2)
            phase_started_at = now

        def _performance_snapshot(*, total: bool = False) -> Dict[str, Any]:
            snapshot = dict(performance)
            snapshot["elapsed_ms"] = round(
                (time.perf_counter() - run_started_at) * 1000, 2
            )
            if total:
                snapshot["total_ms"] = snapshot["elapsed_ms"]
            return snapshot

        request = request_with_workflow_checkpoint(request)
        request = self._request_with_inferred_target_path(request)
        ledger = FileTaskLedger(request.run_id)
        if self._is_cancelled(request):
            yield self._cancelled_event(ledger, request)
            return

        plan_result = yield from FileTaskPlanningPhase(self).stream(
            ledger=ledger,
            request=request,
            mark_phase=_mark_phase,
            performance_snapshot=_performance_snapshot,
        )
        if plan_result.terminal:
            return
        context_files = plan_result.context_files
        known_tool_gap = plan_result.known_tool_gap
        execution_context = plan_result.execution_context
        classification = plan_result.classification
        intent_plan = plan_result.intent_plan
        quick_action_mode = plan_result.quick_action_mode
        write_authorized = plan_result.write_authorized
        write_required = plan_result.write_required
        tool_defs = plan_result.tool_defs
        tool_gateway = plan_result.tool_gateway
        executor = plan_result.executor
        recipe_skeleton = plan_result.recipe_skeleton
        completion_contract_payload = plan_result.completion_contract_payload
        completion_criteria = plan_result.completion_criteria
        workflow_state = plan_result.workflow_state
        classification_payload = plan_result.classification_payload

        context_result = yield from FileTaskContextReadPhase(self).stream(
            ledger=ledger,
            request=request,
            context_files=context_files,
            recipe_skeleton=recipe_skeleton,
            workflow_state=workflow_state,
            executor=executor,
            read_limit=_READ_LIMIT,
        )
        if context_result.cancelled:
            return
        snippets = context_result.snippets

        execution_result = yield from FileTaskKernelAdapter(self).stream(
            ledger=ledger,
            request=request,
            snippets=snippets,
            context_files=context_files,
            known_tool_gap=known_tool_gap,
            classification=classification,
            intent_plan=intent_plan,
            execution_context=execution_context,
            recipe_skeleton=recipe_skeleton,
            tool_defs=tool_defs,
            tool_gateway=tool_gateway,
            workflow_state=workflow_state,
            completion_criteria=completion_criteria,
            write_authorized=write_authorized,
            write_required=write_required,
            executor=executor,
        )
        if execution_result.cancelled:
            return
        file_changes = execution_result.file_changes
        final_summary = execution_result.final_summary
        completed_task = execution_result.completed_task
        model_failed = execution_result.model_failed
        execution_failure = execution_result.execution_failure
        readonly_fallback_used = execution_result.readonly_fallback_used
        planner_runtime_payload = execution_result.planner_runtime_payload
        last_check_payload = execution_result.last_check_payload
        tool_gap = execution_result.tool_gap
        next_action_artifact = execution_result.next_action_artifact
        tool_runtime_outcome = execution_result.tool_runtime_outcome
        generated_artifacts = execution_result.generated_artifacts
        readonly_tool_outputs = execution_result.readonly_tool_outputs
        yield from FileTaskFinalizationPhase(self).stream(
            ledger=ledger,
            request=request,
            executor=executor,
            snippets=snippets,
            context_files=context_files,
            classification=classification,
            classification_payload=classification_payload,
            completion_contract_payload=completion_contract_payload,
            completion_criteria=completion_criteria,
            recipe_skeleton=recipe_skeleton,
            workflow_state=workflow_state,
            write_intent=write_required,
            quick_action_mode=quick_action_mode,
            file_changes=file_changes,
            final_summary=final_summary,
            completed_task=completed_task,
            model_failed=model_failed,
            execution_failure=execution_failure,
            readonly_fallback_used=readonly_fallback_used,
            planner_runtime_payload=planner_runtime_payload,
            last_check_payload=last_check_payload,
            tool_gap=tool_gap,
            next_action_artifact=next_action_artifact,
            tool_runtime_outcome=tool_runtime_outcome,
            generated_artifacts=generated_artifacts,
            readonly_tool_outputs=readonly_tool_outputs,
            performance_snapshot=_performance_snapshot,
        )

    def _is_cancelled(self, request: FileTaskRequest) -> bool:
        return is_cancel_requested(str(request.run_id or ""))

    def _cancelled_event(
        self, ledger: FileTaskLedger, request: FileTaskRequest
    ) -> FileTaskEvent:
        return ledger.event(
            "run.cancelled",
            {
                "task": request.task,
                "mode": "whitebox_v1",
                "summary": "任务已被用户取消。",
                "completed_task": False,
                "runtime": {
                    "terminal_status": "cancelled",
                    "execution_path": "cancelled",
                    "model_failed": False,
                    "readonly_fallback_used": False,
                },
            },
            step_id="run",
        )

    def _build_runtime_metadata(
        self,
        *,
        terminal_status: str,
        readonly_fallback_used: bool,
        model_failed: bool,
        planner_payload: Optional[Dict[str, Any]] = None,
        execution_failure: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return _step_payload_build_runtime_metadata(
            terminal_status=terminal_status,
            readonly_fallback_used=readonly_fallback_used,
            model_failed=model_failed,
            planner_payload=planner_payload,
            execution_failure=execution_failure,
        )

    def _with_runtime_context(
        self,
        artifact: Optional[Dict[str, Any]],
        runtime_metadata: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        return _step_payload_with_runtime_context(artifact, runtime_metadata)

    def _step_result_file_changes(
        self, file_changes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        return _step_payload_step_result_file_changes(file_changes)

    def _build_step_result_payload(
        self,
        *,
        title: str,
        summary: str,
        status: str = "completed",
        round_index: int = 0,
        snippet_count: int = 0,
        snippets: Optional[List[Dict[str, Any]]] = None,
        file_changes: Optional[List[Dict[str, Any]]] = None,
        runtime: Optional[Dict[str, Any]] = None,
        passed: Optional[bool] = None,
        next_action_artifact: Optional[Dict[str, Any]] = None,
        supervisor_audit: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return _step_payload_build_step_result_payload(
            title=title,
            summary=summary,
            status=status,
            round_index=round_index,
            snippet_count=snippet_count,
            snippets=snippets,
            file_changes=file_changes,
            runtime=runtime,
            passed=passed,
            next_action_artifact=next_action_artifact,
            supervisor_audit=supervisor_audit,
        )

    def _public_context_snippets(
        self, snippets: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        return _step_payload_public_context_snippets(snippets)

    def _execute_step_summary(
        self,
        *,
        round_index: int,
        final_summary: str,
        model_failed: bool,
        tool_gap: Optional[Dict[str, Any]],
        file_changes: List[Dict[str, Any]],
        tool_runtime_outcome: Optional[Dict[str, Any]],
    ) -> str:
        return _step_payload_execute_step_summary(
            round_index=round_index,
            final_summary=final_summary,
            model_failed=model_failed,
            tool_gap=tool_gap,
            file_changes=file_changes,
            tool_runtime_outcome=tool_runtime_outcome,
            runtime_status=self._tool_runtime_status(tool_runtime_outcome),
        )

    def _execute_step_result_status(
        self,
        *,
        completed: bool,
        tool_gap: Optional[Dict[str, Any]],
        tool_runtime_outcome: Optional[Dict[str, Any]],
        model_failed: bool,
    ) -> str:
        return _step_payload_execute_step_result_status(
            completed=completed,
            tool_gap=tool_gap,
            model_failed=model_failed,
            runtime_status=self._tool_runtime_status(tool_runtime_outcome),
        )

    def _check_step_result_status(self, check_payload: Dict[str, Any]) -> str:
        return _step_payload_check_step_result_status(check_payload)

    def _request_with_inferred_target_path(
        self, request: FileTaskRequest
    ) -> FileTaskRequest:
        aliased_target = _targeting_target_path_with_file_alias(
            request, request.target_path
        )
        if aliased_target and aliased_target != str(request.target_path or "").strip():
            request = self._request_with_target_path(request, aliased_target)

        # An answer has no inferred write destination. An explicit new output
        # may supersede an editor's inherited source target; other structured
        # targets remain authoritative.
        if self._explicit_output_mode(request) == "answer":
            return request

        current_target = str(request.target_path or "").strip()
        explicit_output = _targeting_resolve_explicit_output_against_request_target(
            current_target,
            self._explicit_output_path_from_task(
                request.task,
                known_paths=[
                    str(item.path or item.name or "")
                    for item in [*list(request.files or []), request.current_file]
                    if item
                ]
                + [current_target],
            ),
        )
        if explicit_output:
            if not current_target:
                return self._request_with_target_path(request, explicit_output)
            target_normalized = current_target.replace("\\", "/")
            output_normalized = explicit_output.replace("\\", "/")
            binds_output_directory = (
                "/" not in target_normalized
                and "/" in output_normalized
                and Path(target_normalized).name.casefold()
                == Path(output_normalized).name.casefold()
            )
            if (
                self._request_target_points_to_source(request, current_target)
                or binds_output_directory
            ) and not self._same_task_path(current_target, explicit_output):
                return self._request_with_target_path(request, explicit_output)
            return request

        if current_target:
            return request

        inferred = self._explicit_write_target_path_from_task(request.task)
        if not inferred:
            return request
        return self._request_with_target_path(request, inferred)

    def _request_with_target_path(
        self, request: FileTaskRequest, target_path: str
    ) -> FileTaskRequest:
        updated = _targeting_request_with_target_path(request, target_path)
        clean_target = str(updated.target_path or "").strip()
        if not clean_target:
            return updated

        def retarget_file(file_info: FileTaskFile) -> FileTaskFile:
            is_target = self._same_task_path(
                file_info.path or file_info.name, clean_target
            )
            if bool(file_info.target) == is_target:
                return file_info
            return FileTaskFile(
                path=file_info.path,
                name=file_info.name,
                type=file_info.type,
                content=file_info.content,
                target=is_target,
            )

        current_file = updated.current_file
        if current_file is not None:
            current_file = retarget_file(current_file)
        return FileTaskRequest(
            task=updated.task,
            task_id=updated.task_id,
            run_id=updated.run_id,
            session_id=updated.session_id,
            files=[retarget_file(file_info) for file_info in updated.files],
            current_file=current_file,
            selection=updated.selection,
            selection_source=updated.selection_source,
            target_path=updated.target_path,
            model_mode=updated.model_mode,
            model_id=updated.model_id,
            history=list(updated.history),
            options=dict(updated.options),
            routing_decision=updated.routing_decision,
        )

    def _request_target_points_to_source(
        self, request: FileTaskRequest, target_path: str
    ) -> bool:
        return _targeting_request_target_points_to_source(
            request,
            target_path,
            same_path=self._same_task_path,
        )

    def _explicit_output_path_from_task(self, task: str, *, known_paths=()) -> str:
        return _targeting_explicit_output_path_from_task(
            task,
            has_artifact_creation_intent=self._has_artifact_creation_intent,
            known_paths=known_paths,
        )

    @staticmethod
    def _explicit_write_target_path_from_task(task: str) -> str:
        return _targeting_explicit_write_target_path_from_task(task)

    def _protected_source_write_block_message(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        request: FileTaskRequest,
        files: List[FileTaskFile],
    ) -> str:
        return _targeting_protected_source_write_block_message(
            tool_name=tool_name,
            tool_args=tool_args,
            request=request,
            files=files,
            has_source_scoped_write_negation=self._has_source_scoped_write_negation,
            has_artifact_creation_intent=self._has_artifact_creation_intent,
            same_path=self._same_task_path,
        )

    def _same_task_path(self, left: Any, right: Any) -> bool:
        return _targeting_same_task_path(
            left,
            right,
            resolve_task_file_path=self._resolve_task_file_path,
        )

    def _should_skip_uncreated_target_context(
        self, request: FileTaskRequest, file_info: FileTaskFile
    ) -> bool:
        return _targeting_should_skip_uncreated_target_context(
            request,
            file_info,
            same_path=self._same_task_path,
            has_artifact_creation_intent=self._has_artifact_creation_intent,
            resolve_task_file_path=self._resolve_task_file_path,
        )

    def _context_files(self, request: FileTaskRequest) -> List[FileTaskFile]:
        return _targeting_context_files(
            request,
            explicitly_mentioned_files=self._files_explicitly_mentioned_in_task(
                request.task,
                known_paths=[
                    str(item.path or item.name or "")
                    for item in [*list(request.files or []), request.current_file]
                    if item
                ]
                + [str(request.target_path or "")],
            ),
        )

    def _files_explicitly_mentioned_in_task(
        self, task: str, *, known_paths=()
    ) -> List[FileTaskFile]:
        return _targeting_files_explicitly_mentioned_in_task(
            workspace_root=self._resolved_workspace_root(),
            task=task,
            known_paths=known_paths,
        )

    def _resolved_workspace_root(self) -> Optional[Path]:
        return _targeting_resolved_workspace_root(self._workspace_root)

    @staticmethod
    def _task_text_mentions_path(task_text: str, rel_path: str) -> bool:
        return _targeting_task_text_mentions_path(task_text, rel_path)

    def _build_tool_gateway(
        self, request: FileTaskRequest, context_files: List[FileTaskFile]
    ) -> FileTaskToolGateway:
        if self._tool_gateway is not None:
            return self._tool_gateway
        providers = [self._tool_provider] if self._tool_provider is not None else None
        return FileTaskToolGateway(
            context=FileTaskToolContext(
                task_files=[file_info.public_dict() for file_info in context_files],
                workspace_root=str(
                    self._resolved_workspace_root() or self._workspace_root
                ),
                request_context={
                    "task": request.task,
                    "run_id": request.run_id,
                    "target_path": request.target_path,
                    "options": (
                        dict(request.options)
                        if isinstance(request.options, dict)
                        else {}
                    ),
                    "model_mode": request.model_mode,
                    "model_id": request.model_id,
                },
            ),
            providers=providers,
            tool_executor=self._tool_executor,
        )

    def _tool_defs_for_classification(
        self,
        tool_defs: List[Dict[str, Any]],
        classification: FileTaskClassification,
    ) -> List[Dict[str, Any]]:
        # Semantic tool selection belongs to KernelRuntime.  This boundary
        # only receives tools already admitted by the capability and
        # write-safety gateways, so it must not narrow them by a recipe or
        # keyword-derived task family.
        return list(tool_defs)

    def _run_builtin_tool(
        self,
        ledger: FileTaskLedger,
        executor: ToolExecutor,
        *,
        step_id: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        file_changes: List[Dict[str, Any]],
    ) -> tuple[Dict[str, Any], List[FileTaskEvent]]:
        return _builtin_tool_runner_run_builtin_tool(
            ledger,
            executor,
            step_id=step_id,
            tool_name=tool_name,
            tool_args=tool_args,
            file_changes=file_changes,
            extract_file_changes=self._extract_file_changes,
        )

    def _request_has_file_type(self, request: FileTaskRequest, file_type: str) -> bool:
        return request_has_file_type(request, file_type)

    def _consume_streaming_tool_result(
        self,
        ledger: FileTaskLedger,
        *,
        step_id: str,
        stream_result: FileTaskToolStreamResult,
    ) -> Iterable[FileTaskEvent | Any]:
        final_result: Any = None
        for chunk in stream_result.chunks:
            if not isinstance(chunk, FileTaskToolStreamChunk):
                continue
            if str(chunk.kind or "").strip().lower() == "event":
                event_type = str(chunk.event_type or "").strip()
                if not event_type:
                    continue
                payload = dict(chunk.payload) if isinstance(chunk.payload, dict) else {}
                yield ledger.event(event_type, payload, step_id=step_id)
                continue
            if str(chunk.kind or "").strip().lower() == "result":
                final_result = chunk.payload
        return final_result

    def _has_write_intent(self, task: str) -> bool:
        return _intent_has_write_intent(task)

    def _has_explicit_write_intent(self, task: str) -> bool:
        return _intent_has_explicit_write_intent(task)

    def _has_readonly_write_negation(self, task: str) -> bool:
        return _intent_has_readonly_write_negation(task)

    def _has_global_readonly_write_negation(self, task: str) -> bool:
        return _intent_has_global_readonly_write_negation(task)

    def _has_source_scoped_write_negation(self, task: str) -> bool:
        return _intent_has_source_scoped_write_negation(task)

    def _has_artifact_creation_intent(self, task: str) -> bool:
        return _intent_has_artifact_creation_intent(task)

    def _explicit_output_mode(self, request: FileTaskRequest) -> str:
        return _intent_explicit_output_mode(request)

    def _quick_action_mode(self, request: FileTaskRequest) -> str:
        return _intent_quick_action_mode(request)
