# =============================================================================
# Koto File Task Runtime — Public API Index
# =============================================================================
# Lines: 3421 (guarded) | 1 class (FileTaskRuntime) | ~140 private methods
#
# PUBLIC API:
#   request_cancel(run_id) .... Register cancellation for a running task
#   is_cancel_requested(run_id). Check if cancellation was requested
#   FileTaskRuntime .......... Main orchestrator for file-based AI tasks
#     .run(request) .......... Execute a file task end-to-end
#
# INTERNAL STRUCTURE (FileTaskRuntime private methods):
#   Classification ... _classify_request, _infer_output_mode, _quick_action_mode
#   Intent ............ _adjudicate_intent_if_needed, _apply_intent_adjudication
#   Planning .......... _build_plan, _resolve_intent_plan, _fallback_intent_plan
#   Execution ......... _run_builtin_tool, _consume_streaming_tool_result
#   Quality ........... _evaluate_task_quality_gate, _verify_task
#   Stepwise .......... _stepwise_docx_*, _write_stepwise_pdf_docx_native
#   Readonly .......... _readonly_answer_required_message, _readonly_tool_*
#   Heuristics ........ _looks_like_chart_request, _looks_like_ppt_request, ...
#   Sandbox ........... (delegated to task_tools.py helpers)
# =============================================================================
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskExecutionContext,
    FileTaskExecutionBrief,
    FileTaskEvent,
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskLedger,
    FileTaskRequirementSet,
    FileTaskRequest,
    FileTaskToolStreamChunk,
    FileTaskToolStreamResult,
)
from app.core.agent.file_task_intent_planner import FileTaskIntentPlanner
from app.core.agent._file_task_stepwise_helpers import (
    file_task_suffix as _file_task_suffix,
    looks_like_windowed_pdf_task as _looks_like_windowed_pdf_task,
    native_stepwise_pdf_text_quality_guard_payload as _native_stepwise_pdf_text_quality_guard_payload,
    normalized_pdf_body as _normalized_pdf_body,
    pdf_context_read_args as _pdf_context_read_args,
    pdf_text_quality as _pdf_text_quality,
    should_force_pdf_tool_read as _should_force_pdf_tool_read,
    stepwise_docx_content_quality_block_message as _stepwise_docx_content_quality_block_message,
    stepwise_docx_target_path as _stepwise_docx_target_path,
    stepwise_docx_wait_artifact as _stepwise_docx_wait_artifact,
    stepwise_docx_write_block_message as _stepwise_docx_write_block_message,
    stepwise_pdf_fallback_insights as _stepwise_pdf_fallback_insights,
    stepwise_pdf_fallback_paragraphs as _stepwise_pdf_fallback_paragraphs,
    stepwise_pdf_step_index as _stepwise_pdf_step_index,
    stepwise_pdf_window_pages as _stepwise_pdf_window_pages,
)
from app.core.agent.file_task_capability import (
    build_request_capability_profiles,
    native_tool_gap_for_request,
)
from app.core.agent.file_task_classification import (
    adjudicate_intent_if_needed as _intent_adjudicator_adjudicate_if_needed,
    apply_classification_intent_overrides,
    apply_followup_annotation_overrides,
    apply_intent_adjudication as _classification_contract_apply_intent_adjudication,
    apply_recipe_classification,
    apply_write_intent_reason_codes,
    build_classification_pipeline_state,
    build_classification_reason_codes,
    build_decision_context_payload,
    build_final_classification,
    build_intent_adjudication_contract_context,
    build_mainline_contract_context,
    classification_task_text as _intent_adjudication_classification_task_text,
    demote_classification_to_read as _classification_contract_demote_to_read,
    infer_task_family_operation as _classification_semantics_infer_task_family_operation,
    intent_adjudicator_system_prompt as _intent_adjudication_system_prompt,
    normalize_mainline_contract as _classification_contract_normalize_mainline,
    request_with_task as _intent_adjudication_request_with_task,
    routing_decision_payload as _decision_context_routing_decision_payload,
    should_adjudicate_intent as _intent_adjudication_should_adjudicate_intent,
)
from app.core.agent.file_task_completion_contract import build_completion_contract
from app.core.agent.file_task_doc_annotate_request import (
    docx_annotation_contract_for_request as _doc_annotate_contract_for_request,
    docx_annotation_has_request_contract as _doc_annotate_has_request_contract,
    is_docx_annotation_request as _doc_annotate_is_annotation_request,
    is_docx_clear_review_request as _doc_annotate_is_clear_review_request,
)
from app.core.agent.file_task_docx_edit_guard import (
    local_docx_edit_block_message as _docx_edit_local_block_message,
    tool_args_docx_paragraph_count as _docx_edit_paragraph_count,
)
from app.core.agent.file_task_guard_emission import build_tool_guard_emission
from app.core.agent.file_task_model import FileTaskModelClient
from app.core.agent.file_task_review_intent import (
    request_has_file_type,
)
from app.core.agent.file_task_runtime_patterns import (
    _DOCX_ANNOTATE_INTENT_WORDS,
    _MAX_MODEL_ROUNDS,
    _READ_LIMIT,
    _RUN_PYTHON_ARTIFACT_WRITE_PATTERNS,
    _RUN_PYTHON_STRONG_WRITE_PATTERNS,
)
from app.core.agent.file_task_recipes import (
    select_task_recipe,
)
from app.core.agent.file_task_validation import (
    build_file_task_requirements,
    validate_file_task_plan,
)
from app.core.agent.file_task_whitebox import (
    WhiteboxExecutionPlan,
    build_decision_audit,
    build_recipe_skeleton,
    extract_whitebox_execution_plan,
    validate_whitebox_plan,
)
from app.core.agent.file_task_cancel import (
    is_cancel_requested as _is_cancel_requested,
    request_cancel as _request_cancel,
)
from app.core.agent.file_task_runtime_utils import (
    _compact_line,
    _is_error_result,
    _json_payload,
    _preview,
)
from app.core.agent.file_task_plan_presentation import (
    tool_plan_description as _plan_presentation_description,
    tool_plan_title as _plan_presentation_title,
)
from app.core.agent.file_task_execution_loop import FileTaskExecutionLoop
from app.core.agent.file_task_finalization import FileTaskFinalizationPhase
from app.core.agent.file_task_context_read import FileTaskContextReadPhase
from app.core.agent.file_task_planning import FileTaskPlanningPhase
from app.core.agent.file_task_targeting import (
    context_files as _targeting_context_files,
    explicit_output_path_from_task as _targeting_explicit_output_path_from_task,
    explicit_write_target_path_from_task as _targeting_explicit_write_target_path_from_task,
    files_explicitly_mentioned_in_task as _targeting_files_explicitly_mentioned_in_task,
    protected_source_write_block_message as _targeting_protected_source_write_block_message,
    request_target_points_to_source as _targeting_request_target_points_to_source,
    request_with_target_path as _targeting_request_with_target_path,
    resolved_workspace_root as _targeting_resolved_workspace_root,
    same_task_path as _targeting_same_task_path,
    should_skip_uncreated_target_context as _targeting_should_skip_uncreated_target_context,
    target_path_with_file_alias as _targeting_target_path_with_file_alias,
    task_text_mentions_path as _targeting_task_text_mentions_path,
)
from app.core.agent.file_task_intent_predicates import (
    explicit_output_mode as _intent_explicit_output_mode,
    has_artifact_creation_intent as _intent_has_artifact_creation_intent,
    has_explicit_write_intent as _intent_has_explicit_write_intent,
    has_global_readonly_write_negation as _intent_has_global_readonly_write_negation,
    has_readonly_write_negation as _intent_has_readonly_write_negation,
    has_source_scoped_write_negation as _intent_has_source_scoped_write_negation,
    has_strong_write_intent as _intent_has_strong_write_intent,
    has_target_context as _intent_has_target_context,
    has_write_intent as _intent_has_write_intent,
    infer_output_mode as _intent_infer_output_mode,
    is_advisory_analysis_request as _intent_is_advisory_analysis_request,
    is_diagnostic_request as _intent_is_diagnostic_request,
    quick_action_mode as _intent_quick_action_mode,
)
from app.core.agent.file_task_readonly_summary import (
    fallback_readonly_summary as _readonly_fallback_summary,
    readonly_answer_required_message as _readonly_answer_required_message,
    readonly_context_source_lines as _readonly_context_source_lines,
    readonly_context_summary as _readonly_context_summary,
    readonly_tool_points as _readonly_tool_points,
    readonly_tool_source_label as _readonly_tool_source_label,
)
from app.core.agent.file_task_readonly_loop_guard import (
    READONLY_ANSWER_GUARD_PENDING_SUMMARY,
    READONLY_DUPLICATE_GUARD_SUMMARY,
    WRITE_DUPLICATE_STOP_SUMMARY,
    WRITE_DUPLICATE_SUPERVISOR_SUMMARY,
    answer_only_round as _readonly_answer_only_round,
    discard_answer_only_tool_calls as _readonly_discard_answer_only_tool_calls,
    duplicate_guard_tool_payload as _readonly_duplicate_guard_tool_payload,
    readonly_duplicate_final_summary as _readonly_duplicate_final_summary,
    readonly_duplicate_guard_reminder as _readonly_duplicate_guard_reminder,
    should_retry_readonly_answer_guard as _readonly_should_retry_answer_guard,
    should_retry_readonly_duplicate_guard as _readonly_should_retry_duplicate_guard,
    should_retry_write_duplicate_guard as _readonly_should_retry_write_duplicate_guard,
    supervisor_guard_tool_payload as _readonly_supervisor_guard_tool_payload,
)
from app.core.agent.file_task_quality_gate import (
    change_operations as _quality_change_operations,
    change_sum_int as _quality_change_sum_int,
    evaluate_task_quality_gate as _quality_evaluate_task_quality_gate,
    quality_gate_result as _quality_gate_result,
    repair_retry_message as _quality_repair_retry_message,
    should_attempt_repair as _quality_should_attempt_repair,
    success_criteria as _quality_success_criteria,
    target_or_request_type as _quality_target_or_request_type,
)
from app.core.agent.file_task_verification import (
    verification_precheck as _verification_precheck,
)
from app.core.agent.task_supervisor import TaskSupervisor, SupervisionResult
from app.core.agent.file_task_supervisor_prompts import (
    blocked_run_python_message as _supervisor_blocked_run_python_message,
    duplicate_supervisor_retry_message as _supervisor_duplicate_retry_message,
    file_types as _supervisor_file_types,
    looks_like_chart_request as _supervisor_looks_like_chart_request,
    looks_like_docx_report_request as _supervisor_looks_like_docx_report_request,
    looks_like_financial_request as _supervisor_looks_like_financial_request,
    looks_like_financial_xlsx_docx_chart_report_task as _supervisor_looks_like_financial_report_task,
    looks_like_pdf_python_text_read as _supervisor_looks_like_pdf_python_text_read,
    looks_like_polish_request as _supervisor_looks_like_polish_request,
    looks_like_ppt_request as _supervisor_looks_like_ppt_request,
    looks_like_ppt_slide_write_request as _supervisor_looks_like_ppt_slide_write_request,
    looks_like_problem_analysis_request as _supervisor_looks_like_problem_analysis_request,
    looks_like_summary_request as _supervisor_looks_like_summary_request,
    looks_like_table_request as _supervisor_looks_like_table_request,
    looks_like_translation_request as _supervisor_looks_like_translation_request,
    should_prompt_for_write_after_tool_round as _supervisor_should_prompt_for_write_after_tool_round,
    write_retry_message as _supervisor_write_retry_message,
)
from app.core.agent.file_task_message_payload import build_file_task_runtime_messages
from app.core.agent.file_task_followup_context import (
    followup_context as _build_followup_context,
)
from app.core.agent.file_task_system_prompt_builder import (
    build_file_task_runtime_system_prompt,
)
from app.core.agent.file_task_terminal_report import (
    apply_terminal_check_overrides,
    build_terminal_run_summary,
    terminal_completed_task,
)
from app.core.agent.file_task_execution_brief import (
    execution_brief_schema as _brief_execution_brief_schema,
    extract_execution_brief as _brief_extract_execution_brief,
    looks_like_brief_only_content as _brief_looks_like_brief_only_content,
    normalize_execution_brief as _brief_normalize_execution_brief,
)
from app.core.agent.file_task_model_response import (
    coerce_tool_calls as _model_response_coerce_tool_calls,
    normalize_model_response as _model_response_normalize_model_response,
    tool_batch_signature as _model_response_tool_batch_signature,
)
from app.core.agent.file_task_step_payload import (
    build_runtime_metadata as _step_payload_build_runtime_metadata,
    build_step_result_payload as _step_payload_build_step_result_payload,
    check_step_result_status as _step_payload_check_step_result_status,
    execute_step_result_status as _step_payload_execute_step_result_status,
    execute_step_summary as _step_payload_execute_step_summary,
    public_context_snippets as _step_payload_public_context_snippets,
    step_result_file_changes as _step_payload_step_result_file_changes,
    with_runtime_context as _step_payload_with_runtime_context,
)
from app.core.agent.file_task_step_verification import (
    build_supervisor_step_verification_payload as _build_supervisor_step_verification_payload,
)
from app.core.agent.file_task_builtin_tool_runner import (
    run_builtin_tool as _builtin_tool_runner_run_builtin_tool,
)
from app.core.agent.file_task_workflow_state import (
    attach_workflow_checkpoint,
    build_workflow_state,
    request_with_workflow_checkpoint,
    supervisor_status_payload,
    workflow_resume_control,
    window_read_args_for_file,
)
from app.core.agent.file_task_supervisor_audit import (
    build_supervisor_audit,
)
from app.core.agent.file_task_result_markers import (
    KOTO_CREATED_RESULT_MARKER,
    KOTO_MODIFIED_RESULT_MARKER,
)
from app.core.agent.file_task_tool_catalog import (
    extract_koto_paths,
    file_states_for_changes,
    is_file_task_tool,
    is_write_tool,
    supported_file_workflows,
    tool_result_preview,
    stringify_result,
    write_target_for_tool,
)
from app.core.agent.file_task_tool_feedback import (
    code_output_preview as _feedback_code_output_preview,
    extract_file_changes as _feedback_extract_file_changes,
    extract_tool_runtime_outcome as _feedback_extract_tool_runtime_outcome,
    readonly_run_python_write_block_message as _feedback_readonly_run_python_write_block_message,
    readonly_write_tool_block_message as _feedback_readonly_write_tool_block_message,
    tool_artifacts as _feedback_tool_artifacts,
    tool_feedback_for_model as _feedback_tool_feedback_for_model,
    tool_result_for_model as _feedback_tool_result_for_model,
    tool_runtime_status as _feedback_tool_runtime_status,
    truncate_tool_feedback_value as _feedback_truncate_tool_feedback_value,
)
from app.core.agent.file_task_tool_gateway import (
    FileTaskToolContext,
    FileTaskToolGateway,
    FileTaskToolProvider,
    ToolExecutor,
)
from app.core.agent.tool_design_protocol import (
    TOOL_DESIGN_PROTOCOL,
    build_next_action_artifact,
    extract_first_json_value,
    extract_tool_gap_from_response,
    merge_tool_gaps,
)
logger = logging.getLogger(__name__)

ModelCaller = Callable[..., Dict[str, Any]]

def request_cancel(run_id: str) -> bool:
    return _request_cancel(run_id)


def is_cancel_requested(run_id: str) -> bool:
    return _is_cancel_requested(run_id)


_MAX_VERIFY_REPAIR_ATTEMPTS = 2
_MAX_WRITE_OPS_PER_FILE = 1
_IMAGE_ARTIFACT_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "bmp", "gif"}


class FileTaskRuntime:
    """First Koto-native whitebox runtime for file-assistant complex tasks.

    Typed file-task runtime with an allowlisted model -> tool -> checker loop.

    The model can plan and call tools freely, but only through the Koto-native
    tool catalog. The runtime owns event logging, duplicate-write guards, file
    change detection, and final verification.
    """

    def __init__(
        self,
        *,
        tool_executor: Optional[ToolExecutor] = None,
        tool_provider: Optional[FileTaskToolProvider] = None,
        tool_gateway: Optional[FileTaskToolGateway] = None,
        model_client: Optional[FileTaskModelClient | ModelCaller] = None,
        intent_planner: Optional[FileTaskIntentPlanner] = None,
        gemini_client: Any = None,
        workspace_root: str = "",
        task_supervisor: Optional[TaskSupervisor] = None,
        yield_thinking: Any = None,
        max_rounds: int = _MAX_MODEL_ROUNDS,
    ):
        self._tool_executor = tool_executor
        self._tool_provider = tool_provider
        self._tool_gateway = tool_gateway
        self._model_client = model_client or FileTaskModelClient()
        self._intent_planner = intent_planner or FileTaskIntentPlanner()
        self._gemini_client = gemini_client
        self._workspace_root = workspace_root
        self._max_rounds = max(1, int(max_rounds or _MAX_MODEL_ROUNDS))
        self._task_supervisor = task_supervisor
        self._yield_thinking = yield_thinking


# ═══════════════════════════════════════════════════════════════
    # Main Entry Point
    # ═══════════════════════════════════════════════════════════════
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
            snapshot["elapsed_ms"] = round((time.perf_counter() - run_started_at) * 1000, 2)
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
        requirements = plan_result.requirements
        plan_check = plan_result.plan_check
        quick_action_mode = plan_result.quick_action_mode
        simple_quick_action = plan_result.simple_quick_action
        write_intent = plan_result.write_intent
        bridge_execution_mode = plan_result.bridge_execution_mode
        tool_defs = plan_result.tool_defs
        executor = plan_result.executor
        recipe_skeleton = plan_result.recipe_skeleton
        completion_contract_payload = plan_result.completion_contract_payload
        completion_criteria = plan_result.completion_criteria
        workflow_state = plan_result.workflow_state
        constraint_audit = plan_result.constraint_audit
        supervisor_audit_payload = plan_result.supervisor_audit_payload
        classification_payload = plan_result.classification_payload
        intent_plan_payload = plan_result.intent_plan_payload
        requirements_payload = plan_result.requirements_payload
        plan_check_payload = plan_result.plan_check_payload
        decision_context_payload = plan_result.decision_context_payload

        if bridge_execution_mode:
            yield from self._stream_doc_annotate_bridge_execution(
                ledger,
                request,
                classification_payload=classification_payload,
                intent_plan_payload=intent_plan_payload,
                requirements_payload=requirements_payload,
                plan_check_payload=plan_check_payload,
                recipe_skeleton=recipe_skeleton,
                completion_contract_payload=completion_contract_payload,
                workflow_state=workflow_state,
                constraint_audit=constraint_audit,
                quick_action_mode=quick_action_mode,
            )
            return

        if (
            str(classification.selected_recipe or "").strip()
            == "long_docx_stepwise_polish_writeback"
            or str(classification.execution_mode or "").strip()
            == "long_docx_stepwise_polish_writeback"
        ):
            yield from self._stream_long_docx_stepwise_polish_writeback(
                ledger,
                request,
                context_files,
                classification,
                intent_plan,
                requirements_payload,
                plan_check_payload,
                recipe_skeleton,
                constraint_audit,
                quick_action_mode,
                classification_payload,
                intent_plan_payload,
            )
            return

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

        execution_result = yield from FileTaskExecutionLoop(self).stream(
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
            workflow_state=workflow_state,
            completion_criteria=completion_criteria,
            write_intent=write_intent,
            executor=executor,
            max_verify_repair_attempts=_MAX_VERIFY_REPAIR_ATTEMPTS,
            max_write_ops_per_file=_MAX_WRITE_OPS_PER_FILE,
        )
        if execution_result.cancelled:
            return
        execute_step_id = execution_result.execute_step_id
        file_changes = execution_result.file_changes
        final_summary = execution_result.final_summary
        completed_task = execution_result.completed_task
        model_failed = execution_result.model_failed
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
            write_intent=write_intent,
            quick_action_mode=quick_action_mode,
            file_changes=file_changes,
            final_summary=final_summary,
            completed_task=completed_task,
            model_failed=model_failed,
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
    ) -> Dict[str, Any]:
        return _step_payload_build_runtime_metadata(
            terminal_status=terminal_status,
            readonly_fallback_used=readonly_fallback_used,
            model_failed=model_failed,
            planner_payload=planner_payload,
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

        explicit_output = self._explicit_output_path_from_task(request.task)
        if explicit_output:
            current_target = str(request.target_path or "").strip()
            if not current_target or not self._same_task_path(current_target, explicit_output):
                return self._request_with_target_path(request, explicit_output)
            return request

        inferred = self._explicit_write_target_path_from_task(request.task)
        if not inferred:
            return request
        current_target = str(request.target_path or "").strip()
        if current_target:
            if self._same_task_path(current_target, inferred):
                return request
            if not (
                self._has_source_scoped_write_negation(request.task)
                and self._request_target_points_to_source(request, current_target)
            ):
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
            is_target = self._same_task_path(file_info.path or file_info.name, clean_target)
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

    def _explicit_output_path_from_task(self, task: str) -> str:
        return _targeting_explicit_output_path_from_task(
            task,
            has_artifact_creation_intent=self._has_artifact_creation_intent,
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


# ═══════════════════════════════════════════════════════════════
    # File Context & Targeting
    # ═══════════════════════════════════════════════════════════════
    def _context_files(self, request: FileTaskRequest) -> List[FileTaskFile]:
        return _targeting_context_files(
            request,
            explicitly_mentioned_files=self._files_explicitly_mentioned_in_task(
                request.task
            ),
        )

    def _files_explicitly_mentioned_in_task(self, task: str) -> List[FileTaskFile]:
        return _targeting_files_explicitly_mentioned_in_task(
            workspace_root=self._resolved_workspace_root(),
            task=task,
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
                workspace_root=str(self._resolved_workspace_root() or self._workspace_root),
                gemini_client=self._gemini_client,
                request_context={
                    "task": request.task,
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
        selected_recipe = str(classification.selected_recipe or "").strip()
        if selected_recipe not in {
            "docx_compare_annotation",
            "docx_contract_compare_review",
        }:
            return tool_defs
        allowed = {
            "parse_file_to_text",
            "verify_task_completion",
            *[
                str(name or "").strip()
                for name in classification.matched_capabilities
                if str(name or "").strip()
            ],
        }
        forbidden = {"annotate_file"}
        return [
            definition
            for definition in tool_defs
            if str(definition.get("name") or "").strip() in allowed
            and str(definition.get("name") or "").strip() not in forbidden
        ]

    def _recipe_tool_block_message(
        self,
        tool_name: str,
        classification: FileTaskClassification,
        exposed_tool_names: set[str],
    ) -> str:
        selected_recipe = str(classification.selected_recipe or "").strip()
        allowed_text = ", ".join(sorted(exposed_tool_names)) or "当前路线工具集"
        if selected_recipe in {
            "docx_compare_annotation",
            "docx_contract_compare_review",
        }:
            return (
                f"工具 {tool_name} 不属于当前 DOCX 对比批注路线。"
                "这是两份 DOCX 的差异比较任务，不是单文档审校；"
                "请使用 plan_docx_compare_annotations 定位差异，"
                "再使用 write_docx_comments 写入目标 DOCX 原文批注。"
                f" 当前允许工具：{allowed_text}。"
            )
        return (
            f"工具 {tool_name} 不属于当前任务路线 {selected_recipe or '未命名路线'}。"
            f" 当前允许工具：{allowed_text}。"
        )

    def _stream_doc_annotate_bridge_execution(
        self,
        ledger: FileTaskLedger,
        request: FileTaskRequest,
        *,
        classification_payload: Dict[str, Any],
        intent_plan_payload: Dict[str, Any],
        requirements_payload: Dict[str, Any],
        plan_check_payload: Dict[str, Any],
        recipe_skeleton: Dict[str, Any],
        completion_contract_payload: Dict[str, Any],
        workflow_state: Dict[str, Any],
        constraint_audit: Dict[str, Any],
        quick_action_mode: str,
    ) -> Iterable[FileTaskEvent]:
        from app.core.agent.file_task_doc_annotate_runner import FileTaskDocAnnotateRunner

        yield from FileTaskDocAnnotateRunner(self).stream_bridge_execution(
            ledger,
            request,
            classification_payload=classification_payload,
            intent_plan_payload=intent_plan_payload,
            requirements_payload=requirements_payload,
            plan_check_payload=plan_check_payload,
            recipe_skeleton=recipe_skeleton,
            completion_contract_payload=completion_contract_payload,
            workflow_state=workflow_state,
            constraint_audit=constraint_audit,
            quick_action_mode=quick_action_mode,
        )

    def _stream_long_docx_stepwise_polish_writeback(
        self,
        ledger: FileTaskLedger,
        request: FileTaskRequest,
        context_files: List[FileTaskFile],
        classification: FileTaskClassification,
        intent_plan: FileTaskIntentPlan,
        requirements_payload: Dict[str, Any],
        plan_check_payload: Dict[str, Any],
        recipe_skeleton: Dict[str, Any],
        constraint_audit: Dict[str, Any],
        quick_action_mode: str,
        classification_payload: Dict[str, Any],
        intent_plan_payload: Dict[str, Any],
    ) -> Iterable[FileTaskEvent]:
        from app.core.agent.file_task_docx_stepwise_runner import FileTaskDocxStepwiseRunner

        yield from FileTaskDocxStepwiseRunner(self).stream_polish_writeback(
            ledger,
            request,
            context_files,
            classification,
            intent_plan,
            requirements_payload,
            plan_check_payload,
            recipe_skeleton,
            constraint_audit,
            quick_action_mode,
            classification_payload,
            intent_plan_payload,
        )

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


# ═══════════════════════════════════════════════════════════════
    # Intent Predicates (delegated to file_task_intent_predicates)
    # ═══════════════════════════════════════════════════════════════
    def _has_write_intent(self, task: str) -> bool:
        return _intent_has_write_intent(task)

    def _has_strong_write_intent(self, task: str) -> bool:
        return _intent_has_strong_write_intent(task)

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

    def _is_advisory_analysis_request(self, task: str) -> bool:
        return _intent_is_advisory_analysis_request(task)

    def _is_diagnostic_request(self, task: str) -> bool:
        return _intent_is_diagnostic_request(task)

    def _explicit_output_mode(self, request: FileTaskRequest) -> str:
        return _intent_explicit_output_mode(request)

    def _has_target_context(
        self, request: FileTaskRequest, files: List[FileTaskFile]
    ) -> bool:
        return _intent_has_target_context(request, files)

    def _infer_output_mode(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        *,
        write_intent: bool,
        diagnostic_request: bool,
        docx_annotation_request: bool,
        advisory_analysis_request: bool,
    ) -> str:
        return _intent_infer_output_mode(
            request,
            files,
            write_intent=write_intent,
            diagnostic_request=diagnostic_request,
            docx_annotation_request=docx_annotation_request,
            advisory_analysis_request=advisory_analysis_request,
        )

    def _quick_action_mode(self, request: FileTaskRequest) -> str:
        return _intent_quick_action_mode(request)

    def _classify_request(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        known_tool_gap: Optional[Dict[str, Any]] = None,
    ) -> FileTaskClassification:
        options = request.options if isinstance(request.options, dict) else {}
        followup_context = self._followup_context(request)
        resume_control = workflow_resume_control(request)
        classification_task = self._classification_task_text(request, resume_control)
        classification_request = self._request_with_task(request, classification_task)
        planner_policy, planner_reason, planner_backend = self._planner_classification(
            request
        )
        classification_state = build_classification_pipeline_state(
            classification_task=classification_task,
            classification_request=classification_request,
            files=files,
            followup_context=followup_context,
            resume_control=resume_control,
            planner_policy=planner_policy,
            planner_reason=planner_reason,
            planner_backend=planner_backend,
            is_docx_annotation_request=_doc_annotate_is_annotation_request,
            is_docx_clear_review_request=_doc_annotate_is_clear_review_request,
            is_diagnostic_request=self._is_diagnostic_request,
        )
        classification_signals = classification_state.signals
        classification_flow = classification_state.flow
        matched_capabilities = classification_signals.matched_capabilities
        advisory_analysis_request = classification_signals.advisory_analysis_request
        readonly_write_negation = classification_signals.readonly_write_negation
        raw_write_intent = classification_signals.raw_write_intent
        write_intent = classification_signals.write_intent
        raw_docx_annotation_request = (
            classification_signals.raw_docx_annotation_request
        )
        docx_annotation_request = classification_signals.docx_annotation_request
        clear_docx_review_request = classification_signals.clear_docx_review_request
        docx_compare_annotate_request = (
            classification_signals.docx_compare_annotate_request
        )
        chart_request = classification_signals.chart_request
        table_request = classification_signals.table_request
        summary_request = classification_signals.summary_request
        translation_request = classification_signals.translation_request
        polish_request = classification_signals.polish_request
        financial_request = classification_signals.financial_request
        ppt_slide_write_request = classification_signals.ppt_slide_write_request
        ppt_design_request = classification_signals.ppt_design_request
        docx_report_request = classification_signals.docx_report_request
        diagnostic_request = classification_state.diagnostic_request
        request_kind = classification_flow.request_kind
        execution_mode = classification_flow.execution_mode
        reason_codes: List[str] = [
            *classification_flow.reason_codes,
            *classification_signals.reason_codes,
        ]
        stepwise_pdf_docx_resume = classification_flow.stepwise_pdf_docx_resume
        followup_action = classification_flow.followup_action
        previous_task_family = classification_flow.previous_task_family
        previous_task_execution_mode = classification_flow.previous_task_execution_mode
        previous_task_output_mode = classification_flow.previous_task_output_mode
        previous_task_intent_can_apply = (
            classification_flow.previous_task_intent_can_apply
        )
        resume_adapter = classification_flow.resume_adapter
        override_flags = apply_classification_intent_overrides(
            request_kind=request_kind,
            followup_action=followup_action,
            summary_request=summary_request,
            docx_report_request=docx_report_request,
            write_intent=write_intent,
            raw_write_intent=raw_write_intent,
            diagnostic_request=diagnostic_request,
            readonly_write_negation=readonly_write_negation,
            clear_docx_review_request=clear_docx_review_request,
            docx_compare_annotate_request=docx_compare_annotate_request,
            docx_annotation_request=docx_annotation_request,
            raw_docx_annotation_request=raw_docx_annotation_request,
            explicit_output_mode=self._explicit_output_mode(request),
            artifact_creation_intent=self._has_artifact_creation_intent(
                classification_task
            ),
            explicit_write_intent=self._has_explicit_write_intent(
                classification_task
            ),
            strong_write_intent=self._has_strong_write_intent(classification_task),
            force_long_pdf_docx_write=classification_flow.force_long_pdf_docx_write,
            stepwise_pdf_docx_resume=stepwise_pdf_docx_resume,
            reason_codes=reason_codes,
        )
        summary_request = override_flags.summary_request
        docx_report_request = override_flags.docx_report_request
        write_intent = override_flags.write_intent
        raw_write_intent = override_flags.raw_write_intent
        diagnostic_request = override_flags.diagnostic_request
        docx_annotation_request = override_flags.docx_annotation_request
        raw_docx_annotation_request = override_flags.raw_docx_annotation_request
        reason_codes = override_flags.reason_codes

        followup_annotation = apply_followup_annotation_overrides(
            classification_request=classification_request,
            request_kind=request_kind,
            followup_action=followup_action,
            previous_task_family=previous_task_family,
            previous_task_execution_mode=previous_task_execution_mode,
            previous_task_output_mode=previous_task_output_mode,
            previous_task_intent_can_apply=previous_task_intent_can_apply,
            resume_adapter=resume_adapter,
            docx_annotation_request=docx_annotation_request,
            write_intent=write_intent,
            execution_mode=execution_mode,
            reason_codes=reason_codes,
        )
        docx_annotation_request = followup_annotation.docx_annotation_request
        write_intent = followup_annotation.write_intent
        execution_mode = followup_annotation.execution_mode
        reason_codes = followup_annotation.reason_codes

        write_intent_reasons = apply_write_intent_reason_codes(
            write_intent=write_intent,
            explicit_output_mode=str(options.get("output_mode") or ""),
            diagnostic_request=diagnostic_request,
            reason_codes=reason_codes,
        )
        reason_codes = write_intent_reasons.reason_codes

        recipe_classification = apply_recipe_classification(
            classification_request=classification_request,
            classification_task=classification_task,
            files=files,
            write_intent=write_intent,
            stepwise_pdf_docx_resume=stepwise_pdf_docx_resume,
            matched_capabilities=matched_capabilities,
            execution_mode=execution_mode,
            reason_codes=reason_codes,
        )
        recipe_candidates = recipe_classification.candidates
        selected_recipe_match = recipe_classification.selected
        matched_capabilities = recipe_classification.matched_capabilities
        execution_mode = recipe_classification.execution_mode
        reason_codes = recipe_classification.reason_codes

        classification_reasons = build_classification_reason_codes(
            reason_codes=reason_codes,
            planner_policy=planner_policy,
            planner_reason=planner_reason,
            planner_backend=planner_backend,
            known_tool_gap=known_tool_gap,
            matched_capabilities=matched_capabilities,
            chart_request=chart_request,
            table_request=table_request,
            summary_request=summary_request,
            translation_request=translation_request,
            polish_request=polish_request,
            financial_request=financial_request,
            ppt_slide_write_request=ppt_slide_write_request,
            ppt_design_request=ppt_design_request,
            docx_report_request=docx_report_request,
        )
        reason_codes = classification_reasons.reason_codes
        known_gap_name = classification_reasons.known_gap_name

        (
            task_family,
            operation_kind,
            docx_annotation_request,
            matched_capabilities,
            execution_mode,
        ) = _classification_semantics_infer_task_family_operation(
            diagnostic_request=diagnostic_request,
            clear_docx_review_request=clear_docx_review_request,
            selected_recipe_match=selected_recipe_match,
            docx_compare_annotate_request=docx_compare_annotate_request,
            docx_annotation_request=docx_annotation_request,
            financial_request=financial_request,
            chart_request=chart_request,
            docx_report_request=docx_report_request,
            ppt_slide_write_request=ppt_slide_write_request,
            translation_request=translation_request,
            polish_request=polish_request,
            problem_analysis_request=self._looks_like_problem_analysis_request(
                classification_task
            ),
            summary_request=summary_request,
            table_request=table_request,
            write_intent=write_intent,
            matched_capabilities=matched_capabilities,
            execution_mode=execution_mode,
        )

        return build_final_classification(
            request=request,
            files=files,
            output_mode_resolver=lambda resolved_request, resolved_files: self._infer_output_mode(
                resolved_request,
                list(resolved_files),
                write_intent=write_intent,
                diagnostic_request=diagnostic_request,
                docx_annotation_request=docx_annotation_request,
                advisory_analysis_request=advisory_analysis_request,
            ),
            request_kind=request_kind,
            task_family=task_family,
            operation_kind=operation_kind,
            execution_mode=execution_mode,
            write_intent=write_intent,
            diagnostic_request=diagnostic_request,
            docx_annotation_request=docx_annotation_request,
            advisory_analysis_request=advisory_analysis_request,
            readonly_write_negation=readonly_write_negation,
            raw_write_intent=raw_write_intent,
            raw_docx_annotation_request=raw_docx_annotation_request,
            planner_policy=planner_policy,
            planner_reason=planner_reason,
            planner_backend=planner_backend,
            known_gap_name=known_gap_name,
            matched_capabilities=matched_capabilities,
            reason_codes=reason_codes,
            selected_recipe_match=selected_recipe_match,
            recipe_candidates=recipe_candidates,
        )

    def _effective_planner_classification(
        self, request: FileTaskRequest
    ) -> tuple[str, str, str]:
        return self._planner_classification(request)

    def _classification_task_text(
        self, request: FileTaskRequest, resume_control: Dict[str, Any]
    ) -> str:
        return _intent_adjudication_classification_task_text(
            request,
            resume_control,
        )

    def _request_with_task(
        self, request: FileTaskRequest, task_text: str
    ) -> FileTaskRequest:
        return _intent_adjudication_request_with_task(
            request,
            task_text,
        )

    def _should_adjudicate_intent(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        classification: FileTaskClassification,
    ) -> bool:
        task_text = str(request.task or "").strip()
        return _intent_adjudication_should_adjudicate_intent(
            request=request,
            classification=classification,
            readonly_write_negation=self._has_readonly_write_negation(task_text),
            explicit_output_mode=self._explicit_output_mode(request),
            has_target_context=self._has_target_context(request, files),
        )

    def _intent_adjudicator_system_prompt(self) -> str:
        return _intent_adjudication_system_prompt()

    def _adjudicate_intent_if_needed(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        classification: FileTaskClassification,
    ) -> Dict[str, Any]:
        return _intent_adjudicator_adjudicate_if_needed(
            request=request,
            files=files,
            classification=classification,
            should_adjudicate=self._should_adjudicate_intent,
            call_model=self._call_model,
            logger=logger,
        )

    def _apply_intent_adjudication(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        classification: FileTaskClassification,
        adjudication: Dict[str, Any],
    ) -> FileTaskClassification:
        contract_context = build_intent_adjudication_contract_context(request.task)
        return _classification_contract_apply_intent_adjudication(
            request,
            files,
            classification,
            adjudication,
            readonly_write_negation=contract_context.readonly_write_negation,
            artifact_creation_intent=contract_context.artifact_creation_intent,
            global_readonly_write_negation=contract_context.global_readonly_write_negation,
            strong_write_intent=contract_context.strong_write_intent,
        )

    def _normalize_mainline_contract(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        classification: FileTaskClassification,
    ) -> FileTaskClassification:
        task_text = str(request.task or "")
        contract_context = build_mainline_contract_context(
            task_text=task_text,
            explicit_output_mode=self._explicit_output_mode(request),
            readonly_write_negation=self._has_readonly_write_negation(task_text),
            has_target_context=self._has_target_context(request, files),
            docx_annotation_has_contract=_doc_annotate_contract_for_request(
                request, files
            ),
            strong_write_intent=self._has_strong_write_intent(task_text),
        )
        return _classification_contract_normalize_mainline(
            request,
            files,
            classification=classification,
            explicit_output_mode=contract_context.explicit_output_mode,
            readonly_write_negation=contract_context.readonly_write_negation,
            has_target_context=contract_context.has_target_context,
            docx_annotation_has_contract=contract_context.docx_annotation_has_contract,
            write_has_contract_anchor=contract_context.write_has_contract_anchor,
        )

    def _demote_classification_to_read(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        classification: FileTaskClassification,
        *,
        reason: str,
    ) -> FileTaskClassification:
        return _classification_contract_demote_to_read(
            request,
            files,
            classification,
            reason=reason,
        )

    def _build_execution_context(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        *,
        known_tool_gap: Optional[Dict[str, Any]] = None,
        classification: Optional[FileTaskClassification] = None,
        intent_plan: Optional[FileTaskIntentPlan] = None,
        intent_adjudication: Optional[Dict[str, Any]] = None,
        quick_action_mode: str = "",
    ) -> FileTaskExecutionContext:
        resolved_known_tool_gap = (
            known_tool_gap
            if isinstance(known_tool_gap, dict)
            else native_tool_gap_for_request(request)
        )
        resolved_classification = classification or self._classify_request(
            request, files, resolved_known_tool_gap
        )
        resolved_intent_plan = self._resolve_intent_plan(
            request,
            files,
            known_tool_gap=resolved_known_tool_gap,
            classification=resolved_classification,
            intent_plan=intent_plan,
        )
        requirements = build_file_task_requirements(request, resolved_classification)
        plan_check = validate_file_task_plan(
            requirements, resolved_classification, resolved_intent_plan
        )
        (
            effective_planner_policy,
            effective_planner_reason,
            effective_planner_backend,
        ) = self._effective_planner_classification(request)
        resolved_quick_action_mode = (
            str(quick_action_mode or self._quick_action_mode(request)).strip().lower()
        )
        return FileTaskExecutionContext(
            classification=resolved_classification,
            intent_plan=resolved_intent_plan,
            requirements=requirements,
            plan_check=plan_check,
            known_tool_gap=resolved_known_tool_gap,
            intent_adjudication=dict(intent_adjudication or {}),
            effective_planner_policy=effective_planner_policy,
            effective_planner_reason=effective_planner_reason,
            effective_planner_backend=effective_planner_backend,
            quick_action_mode=resolved_quick_action_mode,
            simple_quick_action=resolved_quick_action_mode == "simple",
        )

    def _constraint_audit(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        classification: FileTaskClassification,
        intent_plan: FileTaskIntentPlan,
        requirements: FileTaskRequirementSet,
        recipe_skeleton: Dict[str, Any],
    ) -> Dict[str, Any]:
        hard: List[str] = ["allowlist_tools_only"]
        soft: List[str] = []
        conflicts: List[str] = []

        recipe_id = str(recipe_skeleton.get("recipe_id") or "").strip()
        if recipe_id and recipe_id != "generic_file_task":
            hard.append(f"recipe:{recipe_id}")
        if bool(requirements.write_required):
            hard.append("write_requires_file_changed")
        if bool(recipe_skeleton.get("quality_gates")):
            hard.append("quality_gates_enforced")
        if recipe_id == "financial_xlsx_docx_report":
            hard.append("financial_whitebox_workflow")

        target_type = (
            str(requirements.target_file_type or classification.target_file_type or "")
            .strip()
            .lower()
        )
        if target_type in {"docx", "doc", "pptx", "ppt", "xlsx", "xlsm"}:
            hard.append("explicit_or_unambiguous_target_required")

        if classification.output_mode == "hybrid":
            soft.append("hybrid_mode_default_no_write_without_apply")
        if intent_plan.requires_confirmation:
            soft.append("confirmation_required_before_apply")
        if recipe_id == "generic_file_task":
            soft.append("model_guided_generic_loop")

        if requirements.write_required and classification.output_mode != "write":
            conflicts.append("write_required_output_mode_mismatch")
        if requirements.write_required and intent_plan.write_intent is False:
            conflicts.append("write_required_intent_plan_mismatch")
        if not requirements.write_required and classification.output_mode == "write":
            conflicts.append("readonly_request_escalated_to_write")

        same_type_files = (
            self._context_files_by_type(files, {target_type}) if target_type else []
        )
        write_target_required = (
            bool(requirements.write_required)
            or bool(classification.write_intent)
            or str(classification.output_mode or "").strip().lower() == "write"
            or bool(intent_plan.write_intent)
            or str(intent_plan.output_mode or "").strip().lower() == "write"
        )
        if (
            write_target_required
            and target_type
            and len(same_type_files) > 1
            and not str(request.target_path or "").strip()
        ):
            conflicts.append(f"ambiguous_target:{target_type}")

        return {
            "version": "file_task_constraint_audit_v1",
            "hard_constraints": sorted(set(hard)),
            "soft_constraints": sorted(set(soft)),
            "ignored_deprecated_options": [],
            "conflicts": sorted(set(conflicts)),
            "status": "conflict" if conflicts else "clear",
        }

    def _planner_classification(self, request: FileTaskRequest) -> tuple[str, str, str]:
        return "native_only", "file_task_native_only", "native"

    def _sanitize_planner_options(self, options: Dict[str, Any]) -> Dict[str, Any]:
        return {
            str(key): value
            for key, value in dict(options or {}).items()
            if "planner" not in str(key)
        }

    def _clone_request_with_options(
        self, request: FileTaskRequest, options: Dict[str, Any]
    ) -> FileTaskRequest:
        return FileTaskRequest(
            task=request.task,
            run_id=request.run_id,
            session_id=request.session_id,
            files=list(request.files),
            current_file=request.current_file,
            selection=request.selection,
            selection_source=request.selection_source,
            target_path=request.target_path,
            model_mode=request.model_mode,
            model_id=request.model_id,
            history=list(request.history),
            options=dict(options),
            routing_decision=request.routing_decision,
        )

    def _initial_model_request(self, request: FileTaskRequest) -> FileTaskRequest:
        options = self._sanitize_planner_options(dict(request.options or {}))
        options["planner_policy"] = "native_only"
        options["planner_runtime_reason"] = "file_task_native_only"
        return self._clone_request_with_options(request, options)

    def _request_after_execution_brief(
        self,
        original_request: FileTaskRequest,
        current_request: FileTaskRequest,
        brief: FileTaskExecutionBrief,
    ) -> FileTaskRequest:
        options = self._sanitize_planner_options(dict(current_request.options or {}))
        options["planner_policy"] = "native_only"
        options["planner_runtime_reason"] = "file_task_native_only"
        return self._clone_request_with_options(original_request, options)

    def _build_plan(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        write_intent: bool,
        output_mode: str,
        known_tool_gap: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        recipe_match = select_task_recipe(request, files, write_intent=write_intent)
        if recipe_match and recipe_match.recipe.plan_steps:
            return [dict(step) for step in recipe_match.recipe.plan_steps]
        context_parts = []
        if files:
            context_parts.append(f"{len(files)} 个文件")
        if request.selection:
            context_parts.append("1 段选区")
        context_detail = "和".join(context_parts)
        steps = [
            {
                "id": "context",
                "title": "读取显式上下文",
                "description": (
                    f"读取 {context_detail}，并保留来源引用。"
                    if context_detail
                    else "检查是否有选区、附件或明确当前文件。"
                ),
            },
            {
                "id": "execute",
                "title": "执行任务",
                "description": self._execute_plan_description(
                    write_intent, output_mode, known_tool_gap
                ),
            },
            {
                "id": "check",
                "title": "核验结果",
                "description": "输出检查结论和剩余动作，避免静默失败。",
            },
        ]
        return steps

    def _resolve_intent_plan(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        *,
        known_tool_gap: Optional[Dict[str, Any]] = None,
        classification: Optional[FileTaskClassification] = None,
        intent_plan: Optional[FileTaskIntentPlan] = None,
    ) -> FileTaskIntentPlan:
        resolved_classification = classification or self._classify_request(
            request, files, known_tool_gap
        )
        if isinstance(intent_plan, FileTaskIntentPlan):
            planned = intent_plan
        else:
            try:
                planned = self._intent_planner.plan(
                    request,
                    files,
                    resolved_classification,
                    known_tool_gap=known_tool_gap,
                )
            except Exception as exc:
                logger.warning("[FileTaskRuntime] intent planner failed: %s", exc)
                planned = self._fallback_intent_plan(
                    request, files, resolved_classification, known_tool_gap
                )
            if not isinstance(planned, FileTaskIntentPlan):
                planned = self._fallback_intent_plan(
                    request, files, resolved_classification, known_tool_gap
                )

        planned.intent_type = (
            str(
                planned.intent_type or resolved_classification.task_family or "analyze"
            ).strip()
            or "analyze"
        )
        planned.output_mode = (
            str(resolved_classification.output_mode or planned.output_mode or "answer")
            .strip()
            .lower()
            or "answer"
        )
        planned.confidence = float(
            resolved_classification.confidence
            if resolved_classification.confidence is not None
            else planned.confidence or 0.0
        )
        planned.write_intent = bool(resolved_classification.write_intent)
        if not str(planned.goal_statement or "").strip():
            planned.goal_statement = self._fallback_intent_goal_statement(
                request, resolved_classification, known_tool_gap
            )
        if not planned.dynamic_steps:
            planned.dynamic_steps = self._build_plan(
                request,
                files,
                resolved_classification.write_intent,
                planned.output_mode,
                known_tool_gap,
            )
        if not planned.reason_codes:
            planned.reason_codes = [
                item for item in resolved_classification.reason_codes if item
            ]
        return planned

    def _fallback_intent_plan(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        classification: FileTaskClassification,
        known_tool_gap: Optional[Dict[str, Any]] = None,
    ) -> FileTaskIntentPlan:
        output_mode = (
            str(classification.output_mode or "answer").strip().lower() or "answer"
        )
        requires_confirmation = output_mode == "hybrid" and self._fallback_requires_explicit_confirmation(request)
        recommended_strategy = self._fallback_intent_strategy(
            classification,
            output_mode,
            known_tool_gap,
            requires_confirmation=requires_confirmation,
        )
        can_apply = output_mode in {
            "write",
            "hybrid",
        } and self._fallback_intent_has_apply_target(request, files)
        reason_codes = [item for item in classification.reason_codes if item]
        reason_codes.extend(
            [
                "intent_plan:fallback",
                f"intent_type:{classification.task_family or 'analyze'}",
                f"strategy:{recommended_strategy}",
            ]
        )
        if can_apply:
            reason_codes.append("can_apply")
        if requires_confirmation:
            reason_codes.append("requires_confirmation")
        return FileTaskIntentPlan(
            intent_type=classification.task_family or "analyze",
            goal_statement=self._fallback_intent_goal_statement(
                request, classification, known_tool_gap
            ),
            output_mode=output_mode,
            confidence=float(classification.confidence or 0.0),
            write_intent=bool(classification.write_intent),
            can_apply=can_apply,
            requires_confirmation=requires_confirmation,
            recommended_strategy=recommended_strategy,
            dynamic_steps=self._build_plan(
                request, files, classification.write_intent, output_mode, known_tool_gap
            ),
            reason_codes=reason_codes,
        )

    def _fallback_intent_goal_statement(
        self,
        request: FileTaskRequest,
        classification: FileTaskClassification,
        known_tool_gap: Optional[Dict[str, Any]] = None,
    ) -> str:
        task_text = _preview(request.task, 180) or "当前文件任务"
        output_mode = (
            str(classification.output_mode or "answer").strip().lower() or "answer"
        )
        if known_tool_gap:
            return f"识别缺失原生能力并输出可落地工具设计：{task_text}"
        if classification.request_kind == "resume":
            return f"延续上一轮待确认的文件任务：{task_text}"
        if output_mode == "write":
            return f"完成真实文件修改并交付结果：{task_text}"
        if output_mode == "hybrid":
            if self._fallback_requires_explicit_confirmation(request):
                return f"先分析并整理可应用建议，再等待确认：{task_text}"
            return f"先分析并整理可应用建议，后续可按用户要求应用：{task_text}"
        return f"基于显式上下文给出结论或答复：{task_text}"

    def _fallback_intent_strategy(
        self,
        classification: FileTaskClassification,
        output_mode: str,
        known_tool_gap: Optional[Dict[str, Any]] = None,
        *,
        requires_confirmation: bool = False,
    ) -> str:
        if known_tool_gap:
            return "design_new_tool"
        if classification.request_kind == "resume":
            return "resume_previous_plan"
        if output_mode == "write":
            return "write_through"
        if output_mode == "hybrid":
            return "analyze_then_confirm" if requires_confirmation else "analyze_then_optional_apply"
        return "answer_only"

    def _fallback_requires_explicit_confirmation(self, request: FileTaskRequest) -> bool:
        task_text = str(request.task or "").strip()
        if re.search(
            r"(?:确认后|等(?:我|用户)?确认|等待(?:我|用户)?确认|我确认后|用户确认后|"
            r"确认(?:了|完)?再|先.{0,24}(?:等|等待).{0,12}确认|"
            r"等(?:我|用户)?(?:说)?继续|回复继续|说继续|"
            r"wait for (?:my |user )?confirmation|confirm(?:ation)? before (?:apply|applying|write|writing))",
            task_text,
            re.IGNORECASE,
        ):
            return True
        options = request.options if isinstance(request.options, dict) else {}
        return bool(options.get("requires_confirmation") or options.get("confirm_before_apply"))

    def _fallback_intent_has_apply_target(
        self, request: FileTaskRequest, files: List[FileTaskFile]
    ) -> bool:
        if str(request.target_path or "").strip():
            return True
        if request.selection:
            return True
        return any(
            file_info.target or file_info.path or file_info.name for file_info in files
        )

    def _execute_plan_description(
        self,
        write_intent: bool,
        output_mode: str,
        known_tool_gap: Optional[Dict[str, Any]],
    ) -> str:
        if known_tool_gap:
            capability = str(known_tool_gap.get("missing_capability") or "缺失能力").strip()
            return f"当前任务触发 Koto 原生能力缺口：{capability}；模型需要产出 {TOOL_DESIGN_PROTOCOL} 工具规格，不调用未注册工具。"
        if write_intent:
            return "模型在 Koto allowlist 工具目录内规划并执行，写入后产生 file.changed 事件。"
        if output_mode == "hybrid":
            return "模型先读取文件并给出可应用的分析建议；当前轮不默认直接写入原文件。"
        return "模型可读取文件、调用分析工具并生成可审计答复。"

    def _output_mode_label(self, output_mode: str) -> str:
        normalized = str(output_mode or "").strip().lower()
        if normalized == "write":
            return "写入文件"
        if normalized == "hybrid":
            return "先分析后决定"
        return "只给答案"

    def _output_mode_guidance(self, classification: FileTaskClassification) -> str:
        output_mode = str(classification.output_mode or "answer").strip().lower()
        label = self._output_mode_label(output_mode)
        if output_mode == "write":
            return (
                f"当前任务反馈模式：{label}。\n"
                "本轮目标是完成真实文件修改；除非进入等待确认状态，否则不要只给建议或总结就结束。\n"
                "如果没有产生真实 file.changed，就不能把任务说成已完成。\n"
                "任务全部完成后，用三部分简短汇报（不要写\"总结与回答\"这类大标题，不要重复前面的步骤日志）：\n"
                "① 核心结果：1-2句话说明完成了什么。\n"
                "② 产出清单，每条一行：- 文件名：描述（如\"- chart1.png：收入趋势\"；\"- xxx.docx：已写入N段分析、插入M张图表\"）。\n"
                "③ 发现的问题，每条一行：- 问题描述（简明扼要，不超过两行）。\n"
                "各部分之间空一行即可，不要加\"总结与回答\"\"任务完成\"\"执行过程\"等冗余标题。\n"
            )
        if output_mode == "hybrid":
            return (
                f"当前任务反馈模式：{label}。\n"
                "本轮先基于显式上下文给出分析、问题清单、修改方向或可应用方案。\n"
                "除非用户这轮已经明确要求直接应用到文件，否则不要直接调用写入工具，也不要声称文件已经更新。\n"
                "如果需要后续落盘，应先把建议说清楚，再等待用户继续要求应用。\n"
            )
        return (
            f"当前任务反馈模式：{label}。\n"
            "本轮默认只返回分析、总结、解释或结论。\n"
            "不要调用写入工具，不要伪造 file.changed，也不要把结果描述成已经写入文件。\n"
            "只有当用户明确要求把结果写入文件时，才改走写回路径。\n"
        )

    def _intent_plan_guidance(self, intent_plan: FileTaskIntentPlan) -> str:
        lines = ["高阶意图规划："]
        goal_statement = str(intent_plan.goal_statement or "").strip()
        if goal_statement:
            lines.append(f"- 目标：{goal_statement}")
        lines.append(
            f"- 策略：{str(intent_plan.recommended_strategy or 'answer_only').strip() or 'answer_only'}"
        )
        lines.append(f"- 可应用：{'是' if intent_plan.can_apply else '否'}")
        lines.append(f"- 当前轮会暂停等待确认：{'是' if intent_plan.requires_confirmation else '否'}")
        if intent_plan.dynamic_steps:
            lines.append("- 计划步骤：")
            for index, step in enumerate(intent_plan.dynamic_steps[:8], start=1):
                if not isinstance(step, dict):
                    continue
                title = str(
                    step.get("title") or step.get("id") or f"步骤 {index}"
                ).strip()
                description = str(step.get("description") or "").strip()
                lines.append(
                    f"  {index}. {title}" + (f"：{description}" if description else "")
                )
        if intent_plan.write_intent:
            lines.append("- 监管约束：写入型任务必须产生真实 file.changed；分步确认任务必须先完成本步骤写入，再进入等待用户继续。")
        return "\n".join(lines) + "\n"

    def _execution_brief_schema(self) -> Dict[str, Any]:
        return _brief_execution_brief_schema()

    def _normalize_execution_brief(
        self, value: Any
    ) -> Optional[FileTaskExecutionBrief]:
        return _brief_normalize_execution_brief(value)

    def _looks_like_brief_only_content(self, content_text: str) -> bool:
        return _brief_looks_like_brief_only_content(content_text)

    def _extract_execution_brief(
        self,
        response: Any,
        content_text: str,
    ) -> tuple[Optional[FileTaskExecutionBrief], str]:
        return _brief_extract_execution_brief(response, content_text)

    def _extract_execution_brief_tool_call(
        self,
        tool_calls: List[Dict[str, Any]],
    ) -> tuple[Optional[FileTaskExecutionBrief], List[Dict[str, Any]]]:
        if not tool_calls:
            return None, []

        brief: Optional[FileTaskExecutionBrief] = None
        remaining: List[Dict[str, Any]] = []
        for tool_call in tool_calls:
            tool_name = str((tool_call or {}).get("name") or "").strip()
            if tool_name != "execution_brief":
                remaining.append(tool_call)
                continue

            candidate = (tool_call or {}).get("args") or {}
            parsed = self._normalize_execution_brief(candidate)
            if parsed and brief is None:
                brief = parsed

        return brief, remaining

    def _execution_brief_continue_message(
        self,
        request: FileTaskRequest,
        brief: FileTaskExecutionBrief,
    ) -> str:
        summary = brief.summary or brief.objective or "已完成任务分析。"
        lines = [
            f"已收到 execution_brief：{summary}",
            "下一轮请在白盒任务骨架内直接调用需要的 Koto 工具继续执行，不要重复输出同一份 brief。",
        ]
        if request.target_path:
            lines.append(f"当前目标文件是：{request.target_path}。")
        return " ".join(lines)

    def _execution_plan_continue_message(
        self,
        request: FileTaskRequest,
        execution_plan: WhiteboxExecutionPlan,
        recipe_skeleton: Dict[str, Any],
    ) -> str:
        summary = execution_plan.plan_summary or execution_plan.goal or "已完成白盒执行计划。"
        lines = [
            f"已收到 execution_plan：{summary}",
            "现在请按该计划继续调用 Koto allowlist 工具执行；不要重复输出计划，也不要跳过必需写入/核验步骤。",
        ]
        required_operations = (
            recipe_skeleton.get("completion_check", {}).get("required_operations")
            if isinstance(recipe_skeleton.get("completion_check"), dict)
            else []
        )
        if required_operations:
            lines.append(
                "完成检查要求包含："
                + "、".join(
                    str(item) for item in required_operations if str(item or "").strip()
                )
            )
        if request.target_path:
            lines.append(f"目标文件：{request.target_path}。")
        return " ".join(lines)

    def _whitebox_plan_repair_message(
        self,
        gate_payload: Dict[str, Any],
        recipe_skeleton: Dict[str, Any],
    ) -> str:
        lines = [
            "白盒计划审查未通过或不完整，请修复计划后继续执行。",
            "必须遵守 recipe_skeleton 的 required_steps、allowed_tools、success_criteria 和 completion_check。",
        ]
        violations = (
            gate_payload.get("violations")
            if isinstance(gate_payload.get("violations"), list)
            else []
        )
        warnings = (
            gate_payload.get("warnings")
            if isinstance(gate_payload.get("warnings"), list)
            else []
        )
        if violations:
            lines.append("阻断问题：" + "；".join(str(item) for item in violations[:6]))
        if warnings:
            lines.append("需要补强：" + "；".join(str(item) for item in warnings[:6]))
        allowed_tools = (
            recipe_skeleton.get("allowed_tools")
            if isinstance(recipe_skeleton.get("allowed_tools"), list)
            else []
        )
        if allowed_tools:
            lines.append(
                "只能调用这些工具："
                + "、".join(
                    str(item) for item in allowed_tools[:30] if str(item or "").strip()
                )
            )
        return "\n".join(lines)

    def _build_confirmed_plan(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        tool_calls: List[Dict[str, Any]],
        write_intent: bool,
        content_text: str,
    ) -> Dict[str, Any]:
        steps: List[Dict[str, Any]] = []
        seen: set[str] = set()
        has_write_step = False

        for idx, tool_call in enumerate(tool_calls, start=1):
            tool_name = str(tool_call.get("name") or "").strip()
            tool_args = dict(tool_call.get("args") or {})
            if not tool_name:
                continue
            signature = json.dumps(
                {"name": tool_name, "args": tool_args},
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            if signature in seen:
                continue
            seen.add(signature)
            has_write_step = has_write_step or (
                is_write_tool(tool_name) and tool_name != "run_python_code"
            )
            steps.append(
                {
                    "id": f"model_step_{idx}",
                    "tool_name": tool_name,
                    "title": self._tool_plan_title(tool_name),
                    "description": self._tool_plan_description(
                        tool_name, tool_args, files, request
                    ),
                }
            )

        if write_intent and not has_write_step:
            steps.append(self._inferred_write_plan_step(request, files))

        steps.append(
            {
                "id": "verify",
                "title": "核验结果",
                "description": "检查目标文件是否真的更新，并给出最终结论。",
            }
        )

        clean_summary = _preview(content_text, 180) if content_text else "AI 已确认执行方案。"
        return {
            "summary": clean_summary,
            "steps": steps,
            "estimated": True,
            "note": "实际步骤会根据读取结果和工具返回自动微调。",
        }

    def _tool_plan_title(self, tool_name: str) -> str:
        return _plan_presentation_title(tool_name)

    def _tool_plan_description(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        files: List[FileTaskFile],
        request: FileTaskRequest,
    ) -> str:
        return _plan_presentation_description(self, tool_name, tool_args, files, request)

    def _inferred_write_plan_step(
        self, request: FileTaskRequest, files: List[FileTaskFile]
    ) -> Dict[str, Any]:
        source = self._first_file_name(files, {"xlsx", "xlsm", "csv"})
        docx_target = (
            self._typed_target_display_path(request, {"docx", "doc"})
            or self._first_file_name(files, {"docx"}, target=True)
            or self._first_file_name(files, {"docx"})
        )
        pptx_target = (
            self._typed_target_display_path(request, {"pptx", "ppt"})
            or self._first_file_name(files, {"pptx"}, target=True)
            or self._first_file_name(files, {"pptx"})
        )
        text_target = self._typed_target_display_path(
            request, {"txt", "md", "csv", "json", "py", "js", "html", "css"}
        ) or self._first_file_name(
            files, {"txt", "md", "csv", "json", "py", "js", "html", "css"}, target=True
        )
        task_lower = (request.task or "").lower()
        if (
            source
            and docx_target
            and self._looks_like_financial_xlsx_docx_chart_report_task(request, files)
        ):
            return {
                "id": "inferred_write",
                "title": "写入问题和图表",
                "description": f"读取完成后，先生成真实财务图表图片并整理问题清单，再写入 {docx_target}。",
            }
        if source and docx_target:
            return {
                "id": "inferred_write",
                "title": "写入 Word 表格",
                "description": f"读取完成后，把 {source} 的表格数据写入 {docx_target}。",
            }
        if text_target:
            return {
                "id": "inferred_write",
                "title": "写回文本文件",
                "description": f"读取完成后，把处理结果写回 {text_target}。",
            }
        if pptx_target or "ppt" in task_lower or "幻灯片" in task_lower:
            if any(
                word in task_lower
                for word in (
                    "风格",
                    "主题",
                    "版式",
                    "美化",
                    "排版",
                    "配色",
                    "视觉",
                    "theme",
                    "layout",
                    "design",
                )
            ):
                return {
                    "id": "inferred_write",
                    "title": "设计 PPT 主题版式",
                    "description": f"读取完成后，为 {pptx_target or '目标 PPT'} 套用统一主题、字体、配色和安全版式。",
                }
            return {
                "id": "inferred_write",
                "title": "写入 PPT 内容",
                "description": f"读取完成后，把整理结果写入 {pptx_target or '目标 PPT'}。",
            }
        target = self._display_path(request.target_path) or next(
            (
                self._display_path(file_info.path)
                for file_info in files
                if file_info.target and file_info.path
            ),
            "目标文件",
        )
        return {
            "id": "inferred_write",
            "title": "写入目标文件",
            "description": f"读取完成后，把处理结果写入 {target}。",
        }

    def _typed_target_display_path(
        self, request: FileTaskRequest, types: set[str]
    ) -> str:
        raw = str(request.target_path or "").strip()
        suffix = Path(raw).suffix.lstrip(".").lower()
        if raw and suffix in types:
            return self._display_path(raw)
        return ""

    def _first_file_name(
        self, files: List[FileTaskFile], types: set[str], *, target: bool = False
    ) -> str:
        for file_info in files:
            file_type = (
                file_info.type
                or Path(file_info.path or file_info.name).suffix.lstrip(".")
            ).lower()
            if target and not file_info.target:
                continue
            if types and file_type not in types:
                continue
            return file_info.name or self._display_path(file_info.path)
        return ""

    def _first_context_file(
        self, files: List[FileTaskFile], types: set[str], *, target: bool = False
    ) -> Optional[FileTaskFile]:
        for file_info in files:
            file_type = (
                file_info.type
                or Path(file_info.path or file_info.name).suffix.lstrip(".")
            ).lower()
            if target and not file_info.target:
                continue
            if types and file_type not in types:
                continue
            return file_info
        return None

    def _context_files_by_type(
        self, files: List[FileTaskFile], types: set[str]
    ) -> List[FileTaskFile]:
        matches: List[FileTaskFile] = []
        for file_info in files:
            file_type = (
                file_info.type
                or Path(file_info.path or file_info.name).suffix.lstrip(".")
            ).lower()
            if types and file_type not in types:
                continue
            matches.append(file_info)
        return matches

    def _display_path(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        path_parts = text.replace("\\", "/").rsplit("/", 1)
        return path_parts[len(path_parts) - 1] if path_parts else text

    def _repair_tool_args_for_context(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        request: FileTaskRequest,
        files: List[FileTaskFile],
        *,
        generated_artifacts: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        args = dict(tool_args or {})
        if (
            tool_name
            in {
                "write_docx_content",
                "insert_docx_paragraph",
                "insert_image_into_docx",
                "clear_docx_review_marks",
            }
            and not str(args.get("path") or "").strip()
        ):
            target = self._single_target_path_for_types(request, files, {"docx", "doc"})
            if target:
                args["path"] = target
        if tool_name == "insert_image_into_docx":
            raw_image_path = str(args.get("image_path") or "").strip()
            if not self._resolve_task_file_path(raw_image_path):
                generated_image = self._latest_generated_image_artifact_path(
                    generated_artifacts or [], raw_image_path
                )
                if generated_image:
                    args["image_path"] = generated_image
        if tool_name == "insert_docx_paragraph" and self._task_requests_docx_append_end(
            request.task
        ):
            args.pop("before_heading", None)
            args.pop("after_heading", None)
        if (
            tool_name == "design_pptx_theme_layout"
            and not str(args.get("path") or "").strip()
        ):
            target = self._single_target_path_for_types(request, files, {"pptx", "ppt"})
            if target:
                args["path"] = target
        if tool_name == "write_sheet_data" and not str(args.get("path") or "").strip():
            target = self._single_target_path_for_types(
                request, files, {"xlsx", "xlsm"}
            )
            if target:
                args["path"] = target
        if tool_name == "insert_excel_as_docx_table":
            if not str(args.get("target_path") or "").strip():
                target = self._single_target_path_for_types(
                    request, files, {"docx", "doc"}
                )
                if target:
                    args["target_path"] = target
            if not str(args.get("source_path") or "").strip():
                source = self._single_source_path_for_types(
                    request, files, {"xlsx", "xlsm"}
                )
                if source:
                    args["source_path"] = source
        if tool_name == "write_docx_content" and "paragraphs" not in args:
            for key in ("content", "text", "markdown", "body"):
                value = args.get(key)
                if str(value or "").strip():
                    args["paragraphs"] = value
                    break
        return args

    def _remember_generated_artifacts(
        self, target: List[Dict[str, Any]], artifacts: List[Dict[str, Any]]
    ) -> None:
        seen = {
            os.path.normcase(str(item.get("path") or "").strip())
            for item in target
            if str(item.get("path") or "").strip()
        }
        for artifact in artifacts or []:
            if not isinstance(artifact, dict):
                continue
            kind = str(artifact.get("kind") or "").strip().lower()
            path = str(artifact.get("path") or "").strip()
            if kind != "image" or not path or not os.path.exists(path):
                continue
            key = os.path.normcase(path)
            if key in seen:
                continue
            seen.add(key)
            target.append(dict(artifact))

    def _latest_generated_image_artifact_path(
        self, artifacts: List[Dict[str, Any]], requested_path: str = ""
    ) -> str:
        images = [
            artifact
            for artifact in artifacts or []
            if isinstance(artifact, dict)
            and str(artifact.get("kind") or "").strip().lower() == "image"
            and str(artifact.get("path") or "").strip()
            and os.path.exists(str(artifact.get("path") or "").strip())
        ]
        if not images:
            return ""
        requested_name = Path(str(requested_path or "").replace("\\", "/")).name.lower()
        if requested_name:
            for artifact in reversed(images):
                artifact_name = str(artifact.get("name") or "").strip().lower()
                artifact_path = str(artifact.get("path") or "").strip()
                if artifact_name == requested_name or Path(artifact_path).name.lower() == requested_name:
                    return artifact_path
        return str(images[len(images) - 1].get("path") or "").strip()

    def _write_dedupe_key_for_tool(
        self, tool_name: str, tool_args: Dict[str, Any]
    ) -> str:
        target = write_target_for_tool(tool_name, tool_args)
        if tool_name != "insert_image_into_docx":
            return f"{tool_name}::{target}"
        image_path = str(tool_args.get("image_path") or "").strip()
        resolved_image = self._resolve_task_file_path(image_path) or image_path
        image_key = os.path.normcase(os.path.normpath(resolved_image)) if resolved_image else ""
        if not image_key:
            image_key = Path(image_path.replace("\\", "/")).name.lower()
        return f"{tool_name}::{target}::{image_key}"

    def _is_docx_chart_write_request(
        self, request: FileTaskRequest, files: List[FileTaskFile]
    ) -> bool:
        target = self._single_target_path_for_types(request, files, {"docx", "doc"})
        target_type = Path(str(request.target_path or target or "")).suffix.lstrip(".").lower()
        return bool(
            target_type in {"docx", "doc"}
            and (
                self._looks_like_chart_request(request.task)
                or self._looks_like_financial_xlsx_docx_chart_report_task(request, files)
            )
        )

    def _generated_image_artifact_key(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        resolved = self._resolve_task_file_path(text) or text
        try:
            return os.path.normcase(os.path.normpath(resolved))
        except Exception:
            return resolved.lower()

    def _generated_image_artifact_name(self, artifact: Dict[str, Any]) -> str:
        name = str(artifact.get("name") or "").strip()
        if name:
            return name
        path = str(artifact.get("path") or "").strip()
        return Path(path.replace("\\", "/")).name if path else "图表图片"

    def _pending_generated_docx_images(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        generated_artifacts: List[Dict[str, Any]],
        file_changes: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not generated_artifacts or not self._is_docx_chart_write_request(request, files):
            return []

        inserted_keys: set[str] = set()
        inserted_names: set[str] = set()
        for change in file_changes or []:
            if not isinstance(change, dict):
                continue
            if str(change.get("operation") or "").strip() != "insert_image_into_docx":
                continue
            image_path = str(change.get("image_path") or "").strip()
            image_name = str(change.get("image_name") or "").strip()
            if image_path:
                inserted_keys.add(self._generated_image_artifact_key(image_path))
                inserted_names.add(Path(image_path.replace("\\", "/")).name.lower())
            if image_name:
                inserted_names.add(image_name.lower())

        pending: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for artifact in generated_artifacts or []:
            if not isinstance(artifact, dict):
                continue
            kind = str(artifact.get("kind") or "").strip().lower()
            path = str(artifact.get("path") or "").strip()
            name = self._generated_image_artifact_name(artifact)
            ext = Path(name or path).suffix.lstrip(".").lower()
            if kind != "image" or ext not in _IMAGE_ARTIFACT_EXTENSIONS:
                continue
            if path and not os.path.exists(path):
                continue
            key = self._generated_image_artifact_key(path or name)
            name_key = name.lower()
            if key in inserted_keys or name_key in inserted_names:
                continue
            if key in seen or name_key in seen:
                continue
            seen.add(key or name_key)
            pending.append(dict(artifact))
        return pending

    def _generated_docx_image_insert_guard_message(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        pending_images: List[Dict[str, Any]],
    ) -> str:
        target = (
            self._single_target_path_for_types(request, files, {"docx", "doc"})
            or str(request.target_path or "").strip()
            or "目标 DOCX"
        )
        names = [
            self._generated_image_artifact_name(item)
            for item in pending_images[:8]
            if isinstance(item, dict)
        ]
        name_text = "、".join(name for name in names if name)
        return (
            "已生成图表图片，但尚未全部作为真实 Word 图片插入目标 DOCX。"
            f"请继续调用 insert_image_into_docx，path 使用 {target}，"
            f"逐张插入这些剩余图片：{name_text or '所有剩余图表图片'}。"
            "不要只在总结中描述图片，也不要只打开图片预览。"
        )

    def _generated_docx_image_quality_failure(
        self,
        check_payload: Dict[str, Any],
        pending_images: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not pending_images:
            return check_payload
        names = [
            self._generated_image_artifact_name(item)
            for item in pending_images[:8]
            if isinstance(item, dict)
        ]
        remaining_text = (
            "仍有生成图表未插入 DOCX："
            + ("、".join(name for name in names if name) or "剩余图表图片")
        )
        payload = dict(check_payload or {})
        criteria = list(payload.get("criteria_results") or [])
        criteria.append(
            self._quality_gate_result(
                criterion="generated_chart_images_inserted_into_docx",
                passed=False,
                detail=remaining_text,
                priority="critical",
            )
        )
        remaining = list(payload.get("remaining") or [])
        remaining.insert(0, remaining_text)
        payload.update(
            {
                "passed": False,
                "status": "quality_gate_failed",
                "summary": "文件已有变更，但生成的图表图片没有全部写入目标 DOCX。",
                "remaining": remaining,
                "criteria_results": criteria,
            }
        )
        return payload

    def _task_requests_docx_append_end(self, task: Any) -> bool:
        text = str(task or "")
        return bool(
            re.search(
                r"(?:追加|附加|加到.{0,12}末尾|放到.{0,12}末尾|写到.{0,12}末尾|文末|末尾|最后|append|at the end|end of)",
                text,
                re.IGNORECASE,
            )
        )

    def _single_target_path_for_types(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        file_types: set[str],
    ) -> str:
        target_path = str(request.target_path or "").strip()
        if target_path:
            suffix = Path(target_path).suffix.lower().lstrip(".")
            if not suffix or suffix in file_types:
                return target_path
        candidates: List[str] = []
        for file_info in files or []:
            if not getattr(file_info, "target", False):
                continue
            path = str(file_info.path or file_info.name or "").strip()
            suffix = str(file_info.type or "").strip().lower().lstrip(".") or Path(
                path
            ).suffix.lower().lstrip(".")
            if path and suffix in file_types:
                candidates.append(path)
        unique = list(dict.fromkeys(candidates))
        return unique[0] if len(unique) == 1 else ""

    def _single_source_path_for_types(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        file_types: set[str],
    ) -> str:
        candidates: List[str] = []
        for file_info in files or []:
            if getattr(file_info, "target", False):
                continue
            path = str(file_info.path or file_info.name or "").strip()
            suffix = str(file_info.type or "").strip().lower().lstrip(".") or Path(
                path
            ).suffix.lower().lstrip(".")
            if path and suffix in file_types:
                candidates.append(path)
        unique = list(dict.fromkeys(candidates))
        return unique[0] if len(unique) == 1 else ""

    def _resolve_task_file_path(self, path: Any) -> str:
        raw = str(path or "").strip()
        if not raw:
            return ""
        if os.path.isabs(raw) and os.path.exists(raw):
            return os.path.normpath(raw)
        try:
            from app.core.agent import task_tools

            resolved = task_tools._resolve_path(raw)  # type: ignore[attr-defined]
            if resolved and os.path.exists(resolved):
                return os.path.normpath(resolved)
        except Exception as exc:
            logger.debug(
                "[FileTaskRuntime] workspace path resolution skipped for %r: %s",
                raw,
                exc,
            )
        return ""

    def _plan_summary(
        self, request: FileTaskRequest, files: List[FileTaskFile], write_intent: bool
    ) -> str:
        explicit_output = self._explicit_output_path_from_task(request.task)
        if write_intent and explicit_output:
            suffix = "，并引用 1 段选区" if request.selection else ""
            return f"准备生成 {Path(explicit_output).name}{suffix}。"
        target = request.target_path or next((f.path for f in files if f.target), "")
        has_selection = bool(request.selection)
        if write_intent and target:
            suffix = "，并引用 1 段选区" if has_selection else ""
            return f"准备更新 {Path(target).name}{suffix}。"
        if files and has_selection:
            return f"准备处理 {len(files)} 个文件和 1 段选区。"
        if files:
            return f"准备处理 {len(files)} 个文件。"
        if has_selection:
            return "准备处理 1 段选区。"
        return "准备处理当前任务。"

    def _verification_target_path(
        self, request: FileTaskRequest, file_changes: List[Dict[str, Any]]
    ) -> str:
        explicit_output = self._explicit_output_path_from_task(request.task)
        if explicit_output:
            for change in file_changes:
                if not isinstance(change, dict):
                    continue
                changed_path = str(
                    change.get("path")
                    or change.get("file_path")
                    or change.get("output_path")
                    or change.get("target_path")
                    or ""
                ).strip()
                if changed_path and self._same_task_path(changed_path, explicit_output):
                    return changed_path
            return explicit_output
        return str(request.target_path or "").strip()

    def _write_stepwise_pdf_docx_native(
        self,
        ledger: FileTaskLedger,
        request: FileTaskRequest,
        executor: ToolExecutor,
        snippets: List[Dict[str, Any]],
        files: List[FileTaskFile],
        recipe_skeleton: Dict[str, Any],
        step_id: str,
        *,
        reason: str,
        fallback: bool,
        model_unavailable: bool,
    ):
        if not _looks_like_windowed_pdf_task(request, recipe_skeleton):
            return None
        pdf_snippet = next(
            (
                item
                for item in snippets
                if str(item.get("source") or item.get("path") or "")
                .lower()
                .endswith(".pdf")
                or str(item.get("path") or "").lower().endswith(".pdf")
            ),
            None,
        )
        if not pdf_snippet:
            return None
        text_quality = _pdf_text_quality(
            pdf_snippet.get("_raw_text") or pdf_snippet.get("preview") or ""
        )
        if not text_quality.get("usable"):
            reason_text = str(text_quality.get("reason") or "low_quality_pdf_text")
            yield ledger.event(
                "tool.finished",
                _native_stepwise_pdf_text_quality_guard_payload(reason_text),
                step_id=step_id,
            )
            return None
        target_path = self._stepwise_docx_target_path(request, files)
        if not target_path:
            return None

        paragraphs = self._stepwise_pdf_fallback_paragraphs(
            request, pdf_snippet, RuntimeError(reason)
        )
        tool_args = {
            "path": target_path,
            "paragraphs": json.dumps(paragraphs, ensure_ascii=False),
        }
        started_payload = {
            "tool_name": "write_docx_content",
            "tool_args": tool_args,
            "native_stepwise": True,
            "reason": reason,
        }
        if fallback:
            started_payload["fallback"] = True
        yield ledger.event("tool.started", started_payload, step_id=step_id)
        try:
            result = executor("write_docx_content", tool_args)
            success = not _is_error_result(result)
        except Exception as write_exc:
            result = f"Error: {write_exc}"
            success = False
            logger.warning(
                "[FileTaskRuntime] stepwise PDF native write failed: %s", write_exc
            )

        finished_payload = {
            "tool_name": "write_docx_content",
            "success": success,
            "native_stepwise": True,
            "model_unavailable": bool(model_unavailable),
            "result_preview": tool_result_preview("write_docx_content", result, 1200),
        }
        if fallback:
            finished_payload["fallback"] = True
        yield ledger.event("tool.finished", finished_payload, step_id=step_id)
        if not success:
            return None
        changes = self._extract_file_changes("write_docx_content", tool_args, result)
        return changes[0] if changes else None

    def _stepwise_docx_target_path(
        self, request: FileTaskRequest, files: List[FileTaskFile]
    ) -> str:
        return _stepwise_docx_target_path(request, files)

    def _tool_args_docx_paragraph_count(self, tool_args: Dict[str, Any]) -> int:
        return _docx_edit_paragraph_count(tool_args)

    def _local_docx_edit_block_message(
        self,
        request: FileTaskRequest,
        tool_name: str,
        tool_args: Dict[str, Any],
    ) -> str:
        return _docx_edit_local_block_message(
            task_text=str(request.task or ""),
            tool_name=tool_name,
            tool_args=tool_args,
        )

    def _stepwise_docx_write_block_message(
        self,
        request: FileTaskRequest,
        snippets: List[Dict[str, Any]],
        recipe_skeleton: Dict[str, Any],
        tool_name: str,
        tool_args: Dict[str, Any],
    ) -> str:
        return _stepwise_docx_write_block_message(
            request=request,
            snippets=snippets,
            recipe_skeleton=recipe_skeleton,
            tool_name=tool_name,
            tool_args=tool_args,
        )

    def _stepwise_docx_content_quality_block_message(
        self, snippets: List[Dict[str, Any]], text: str
    ) -> str:
        return _stepwise_docx_content_quality_block_message(snippets, text)

    def _stepwise_docx_wait_artifact(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        snippets: List[Dict[str, Any]],
        file_changes: List[Dict[str, Any]],
        recipe_skeleton: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        return _stepwise_docx_wait_artifact(
            request=request,
            files=files,
            snippets=snippets,
            file_changes=file_changes,
            recipe_skeleton=recipe_skeleton,
            target_path_fallback=self._stepwise_docx_target_path(request, files),
        )

    def _stepwise_pdf_fallback_paragraphs(
        self,
        request: FileTaskRequest,
        pdf_snippet: Dict[str, Any],
        exc: Exception,
    ) -> List[Dict[str, str]]:
        return _stepwise_pdf_fallback_paragraphs(pdf_snippet, exc)

    def _stepwise_pdf_fallback_insights(self, preview: str) -> List[str]:
        return _stepwise_pdf_fallback_insights(preview)

    def _fallback_readonly_summary(
        self,
        request: FileTaskRequest,
        snippets: List[Dict[str, Any]],
        files: List[FileTaskFile],
        exc: Exception,
    ) -> str:
        return _readonly_fallback_summary(
            request=request,
            snippets=snippets,
            files=files,
            exc=exc,
            display_path=self._display_path,
        )

    def _readonly_answer_required_message(
        self,
        request: FileTaskRequest,
        snippets: List[Dict[str, Any]],
        readonly_tool_outputs: List[Dict[str, Any]],
    ) -> str:
        return _readonly_answer_required_message(
            request=request,
            snippets=snippets,
            readonly_tool_outputs=readonly_tool_outputs,
            display_path=self._display_path,
        )

    def _readonly_context_source_lines(
        self,
        snippets: List[Dict[str, Any]],
        readonly_tool_outputs: List[Dict[str, Any]],
        *,
        limit: int = 5,
    ) -> List[str]:
        return _readonly_context_source_lines(
            snippets=snippets,
            readonly_tool_outputs=readonly_tool_outputs,
            display_path=self._display_path,
            limit=limit,
        )

    def _readonly_context_summary(
        self,
        request: FileTaskRequest,
        snippets: List[Dict[str, Any]],
        readonly_tool_outputs: List[Dict[str, Any]],
    ) -> str:
        return _readonly_context_summary(
            request=request,
            snippets=snippets,
            readonly_tool_outputs=readonly_tool_outputs,
            display_path=self._display_path,
        )

    def _readonly_tool_source_label(self, item: Dict[str, Any]) -> str:
        return _readonly_tool_source_label(item, display_path=self._display_path)

    def _readonly_tool_points(self, item: Dict[str, Any]) -> List[str]:
        return _readonly_tool_points(item)

    def _success_criteria(
        self, request: FileTaskRequest, write_intent: bool, output_mode: str
    ) -> List[str]:
        return _quality_success_criteria(
            request,
            write_intent=write_intent,
            output_mode=output_mode,
        )

    def _file_types(self, files: List[FileTaskFile]) -> set[str]:
        return _supervisor_file_types(files)

    def _looks_like_chart_request(self, task: str) -> bool:
        return _supervisor_looks_like_chart_request(task)

    def _looks_like_problem_analysis_request(self, task: str) -> bool:
        return _supervisor_looks_like_problem_analysis_request(task)

    def _looks_like_financial_request(self, task: str) -> bool:
        return _supervisor_looks_like_financial_request(task)

    def _looks_like_table_request(self, task: str) -> bool:
        return _supervisor_looks_like_table_request(task)

    def _looks_like_summary_request(self, task: str) -> bool:
        return _supervisor_looks_like_summary_request(task)

    def _looks_like_translation_request(self, task: str) -> bool:
        return _supervisor_looks_like_translation_request(task)

    def _looks_like_polish_request(self, task: str) -> bool:
        return _supervisor_looks_like_polish_request(task)

    def _looks_like_ppt_request(self, task: str, files: List[FileTaskFile]) -> bool:
        return _supervisor_looks_like_ppt_request(task, files)

    def _looks_like_ppt_slide_write_request(
        self, request: FileTaskRequest, files: List[FileTaskFile]
    ) -> bool:
        return _supervisor_looks_like_ppt_slide_write_request(request, files)

    def _looks_like_docx_report_request(
        self, request: FileTaskRequest, files: List[FileTaskFile]
    ) -> bool:
        return _supervisor_looks_like_docx_report_request(request, files)

    def _looks_like_financial_xlsx_docx_chart_report_task(
        self, request: FileTaskRequest, files: List[FileTaskFile]
    ) -> bool:
        return _supervisor_looks_like_financial_report_task(request, files)

    def _looks_like_pdf_python_text_read(self, code: Any) -> bool:
        return _supervisor_looks_like_pdf_python_text_read(code)

    def _blocked_run_python_message(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        request: FileTaskRequest,
        files: List[FileTaskFile],
    ) -> str:
        return _supervisor_blocked_run_python_message(
            tool_name=tool_name,
            tool_args=tool_args,
            request=request,
            files=files,
        )

    def _should_prompt_for_write_after_tool_round(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        tool_calls: List[Dict[str, Any]],
        round_index: int,
    ) -> bool:
        return _supervisor_should_prompt_for_write_after_tool_round(
            request=request,
            files=files,
            tool_calls=tool_calls,
            round_index=round_index,
        )

    def _write_retry_message(
        self, request: FileTaskRequest, files: List[FileTaskFile]
    ) -> str:
        return _supervisor_write_retry_message(request, files)

    def _duplicate_supervisor_retry_message(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        classification: FileTaskClassification,
        intent_plan: FileTaskIntentPlan,
        tool_calls: List[Dict[str, Any]],
    ) -> str:
        return _supervisor_duplicate_retry_message(
            request=request,
            files=files,
            classification=classification,
            intent_plan=intent_plan,
            tool_calls=tool_calls,
        )

    def _build_system_prompt(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        known_tool_gap: Optional[Dict[str, Any]] = None,
        classification: Optional[FileTaskClassification] = None,
        intent_plan: Optional[FileTaskIntentPlan] = None,
        execution_context: Optional[FileTaskExecutionContext] = None,
        recipe_skeleton: Optional[Dict[str, Any]] = None,
    ) -> str:
        resolved_context = execution_context or self._build_execution_context(
            request,
            files,
            known_tool_gap=known_tool_gap,
            classification=classification,
            intent_plan=intent_plan,
        )
        return build_file_task_runtime_system_prompt(
            request=request,
            files=files,
            classification=resolved_context.classification,
            intent_plan=resolved_context.intent_plan,
            known_tool_gap=resolved_context.known_tool_gap,
            recipe_skeleton=recipe_skeleton,
            execution_brief_schema=self._execution_brief_schema(),
            output_mode_guidance=self._output_mode_guidance,
            intent_plan_guidance=self._intent_plan_guidance,
            financial_chart_docx_enabled=self._looks_like_financial_xlsx_docx_chart_report_task(
                request, files
            ),
            display_path=self._display_path,
            first_file_name=self._first_file_name,
            current_date=_dt.datetime.now().strftime("%Y-%m-%d"),
        )

    def _build_messages(
        self,
        request: FileTaskRequest,
        snippets: List[Dict[str, Any]],
        files: List[FileTaskFile],
        known_tool_gap: Optional[Dict[str, Any]] = None,
        classification: Optional[FileTaskClassification] = None,
        intent_plan: Optional[FileTaskIntentPlan] = None,
        execution_context: Optional[FileTaskExecutionContext] = None,
        recipe_skeleton: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        resolved_context = execution_context or self._build_execution_context(
            request,
            files,
            known_tool_gap=known_tool_gap,
            classification=classification,
            intent_plan=intent_plan,
        )
        resolved_classification = resolved_context.classification
        resolved_intent_plan = resolved_context.intent_plan
        resolved_known_tool_gap = resolved_context.known_tool_gap
        return build_file_task_runtime_messages(
            request=request,
            snippets=snippets,
            files=files,
            classification=resolved_classification,
            intent_plan=resolved_intent_plan,
            known_tool_gap=resolved_known_tool_gap,
            recipe_skeleton=recipe_skeleton,
            execution_brief_schema=self._execution_brief_schema(),
        )

    def _followup_context(self, request: FileTaskRequest) -> Dict[str, Any]:
        return _build_followup_context(request)

    def _call_model(
        self,
        *,
        request: FileTaskRequest,
        messages: List[Dict[str, Any]],
        system: str,
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if hasattr(self._model_client, "call"):
            return self._model_client.call(request=request, messages=messages, system=system, tools=tools)  # type: ignore[union-attr]
        return self._model_client(request=request, messages=messages, system=system, tools=tools)  # type: ignore[misc]

    def _normalize_model_response(
        self,
        response: Dict[str, Any],
        tool_defs: List[Dict[str, Any]],
    ) -> tuple[str, List[Dict[str, Any]]]:
        return _model_response_normalize_model_response(response, tool_defs)

    def _coerce_tool_calls(self, raw_tool_calls: Any) -> List[Dict[str, Any]]:
        return _model_response_coerce_tool_calls(raw_tool_calls)

    def _tool_batch_signature(self, tool_calls: List[Dict[str, Any]]) -> str:
        return _model_response_tool_batch_signature(tool_calls)

    def _extract_file_changes(
        self, tool_name: str, tool_args: Dict[str, Any], result: Any
    ) -> List[Dict[str, Any]]:
        return _feedback_extract_file_changes(
            tool_name,
            tool_args,
            result,
            created_marker=KOTO_CREATED_RESULT_MARKER,
            modified_marker=KOTO_MODIFIED_RESULT_MARKER,
        )

    def _tool_result_for_model(self, tool_name: str, result: Any) -> Any:
        return _feedback_tool_result_for_model(
            tool_name,
            result,
            created_marker=KOTO_CREATED_RESULT_MARKER,
            modified_marker=KOTO_MODIFIED_RESULT_MARKER,
        )

    def _tool_feedback_for_model(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        model_result: Any,
        *,
        success: bool,
        blocked: bool = False,
        skipped: bool = False,
        invalid: bool = False,
    ) -> str:
        return _feedback_tool_feedback_for_model(
            tool_name,
            tool_args,
            model_result,
            success=success,
            blocked=blocked,
            skipped=skipped,
            invalid=invalid,
        )

    def _readonly_write_tool_block_message(
        self,
        tool_name: str,
        request: FileTaskRequest,
        output_mode: str,
    ) -> str:
        return _feedback_readonly_write_tool_block_message(
            tool_name=tool_name,
            task=request.task,
            mode_label=self._output_mode_label(output_mode),
        )

    def _readonly_run_python_write_block_message(
        self,
        tool_args: Dict[str, Any],
        request: FileTaskRequest,
        output_mode: str,
    ) -> str:
        return _feedback_readonly_run_python_write_block_message(
            tool_args=tool_args,
            task=request.task,
            mode_label=self._output_mode_label(output_mode),
            explicit_readonly=self._has_readonly_write_negation(request.task),
            strong_write_patterns=_RUN_PYTHON_STRONG_WRITE_PATTERNS,
            artifact_write_patterns=_RUN_PYTHON_ARTIFACT_WRITE_PATTERNS,
        )

    def _extract_tool_runtime_outcome(self, result: Any) -> Optional[Dict[str, Any]]:
        return _feedback_extract_tool_runtime_outcome(result)

    def _tool_runtime_status(
        self, tool_runtime_outcome: Optional[Dict[str, Any]]
    ) -> str:
        return _feedback_tool_runtime_status(tool_runtime_outcome)

    def _truncate_tool_feedback_value(self, value: Any, *, depth: int = 0) -> Any:
        return _feedback_truncate_tool_feedback_value(value, depth=depth)

    def _tool_artifacts(self, tool_name: str, result: Any) -> List[Dict[str, Any]]:
        return _feedback_tool_artifacts(tool_name, result)

    def _should_attempt_repair(
        self,
        check_payload: Optional[Dict[str, Any]],
        *,
        round_index: int,
        repair_attempts: int,
    ) -> bool:
        return _quality_should_attempt_repair(
            check_payload,
            round_index=round_index,
            repair_attempts=repair_attempts,
            max_rounds=self._max_rounds + _MAX_VERIFY_REPAIR_ATTEMPTS,
            max_repair_attempts=_MAX_VERIFY_REPAIR_ATTEMPTS,
        )

    def _change_operations(self, file_changes: List[Dict[str, Any]]) -> set[str]:
        return _quality_change_operations(file_changes)

    def _change_sum_int(self, file_changes: List[Dict[str, Any]], key: str) -> int:
        return _quality_change_sum_int(file_changes, key)

    def _target_or_request_type(
        self, request: FileTaskRequest, file_changes: List[Dict[str, Any]]
    ) -> str:
        return _quality_target_or_request_type(request, file_changes)

    def _quality_gate_result(
        self,
        *,
        criterion: str,
        passed: bool,
        detail: str,
        priority: str = "high",
    ) -> Dict[str, Any]:
        return _quality_gate_result(
            criterion=criterion,
            passed=passed,
            detail=detail,
            priority=priority,
        )

    def _evaluate_task_quality_gate(
        self,
        request: FileTaskRequest,
        file_changes: List[Dict[str, Any]],
        *,
        write_intent: bool,
        output_mode: str,
    ) -> Dict[str, Any]:
        return _quality_evaluate_task_quality_gate(
            request,
            file_changes,
            write_intent=write_intent,
            output_mode=output_mode,
        )

    def _repair_retry_message(
        self,
        request: FileTaskRequest,
        check_payload: Dict[str, Any],
        file_changes: List[Dict[str, Any]],
    ) -> str:
        return _quality_repair_retry_message(request, check_payload, file_changes)

    def _code_output_preview(
        self, tool_name: str, result: Any, result_text: str
    ) -> str:
        return _feedback_code_output_preview(tool_name, result, result_text)

    def _verify_task(
        self,
        request: FileTaskRequest,
        executor: ToolExecutor,
        file_changes: List[Dict[str, Any]],
        write_intent: bool,
        output_mode: str,
        model_failed: bool,
        readonly_fallback_used: bool = False,
        tool_runtime_outcome: Optional[Dict[str, Any]] = None,
        tool_gap: Optional[Dict[str, Any]] = None,
        next_action_artifact: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        runtime_status = self._tool_runtime_status(tool_runtime_outcome)
        precheck = _verification_precheck(
            request=request,
            file_changes=file_changes,
            write_intent=write_intent,
            model_failed=model_failed,
            readonly_fallback_used=readonly_fallback_used,
            runtime_status=runtime_status,
            tool_runtime_outcome=tool_runtime_outcome,
            tool_gap=tool_gap,
            next_action_artifact=next_action_artifact,
            requires_file_change_before_pause=self._requires_file_change_before_pause(request),
        )
        if precheck is not None:
            return precheck

        if file_changes:
            verify_target_path = self._verification_target_path(request, file_changes)
            verify_args = {
                "task_description": request.task,
                "file_states": json.dumps(
                    file_states_for_changes(file_changes, workspace_root=self._workspace_root), ensure_ascii=False
                ),
                "file_changes": json.dumps(file_changes, ensure_ascii=False),
                "target_path": verify_target_path,
                "model_mode": request.model_mode,
            }
            try:
                result = executor("verify_task_completion", verify_args)
                payload = _json_payload(result)
            except Exception as exc:
                logger.warning(
                    "[FileTaskRuntime] verify_task_completion failed: %s", exc
                )
                payload = {
                    "completed": False,
                    "summary": f"文件已变更，但 AI 核验工具不可用：{exc}",
                }

            if payload.get("error"):
                return {
                    "passed": False,
                    "status": "verify_error",
                    "summary": f"文件已变更，但核验工具返回错误：{payload.get('error')}",
                    "remaining": ["修复模型/核验工具配置后重新核验"],
                    "criteria_results": [
                        {
                            "criterion": "verification_tool_available",
                            "passed": False,
                            "detail": f"核验工具返回错误：{payload.get('error')}",
                            "priority": "critical",
                        }
                    ],
                }

            completed = payload.get("completed")
            passed = bool(completed) if completed is not None else True
            quality_gate = self._evaluate_task_quality_gate(
                request,
                file_changes,
                write_intent=write_intent,
                output_mode=output_mode,
            )
            verification_criteria = payload.get("criteria_results") or []
            combined_criteria = [
                *verification_criteria,
                *quality_gate.get("criteria_results", []),
            ]
            if not quality_gate.get("passed", True):
                remaining = list(quality_gate.get("remaining") or [])
                if payload.get("remaining_steps"):
                    remaining.extend(
                        str(item)
                        for item in payload.get("remaining_steps") or []
                        if str(item or "").strip()
                    )
                summary = "文件已有变更，但未满足本任务的关键质量门禁。"
                if remaining:
                    summary = f"{summary}还需处理：{remaining[0]}"
                return {
                    "passed": False,
                    "status": "quality_gate_failed",
                    "summary": summary,
                    "confidence": payload.get("confidence"),
                    "remaining": remaining or ["补齐任务要求的关键产物后重新核验"],
                    "criteria_results": combined_criteria,
                }
            return {
                "passed": passed,
                "status": "verified" if passed else "needs_attention",
                "summary": str(
                    payload.get("summary") or ("文件变更已记录。" if passed else "核验未通过。")
                ),
                "confidence": payload.get("confidence"),
                "remaining": payload.get("remaining_steps")
                or ([] if passed else ["根据核验结果继续修复"]),
                "criteria_results": combined_criteria,
            }

        return {
            "passed": True,
            "status": "completed" if not model_failed else "context_only",
            "summary": (
                "已完成分析建议，当前未直接写入文件。" if output_mode == "hybrid" else "已完成只读任务，没有产生文件写入。"
            ),
            "remaining": [],
        }

    def _readonly_task_requires_file_context(
        self, request: FileTaskRequest, context_files: List[FileTaskFile]
    ) -> bool:
        if context_files:
            return True
        if request.current_file or request.files or str(request.target_path or "").strip():
            return True
        return bool(
            re.search(
                r"\.(?:csv|docx?|md|pdf|pptx?|txt|xlsx?)(?=$|[^\w])",
                str(request.task or ""),
                re.IGNORECASE,
            )
        )

    def _unsatisfied_explicit_read_file_references(
        self,
        request: FileTaskRequest,
        snippets: List[Dict[str, Any]],
        readonly_tool_outputs: List[Dict[str, Any]],
    ) -> List[str]:
        references = self._file_references_in_task_text(request.task)
        if not references:
            return []
        satisfied_refs = [
            reference
            for reference in references
            if self._explicit_file_reference_was_read(
                reference, snippets, readonly_tool_outputs
            )
        ]
        if satisfied_refs:
            return [reference for reference in references if reference not in satisfied_refs]
        return references

    @staticmethod
    def _file_references_in_task_text(task: str) -> List[str]:
        task_text = str(task or "")
        if not task_text:
            return []
        pattern = re.compile(
            r"([^\s\"'<>|]+?\.(?:csv|docx?|md|pdf|pptx?|txt|xlsx?))(?=$|[\s,，。；;、!?！？)）\]】])",
            re.IGNORECASE,
        )
        references: List[str] = []
        seen: set[str] = set()
        for match in pattern.finditer(task_text):
            reference = match.group(1).strip(" \t\r\n,，。；;、!?！？()（）[]【】")
            if not reference:
                continue
            normalized = reference.replace("\\", "/").casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            references.append(reference)
        return references

    @staticmethod
    def _explicit_file_reference_was_read(
        reference: str,
        snippets: List[Dict[str, Any]],
        readonly_tool_outputs: List[Dict[str, Any]],
    ) -> bool:
        ref_norm = reference.replace("\\", "/").casefold()
        ref_name = Path(reference.replace("\\", "/")).name.casefold()
        def _matches_path(value: Any) -> bool:
            text = str(value or "").replace("\\", "/").casefold()
            if not text:
                return False
            return ref_norm in text or bool(ref_name and ref_name in text)
        for snippet in snippets:
            if any(
                _matches_path(snippet.get(key))
                for key in ("path", "source", "name")
            ):
                return True
        content_read_tools = {
            "parse_file_to_text",
            "read_sheet_data",
            "read_docx_content",
            "read_file_range",
            "inspect_workbook_structure",
            "audit_financial_workbook",
        }
        for output in readonly_tool_outputs:
            if str(output.get("tool_name") or "") not in content_read_tools:
                continue
            args = output.get("args")
            if isinstance(args, dict) and any(
                _matches_path(args.get(key)) for key in ("path", "file_path")
            ):
                return True
        return False
    def _requires_file_change_before_pause(self, request: FileTaskRequest) -> bool:
        request_files = getattr(request, "files", []) or []
        recipe_match = select_task_recipe(request, request_files, write_intent=True)
        if not recipe_match:
            return False
        if recipe_match.recipe.quality_gates:
            return any(
                str(gate.get("operation") or "").strip()
                for gate in recipe_match.recipe.quality_gates
            )
        return any(
            "file.changed" in str(item or "")
            for item in recipe_match.recipe.success_criteria
        )
