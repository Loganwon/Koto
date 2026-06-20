from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
import tempfile
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
    normalized_pdf_body as _normalized_pdf_body,
    pdf_context_read_args as _pdf_context_read_args,
    pdf_text_quality as _pdf_text_quality,
    should_force_pdf_tool_read as _should_force_pdf_tool_read,
    stepwise_pdf_step_index as _stepwise_pdf_step_index,
    stepwise_pdf_window_pages as _stepwise_pdf_window_pages,
)
from app.core.agent.file_task_capability import (
    build_request_capability_profiles,
    matched_native_capability_names,
    native_tool_gap_for_request,
)
from app.core.agent.file_task_completion_contract import build_completion_contract
from app.core.agent.file_task_model import FileTaskModelClient
from app.core.agent.file_task_review_intent import (
    has_explicit_docx_review_intent,
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
    FileTaskRecipeMatch,
    recipe_matches,
    request_file_types,
    request_target_file_type,
    select_task_recipe,
    semantic_markers,
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
from app.core.agent.file_task_prompt_sections import (
    clear_docx_review_guidance as _prompt_clear_docx_review_guidance,
    docx_compare_annotate_guidance as _prompt_docx_compare_annotate_guidance,
    financial_chart_docx_guidance as _prompt_financial_chart_docx_guidance,
    followup_guidance as _prompt_followup_guidance,
    single_docx_annotate_guidance as _prompt_single_docx_annotate_guidance,
)
from app.core.agent.file_task_messages import (
    build_file_task_messages as _build_file_task_messages,
)
from app.core.agent.file_task_followup_context import (
    followup_context as _build_followup_context,
)
from app.core.agent.file_task_system_prompt import (
    build_file_task_system_prompt as _build_file_task_system_prompt,
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
from app.core.agent.file_task_docx_stepwise import (
    docx_polish_wait_artifact as _docx_stepwise_docx_polish_wait_artifact,
    docx_polish_window_prompt as _docx_stepwise_docx_polish_window_prompt,
    parse_polished_docx_paragraphs as _docx_stepwise_parse_polished_docx_paragraphs,
    read_docx_paragraph_window as _docx_stepwise_read_docx_paragraph_window,
    rewrite_docx_paragraph_window as _docx_stepwise_rewrite_docx_paragraph_window,
    simple_polish_docx_paragraph as _docx_stepwise_simple_polish_docx_paragraph,
    stepwise_docx_polish_target_path as _docx_stepwise_polish_target_path,
)
from app.core.agent.file_task_builtin_tool_runner import (
    run_builtin_tool as _builtin_tool_runner_run_builtin_tool,
)
from app.core.agent.file_task_intent_adjudication import (
    classification_task_text as _intent_adjudication_classification_task_text,
    intent_adjudicator_messages as _intent_adjudication_messages,
    intent_adjudicator_system_prompt as _intent_adjudication_system_prompt,
    normalize_intent_adjudication_response as _intent_adjudication_normalize_response,
    request_with_task as _intent_adjudication_request_with_task,
    should_adjudicate_intent as _intent_adjudication_should_adjudicate_intent,
)
from app.core.agent.file_task_classification_contract import (
    apply_intent_adjudication as _classification_contract_apply_intent_adjudication,
    demote_classification_to_read as _classification_contract_demote_to_read,
    docx_annotation_has_contract as _classification_contract_docx_annotation_has_contract,
    has_create_or_export_contract as _classification_contract_has_create_or_export_contract,
    normalize_mainline_contract as _classification_contract_normalize_mainline,
    refresh_classification_recipe as _classification_contract_refresh_recipe,
    write_has_contract_anchor as _classification_contract_write_has_contract_anchor,
)
from app.core.agent.file_task_classification_semantics import (
    infer_task_family_operation as _classification_semantics_infer_task_family_operation,
    semantic_reason_codes as _classification_semantics_reason_codes,
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

    def run(self, request: FileTaskRequest) -> Iterable[FileTaskEvent]:
        request = request_with_workflow_checkpoint(request)
        request = self._request_with_inferred_target_path(request)
        ledger = FileTaskLedger(request.run_id)
        if self._is_cancelled(request):
            yield self._cancelled_event(ledger, request)
            return

        context_files = self._context_files(request)
        base_classification = self._classify_request(request, context_files)
        intent_adjudication = self._adjudicate_intent_if_needed(
            request, context_files, base_classification
        )
        classification = self._apply_intent_adjudication(
            request, context_files, base_classification, intent_adjudication
        )
        classification = self._normalize_mainline_contract(
            request, context_files, classification
        )

        execution_context = self._build_execution_context(
            request,
            context_files,
            classification=classification,
            intent_adjudication=intent_adjudication,
            quick_action_mode=self._quick_action_mode(request),
        )
        known_tool_gap = execution_context.known_tool_gap
        classification = execution_context.classification
        intent_plan = execution_context.intent_plan
        requirements = execution_context.requirements
        plan_check = execution_context.plan_check
        quick_action_mode = execution_context.quick_action_mode
        simple_quick_action = execution_context.simple_quick_action
        write_intent = execution_context.write_intent
        if classification.execution_mode != "doc_annotate_bridge":
            from app.core.agent import file_task_doc_annotate_boundary

            if (
                file_task_doc_annotate_boundary.should_use_bridge_execution(request)
                and self._docx_annotation_has_contract(
                    request, context_files, classification
                )
            ):
                classification.execution_mode = "doc_annotate_bridge"
                classification.task_family = "annotate"
                classification.operation_kind = "annotate"
                classification.output_mode = "write"
                classification.write_intent = True
                classification.docx_annotation_request = True
                if "annotate_file" not in classification.matched_capabilities:
                    classification.matched_capabilities.append("annotate_file")
                if "read_docx_content" not in classification.matched_capabilities:
                    classification.matched_capabilities.append("read_docx_content")
                if not classification.selected_recipe:
                    classification.selected_recipe = (
                        file_task_doc_annotate_boundary.bridge_recipe_id(request)
                    )
                classification.reason_codes.append(
                    "doc_annotate_bridge_execution_fallback"
                )
                write_intent = True
        bridge_execution_mode = classification.execution_mode == "doc_annotate_bridge"
        if bridge_execution_mode:
            tool_defs = []
            executor = None
        else:
            gateway = self._build_tool_gateway(request, context_files)
            tool_defs = self._tool_defs_for_classification(
                gateway.definitions(),
                classification,
            )
            executor = gateway.execute
        recipe_skeleton = build_recipe_skeleton(
            request,
            context_files,
            classification,
            intent_plan,
            tool_defs,
        )
        completion_contract = build_completion_contract(
            request,
            context_files,
            classification,
            intent_plan,
            requirements,
            recipe_skeleton,
        )
        completion_contract_payload = completion_contract.public_dict()
        completion_criteria = completion_contract.success_criteria()
        workflow_state = build_workflow_state(
            request,
            context_files,
            classification,
            recipe_skeleton,
            completion_contract=completion_contract_payload,
        )
        constraint_audit = self._constraint_audit(
            request,
            context_files,
            classification,
            intent_plan,
            requirements,
            recipe_skeleton,
        )
        supervisor_audit = build_supervisor_audit(
            request=request,
            files=context_files,
            classification=classification,
            intent_plan=intent_plan,
            requirements=requirements,
            plan_check=plan_check,
            constraint_audit=constraint_audit,
        )
        supervisor_audit_payload = supervisor_audit.public_dict()
        workflow_state["supervisor_audit"] = supervisor_audit_payload

        classification_payload = classification.public_dict()
        intent_plan_payload = intent_plan.public_dict()
        requirements_payload = requirements.public_dict()
        plan_check_payload = plan_check.public_dict()
        plan_runtime = self._build_runtime_metadata(
            terminal_status="plan_checked",
            readonly_fallback_used=False,
            model_failed=False,
            planner_payload={
                "backend": execution_context.effective_planner_backend or "native",
                "source": "native",
                "policy": execution_context.effective_planner_policy or "native_only",
                "transport": "native",
                "reason": execution_context.effective_planner_reason
                or "file_task_native_only",
                "round": 1,
            },
            planner_fallback_payload={},
        )

        yield ledger.event(
            "run.started",
            {
                "task": request.task,
                "mode": "whitebox_v1",
                "file_count": len(context_files),
                "target_path": request.target_path,
                "model_mode": request.model_mode,
                "model_id": request.model_id,
                "quick_action_mode": quick_action_mode,
                "workflow_version": recipe_skeleton.get("version"),
                "recipe_skeleton": recipe_skeleton,
                "completion_contract": completion_contract_payload,
                "workflow_state": workflow_state,
                "constraint_audit": constraint_audit,
                "supervisor_audit": supervisor_audit_payload,
                **classification_payload,
                "intent_plan": intent_plan_payload,
            },
        )
        yield ledger.event(
            "supervisor.status",
            supervisor_status_payload(
                workflow_state,
                stage="planned",
                summary=supervisor_audit.summary,
                active_step_id="read_context",
                supervisor_audit=supervisor_audit_payload,
            ),
            step_id="plan",
        )

        if self._is_cancelled(request):
            yield self._cancelled_event(ledger, request)
            return

        if not simple_quick_action:
            yield ledger.event(
                "task.classified",
                {
                    **execution_context.public_dict(),
                    "workflow_state": workflow_state,
                    "supervisor_audit": supervisor_audit_payload,
                },
                step_id="plan",
            )
        yield ledger.event(
            "plan.checked",
            {
                **plan_check_payload,
                "requirements": requirements_payload,
                "completion_contract": completion_contract_payload,
                "constraint_audit": constraint_audit,
                "workflow_state": workflow_state,
                "supervisor_audit": supervisor_audit_payload,
                **(
                    {
                        "quick_action_bypass": True,
                    }
                    if simple_quick_action
                    else {}
                ),
            },
            step_id="plan",
        )

        if not supervisor_audit.execution_allowed and plan_check.passed:
            yield ledger.event(
                "supervisor.intervention",
                {
                    "reason": "supervisor_audit_blocked",
                    "summary": supervisor_audit.summary,
                    "supervisor_audit": supervisor_audit_payload,
                    "constraint_audit": constraint_audit,
                    "plan_check": plan_check_payload,
                },
                step_id="plan",
            )
            yield ledger.event(
                "step.result",
                self._build_step_result_payload(
                    title="监管检查",
                    summary=supervisor_audit.summary,
                    status="failed",
                    runtime=plan_runtime,
                    passed=False,
                    supervisor_audit=supervisor_audit_payload,
                ),
                step_id="plan",
            )
            yield ledger.event(
                "run.finished",
                {
                    "task": request.task,
                    "mode": "whitebox_v1",
                    "summary": supervisor_audit.summary,
                    "completed_task": False,
                    "context": [],
                    "file_changes": [],
                    "runtime": plan_runtime,
                    "quick_action_mode": quick_action_mode,
                    "intent_plan": intent_plan_payload,
                    "requirements": requirements_payload,
                    "plan_check": plan_check_payload,
                    "recipe_skeleton": recipe_skeleton,
                    "completion_contract": completion_contract_payload,
                    "workflow_state": workflow_state,
                    "constraint_audit": constraint_audit,
                    "supervisor_audit": supervisor_audit_payload,
                    **classification_payload,
                },
            )
            return

        if not plan_check.passed:
            yield ledger.event(
                "step.result",
                self._build_step_result_payload(
                    title="规划检查",
                    summary=plan_check.summary,
                    status="failed",
                    runtime=plan_runtime,
                    passed=False,
                ),
                step_id="plan",
            )
            yield ledger.event(
                "run.finished",
                {
                    "task": request.task,
                    "mode": "whitebox_v1",
                    "summary": plan_check.summary,
                    "completed_task": False,
                    "context": [],
                    "file_changes": [],
                    "runtime": plan_runtime,
                    "quick_action_mode": quick_action_mode,
                    "intent_plan": intent_plan_payload,
                    "requirements": requirements_payload,
                    "plan_check": plan_check_payload,
                    "recipe_skeleton": recipe_skeleton,
                    "completion_contract": completion_contract_payload,
                    "workflow_state": workflow_state,
                    "constraint_audit": constraint_audit,
                    "supervisor_audit": supervisor_audit_payload,
                    **classification_payload,
                },
            )
            return

        plan_steps = intent_plan.dynamic_steps or self._build_plan(
            request,
            context_files,
            write_intent,
            classification.output_mode,
            known_tool_gap,
        )
        if not simple_quick_action:
            yield ledger.event(
                "plan.created",
                {
                    "summary": self._plan_summary(request, context_files, write_intent),
                    "steps": plan_steps,
                    "success_criteria": completion_criteria,
                    "tool_families": supported_file_workflows(),
                    "intent_plan": intent_plan_payload,
                    "recipe_skeleton": recipe_skeleton,
                    "completion_contract": completion_contract_payload,
                    "workflow_state": workflow_state,
                    "constraint_audit": constraint_audit,
                    "supervisor_audit": supervisor_audit_payload,
                },
            )

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

        context_step_id = "context"
        if self._is_cancelled(request):
            yield self._cancelled_event(ledger, request)
            return
        yield ledger.event(
            "step.started",
            {
                "title": "读取显式上下文",
                "detail": "只使用用户附加、选中或明确指向的文件。",
            },
            step_id=context_step_id,
        )

        snippets: List[Dict[str, Any]] = []
        if request.selection:
            snippets.append(
                {
                    "source": request.selection_source or "selection",
                    "preview": _preview(request.selection, 500),
                    "chars": len(request.selection),
                }
            )
            yield ledger.event(
                "tool.finished",
                {
                    "tool_name": "selection_context",
                    "success": True,
                    "result_preview": _preview(request.selection, 500),
                },
                step_id=context_step_id,
            )

        for file_info in context_files:
            if self._is_cancelled(request):
                yield self._cancelled_event(ledger, request)
                return
            if self._should_skip_uncreated_target_context(request, file_info):
                continue
            if (
                _looks_like_windowed_pdf_task(request, recipe_skeleton)
                and file_info.target
                and _file_task_suffix(file_info) in {"doc", "docx"}
            ):
                continue
            force_pdf_tool_read = _should_force_pdf_tool_read(
                request, file_info, recipe_skeleton
            )
            if file_info.content and not force_pdf_tool_read:
                snippets.append(
                    {
                        "source": file_info.name or file_info.path,
                        "path": file_info.path,
                        "preview": _preview(file_info.content, 500),
                        "chars": len(file_info.content),
                    }
                )
                yield ledger.event(
                    "tool.finished",
                    {
                        "tool_name": "provided_file_context",
                        "success": True,
                        "path": file_info.path,
                        "result_preview": _preview(file_info.content, 500),
                    },
                    step_id=context_step_id,
                )
                continue

            if not file_info.path:
                continue
            window_args = window_read_args_for_file(
                workflow_state,
                file_info,
                default_max_chars=_READ_LIMIT,
            )
            args = window_args or (
                _pdf_context_read_args(request, file_info, recipe_skeleton)
                if force_pdf_tool_read
                else {"path": file_info.path, "max_chars": _READ_LIMIT}
            )
            yield ledger.event(
                "tool.started",
                {
                    "tool_name": "parse_file_to_text",
                    "tool_args": args,
                },
                step_id=context_step_id,
            )
            try:
                result = executor("parse_file_to_text", args)
                success = not _is_error_result(result)
                if (
                    success
                    and force_pdf_tool_read
                    and args.get("start_page")
                    and not _pdf_text_quality(result).get("usable")
                ):
                    window_pages = max(
                        1,
                        int(args.get("end_page") or args.get("start_page") or 1)
                        - int(args.get("start_page") or 1)
                        + 1,
                    )
                    for _retry_index in range(3):
                        retry_args = dict(args)
                        retry_start = int(retry_args.get("start_page") or 1) + (
                            window_pages * (_retry_index + 1)
                        )
                        retry_args["start_page"] = retry_start
                        retry_args["end_page"] = retry_start + window_pages - 1
                        retry_result = executor("parse_file_to_text", retry_args)
                        if _is_error_result(retry_result):
                            continue
                        if _pdf_text_quality(retry_result).get("usable"):
                            args = retry_args
                            result = retry_result
                            success = True
                            break
            except Exception as exc:
                result = str(exc)
                success = False
                logger.warning("[FileTaskRuntime] parse_file_to_text failed: %s", exc)
            yield ledger.event(
                "tool.finished",
                {
                    "tool_name": "parse_file_to_text",
                    "success": success,
                    "result_preview": _preview(result),
                },
                step_id=context_step_id,
            )
            if success:
                snippet = {
                    "source": file_info.name or file_info.path,
                    "path": file_info.path,
                    "preview": _preview(result, 500),
                    "chars": len(str(result or "")),
                }
                if str(Path(str(file_info.path or "")).suffix).lower() == ".pdf":
                    if args.get("start_page"):
                        snippet["start_page"] = int(args.get("start_page") or 1)
                    if args.get("end_page"):
                        snippet["end_page"] = int(args.get("end_page") or 0)
                    snippet["_raw_text"] = str(result or "")
                window_unit = str(args.get("window_unit") or "").strip()
                if window_unit:
                    snippet["window_unit"] = window_unit
                    if args.get("start"):
                        snippet["window_start"] = int(args.get("start") or 1)
                    if args.get("end"):
                        snippet["window_end"] = int(args.get("end") or 0)
                    if "sheet_index" in args:
                        snippet["sheet_index"] = int(args.get("sheet_index") or 0)
                snippets.append(snippet)

        context_summary = (
            f"已整理 {len(snippets)} 份上下文片段。" if snippets else "没有显式文件或选区可读取。"
        )
        yield ledger.event(
            "step.finished",
            {
                "summary": context_summary,
            },
            step_id=context_step_id,
        )
        yield ledger.event(
            "step.result",
            self._build_step_result_payload(
                title="读取显式上下文",
                summary=context_summary,
                status="completed" if snippets else "needs_attention",
                snippet_count=len(snippets),
                snippets=snippets,
            ),
            step_id=context_step_id,
        )
        yield ledger.event(
            "supervisor.status",
            supervisor_status_payload(
                workflow_state,
                stage="reading",
                summary=context_summary,
                active_step_id="model_reasoning",
                completed_step_ids=["read_context"],
            ),
            step_id=context_step_id,
        )

        execute_step_id = "execute"
        yield ledger.event(
            "step.started",
            {
                "title": "模型规划并调用工具",
                "detail": "模型只能调用 Koto 文件工具目录中的 allowlist 工具。",
                "max_rounds": self._max_rounds,
            },
            step_id=execute_step_id,
        )
        yield ledger.event(
            "supervisor.status",
            supervisor_status_payload(
                workflow_state,
                stage="analyzing",
                summary="模型正在按主线计划选择 Koto 文件工具。",
                active_step_id="model_reasoning",
                completed_step_ids=["read_context"],
            ),
            step_id=execute_step_id,
        )

        messages = self._build_messages(
            request,
            snippets,
            context_files,
            known_tool_gap,
            classification,
            intent_plan,
            execution_context=execution_context,
            recipe_skeleton=recipe_skeleton,
        )
        system = self._build_system_prompt(
            request,
            context_files,
            known_tool_gap,
            classification,
            intent_plan,
            execution_context=execution_context,
            recipe_skeleton=recipe_skeleton,
        )
        model_request = self._initial_model_request(request)
        completed_write_ops: Dict[str, int] = {}
        file_changes: List[Dict[str, Any]] = []
        final_summary = ""
        completed_task = False
        model_failed = False
        readonly_fallback_used = False
        last_tool_batch_signature = ""
        planner_runtime_payload: Dict[str, Any] = {}
        planner_fallback_runtime_payload: Dict[str, Any] = {}
        last_tool_gap_signature = ""
        plan_confirmed_emitted = False
        last_execution_brief_signature = ""
        write_guard_injected = False
        readonly_answer_guard_injected = False
        duplicate_supervisor_guard_injected = False
        readonly_tool_outputs: List[Dict[str, Any]] = []
        repair_attempts = 0
        last_check_payload: Optional[Dict[str, Any]] = None
        pending_repair_check_payload: Optional[Dict[str, Any]] = None
        tool_gap: Optional[Dict[str, Any]] = None
        next_action_artifact: Optional[Dict[str, Any]] = None
        tool_runtime_outcome: Optional[Dict[str, Any]] = None
        generated_artifacts: List[Dict[str, Any]] = []
        active_execution_plan: Optional[WhiteboxExecutionPlan] = None
        last_execution_plan_signature = ""

        for round_index in range(1, self._max_rounds + 1):
            if self._is_cancelled(request):
                yield self._cancelled_event(ledger, request)
                return
            planner_fallback_runtime_payload = {}
            yield ledger.event(
                "model.call.started",
                {
                    "round": round_index,
                    "model_mode": request.model_mode,
                    "model_id": request.model_id,
                    "tool_count": len(tool_defs),
                    "message_count": len(messages),
                },
                step_id=execute_step_id,
            )
            try:
                response = self._call_model(
                    request=model_request,
                    messages=messages,
                    system=system,
                    tools=tool_defs,
                )
            except Exception as exc:
                logger.warning("[FileTaskRuntime] model call failed: %s", exc)
                yield ledger.event(
                    "model.call.finished",
                    {
                        "round": round_index,
                        "success": False,
                        "model_mode": request.model_mode,
                        "model_id": request.model_id,
                        "error": _preview(str(exc), 240),
                    },
                    step_id=execute_step_id,
                )
                deterministic_change = yield from self._write_stepwise_pdf_docx_native(
                    ledger,
                    request,
                    executor,
                    snippets,
                    context_files,
                    recipe_skeleton,
                    execute_step_id,
                    reason="model_unavailable",
                    fallback=True,
                    model_unavailable=True,
                )
                if deterministic_change:
                    file_changes.append(deterministic_change)
                    completed_task = True
                    model_failed = True
                    final_summary = str(
                        deterministic_change.get("summary")
                        or "模型不可用，已使用 Koto 原生流程写入当前分步结果。"
                    )
                    yield ledger.event(
                        "file.changed", deterministic_change, step_id=execute_step_id
                    )
                    yield ledger.event(
                        "step.result",
                        self._build_step_result_payload(
                            title="模型不可用兜底写入",
                            summary=final_summary,
                            status="completed",
                            round_index=round_index,
                            file_changes=file_changes,
                        ),
                        step_id=execute_step_id,
                    )
                    break
                fallback_summary = (
                    ""
                    if write_intent
                    else self._fallback_readonly_summary(
                        request,
                        snippets,
                        context_files,
                        exc,
                    )
                )
                if fallback_summary:
                    readonly_fallback_used = True
                    completed_task = True
                    final_summary = fallback_summary
                    yield ledger.event(
                        "tool.finished",
                        {
                            "tool_name": "model_message",
                            "success": True,
                            "fallback": True,
                            "model_unavailable": True,
                            "result_preview": fallback_summary,
                        },
                        step_id=execute_step_id,
                    )
                    yield ledger.event(
                        "step.result",
                        self._build_step_result_payload(
                            title="模型规划并调用工具",
                            summary=fallback_summary,
                            status="completed",
                            round_index=round_index,
                        ),
                        step_id=execute_step_id,
                    )
                else:
                    model_failed = True
                    error_text = f"模型调用失败：{exc}"
                    yield ledger.event(
                        "run.error",
                        {
                            "text": error_text,
                            "recoverable": not write_intent,
                        },
                        step_id=execute_step_id,
                    )
                    yield ledger.event(
                        "step.result",
                        self._build_step_result_payload(
                            title="模型规划并调用工具",
                            summary=error_text,
                            status="failed",
                            round_index=round_index,
                        ),
                        step_id=execute_step_id,
                    )
                break

            if self._is_cancelled(request):
                yield self._cancelled_event(ledger, request)
                return

            planner_runtime_payload = {
                "backend": execution_context.effective_planner_backend or "native",
                "source": "native",
                "policy": execution_context.effective_planner_policy or "native_only",
                "transport": "native",
                "reason": execution_context.effective_planner_reason
                or "file_task_native_only",
                "round": round_index,
            }
            planner_meta = dict(planner_runtime_payload)

            tool_gap = extract_tool_gap_from_response(response)
            if tool_gap and known_tool_gap:
                tool_gap = merge_tool_gaps(tool_gap, known_tool_gap)
            content_text, tool_calls = self._normalize_model_response(
                response, tool_defs
            )
            yield ledger.event(
                "model.call.finished",
                {
                    "round": round_index,
                    "success": True,
                    "model_mode": request.model_mode,
                    "model_id": request.model_id,
                    "tool_call_count": len(tool_calls),
                    "content_chars": len(content_text or ""),
                    "has_execution_plan": bool(
                        isinstance(response, dict)
                        and (
                            isinstance(response.get("execution_plan"), dict)
                            or isinstance(response.get("plan"), dict)
                        )
                    ),
                    "has_tool_gap": bool(tool_gap),
                },
                step_id=execute_step_id,
            )
            execution_brief, content_text = self._extract_execution_brief(
                response, content_text
            )
            tool_execution_brief, tool_calls = self._extract_execution_brief_tool_call(
                tool_calls
            )
            if tool_execution_brief and not execution_brief:
                execution_brief = tool_execution_brief
            execution_plan = extract_whitebox_execution_plan(response, content_text)
            if execution_plan:
                plan_payload = execution_plan.public_dict()
                plan_signature = json.dumps(
                    plan_payload, ensure_ascii=False, sort_keys=True, default=str
                )
                if plan_signature != last_execution_plan_signature:
                    active_execution_plan = execution_plan
                    last_execution_plan_signature = plan_signature
                    yield ledger.event(
                        "plan.proposed", plan_payload, step_id=execute_step_id
                    )
                    gate_payload = validate_whitebox_plan(
                        execution_plan, recipe_skeleton
                    )
                    yield ledger.event(
                        "plan.gated", gate_payload, step_id=execute_step_id
                    )
                    if not gate_payload.get("passed"):
                        if round_index < self._max_rounds:
                            repair_message = self._whitebox_plan_repair_message(
                                gate_payload, recipe_skeleton
                            )
                            yield ledger.event(
                                "tool.finished",
                                {
                                    "tool_name": "plan_gate",
                                    "success": False,
                                    "result_preview": repair_message,
                                },
                                step_id=execute_step_id,
                            )
                            messages.append({"role": "user", "content": repair_message})
                            continue
                        final_summary = str(gate_payload.get("summary") or "白盒计划审查未通过。")
                        completed_task = False
                        yield ledger.event(
                            "step.result",
                            self._build_step_result_payload(
                                title="白盒计划审查",
                                summary=final_summary,
                                status="failed",
                                round_index=round_index,
                            ),
                            step_id=execute_step_id,
                        )
                        break
            external_planner_request = False
            if (
                not tool_gap
                and known_tool_gap
                and not tool_calls
                and not external_planner_request
                and not bool(
                    (model_request.options or {}).get(
                        "planner_runtime_fallback_attempted"
                    )
                )
            ):
                tool_gap = known_tool_gap

            if execution_brief:
                brief_payload = execution_brief.public_dict()
                brief_signature = json.dumps(
                    brief_payload, ensure_ascii=False, sort_keys=True, default=str
                )
                if brief_signature != last_execution_brief_signature:
                    last_execution_brief_signature = brief_signature
                    yield ledger.event(
                        "plan.briefed", brief_payload, step_id=execute_step_id
                    )

            if tool_gap:
                gap_runtime = self._build_runtime_metadata(
                    terminal_status="tool_gap",
                    readonly_fallback_used=readonly_fallback_used,
                    model_failed=model_failed,
                    planner_payload=planner_runtime_payload,
                    planner_fallback_payload=planner_fallback_runtime_payload,
                )
                next_action_artifact = self._with_runtime_context(
                    build_next_action_artifact(request, tool_gap),
                    gap_runtime,
                )
                gap_payload = {
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
                    "round": round_index,
                }
                gap_signature = json.dumps(
                    gap_payload, ensure_ascii=False, sort_keys=True, default=str
                )
                if gap_signature != last_tool_gap_signature:
                    last_tool_gap_signature = gap_signature
                    yield ledger.event(
                        "tool.missing", gap_payload, step_id=execute_step_id
                    )

            if tool_calls and not plan_confirmed_emitted:
                tool_gate_payload = validate_whitebox_plan(
                    active_execution_plan,
                    recipe_skeleton,
                    tool_calls=tool_calls,
                )
                yield ledger.event(
                    "plan.gated", tool_gate_payload, step_id=execute_step_id
                )
                if not tool_gate_payload.get("passed"):
                    if round_index < self._max_rounds:
                        repair_message = self._whitebox_plan_repair_message(
                            tool_gate_payload, recipe_skeleton
                        )
                        yield ledger.event(
                            "supervisor.intervention",
                            {
                                "reason": "plan_gate_failed",
                                "summary": repair_message,
                                "gate": tool_gate_payload,
                            },
                            step_id=execute_step_id,
                        )
                        messages.append({"role": "user", "content": repair_message})
                        continue
                    final_summary = str(
                        tool_gate_payload.get("summary") or "工具计划未通过白盒审查。"
                    )
                    completed_task = False
                    yield ledger.event(
                        "step.result",
                        self._build_step_result_payload(
                            title="白盒计划审查",
                            summary=final_summary,
                            status="failed",
                            round_index=round_index,
                        ),
                        step_id=execute_step_id,
                    )
                    break
                plan_confirmed_emitted = True
                yield ledger.event(
                    "plan.confirmed",
                    self._build_confirmed_plan(
                        request,
                        context_files,
                        tool_calls,
                        write_intent,
                        content_text,
                    ),
                    step_id=execute_step_id,
                )

            if content_text and (not tool_calls or len(content_text) <= 220):
                yield ledger.event(
                    "tool.finished",
                    {
                        "tool_name": "model_message",
                        "success": True,
                        "result_preview": _preview(content_text, 600),
                    },
                    step_id=execute_step_id,
                )

            model_turn: Dict[str, Any] = {
                "role": "model",
                "content": content_text or "",
            }
            if isinstance(response, dict) and response.get("reasoning_content"):
                model_turn["reasoning_content"] = str(
                    response.get("reasoning_content") or ""
                )
            if tool_calls:
                for tool_call in tool_calls:
                    tool_call.setdefault("id", uuid.uuid4().hex[:8])
                model_turn["tool_calls"] = tool_calls
            raw_parts = (
                response.get("_raw_parts") if isinstance(response, dict) else None
            )
            if raw_parts:
                model_turn["parts"] = raw_parts
            if tool_gap:
                model_turn["tool_gap"] = tool_gap
            messages.append(model_turn)

            if not tool_calls:
                if tool_gap:
                    final_summary = content_text or str(
                        tool_gap.get("summary") or "当前任务缺少对应的 Koto 原生工具。"
                    )
                    completed_task = False
                    yield ledger.event(
                        "step.result",
                        self._build_step_result_payload(
                            title="模型规划并调用工具",
                            summary=final_summary,
                            status="failed",
                            round_index=round_index,
                            file_changes=file_changes,
                            next_action_artifact=next_action_artifact,
                        ),
                        step_id=execute_step_id,
                    )
                    break
                if execution_brief and round_index < self._max_rounds:
                    model_request = self._request_after_execution_brief(
                        request, model_request, execution_brief
                    )
                    reminder = self._execution_brief_continue_message(
                        request, execution_brief
                    )
                    final_summary = (
                        execution_brief.summary or content_text or "已完成任务分析，准备继续执行。"
                    )
                    yield ledger.event(
                        "step.result",
                        self._build_step_result_payload(
                            title="模型规划并调用工具",
                            summary=final_summary,
                            status="pending",
                            round_index=round_index,
                            file_changes=file_changes,
                        ),
                        step_id=execute_step_id,
                    )
                    messages.append({"role": "user", "content": reminder})
                    continue
                if execution_plan and round_index < self._max_rounds:
                    reminder = self._execution_plan_continue_message(
                        request, execution_plan, recipe_skeleton
                    )
                    final_summary = (
                        execution_plan.plan_summary
                        or execution_plan.goal
                        or content_text
                        or "已完成白盒计划，准备继续执行。"
                    )
                    yield ledger.event(
                        "step.result",
                        self._build_step_result_payload(
                            title="白盒执行计划",
                            summary=final_summary,
                            status="pending",
                            round_index=round_index,
                            file_changes=file_changes,
                        ),
                        step_id=execute_step_id,
                    )
                    messages.append({"role": "user", "content": reminder})
                    continue
                runtime_status = self._tool_runtime_status(tool_runtime_outcome)
                awaiting_confirmation = runtime_status == "awaiting_confirmation"
                terminal_write_blocked = runtime_status in {"blocked", "write_blocked"}
                if (
                    write_intent
                    and not file_changes
                    and not awaiting_confirmation
                    and not terminal_write_blocked
                    and not write_guard_injected
                    and round_index < self._max_rounds
                ):
                    write_guard_injected = True
                    reminder = self._write_retry_message(request, context_files)
                    yield ledger.event(
                        "tool.finished",
                        {
                            "tool_name": "write_guard",
                            "success": False,
                            "result_preview": reminder,
                        },
                        step_id=execute_step_id,
                    )
                    messages.append({"role": "user", "content": reminder})
                    final_summary = content_text or "模型未再请求工具调用。"
                    yield ledger.event(
                        "step.result",
                        self._build_step_result_payload(
                            title="模型规划并调用工具",
                            summary=reminder,
                            status="needs_attention",
                            round_index=round_index,
                        ),
                        step_id=execute_step_id,
                    )
                    continue
                if (
                    write_intent
                    and pending_repair_check_payload
                    and round_index < self._max_rounds
                ):
                    repair_message = self._repair_retry_message(
                        request,
                        pending_repair_check_payload,
                        file_changes,
                    )
                    yield ledger.event(
                        "tool.finished",
                        {
                            "tool_name": "repair_guard",
                            "success": False,
                            "result_preview": (
                                "修复轮尚未产生新的文件变更，不能用旧结果通过核验。\n"
                                f"{repair_message}"
                            ),
                        },
                        step_id=execute_step_id,
                    )
                    messages.append({"role": "user", "content": repair_message})
                    final_summary = content_text or "核验失败后的修复尚未完成。"
                    yield ledger.event(
                        "step.result",
                        self._build_step_result_payload(
                            title="修复监管",
                            summary=final_summary,
                            status="needs_attention",
                            round_index=round_index,
                            file_changes=file_changes,
                        ),
                        step_id=execute_step_id,
                    )
                    continue
                if write_intent:
                    last_check_payload = self._verify_task(
                        request,
                        executor,
                        file_changes,
                        write_intent,
                        classification.output_mode,
                        model_failed,
                        readonly_fallback_used=readonly_fallback_used,
                        tool_runtime_outcome=tool_runtime_outcome,
                        tool_gap=tool_gap,
                        next_action_artifact=next_action_artifact,
                    )
                    if self._should_attempt_repair(
                        last_check_payload,
                        round_index=round_index,
                        repair_attempts=repair_attempts,
                    ):
                        repair_attempts += 1
                        repair_runtime = self._build_runtime_metadata(
                            terminal_status=str(
                                last_check_payload.get("status") or ""
                            ).strip(),
                            readonly_fallback_used=readonly_fallback_used,
                            model_failed=model_failed,
                            planner_payload=planner_runtime_payload,
                            planner_fallback_payload=planner_fallback_runtime_payload,
                        )
                        repair_check_payload = dict(last_check_payload)
                        repair_check_payload["runtime"] = repair_runtime
                        repair_check_payload["repair_attempt"] = repair_attempts
                        yield ledger.event(
                            "check.started",
                            {
                                "title": "检查执行状态",
                                "criteria": completion_criteria,
                                "repair_attempt": repair_attempts,
                            },
                            step_id="check",
                        )
                        yield ledger.event(
                            "check.finished", repair_check_payload, step_id="check"
                        )
                        yield ledger.event(
                            "step.result",
                            self._build_step_result_payload(
                                title="检查执行状态",
                                summary=str(
                                    repair_check_payload.get("summary") or "检查未通过。"
                                ),
                                status=(
                                    "completed"
                                    if repair_check_payload.get("passed")
                                    else "needs_attention"
                                ),
                                runtime=repair_runtime,
                                passed=repair_check_payload.get("passed"),
                                file_changes=file_changes,
                                next_action_artifact=repair_check_payload.get(
                                    "next_action_artifact"
                                ),
                            ),
                            step_id="check",
                        )
                        repair_message = self._repair_retry_message(
                            request, last_check_payload, file_changes
                        )
                        yield ledger.event(
                            "tool.finished",
                            {
                                "tool_name": "repair_guard",
                                "success": False,
                                "result_preview": repair_message,
                            },
                            step_id=execute_step_id,
                        )
                        messages.append({"role": "user", "content": repair_message})
                        completed_write_ops.clear()
                        last_tool_batch_signature = ""
                        pending_repair_check_payload = dict(last_check_payload)
                        last_check_payload = None
                        final_summary = (
                            repair_check_payload.get("summary")
                            or content_text
                            or "核验未通过，准备修复。"
                        )
                        continue
                    check_status = (
                        str(last_check_payload.get("status") or "").strip().lower()
                    )
                    final_summary = content_text or str(
                        last_check_payload.get("summary") or "模型未再请求工具调用。"
                    )
                    completed_task = bool(last_check_payload.get("passed"))
                    yield ledger.event(
                        "step.result",
                        self._build_step_result_payload(
                            title="模型规划并调用工具",
                            summary=self._execute_step_summary(
                                round_index=round_index,
                                final_summary=final_summary,
                                model_failed=model_failed,
                                tool_gap=tool_gap,
                                file_changes=file_changes,
                                tool_runtime_outcome=tool_runtime_outcome,
                            ),
                            status=self._execute_step_result_status(
                                completed=completed_task,
                                tool_gap=tool_gap,
                                tool_runtime_outcome=tool_runtime_outcome,
                                model_failed=model_failed,
                            ),
                            round_index=round_index,
                            file_changes=file_changes,
                            next_action_artifact=next_action_artifact,
                        ),
                        step_id=execute_step_id,
                    )
                    break
                if (
                    not content_text
                    and (snippets or readonly_tool_outputs)
                    and not readonly_answer_guard_injected
                    and round_index < self._max_rounds
                ):
                    readonly_answer_guard_injected = True
                    reminder = self._readonly_answer_required_message(
                        request, snippets, readonly_tool_outputs
                    )
                    yield ledger.event(
                        "tool.finished",
                        {
                            "tool_name": "readonly_answer_guard",
                            "success": False,
                            "result_preview": reminder,
                        },
                        step_id=execute_step_id,
                    )
                    messages.append({"role": "user", "content": reminder})
                    final_summary = "已读取内容，正在生成可见分析结果。"
                    yield ledger.event(
                        "step.result",
                        self._build_step_result_payload(
                            title="模型规划并调用工具",
                            summary=final_summary,
                            status="pending",
                            round_index=round_index,
                        ),
                        step_id=execute_step_id,
                    )
                    continue
                final_summary = (
                    content_text
                    or self._readonly_context_summary(
                        request, snippets, readonly_tool_outputs
                    )
                    or "已读取上下文，但模型未生成可见分析结果。"
                )
                completed_task = not write_intent or bool(file_changes)
                yield ledger.event(
                    "step.result",
                    self._build_step_result_payload(
                        title="模型规划并调用工具",
                        summary=self._execute_step_summary(
                            round_index=round_index,
                            final_summary=final_summary,
                            model_failed=model_failed,
                            tool_gap=tool_gap,
                            file_changes=file_changes,
                            tool_runtime_outcome=tool_runtime_outcome,
                        ),
                        status=self._execute_step_result_status(
                            completed=completed_task,
                            tool_gap=tool_gap,
                            tool_runtime_outcome=tool_runtime_outcome,
                            model_failed=model_failed,
                        ),
                        round_index=round_index,
                        file_changes=file_changes,
                        next_action_artifact=next_action_artifact,
                    ),
                    step_id=execute_step_id,
                )
                break

            batch_signature = self._tool_batch_signature(tool_calls)
            if batch_signature and batch_signature == last_tool_batch_signature:
                if (
                    write_intent
                    and not file_changes
                    and not duplicate_supervisor_guard_injected
                    and round_index < self._max_rounds
                ):
                    duplicate_supervisor_guard_injected = True
                    final_summary = "检测到重复读取/重复工具调用，监管层已要求模型回到计划主线继续执行。"
                    reminder = self._duplicate_supervisor_retry_message(
                        request,
                        context_files,
                        classification,
                        intent_plan,
                        tool_calls,
                    )
                    yield ledger.event(
                        "tool.finished",
                        {
                            "tool_name": "supervisor_guard",
                            "success": False,
                            "skipped": True,
                            "result_preview": reminder,
                        },
                        step_id=execute_step_id,
                    )
                    yield ledger.event(
                        "step.result",
                        self._build_step_result_payload(
                            title="监管纠偏",
                            summary=final_summary,
                            status="needs_attention",
                            round_index=round_index,
                            file_changes=file_changes,
                        ),
                        step_id=execute_step_id,
                    )
                    messages.append({"role": "user", "content": reminder})
                    continue
                final_summary = "检测到重复工具调用，已自动停止以避免重复写入。"
                yield ledger.event(
                    "tool.finished",
                    {
                        "tool_name": "duplicate_guard",
                        "success": True,
                        "skipped": True,
                        "result_preview": final_summary,
                    },
                    step_id=execute_step_id,
                )
                yield ledger.event(
                    "step.result",
                    self._build_step_result_payload(
                        title="模型规划并调用工具",
                        summary=final_summary,
                        status="needs_attention",
                        round_index=round_index,
                        file_changes=file_changes,
                    ),
                    step_id=execute_step_id,
                )
                break
            last_tool_batch_signature = batch_signature

            for tool_index, tool_call in enumerate(tool_calls, start=1):
                if self._is_cancelled(request):
                    yield self._cancelled_event(ledger, request)
                    return
                tool_name = str(tool_call.get("name") or "").strip()
                tool_args = dict(tool_call.get("args") or {})
                tool_args = self._repair_tool_args_for_context(
                    tool_name,
                    tool_args,
                    request,
                    context_files,
                    generated_artifacts=generated_artifacts,
                )
                tool_call_id = str(tool_call.get("id") or uuid.uuid4().hex[:8])
                current_step_id = f"tool_{round_index}_{tool_index}"
                yield ledger.event(
                    "decision.made",
                    build_decision_audit(
                        request=request,
                        skeleton=recipe_skeleton,
                        tool_name=tool_name,
                        tool_args=tool_args,
                        round_index=round_index,
                        tool_index=tool_index,
                        execution_plan=active_execution_plan,
                    ),
                    step_id=current_step_id,
                )
                tool_stage = "writing" if is_write_tool(tool_name) else "analyzing"
                yield ledger.event(
                    "supervisor.status",
                    supervisor_status_payload(
                        workflow_state,
                        stage=tool_stage,
                        summary=(
                            f"准备调用 {tool_name}，监管层保持主线和工具边界。"
                        ),
                        active_step_id=(
                            "write_output" if tool_stage == "writing" else "model_reasoning"
                        ),
                        completed_step_ids=["read_context"],
                        file_changes=file_changes,
                    ),
                    step_id=current_step_id,
                )

                if not is_file_task_tool(tool_name):
                    error_text = (
                        f"工具 {tool_name or '<empty>'} 不在 Koto 文件任务 allowlist 中。"
                    )
                    yield ledger.event(
                        "tool.finished",
                        {
                            "tool_name": tool_name,
                            "success": False,
                            "result_preview": error_text,
                        },
                        step_id=current_step_id,
                    )
                    messages.append(
                        {
                            "role": "function",
                            "name": tool_name or "invalid_tool",
                            "tool_call_id": tool_call_id,
                            "content": self._tool_feedback_for_model(
                                tool_name or "invalid_tool",
                                tool_args,
                                {"error": error_text},
                                success=False,
                                invalid=True,
                            ),
                        }
                    )
                    continue

                exposed_tool_names = {
                    str(definition.get("name") or "").strip()
                    for definition in tool_defs
                    if str(definition.get("name") or "").strip()
                }
                if exposed_tool_names and tool_name not in exposed_tool_names:
                    error_text = self._recipe_tool_block_message(
                        tool_name,
                        classification,
                        exposed_tool_names,
                    )
                    yield ledger.event(
                        "tool.finished",
                        {
                            "tool_name": tool_name,
                            "success": False,
                            "blocked": True,
                            "result_preview": error_text,
                        },
                        step_id=current_step_id,
                    )
                    messages.append(
                        {
                            "role": "function",
                            "name": tool_name,
                            "tool_call_id": tool_call_id,
                            "content": self._tool_feedback_for_model(
                                tool_name,
                                tool_args,
                                {"error": error_text},
                                success=False,
                                blocked=True,
                            ),
                        }
                    )
                    continue

                if (
                    is_write_tool(tool_name)
                    and tool_name != "run_python_code"
                    and (not write_intent or classification.output_mode != "write")
                ):
                    block_text = self._readonly_write_tool_block_message(
                        tool_name,
                        request,
                        classification.output_mode,
                    )
                    yield ledger.event(
                        "tool.finished",
                        {
                            "tool_name": tool_name,
                            "success": False,
                            "blocked": True,
                            "result_preview": block_text,
                        },
                        step_id=current_step_id,
                    )
                    messages.append(
                        {
                            "role": "function",
                            "name": tool_name,
                            "tool_call_id": tool_call_id,
                            "content": self._tool_feedback_for_model(
                                tool_name,
                                tool_args,
                                {"error": block_text},
                                success=False,
                                blocked=True,
                            ),
                        }
                    )
                    continue

                if tool_name == "run_python_code" and (
                    not write_intent or classification.output_mode != "write"
                ):
                    block_text = self._readonly_run_python_write_block_message(
                        tool_args,
                        request,
                        classification.output_mode,
                    )
                    if block_text:
                        yield ledger.event(
                            "tool.finished",
                            {
                                "tool_name": tool_name,
                                "success": False,
                                "blocked": True,
                                "result_preview": block_text,
                            },
                            step_id=current_step_id,
                        )
                        messages.append(
                            {
                                "role": "function",
                                "name": tool_name,
                                "tool_call_id": tool_call_id,
                                "content": self._tool_feedback_for_model(
                                    tool_name,
                                    tool_args,
                                    {"error": block_text},
                                    success=False,
                                    blocked=True,
                                ),
                            }
                        )
                        continue

                source_write_block = self._protected_source_write_block_message(
                    tool_name,
                    tool_args,
                    request,
                    context_files,
                )
                if source_write_block:
                    yield ledger.event(
                        "tool.finished",
                        {
                            "tool_name": tool_name,
                            "success": False,
                            "blocked": True,
                            "result_preview": source_write_block,
                        },
                        step_id=current_step_id,
                    )
                    messages.append(
                        {
                            "role": "function",
                            "name": tool_name,
                            "tool_call_id": tool_call_id,
                            "content": self._tool_feedback_for_model(
                                tool_name,
                                tool_args,
                                {"error": source_write_block},
                                success=False,
                                blocked=True,
                            ),
                        }
                    )
                    continue

                local_docx_edit_block = self._local_docx_edit_block_message(
                    request,
                    tool_name,
                    tool_args,
                )
                if local_docx_edit_block:
                    yield ledger.event(
                        "tool.finished",
                        {
                            "tool_name": "supervisor_guard",
                            "success": False,
                            "blocked": True,
                            "result_preview": local_docx_edit_block,
                        },
                        step_id=current_step_id,
                    )
                    messages.append(
                        {
                            "role": "function",
                            "name": tool_name,
                            "tool_call_id": tool_call_id,
                            "content": self._tool_feedback_for_model(
                                tool_name,
                                tool_args,
                                {"error": local_docx_edit_block},
                                success=False,
                                blocked=True,
                            ),
                        }
                    )
                    continue

                if is_write_tool(tool_name) and tool_name != "run_python_code":
                    target = write_target_for_tool(tool_name, tool_args)
                    write_key = f"{tool_name}::{target}"
                    if completed_write_ops.get(write_key, 0) >= _MAX_WRITE_OPS_PER_FILE:
                        skip_text = (
                            f"{tool_name} 已成功写入过 {target or '同一目标'}，本次跳过以避免重复覆盖。"
                        )
                        yield ledger.event(
                            "tool.finished",
                            {
                                "tool_name": tool_name,
                                "success": True,
                                "skipped": True,
                                "result_preview": skip_text,
                            },
                            step_id=current_step_id,
                        )
                        messages.append(
                            {
                                "role": "function",
                                "name": tool_name,
                                "tool_call_id": tool_call_id,
                                "content": self._tool_feedback_for_model(
                                    tool_name,
                                    tool_args,
                                    {"summary": skip_text},
                                    success=True,
                                    skipped=True,
                                ),
                            }
                        )
                        continue

                stepwise_write_block = self._stepwise_docx_write_block_message(
                    request,
                    snippets,
                    recipe_skeleton,
                    tool_name,
                    tool_args,
                )
                if stepwise_write_block:
                    yield ledger.event(
                        "tool.finished",
                        {
                            "tool_name": "supervisor_guard",
                            "success": False,
                            "blocked": True,
                            "result_preview": stepwise_write_block,
                        },
                        step_id=current_step_id,
                    )
                    messages.append(
                        {
                            "role": "function",
                            "name": tool_name,
                            "tool_call_id": tool_call_id,
                            "content": self._tool_feedback_for_model(
                                tool_name,
                                tool_args,
                                {"error": stepwise_write_block},
                                success=False,
                                blocked=True,
                            ),
                        }
                    )
                    continue

                yield ledger.event(
                    "tool.started",
                    {
                        "tool_name": tool_name,
                        "tool_args": tool_args,
                        "round": round_index,
                    },
                    step_id=current_step_id,
                )

                blocked_message = self._blocked_run_python_message(
                    tool_name, tool_args, request, context_files
                )
                if blocked_message:
                    yield ledger.event(
                        "tool.finished",
                        {
                            "tool_name": tool_name,
                            "success": False,
                            "blocked": True,
                            "result_preview": blocked_message,
                        },
                        step_id=current_step_id,
                    )
                    messages.append(
                        {
                            "role": "function",
                            "name": tool_name,
                            "tool_call_id": tool_call_id,
                            "content": self._tool_feedback_for_model(
                                tool_name,
                                tool_args,
                                {"error": blocked_message},
                                success=False,
                                blocked=True,
                            ),
                        }
                    )
                    continue

                if tool_name == "run_python_code":
                    yield ledger.event(
                        "code.started",
                        {
                            "code": str(tool_args.get("code") or ""),
                        },
                        step_id=current_step_id,
                    )

                try:
                    result = executor(tool_name, tool_args)
                    if isinstance(result, FileTaskToolStreamResult):
                        result = yield from self._consume_streaming_tool_result(
                            ledger,
                            step_id=current_step_id,
                            stream_result=result,
                        )
                    success = not _is_error_result(result)
                except Exception as exc:
                    result = f"Error: {exc}"
                    success = False
                    logger.warning(
                        "[FileTaskRuntime] tool %s failed: %s", tool_name, exc
                    )

                if self._is_cancelled(request):
                    yield self._cancelled_event(ledger, request)
                    return

                model_result = self._tool_result_for_model(tool_name, result)
                current_tool_runtime_outcome = self._extract_tool_runtime_outcome(
                    result
                )
                if current_tool_runtime_outcome:
                    tool_runtime_outcome = current_tool_runtime_outcome
                    artifact = current_tool_runtime_outcome.get("next_action_artifact")
                    if isinstance(artifact, dict):
                        next_action_artifact = artifact
                runtime_status = self._tool_runtime_status(current_tool_runtime_outcome)
                runtime_blocked = runtime_status in {"blocked", "write_blocked"}
                result_text = stringify_result(model_result)
                if success and not is_write_tool(tool_name):
                    readonly_tool_outputs.append(
                        {
                            "tool_name": tool_name,
                            "args": dict(tool_args),
                            "result": model_result,
                            "preview": tool_result_preview(
                                tool_name, model_result, 1200
                            ),
                        }
                    )
                artifacts = self._tool_artifacts(tool_name, result)
                if tool_name == "run_python_code":
                    yield ledger.event(
                        "code.output",
                        {
                            "text": self._code_output_preview(
                                tool_name, result, result_text
                            ),
                            "stream": "stdout" if success else "stderr",
                        },
                        step_id=current_step_id,
                    )
                    yield ledger.event(
                        "code.finished",
                        {
                            "success": success,
                        },
                        step_id=current_step_id,
                    )

                tool_finished_payload = {
                    "tool_name": tool_name,
                    "success": success,
                    "result_preview": tool_result_preview(
                        tool_name, model_result, 1200
                    ),
                }
                if runtime_blocked:
                    tool_finished_payload["blocked"] = True
                if artifacts:
                    tool_finished_payload["artifacts"] = artifacts
                    if tool_name == "run_python_code":
                        self._remember_generated_artifacts(
                            generated_artifacts, artifacts
                        )
                yield ledger.event(
                    "tool.finished", tool_finished_payload, step_id=current_step_id
                )

                messages.append(
                    {
                        "role": "function",
                        "name": tool_name,
                        "tool_call_id": tool_call_id,
                        "content": self._tool_feedback_for_model(
                            tool_name,
                            tool_args,
                            model_result,
                            success=success,
                            blocked=runtime_blocked,
                        ),
                    }
                )

                extracted_changes = self._extract_file_changes(
                    tool_name, tool_args, result
                )
                if (
                    success
                    and is_write_tool(tool_name)
                    and tool_name != "run_python_code"
                ):
                    target = write_target_for_tool(tool_name, tool_args)
                    write_key = f"{tool_name}::{target}"
                    completed_write_ops[write_key] = (
                        completed_write_ops.get(write_key, 0) + 1
                    )

                if extracted_changes:
                    repair_attempts = 0
                    pending_repair_check_payload = None
                for change in extracted_changes:
                    file_changes.append(change)
                    yield ledger.event("file.changed", change, step_id=current_step_id)

            execute_round_summary = self._execute_step_summary(
                round_index=round_index,
                final_summary=final_summary,
                model_failed=model_failed,
                tool_gap=tool_gap,
                file_changes=file_changes,
                tool_runtime_outcome=tool_runtime_outcome,
            )
            yield ledger.event(
                "step.finished",
                {
                    "title": "模型工具执行完成",
                    "summary": execute_round_summary,
                },
                step_id=execute_step_id,
            )
            yield ledger.event(
                "step.result",
                self._build_step_result_payload(
                    title="模型工具执行完成",
                    summary=execute_round_summary,
                    status=self._execute_step_result_status(
                        completed=not model_failed and not tool_gap,
                        tool_gap=tool_gap,
                        tool_runtime_outcome=tool_runtime_outcome,
                        model_failed=model_failed,
                    ),
                    round_index=round_index,
                    file_changes=file_changes,
                    next_action_artifact=next_action_artifact,
                ),
                step_id=execute_step_id,
            )
            if self._tool_runtime_status(tool_runtime_outcome) in {
                "blocked",
                "write_blocked",
            }:
                final_summary = execute_round_summary
                completed_task = False
                break
            if write_intent and file_changes and not tool_gap:
                last_check_payload = self._verify_task(
                    request,
                    executor,
                    file_changes,
                    write_intent,
                    classification.output_mode,
                    model_failed,
                    readonly_fallback_used=readonly_fallback_used,
                    tool_runtime_outcome=tool_runtime_outcome,
                    tool_gap=tool_gap,
                    next_action_artifact=next_action_artifact,
                )
                if self._should_attempt_repair(
                    last_check_payload,
                    round_index=round_index,
                    repair_attempts=repair_attempts,
                ):
                    repair_attempts += 1
                    repair_runtime = self._build_runtime_metadata(
                        terminal_status=str(
                            last_check_payload.get("status") or ""
                        ).strip(),
                        readonly_fallback_used=readonly_fallback_used,
                        model_failed=model_failed,
                        planner_payload=planner_runtime_payload,
                        planner_fallback_payload=planner_fallback_runtime_payload,
                    )
                    repair_check_payload = dict(last_check_payload)
                    repair_check_payload["runtime"] = repair_runtime
                    repair_check_payload["repair_attempt"] = repair_attempts
                    yield ledger.event(
                            "check.started",
                            {
                                "title": "检查执行状态",
                                "criteria": completion_criteria,
                                "repair_attempt": repair_attempts,
                            },
                        step_id="check",
                    )
                    yield ledger.event(
                        "check.finished", repair_check_payload, step_id="check"
                    )
                    yield ledger.event(
                        "step.result",
                        self._build_step_result_payload(
                            title="检查执行状态",
                            summary=str(
                                repair_check_payload.get("summary") or "检查未通过。"
                            ),
                            status=(
                                "completed"
                                if repair_check_payload.get("passed")
                                else "needs_attention"
                            ),
                            runtime=repair_runtime,
                            passed=repair_check_payload.get("passed"),
                            file_changes=file_changes,
                            next_action_artifact=repair_check_payload.get(
                                "next_action_artifact"
                            ),
                        ),
                        step_id="check",
                    )
                    repair_message = self._repair_retry_message(
                        request, last_check_payload, file_changes
                    )
                    yield ledger.event(
                        "tool.finished",
                        {
                            "tool_name": "repair_guard",
                            "success": False,
                            "result_preview": repair_message,
                        },
                        step_id=execute_step_id,
                    )
                    messages.append({"role": "user", "content": repair_message})
                    completed_write_ops.clear()
                    last_tool_batch_signature = ""
                    pending_repair_check_payload = dict(last_check_payload)
                    last_check_payload = None
                    final_summary = (
                        repair_check_payload.get("summary")
                        or execute_round_summary
                        or "核验未通过，准备修复。"
                    )
                    continue
                final_summary = str(
                    last_check_payload.get("summary") or execute_round_summary
                )
                completed_task = bool(last_check_payload.get("passed"))
                break
            if (
                write_intent
                and not file_changes
                and not write_guard_injected
                and round_index < self._max_rounds
                and self._should_prompt_for_write_after_tool_round(
                    request, context_files, tool_calls, round_index
                )
            ):
                write_guard_injected = True
                reminder = self._write_retry_message(request, context_files)
                yield ledger.event(
                    "tool.finished",
                    {
                        "tool_name": "write_guard",
                        "success": False,
                        "result_preview": reminder,
                    },
                    step_id=execute_step_id,
                )
                messages.append({"role": "user", "content": reminder})

        if write_intent and not file_changes:
            deterministic_change = yield from self._write_stepwise_pdf_docx_native(
                ledger,
                request,
                executor,
                snippets,
                context_files,
                recipe_skeleton,
                execute_step_id,
                reason="model_finished_without_write",
                fallback=True,
                model_unavailable=False,
            )
            if deterministic_change:
                file_changes.append(deterministic_change)
                completed_task = True
                last_check_payload = None
                final_summary = str(
                    deterministic_change.get("summary")
                    or "模型未完成写入，已使用 Koto 原生分步流程写入当前结果。"
                )
                yield ledger.event(
                    "file.changed", deterministic_change, step_id=execute_step_id
                )
                yield ledger.event(
                    "step.result",
                    self._build_step_result_payload(
                        title="原生分步兜底写入",
                        summary=final_summary,
                        status="completed",
                        file_changes=file_changes,
                    ),
                    step_id=execute_step_id,
                )

        if not write_intent and not str(final_summary or "").strip():
            final_summary = self._readonly_context_summary(
                request, snippets, readonly_tool_outputs
            )
            if final_summary:
                completed_task = True

        check_step_id = "check"
        if self._is_cancelled(request):
            yield self._cancelled_event(ledger, request)
            return
        verification_completed_steps = ["read_context", "model_reasoning"]
        if file_changes:
            verification_completed_steps.append("write_output")
        yield ledger.event(
            "check.started",
            {
                "title": "检查执行状态",
                "criteria": completion_criteria,
            },
            step_id=check_step_id,
        )
        yield ledger.event(
            "supervisor.status",
            supervisor_status_payload(
                workflow_state,
                stage="verifying",
                summary="正在核验主线步骤、文件变更和质量门。",
                active_step_id="verify_outputs",
                completed_step_ids=verification_completed_steps,
                file_changes=file_changes,
            ),
            step_id=check_step_id,
        )

        check_payload = (
            dict(last_check_payload)
            if isinstance(last_check_payload, dict)
            else self._verify_task(
                request,
                executor,
                file_changes,
                write_intent,
                classification.output_mode,
                model_failed,
                readonly_fallback_used,
                tool_runtime_outcome,
                tool_gap,
                next_action_artifact,
            )
        )
        if (
            not write_intent
            and not file_changes
            and bool(check_payload.get("passed"))
            and not snippets
            and not readonly_tool_outputs
            and self._readonly_task_requires_file_context(request, context_files)
        ):
            check_payload = dict(check_payload)
            check_payload["passed"] = False
            check_payload["status"] = "needs_attention"
            check_payload["summary"] = "任务明确要求读取文件，但没有成功读取任何显式文件上下文。"
            check_payload["remaining"] = [
                "确认文件位于工作区内，或将目标文件加入临时工作区后重试。"
            ]
            check_payload["criteria_results"] = [
                {
                    "criterion": "explicit_file_context_read",
                    "passed": False,
                    "detail": "任务包含明确文件引用，但运行时没有可用于分析的读取片段。",
                    "priority": "critical",
                }
            ]
        missing_read_refs = self._unsatisfied_explicit_read_file_references(
            request, snippets, readonly_tool_outputs
        )
        if (
            not write_intent
            and not file_changes
            and bool(check_payload.get("passed"))
            and missing_read_refs
        ):
            refs_text = "、".join(missing_read_refs[:3])
            check_payload = dict(check_payload)
            check_payload["passed"] = False
            check_payload["status"] = "needs_attention"
            check_payload["summary"] = (
                f"任务明确要求读取文件，但没有成功读取目标文件：{refs_text}。"
            )
            check_payload["remaining"] = [
                "确认文件名和路径是否正确，或将目标文件加入临时工作区后重试。"
            ]
            check_payload["criteria_results"] = [
                {
                    "criterion": "explicit_file_reference_read",
                    "passed": False,
                    "detail": "任务包含明确文件引用，但读取结果没有覆盖该目标文件。",
                    "priority": "critical",
                }
            ]
        stepwise_artifact = self._stepwise_docx_wait_artifact(
            request,
            context_files,
            snippets,
            file_changes,
            recipe_skeleton,
        )
        if stepwise_artifact and bool(check_payload.get("passed")):
            stepwise_artifact = attach_workflow_checkpoint(
                stepwise_artifact,
                workflow_state,
            )
            next_action_artifact = stepwise_artifact
            check_payload = dict(check_payload)
            check_payload["passed"] = False
            check_payload["status"] = "awaiting_confirmation"
            check_payload["summary"] = "当前步骤已写入 DOCX，等待用户说“继续”后处理下一段。"
            check_payload["remaining"] = ["用户说“继续”后处理下一页窗口，并继续追加 DOCX。"]
            check_payload["next_action_artifact"] = stepwise_artifact
        terminal_runtime = self._build_runtime_metadata(
            terminal_status=str(check_payload.get("status") or "").strip(),
            readonly_fallback_used=readonly_fallback_used,
            model_failed=model_failed,
            planner_payload=planner_runtime_payload,
            planner_fallback_payload=planner_fallback_runtime_payload,
        )
        check_payload["runtime"] = terminal_runtime

        yield ledger.event("check.finished", check_payload, step_id=check_step_id)
        terminal_completed_steps = list(verification_completed_steps)
        if check_payload.get("passed"):
            terminal_completed_steps.append("verify_outputs")
        yield ledger.event(
            "supervisor.status",
            supervisor_status_payload(
                workflow_state,
                stage="completed" if check_payload.get("passed") else "repairing",
                summary=str(check_payload.get("summary") or "检查完成。"),
                active_step_id="" if check_payload.get("passed") else "verify_outputs",
                completed_step_ids=terminal_completed_steps,
                file_changes=file_changes,
                check_payload=check_payload,
            ),
            step_id=check_step_id,
        )
        yield ledger.event(
            "step.result",
            self._build_step_result_payload(
                title="检查执行状态",
                summary=str(check_payload.get("summary") or "检查完成。"),
                status=self._check_step_result_status(check_payload),
                runtime=terminal_runtime,
                passed=check_payload.get("passed"),
                file_changes=file_changes,
                next_action_artifact=check_payload.get("next_action_artifact")
                or next_action_artifact,
            ),
            step_id=check_step_id,
        )
        run_summary = check_payload.get("summary") or final_summary or "任务执行结束。"
        if not write_intent and final_summary and not tool_gap:
            run_summary = final_summary
        if classification_payload.get("selected_recipe") == "docx_contract_compare_review":
            contract_risks = None
            for change in file_changes:
                risks = change.get("contract_risk_summary") if isinstance(change, dict) else None
                if isinstance(risks, list) and risks:
                    contract_risks = risks
                    break
            if (
                isinstance(contract_risks, list)
                and contract_risks
                and "风险关注点" not in str(run_summary)
            ):
                risk_lines = "\n".join(f"- {item}" for item in contract_risks[:5])
                run_summary = f"{run_summary}\n风险关注点：\n{risk_lines}"
        run_payload = {
            "task": request.task,
            "mode": "whitebox_v1",
            "summary": run_summary,
            "completed_task": bool(check_payload.get("passed"))
            and (completed_task or not write_intent or bool(file_changes)),
            "context": self._public_context_snippets(snippets[:8]),
            "file_changes": file_changes,
            "runtime": terminal_runtime,
            "quick_action_mode": quick_action_mode,
            "workflow_version": recipe_skeleton.get("version"),
            "workflow_state": workflow_state,
            "recipe_skeleton": recipe_skeleton,
            "completion_contract": completion_contract_payload,
            **classification_payload,
        }
        if tool_gap:
            run_payload["tool_gap"] = tool_gap
        if next_action_artifact:
            run_payload["next_action_artifact"] = next_action_artifact
        yield ledger.event("run.finished", run_payload)

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
        planner_fallback_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return _step_payload_build_runtime_metadata(
            terminal_status=terminal_status,
            readonly_fallback_used=readonly_fallback_used,
            model_failed=model_failed,
            planner_payload=planner_payload,
            planner_fallback_payload=planner_fallback_payload,
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
                workspace_root=self._workspace_root,
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
        del classification, intent_plan

        target_path = self._stepwise_docx_polish_target_path(request, context_files)
        context_step_id = "context"
        execute_step_id = "execute"
        check_step_id = "check"
        file_changes: List[Dict[str, Any]] = []

        yield ledger.event(
            "step.started",
            {
                "title": "读取当前 DOCX 段落窗口",
                "detail": "按段落窗口读取 Word 当前步骤内容，不一次性润色全文。",
            },
            step_id=context_step_id,
        )

        if not target_path or not Path(target_path).exists():
            summary = "未找到可写回的 DOCX 文件，无法执行分步润色。"
            runtime = self._build_runtime_metadata(
                terminal_status="failed",
                readonly_fallback_used=False,
                model_failed=False,
            )
            yield ledger.event(
                "run.finished",
                {
                    "task": request.task,
                    "mode": "whitebox_v1",
                    "summary": summary,
                    "completed_task": False,
                    "context": [],
                    "file_changes": [],
                    "runtime": runtime,
                    "quick_action_mode": quick_action_mode,
                    "intent_plan": intent_plan_payload,
                    "requirements": requirements_payload,
                    "plan_check": plan_check_payload,
                    "recipe_skeleton": recipe_skeleton,
                    "constraint_audit": constraint_audit,
                    **classification_payload,
                },
            )
            return

        try:
            window = self._read_docx_paragraph_window(request, target_path)
        except Exception as exc:
            summary = f"读取 DOCX 段落失败：{exc}"
            runtime = self._build_runtime_metadata(
                terminal_status="failed",
                readonly_fallback_used=False,
                model_failed=False,
            )
            yield ledger.event(
                "tool.finished",
                {
                    "tool_name": "read_docx_content",
                    "success": False,
                    "path": target_path,
                    "result_preview": summary,
                },
                step_id=context_step_id,
            )
            yield ledger.event(
                "run.finished",
                {
                    "task": request.task,
                    "mode": "whitebox_v1",
                    "summary": summary,
                    "completed_task": False,
                    "context": [],
                    "file_changes": [],
                    "runtime": runtime,
                    "quick_action_mode": quick_action_mode,
                    "intent_plan": intent_plan_payload,
                    "requirements": requirements_payload,
                    "plan_check": plan_check_payload,
                    "recipe_skeleton": recipe_skeleton,
                    "constraint_audit": constraint_audit,
                    **classification_payload,
                },
            )
            return

        if not window["paragraphs"]:
            summary = "当前 DOCX 没有可润色的剩余段落。"
            runtime = self._build_runtime_metadata(
                terminal_status="verified",
                readonly_fallback_used=False,
                model_failed=False,
            )
            yield ledger.event(
                "run.finished",
                {
                    "task": request.task,
                    "mode": "whitebox_v1",
                    "summary": summary,
                    "completed_task": True,
                    "context": [window],
                    "file_changes": [],
                    "runtime": runtime,
                    "quick_action_mode": quick_action_mode,
                    "intent_plan": intent_plan_payload,
                    "requirements": requirements_payload,
                    "plan_check": plan_check_payload,
                    "recipe_skeleton": recipe_skeleton,
                    "constraint_audit": constraint_audit,
                    **classification_payload,
                },
            )
            return

        yield ledger.event(
            "tool.finished",
            {
                "tool_name": "read_docx_content",
                "success": True,
                "path": target_path,
                "result_preview": _preview("\n".join(window["paragraphs"]), 900),
                "paragraph_start": window["start_visible_index"] + 1,
                "paragraph_end": window["end_visible_index"],
            },
            step_id=context_step_id,
        )
        yield ledger.event(
            "step.result",
            self._build_step_result_payload(
                title="读取当前 DOCX 段落窗口",
                summary=(
                    f"已读取第 {window['start_visible_index'] + 1}-"
                    f"{window['end_visible_index']} 个非空段落。"
                ),
                status="completed",
                snippet_count=1,
                snippets=[
                    {
                        "source": Path(target_path).name,
                        "path": target_path,
                        "preview": _preview("\n".join(window["paragraphs"]), 500),
                        "paragraph_start": window["start_visible_index"] + 1,
                        "paragraph_end": window["end_visible_index"],
                    }
                ],
            ),
            step_id=context_step_id,
        )

        yield ledger.event(
            "step.started",
            {
                "title": "润色并写回当前段落",
                "detail": "只处理当前段落窗口，保留文档其他内容。",
            },
            step_id=execute_step_id,
        )

        model_failed = False
        polished: List[str] = []
        try:
            response = self._call_model(
                request=request,
                messages=[
                    {
                        "role": "user",
                        "content": self._docx_polish_window_prompt(
                            request, window["paragraphs"]
                        ),
                    }
                ],
                system=("你是严谨的中文文档润色助手。只润色用户给出的段落窗口，" "保持原意、术语和段落数量；不要扩写成总结，不要添加解释。"),
                tools=[],
            )
            content, _tool_calls = self._normalize_model_response(response, [])
            polished = self._parse_polished_docx_paragraphs(
                content, expected_count=len(window["paragraphs"])
            )
        except Exception as exc:
            model_failed = True
            logger.warning(
                "[FileTaskRuntime] stepwise DOCX polish model failed: %s", exc
            )

        if not polished:
            polished = [
                self._simple_polish_docx_paragraph(text)
                for text in window["paragraphs"]
            ]

        changed_count = self._rewrite_docx_paragraph_window(
            target_path,
            window["paragraph_indices"],
            polished,
        )
        change = {
            "path": target_path,
            "file_type": "docx",
            "operation": "rewrite_docx_paragraph_window",
            "summary": (
                f"已润色并写回第 {window['start_visible_index'] + 1}-"
                f"{window['end_visible_index']} 个非空段落。"
            ),
            "paragraphs_rewritten": changed_count,
            "paragraph_start": window["start_visible_index"] + 1,
            "paragraph_end": window["end_visible_index"],
            "change_type": "modify",
            "focus": True,
        }
        file_changes.append(change)
        yield ledger.event(
            "tool.finished",
            {
                "tool_name": "rewrite_docx_paragraph_window",
                "success": changed_count > 0,
                "path": target_path,
                "result_preview": change["summary"],
                "paragraphs_rewritten": changed_count,
            },
            step_id=execute_step_id,
        )
        yield ledger.event("file.changed", change, step_id=execute_step_id)

        next_artifact = self._docx_polish_wait_artifact(request, target_path, window)
        runtime = self._build_runtime_metadata(
            terminal_status="awaiting_confirmation",
            readonly_fallback_used=False,
            model_failed=model_failed,
        )
        check_payload = self._evaluate_task_quality_gate(
            request,
            file_changes,
            write_intent=True,
            output_mode="write",
        )
        check_payload.update(
            {
                "status": "awaiting_confirmation",
                "summary": "当前段落窗口已写回 DOCX，等待用户说“继续”后处理下一段。",
                "next_action_artifact": next_artifact,
                "runtime": runtime,
            }
        )

        yield ledger.event(
            "step.result",
            self._build_step_result_payload(
                title="润色并写回当前段落",
                summary=change["summary"],
                status="completed",
                file_changes=file_changes,
                runtime=runtime,
                next_action_artifact=next_artifact,
            ),
            step_id=execute_step_id,
        )
        yield ledger.event("check.completed", check_payload, step_id=check_step_id)
        yield ledger.event(
            "step.result",
            self._build_step_result_payload(
                title="核验结果",
                summary="当前步骤已写入 DOCX，等待用户说“继续”后处理下一段。",
                status="awaiting_confirmation",
                file_changes=file_changes,
                runtime=runtime,
                passed=bool(check_payload.get("passed")),
                next_action_artifact=next_artifact,
            ),
            step_id=check_step_id,
        )
        yield ledger.event(
            "run.finished",
            {
                "task": request.task,
                "mode": "whitebox_v1",
                "summary": "当前步骤已写入 DOCX，等待用户说“继续”后处理下一段。",
                "completed_task": True,
                "context": [window],
                "file_changes": file_changes,
                "runtime": runtime,
                "quick_action_mode": quick_action_mode,
                "intent_plan": intent_plan_payload,
                "requirements": requirements_payload,
                "plan_check": plan_check_payload,
                "recipe_skeleton": recipe_skeleton,
                "constraint_audit": constraint_audit,
                "next_action_artifact": next_artifact,
                **classification_payload,
            },
        )

    def _stepwise_docx_polish_target_path(
        self, request: FileTaskRequest, files: List[FileTaskFile]
    ) -> str:
        return _docx_stepwise_polish_target_path(request, files)

    def _read_docx_paragraph_window(
        self, request: FileTaskRequest, path: str
    ) -> Dict[str, Any]:
        return _docx_stepwise_read_docx_paragraph_window(request, path)

    def _docx_polish_window_prompt(
        self, request: FileTaskRequest, paragraphs: List[str]
    ) -> str:
        return _docx_stepwise_docx_polish_window_prompt(request, paragraphs)

    def _parse_polished_docx_paragraphs(
        self, content: str, *, expected_count: int
    ) -> List[str]:
        return _docx_stepwise_parse_polished_docx_paragraphs(
            content,
            expected_count=expected_count,
        )

    def _simple_polish_docx_paragraph(self, text: str) -> str:
        return _docx_stepwise_simple_polish_docx_paragraph(text)

    def _rewrite_docx_paragraph_window(
        self, path: str, paragraph_indices: List[int], paragraphs: List[str]
    ) -> int:
        return _docx_stepwise_rewrite_docx_paragraph_window(
            path,
            paragraph_indices,
            paragraphs,
        )

    def _docx_polish_wait_artifact(
        self, request: FileTaskRequest, target_path: str, window: Dict[str, Any]
    ) -> Dict[str, Any]:
        return _docx_stepwise_docx_polish_wait_artifact(
            request,
            target_path,
            window,
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

    def _is_docx_annotation_request(self, request: FileTaskRequest) -> bool:
        if not self._request_has_file_type(request, "docx"):
            return False
        options = request.options if isinstance(request.options, dict) else {}
        if bool(options.get("skip_doc_annotate_bridge")):
            return False
        from app.core.agent import file_task_doc_annotate_boundary

        if file_task_doc_annotate_boundary.looks_like_docx_review_clear_request(
            request.task
        ):
            return False
        if file_task_doc_annotate_boundary.looks_like_direct_docx_rewrite_request(
            request.task
        ):
            return False
        if file_task_doc_annotate_boundary.looks_like_multi_file_compare_request(
            request
        ):
            return False
        task_lower = str(request.task or "").strip().lower()
        if not task_lower:
            return False
        if (
            self._request_has_file_type(request, "pdf")
            and any(marker in task_lower for marker in ("翻译", "translation", "译稿"))
            and any(marker in task_lower for marker in ("原文", "source", "pdf"))
            and any(marker in task_lower for marker in ("处理", "分段", "拆成", "batch"))
        ):
            return True
        return has_explicit_docx_review_intent(task_lower)

    def _is_docx_clear_review_request(self, request: FileTaskRequest) -> bool:
        if not self._request_has_file_type(request, "docx"):
            return False
        from app.core.agent import file_task_doc_annotate_boundary

        return file_task_doc_annotate_boundary.looks_like_docx_review_clear_request(
            request.task
        )

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
        matched_capabilities = matched_native_capability_names(classification_request)
        advisory_analysis_request = self._is_advisory_analysis_request(
            classification_task
        )
        readonly_write_negation = self._has_readonly_write_negation(classification_task)
        raw_write_intent = self._has_explicit_write_intent(classification_task)
        write_intent = self._has_write_intent(classification_task)
        raw_docx_annotation_request = self._is_docx_annotation_request(
            classification_request
        )
        docx_annotation_request = raw_docx_annotation_request
        clear_docx_review_request = self._is_docx_clear_review_request(
            classification_request
        )
        docx_compare_annotate_request = (
            "compare_docx_and_annotate" in matched_capabilities
        )
        if docx_compare_annotate_request:
            if "annotate_file" in matched_capabilities:
                matched_capabilities = [
                    name for name in matched_capabilities if name != "annotate_file"
                ]
            docx_annotation_request = False
            raw_docx_annotation_request = False
        semantic = semantic_markers(
            classification_task,
            file_types=request_file_types(files),
            target_file_type=request_target_file_type(request, files),
        )
        chart_request = semantic.get("chart_request", False)
        table_request = semantic.get("table_request", False)
        summary_request = semantic.get("summary_request", False)
        translation_request = semantic.get("translation_request", False)
        polish_request = semantic.get("polish_request", False)
        financial_request = semantic.get("financial_request", False)
        ppt_slide_write_request = semantic.get("ppt_slide_write_request", False)
        ppt_design_request = semantic.get("ppt_design_request", False)
        docx_report_request = semantic.get("docx_report_request", False)
        if clear_docx_review_request and "annotate_file" in matched_capabilities:
            matched_capabilities = [
                name for name in matched_capabilities if name != "annotate_file"
            ]
        planner_policy, planner_reason, planner_backend = self._planner_classification(
            request
        )
        resume_adapter = str(resume_control.get("adapter") or "").strip().lower()
        diagnostic_request = self._is_diagnostic_request(classification_task)

        request_kind = "new_task"
        execution_mode = "generic_tool_loop"
        reason_codes: List[str] = []
        stepwise_pdf_docx_resume = False
        followup_action = (
            str(followup_context.get("followup_action") or "").strip().lower()
        )
        previous_task_family = (
            str(followup_context.get("previous_task_family") or "").strip().lower()
        )
        previous_task_execution_mode = (
            str(
                followup_context.get("previous_task_execution_mode")
                or followup_context.get("previous_task_mode")
                or ""
            )
            .strip()
            .lower()
        )
        previous_task_output_mode = (
            str(followup_context.get("previous_task_output_mode") or "").strip().lower()
        )
        previous_task_intent_can_apply = (
            str(followup_context.get("previous_task_intent_can_apply") or "")
            .strip()
            .lower()
        )
        if (
            semantic.get("pdf_source", False)
            and semantic.get("summary_request", False)
            and semantic.get("stepwise_confirmation_request", False)
            and semantic.get("docx_target", False)
        ):
            summary_request = True
            docx_report_request = True
            write_intent = True
            raw_write_intent = True
            reason_codes.append("long_pdf_stepwise_docx_forced_write_intent")
        if resume_control:
            request_kind = "resume"
            execution_mode = "awaiting_confirmation_resume"
            reason_codes.append("workflow_checkpoint_resume")
            if resume_adapter:
                reason_codes.append(f"workflow_adapter:{resume_adapter}")
            if (
                str(resume_control.get("policy") or "").strip().lower()
                == "confirm_each_step"
                and "pdf" in request_file_types(files)
                and request_target_file_type(request, files) in {"docx", "doc"}
            ):
                stepwise_pdf_docx_resume = True
                summary_request = True
                docx_report_request = True
                write_intent = True
                raw_write_intent = True
                reason_codes.append("stepwise_resume_forced_write_intent")
        elif followup_context:
            request_kind = "followup"
            execution_mode = "followup_contextual"
            if followup_action:
                reason_codes.append(f"followup_action:{followup_action}")
            else:
                reason_codes.append("followup_context")

        followup_question_is_new_artifact = (
            request_kind == "followup"
            and followup_action == "question"
            and (
                self._has_artifact_creation_intent(classification_task)
                or self._has_explicit_write_intent(classification_task)
                or raw_write_intent
            )
        )
        if (
            request_kind == "followup"
            and followup_action == "question"
            and not followup_question_is_new_artifact
        ):
            diagnostic_request = True
            reason_codes.append("followup_question")
        elif followup_question_is_new_artifact:
            reason_codes.append("followup_question_new_artifact")

        if clear_docx_review_request:
            reason_codes.append("docx_clear_review_request")
            if not write_intent:
                write_intent = True
                reason_codes.append("docx_clear_review_forced_write_intent")

        if docx_compare_annotate_request:
            reason_codes.append("docx_compare_annotate_request")
            if not write_intent:
                write_intent = True
                reason_codes.append("docx_compare_annotate_forced_write_intent")

        if diagnostic_request:
            reason_codes.append("diagnostic_request")
            diagnostic_write_signal = (
                write_intent
                or raw_write_intent
                or clear_docx_review_request
                or docx_compare_annotate_request
                or self._has_explicit_write_intent(classification_task)
                or self._has_strong_write_intent(classification_task)
            )
            if write_intent or raw_write_intent:
                write_intent = False
            if diagnostic_write_signal:
                reason_codes.append("diagnostic_overrode_write_intent")
            if docx_annotation_request or raw_docx_annotation_request:
                docx_annotation_request = False
                reason_codes.append("diagnostic_overrode_docx_annotation")

        if readonly_write_negation:
            reason_codes.append("readonly_write_negation")
            if write_intent or raw_write_intent:
                write_intent = False
                reason_codes.append("readonly_overrode_write_intent")
            if docx_annotation_request or raw_docx_annotation_request:
                docx_annotation_request = False
                reason_codes.append("readonly_overrode_docx_annotation")

        if self._explicit_output_mode(request) == "answer" and not diagnostic_request:
            if (write_intent or raw_write_intent) and not self._has_strong_write_intent(
                classification_task
            ):
                write_intent = False
                reason_codes.append("answer_mode_overrode_write_intent")
            if docx_annotation_request or raw_docx_annotation_request:
                docx_annotation_request = False
                reason_codes.append("answer_mode_overrode_docx_annotation")

        if resume_adapter == "doc_annotate_bridge":
            docx_annotation_request = True
        if request_kind == "followup" and followup_action == "improve":
            if previous_task_family == "annotate":
                reason_codes.append("followup_previous_task_family:annotate")
                if self._request_has_file_type(classification_request, "docx"):
                    docx_annotation_request = True
            if previous_task_execution_mode in {
                "annotate_tool_loop",
                "awaiting_confirmation_resume",
                "doc_annotate_bridge",
            }:
                reason_codes.append(
                    f"followup_previous_execution_mode:{previous_task_execution_mode}"
                )
                if self._request_has_file_type(classification_request, "docx"):
                    docx_annotation_request = True
        if request_kind == "followup" and followup_action == "apply":
            if (
                previous_task_output_mode in {"hybrid", "write"}
                or previous_task_intent_can_apply == "true"
            ):
                write_intent = True
                reason_codes.append("followup_apply_write_intent")

        if docx_annotation_request:
            if request_kind == "new_task":
                execution_mode = "annotate_tool_loop"
            elif (
                request_kind == "followup"
                and followup_action == "improve"
                and previous_task_execution_mode == "doc_annotate_bridge"
            ):
                execution_mode = "doc_annotate_bridge"
            reason_codes.append("docx_annotation_request")
            if not write_intent:
                write_intent = True
                reason_codes.append("docx_annotation_forced_write_intent")

        if write_intent:
            reason_codes.append("write_intent")
            if (
                str(options.get("output_mode") or "").strip().lower() == "answer"
                and not diagnostic_request
            ):
                output_mode = "write"
                reason_codes.append("answer_mode_overridden_by_write_intent")

        recipe_match_request = classification_request
        if stepwise_pdf_docx_resume:
            recipe_match_request = FileTaskRequest(
                task=(f"{classification_task}\n" "分步 长PDF DOCX 总结 每一步写入并等待确认"),
                run_id=classification_request.run_id,
                session_id=classification_request.session_id,
                files=classification_request.files,
                current_file=classification_request.current_file,
                selection=classification_request.selection,
                selection_source=classification_request.selection_source,
                target_path=classification_request.target_path,
                model_mode=classification_request.model_mode,
                model_id=classification_request.model_id,
                history=classification_request.history,
                options=classification_request.options,
            )
        recipe_candidates = recipe_matches(
            recipe_match_request, files, write_intent=write_intent
        )
        selected_recipe_match = recipe_candidates[0] if recipe_candidates else None
        if selected_recipe_match:
            reason_codes.extend(selected_recipe_match.reason_codes)
            for capability in selected_recipe_match.recipe.matched_capabilities:
                if capability not in matched_capabilities:
                    matched_capabilities.append(capability)
            if selected_recipe_match.recipe.execution_mode != "generic_tool_loop":
                execution_mode = selected_recipe_match.recipe.execution_mode
            if len(recipe_candidates) > 1:
                reason_codes.extend(
                    f"recipe_candidate:{item.recipe.id}"
                    for item in recipe_candidates[1:4]
                )

        if planner_policy:
            reason_codes.append(f"planner_policy:{planner_policy}")
        elif planner_reason == "deferred_to_execution_brief":
            reason_codes.append("planner_deferred:model_first")
        if planner_backend:
            reason_codes.append(f"planner_backend:{planner_backend}")

        known_gap_name = ""
        if isinstance(known_tool_gap, dict):
            known_gap_name = str(known_tool_gap.get("missing_capability") or "").strip()
            if known_gap_name:
                reason_codes.append(f"native_tool_gap:{known_gap_name}")

        reason_codes.extend(f"capability:{name}" for name in matched_capabilities[:4])
        reason_codes.extend(
            _classification_semantics_reason_codes(
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
        )

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

        file_types = sorted(
            {
                str(profile.get("format") or "").strip().lower()
                for profile in build_request_capability_profiles(request)
                if str(profile.get("format") or "").strip()
            }
        )
        target_file_type = (
            Path(str(request.target_path or "")).suffix.lstrip(".").lower()
        )
        if not target_file_type:
            for file_info in files:
                if not file_info.target:
                    continue
                target_file_type = (
                    file_info.type
                    or Path(file_info.path or file_info.name).suffix.lstrip(".")
                ).lower()
                if target_file_type:
                    break

        output_mode = self._infer_output_mode(
            request,
            files,
            write_intent=write_intent,
            diagnostic_request=diagnostic_request,
            docx_annotation_request=docx_annotation_request,
            advisory_analysis_request=advisory_analysis_request,
        )
        if readonly_write_negation:
            output_mode = "answer"

        confidence = 1.0
        if diagnostic_request:
            confidence = (
                0.7 if (raw_write_intent or raw_docx_annotation_request) else 0.9
            )

        return FileTaskClassification(
            request_kind=request_kind,
            task_family=task_family,
            operation_kind=operation_kind,
            execution_mode=execution_mode,
            output_mode=output_mode,
            write_intent=write_intent,
            diagnostic_request=diagnostic_request,
            docx_annotation_request=docx_annotation_request,
            planner_policy=planner_policy,
            planner_reason=planner_reason,
            planner_backend=planner_backend,
            target_file_type=target_file_type,
            known_native_tool_gap=known_gap_name,
            file_types=file_types,
            matched_capabilities=matched_capabilities,
            reason_codes=reason_codes,
            selected_recipe=(
                selected_recipe_match.recipe.id if selected_recipe_match else ""
            ),
            recipe_candidates=[item.public_dict() for item in recipe_candidates[:5]],
            confidence=confidence,
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

    def _intent_adjudicator_messages(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        classification: FileTaskClassification,
    ) -> List[Dict[str, Any]]:
        return _intent_adjudication_messages(request, files, classification)

    def _adjudicate_intent_if_needed(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        classification: FileTaskClassification,
    ) -> Dict[str, Any]:
        try:
            from app.core.routing.task_classifier import TaskClassifier

            tc_type, tc_conf = TaskClassifier.classify(str(request.task)[:500])
            if tc_conf > 0.80 and tc_type not in ("CHAT",):
                return {
                    "source": "task_classifier_fast_path",
                    "adjudicated_type": tc_type,
                    "confidence": tc_conf,
                    "reason": "high-confidence ML classification",
                }
        except Exception:
            pass
        if not self._should_adjudicate_intent(request, files, classification):
            return {}
        try:
            response = self._call_model(
                request=request,
                messages=self._intent_adjudicator_messages(
                    request, files, classification
                ),
                system=self._intent_adjudicator_system_prompt(),
                tools=[],
            )
        except Exception as exc:
            logger.warning("[FileTaskRuntime] intent adjudicator unavailable: %s", exc)
            return {
                "source": "ai_intent_adjudicator",
                "status": "unavailable",
                "error": _preview(str(exc), 240),
            }

        return _intent_adjudication_normalize_response(response)

    def _apply_intent_adjudication(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        classification: FileTaskClassification,
        adjudication: Dict[str, Any],
    ) -> FileTaskClassification:
        task_text = str(request.task or "")
        return _classification_contract_apply_intent_adjudication(
            request,
            files,
            classification,
            adjudication,
            readonly_write_negation=self._has_readonly_write_negation(task_text),
            artifact_creation_intent=self._has_artifact_creation_intent(task_text),
            global_readonly_write_negation=self._has_global_readonly_write_negation(
                task_text
            ),
            strong_write_intent=self._has_strong_write_intent(task_text),
        )

    def _normalize_mainline_contract(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        classification: FileTaskClassification,
    ) -> FileTaskClassification:
        task_text = str(request.task or "")
        return _classification_contract_normalize_mainline(
            request,
            files,
            classification=classification,
            explicit_output_mode=self._explicit_output_mode(request),
            readonly_write_negation=self._has_readonly_write_negation(task_text),
            has_target_context=self._has_target_context(request, files),
            docx_annotation_has_contract=lambda current: self._docx_annotation_has_contract(
                request,
                files,
                current,
            ),
            write_has_contract_anchor=lambda current: self._write_has_contract_anchor(
                request,
                files,
                current,
            ),
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

    def _refresh_classification_recipe(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        classification: FileTaskClassification,
    ) -> FileTaskClassification:
        return _classification_contract_refresh_recipe(request, files, classification)

    def _write_has_contract_anchor(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        classification: FileTaskClassification,
    ) -> bool:
        task_text = str(request.task or "")
        return _classification_contract_write_has_contract_anchor(
            classification,
            task_text=task_text,
            explicit_output_mode=self._explicit_output_mode(request),
            strong_write_intent=self._has_strong_write_intent(task_text),
            docx_annotation_has_contract=self._docx_annotation_has_contract(
                request,
                files,
                classification,
            ),
            create_or_export_contract=self._has_create_or_export_contract(task_text),
        )

    def _docx_annotation_has_contract(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        classification: FileTaskClassification,
    ) -> bool:
        return _classification_contract_docx_annotation_has_contract(
            classification,
            request_has_docx=self._request_has_file_type(request, "docx"),
            direct_docx_annotation_request=self._is_docx_annotation_request(request),
            followup_context=self._followup_context(request),
        )

    @staticmethod
    def _has_create_or_export_contract(task: str) -> bool:
        return _classification_contract_has_create_or_export_contract(task)

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
        if (
            target_type
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

    def _has_explicit_planner_override(self, request: FileTaskRequest) -> bool:
        return False

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
        recommended_strategy = self._fallback_intent_strategy(
            classification, output_mode, known_tool_gap
        )
        can_apply = output_mode in {
            "write",
            "hybrid",
        } and self._fallback_intent_has_apply_target(request, files)
        requires_confirmation = output_mode == "hybrid"
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
            return f"先分析并整理可应用建议，再等待确认：{task_text}"
        return f"基于显式上下文给出结论或答复：{task_text}"

    def _fallback_intent_strategy(
        self,
        classification: FileTaskClassification,
        output_mode: str,
        known_tool_gap: Optional[Dict[str, Any]] = None,
    ) -> str:
        if known_tool_gap:
            return "design_new_tool"
        if classification.request_kind == "resume":
            return "resume_previous_plan"
        if output_mode == "write":
            return "write_through"
        if output_mode == "hybrid":
            return "analyze_then_confirm"
        return "answer_only"

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
        lines.append(f"- 写回前需要确认：{'是' if intent_plan.requires_confirmation else '否'}")
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
        labels = {
            "read_sheet_data": "读取 Excel 表格",
            "inspect_workbook_structure": "检查 Excel 结构",
            "audit_financial_workbook": "审计财务模型",
            "read_docx_content": "读取 Word 内容",
            "parse_file_to_text": "解析文件文本",
            "clear_docx_review_marks": "清除 Word 审阅标记",
            "insert_image_into_docx": "插入 Word 图片",
            "insert_excel_as_docx_table": "写入 Word 表格",
            "write_docx_content": "写入 Word 内容",
            "insert_docx_paragraph": "插入 Word 段落",
            "write_sheet_data": "写入 Excel 单元格",
            "design_pptx_theme_layout": "设计 PPT 主题版式",
            "write_pptx_slides": "更新 PPT 页面",
            "add_pptx_slides": "新增 PPT 页面",
            "create_file": "创建文件",
            "copy_file": "复制文件",
            "read_file_range": "读取文本片段",
            "replace_file_selection": "替换文本选区",
            "compare_files": "对比文件",
            "compare_docx_and_annotate": "对比并标注 Word 差异",
            "extract_to_file": "提取到文件",
            "annotate_file": "添加批注",
            "run_python_code": "运行代码处理",
        }
        return labels.get(tool_name, f"调用工具 {tool_name}")

    def _tool_plan_description(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        files: List[FileTaskFile],
        request: FileTaskRequest,
    ) -> str:
        if tool_name == "read_sheet_data":
            source = (
                self._display_path(tool_args.get("path"))
                or self._first_file_name(files, {"xlsx", "xlsm", "csv"})
                or "表格文件"
            )
            sheet = str(tool_args.get("sheet_name") or "").strip()
            rows = str(tool_args.get("max_rows") or "").strip()
            suffix = f"，工作表：{sheet}" if sheet else ""
            rows_text = f"，最多 {rows} 行" if rows else ""
            return f"读取 {source} 的表格数据{suffix}{rows_text}。"
        if tool_name == "inspect_workbook_structure":
            source = (
                self._display_path(tool_args.get("path"))
                or self._first_file_name(files, {"xlsx", "xlsm"})
                or "Excel 文件"
            )
            return f"检查 {source} 的工作表结构、公式分布和外部链接依赖。"
        if tool_name == "audit_financial_workbook":
            source = (
                self._display_path(tool_args.get("path"))
                or self._first_file_name(files, {"xlsx", "xlsm"})
                or "财务模型"
            )
            return f"审计 {source} 的三表完整性、外部依赖和关键年份序列红旗。"
        if tool_name == "insert_excel_as_docx_table":
            source = (
                self._display_path(tool_args.get("source_path"))
                or self._first_file_name(files, {"xlsx", "xlsm", "csv"})
                or "表格文件"
            )
            target = (
                self._display_path(tool_args.get("target_path"))
                or request.target_path
                or self._first_file_name(files, {"docx"}, target=True)
                or "Word 文档"
            )
            table_title = str(tool_args.get("table_title") or "").strip()
            title_text = f"，表题：{table_title}" if table_title else ""
            return f"把 {source} 的数据作为真实 Word 表格插入 {self._display_path(target) or target}{title_text}。"
        if tool_name == "insert_image_into_docx":
            target = (
                self._display_path(tool_args.get("path"))
                or request.target_path
                or self._first_file_name(files, {"docx"}, target=True)
                or "Word 文档"
            )
            image_path = (
                self._display_path(tool_args.get("image_path"))
                or str(tool_args.get("image_path") or "图片文件").strip()
                or "图片文件"
            )
            title = str(tool_args.get("title") or "").strip()
            title_text = f"，图题：{title}" if title else ""
            return f"把 {image_path} 作为真实图片插入 {self._display_path(target) or target}{title_text}。"
        if tool_name == "write_docx_content":
            target = (
                self._display_path(tool_args.get("path"))
                or request.target_path
                or self._first_file_name(files, {"docx"}, target=True)
                or "Word 文档"
            )
            return f"把生成后的段落写入 {self._display_path(target) or target}。"
        if tool_name == "insert_docx_paragraph":
            target = (
                self._display_path(tool_args.get("path"))
                or request.target_path
                or self._first_file_name(files, {"docx"}, target=True)
                or "Word 文档"
            )
            before = str(tool_args.get("before_heading") or "").strip()
            after = str(tool_args.get("after_heading") or "").strip()
            anchor = f"、位于“{before}”之前" if before else (f"、位于“{after}”之后" if after else "")
            return f"向 {self._display_path(target) or target} 插入一个 Word 段落{anchor}。"
        if tool_name == "clear_docx_review_marks":
            target = (
                self._display_path(tool_args.get("path"))
                or request.target_path
                or self._first_file_name(files, {"docx"}, target=True)
                or "Word 文档"
            )
            scope = (
                str(tool_args.get("scope") or "comments").strip().lower() or "comments"
            )
            if scope == "all":
                return f"清除 {self._display_path(target) or target} 中的批注并接受修订。"
            if scope == "revisions":
                return f"接受并清除 {self._display_path(target) or target} 中的修订标记。"
            return f"清除 {self._display_path(target) or target} 中的全部批注。"
        if tool_name == "write_sheet_data":
            target = (
                self._display_path(tool_args.get("path"))
                or request.target_path
                or self._first_file_name(files, {"xlsx", "xlsm"}, target=True)
                or "Excel 文件"
            )
            sheet = str(tool_args.get("sheet_name") or "").strip()
            sheet_text = f"，工作表：{sheet}" if sheet else ""
            return f"把结构化更新写入 {self._display_path(target) or target}{sheet_text}。"
        if tool_name == "annotate_file":
            target = (
                self._display_path(tool_args.get("path"))
                or request.target_path
                or self._first_file_name(
                    files, {"docx", "pdf", "txt", "md"}, target=True
                )
                or "目标文件"
            )
            requirement = str(tool_args.get("requirement") or "").strip()
            if requirement:
                return f"按要求为 {self._display_path(target) or target} 生成并写回批注：{_compact_line(requirement, 90)}。"
            return f"把结构化批注写入 {self._display_path(target) or target}。"
        if tool_name in {
            "design_pptx_theme_layout",
            "write_pptx_slides",
            "add_pptx_slides",
        }:
            target = (
                self._display_path(tool_args.get("path"))
                or request.target_path
                or self._first_file_name(files, {"pptx"}, target=True)
                or "PPT 文件"
            )
            if tool_name == "design_pptx_theme_layout":
                style_brief = str(tool_args.get("style_brief") or "").strip()
                style_text = f"，风格要求：{style_brief}" if style_brief else ""
                return f"为 {self._display_path(target) or target} 套用统一主题、字体、配色和安全版式{style_text}。"
            action = "新增" if tool_name == "add_pptx_slides" else "更新"
            return f"在 {self._display_path(target) or target} 中{action}幻灯片内容。"
        if tool_name == "parse_file_to_text":
            source = (
                self._display_path(tool_args.get("path"))
                or self._first_file_name(files, set())
                or "文件"
            )
            return f"解析 {source} 的文本内容，供后续分析使用。"
        if tool_name == "read_file_range":
            source = (
                self._display_path(tool_args.get("path"))
                or self._first_file_name(
                    files, {"txt", "md", "csv", "json", "py", "js", "html", "css"}
                )
                or "文本文件"
            )
            start = str(tool_args.get("start_line") or "1").strip()
            end = str(tool_args.get("end_line") or "").strip()
            window = f"第 {start} 到 {end} 行" if end else f"从第 {start} 行开始"
            return f"读取 {source} 的{window}，供后续分析使用。"
        if tool_name == "replace_file_selection":
            target = (
                self._display_path(tool_args.get("path"))
                or request.target_path
                or self._first_file_name(
                    files,
                    {"txt", "md", "csv", "json", "py", "js", "html", "css"},
                    target=True,
                )
                or "文本文件"
            )
            return f"把改写后的选区内容写回 {self._display_path(target) or target}。"
        if tool_name == "compare_files":
            raw_paths = str(tool_args.get("file_paths") or "").strip()
            aspect = str(tool_args.get("aspect") or "content").strip()
            return f"对比文件{f'：{raw_paths}' if raw_paths else ''}，比较维度：{aspect}。"
        if tool_name == "run_python_code":
            return "在沙盒中运行代码处理数据，必要时生成图表或中间文件。"
        target = self._display_path(
            tool_args.get("path")
            or tool_args.get("target_path")
            or tool_args.get("destination")
        )
        return f"执行 {tool_name}{f'，目标：{target}' if target else ''}。"

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

    def _single_context_file(
        self, files: List[FileTaskFile], types: set[str]
    ) -> Optional[FileTaskFile]:
        matches: List[FileTaskFile] = []
        for file_info in files:
            file_type = (
                file_info.type
                or Path(file_info.path or file_info.name).suffix.lstrip(".")
            ).lower()
            if types and file_type not in types:
                continue
            matches.append(file_info)
        return matches[0] if len(matches) == 1 else None

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
        return re.split(r"[\\/]+", text)[-1] or text

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
        return str(images[-1].get("path") or "").strip()

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
        except Exception:
            pass
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
                {
                    "tool_name": "supervisor_guard",
                    "success": False,
                    "blocked": True,
                    "native_stepwise": True,
                    "result_preview": f"监管层阻止写入：当前 PDF 页窗文本质量不足（{reason_text}），不能据此生成分步 DOCX 摘要。",
                },
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
        raw_target = str(request.target_path or "").strip()
        if raw_target:
            return (
                raw_target
                if os.path.isabs(raw_target)
                else str(Path(raw_target).resolve())
            )
        docx_file = self._first_context_file(
            files, {"docx"}, target=True
        ) or self._first_context_file(files, {"docx"})
        if docx_file and docx_file.path:
            return docx_file.path
        pdf_file = self._first_context_file(files, {"pdf"})
        if pdf_file and pdf_file.path:
            pdf_path = Path(pdf_file.path)
            return str(pdf_path.with_name(f"{pdf_path.stem}_分步总结.docx"))
        return ""

    def _latest_pdf_snippet_quality(
        self, snippets: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        pdf_snippets = [
            item
            for item in snippets
            if isinstance(item, dict)
            and (
                str(item.get("source") or item.get("path") or "")
                .lower()
                .endswith(".pdf")
                or str(item.get("path") or "").lower().endswith(".pdf")
            )
        ]
        if not pdf_snippets:
            return {
                "usable": False,
                "reason": "missing_pdf_context",
                "char_count": 0,
                "unique_chars": 0,
            }
        text = str(
            pdf_snippets[-1].get("_raw_text") or pdf_snippets[-1].get("preview") or ""
        )
        return _pdf_text_quality(text)

    def _tool_args_docx_paragraph_text(self, tool_args: Dict[str, Any]) -> str:
        raw_paragraphs = tool_args.get("paragraphs")
        items: Any = []
        if isinstance(raw_paragraphs, str) and raw_paragraphs.strip():
            try:
                items = json.loads(raw_paragraphs)
            except Exception:
                items = []
        elif isinstance(raw_paragraphs, list):
            items = raw_paragraphs
        texts: List[str] = []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    texts.append(str(item.get("text") or ""))
                elif item is not None:
                    texts.append(str(item))
        content = str(tool_args.get("content") or "").strip()
        if content:
            texts.append(content)
        return "\n".join(text for text in texts if text.strip())

    def _tool_args_docx_paragraph_count(self, tool_args: Dict[str, Any]) -> int:
        raw_paragraphs = tool_args.get("paragraphs")
        if isinstance(raw_paragraphs, str) and raw_paragraphs.strip():
            try:
                items = json.loads(raw_paragraphs)
            except Exception:
                return 1
        elif isinstance(raw_paragraphs, list):
            items = raw_paragraphs
        else:
            return 1 if str(tool_args.get("content") or "").strip() else 0
        return len(items) if isinstance(items, list) else 1

    def _local_docx_edit_block_message(
        self,
        request: FileTaskRequest,
        tool_name: str,
        tool_args: Dict[str, Any],
    ) -> str:
        if tool_name != "write_docx_content":
            return ""
        task_text = str(request.task or "")
        if not re.search(
            r"(?:只追加|只加|追加一句|加一句|插入一句|保留已有表格|保留.*表格|append one|add one|insert one|preserve.*table|keep.*table)",
            task_text,
            re.IGNORECASE,
        ):
            return ""
        if self._tool_args_docx_paragraph_count(tool_args) <= 1:
            return ""
        return (
            "监管层阻止写入：当前任务是 DOCX 局部编辑，用户要求只追加少量内容并保留已有表格，"
            "不能用 write_docx_content 把多段正文重新追加到文末。"
            "请改用 insert_docx_paragraph(path=目标 DOCX, text=要追加的句子, "
            "before_heading=下一章节标题，如 Next Actions；如没有下一章节，再使用 after_heading)。"
        )

    def _stepwise_docx_write_block_message(
        self,
        request: FileTaskRequest,
        snippets: List[Dict[str, Any]],
        recipe_skeleton: Dict[str, Any],
        tool_name: str,
        tool_args: Dict[str, Any],
    ) -> str:
        if not _looks_like_windowed_pdf_task(request, recipe_skeleton):
            return ""
        if tool_name == "create_file":
            target = str(tool_args.get("path") or "").strip().lower()
            if not target.endswith(".docx"):
                return ""
        elif tool_name != "write_docx_content":
            return ""
        quality = self._latest_pdf_snippet_quality(snippets)
        if not quality.get("usable"):
            return (
                "监管层阻止写入：当前 PDF 页窗的可提取文本质量不足，不能把水印、乱码或空内容写成总结。"
                f" 质量原因：{quality.get('reason') or 'unknown'}；"
                f"可用字符数：{quality.get('alpha_num_chars') or quality.get('char_count') or 0}；"
                f"唯一字符数：{quality.get('unique_chars') or 0}。"
                " 下一轮请改用新的 start_page/end_page 读取后续页窗；如果连续页窗仍不可读，应停止写入并提示需要 OCR/视觉解析。"
            )

        text = self._tool_args_docx_paragraph_text(tool_args)
        if tool_name != "create_file" and re.search(
            r"^\s*#{1,6}\s+", text, re.MULTILINE
        ):
            return (
                "监管层阻止写入：write_docx_content 的 paragraphs 不能包含 Markdown 标题符号 #。"
                " 请使用 paragraph.style='Heading 1' 这类 Word 段落样式。"
            )
        progress_patterns = (
            r"^\s*步骤\s*\d+\s*[：:]",
            r"当前进度\s*[：:]",
            r"下一步(?:计划|继续|处理)",
            r"等待(?:用户|我|确认|继续)",
            r"请回复\s*[\"“]?继续",
            r"当前步骤已(?:成功)?(?:完成|写入)",
            r"状态\s*[：:]",
            r"file\.changed",
            r"目标\s*DOCX\s*文件已成功更新",
        )
        if any(
            re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            for pattern in progress_patterns
        ):
            return (
                "监管层阻止写入：DOCX 正文不能包含任务进度、等待确认、下一步计划或 file.changed 这类前端提示。"
                " 请重写 paragraphs：只写当前页窗的实质内容摘要、关键发现、证据/主题；"
                "页码只可作为“来源页码：第 x-y 页”这样的简短来源说明，不要写等待继续或下一步计划。"
            )
        quality_block = self._stepwise_docx_content_quality_block_message(
            snippets, text
        )
        if quality_block:
            return quality_block
        return ""

    def _stepwise_docx_content_quality_block_message(
        self, snippets: List[Dict[str, Any]], text: str
    ) -> str:
        latest_pdf_snippet = next(
            (
                item
                for item in reversed(snippets or [])
                if isinstance(item, dict)
                and (
                    str(item.get("source") or item.get("path") or "")
                    .lower()
                    .endswith(".pdf")
                    or str(item.get("path") or "").lower().endswith(".pdf")
                )
            ),
            {},
        )
        expected_start = int(latest_pdf_snippet.get("start_page") or 0)
        expected_end = int(latest_pdf_snippet.get("end_page") or 0)
        expected_range = (
            (expected_start, expected_end) if expected_start and expected_end else None
        )
        body = str(text or "").strip()
        if not body:
            return "监管层阻止写入：当前分步 DOCX 正文为空。请写入当前页窗的摘要、关键发现、结构/内容线索和来源页码。"
        if re.search(r"(^|\s)(?:\*\*[^*\n]+\*\*|__[^_\n]+__|[-*_]{3,})(\s|$)", body):
            return (
                "监管层阻止写入：分步 DOCX 正文不能包含 Markdown 标记（如 **加粗**、---）。"
                " 请用 Word 段落样式和纯文本标签写入。"
            )

        combined_label_patterns = (
            r"文档识别\s*/\s*核心要点",
            r"段落主题\s*/\s*关键发现",
            r"内容线索\s*/\s*案例线索",
        )
        if any(re.search(pattern, body) for pattern in combined_label_patterns):
            return (
                "监管层阻止写入：分步 DOCX 正文不能使用“文档识别/核心要点”这类合并标签。"
                " 请改用固定独立标签：文档识别、段落主题、结构线索、内容线索、来源页码。"
            )

        section_ranges: List[tuple[int, int]] = []
        declared_page_ranges: List[tuple[int, int]] = []
        for line in body.splitlines():
            match = re.match(
                r"^\s*【?\s*第\s*(\d+)\s*[-－—~至]\s*(\d+)\s*页[^。\n]{0,40}(?:】|[:：])",
                line,
            )
            if match:
                section_ranges.append((int(match.group(1)), int(match.group(2))))
            if re.search(r"(?:当前页窗摘要|来源页码)", line):
                for range_match in re.finditer(
                    r"第\s*(\d+)\s*[-－—~至]\s*(\d+)\s*页",
                    line,
                ):
                    declared_page_ranges.append(
                        (int(range_match.group(1)), int(range_match.group(2)))
                    )
        unique_section_ranges = list(dict.fromkeys(section_ranges))
        unique_declared_ranges = list(dict.fromkeys(declared_page_ranges))
        if len(unique_section_ranges) > 1:
            ranges = "、".join(
                f"第 {start}-{end} 页" for start, end in unique_section_ranges[:4]
            )
            return (
                "监管层阻止写入：单个分步窗口的 DOCX 正文不能同时覆盖多个页窗标题。"
                f" 检测到：{ranges}。请只写当前页窗内容，上一页窗内容不要重复写入。"
            )
        if section_ranges and section_ranges.count(section_ranges[0]) > 1:
            start, end = section_ranges[0]
            return f"监管层阻止写入：第 {start}-{end} 页在本次写入中出现了重复小节标题。" " 请合并为一个小节，删除重复标题和重复要点。"
        if (
            expected_range
            and unique_section_ranges
            and unique_section_ranges[0] != expected_range
        ):
            expected_label = f"第 {expected_start}-{expected_end} 页"
            actual_start, actual_end = unique_section_ranges[0]
            return (
                "监管层阻止写入：DOCX 小节页码与当前读取窗口不一致。"
                f" 当前窗口应为 {expected_label}，但正文标题写成第 {actual_start}-{actual_end} 页。"
            )
        if expected_range and unique_declared_ranges:
            mismatched = [
                item for item in unique_declared_ranges if item != expected_range
            ]
            if mismatched:
                expected_label = f"第 {expected_start}-{expected_end} 页"
                actual_start, actual_end = mismatched[0]
                return (
                    "监管层阻止写入：DOCX 页窗标签与当前读取窗口不一致。"
                    f" 当前窗口应为 {expected_label}，但正文写成第 {actual_start}-{actual_end} 页。"
                )

        normalized_blocks: List[str] = []
        for line in body.splitlines():
            cleaned = re.sub(r"\s+", "", line)
            cleaned = re.sub(r"^[\-*•\d.、（）()]+", "", cleaned)
            if len(cleaned) >= 16:
                normalized_blocks.append(cleaned.lower())
        seen_blocks: set[str] = set()
        repeated_blocks: List[str] = []
        for block in normalized_blocks:
            if block in seen_blocks:
                repeated_blocks.append(block)
            seen_blocks.add(block)
        if repeated_blocks:
            return "监管层阻止写入：当前分步 DOCX 正文存在重复段落。请去重后再写入。"

        label_hits = sum(
            1 for label in ("文档识别", "段落主题", "结构线索", "内容线索", "来源页码") if label in body
        )
        if label_hits < 4:
            return (
                "监管层阻止写入：当前分步摘要缺少稳定结构。"
                " 请按“当前页窗摘要 / 文档识别 / 段落主题 / 结构线索 / 内容线索 / 来源页码”重写。"
            )
        return ""

    def _stepwise_docx_wait_artifact(
        self,
        request: FileTaskRequest,
        files: List[FileTaskFile],
        snippets: List[Dict[str, Any]],
        file_changes: List[Dict[str, Any]],
        recipe_skeleton: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if not _looks_like_windowed_pdf_task(request, recipe_skeleton):
            return None
        docx_change = next(
            (
                change
                for change in file_changes
                if str(change.get("operation") or "") == "write_docx_content"
                and str(change.get("path") or change.get("file_path") or "")
                .lower()
                .endswith(".docx")
            ),
            None,
        )
        if not docx_change:
            return None
        target_path = str(
            docx_change.get("path")
            or docx_change.get("file_path")
            or request.target_path
            or self._stepwise_docx_target_path(request, files)
            or ""
        ).strip()
        pdf_file = self._first_context_file(files, {"pdf"})
        latest_pdf_snippet = next(
            (
                item
                for item in reversed(snippets or [])
                if isinstance(item, dict)
                and (
                    str(item.get("source") or item.get("path") or "")
                    .lower()
                    .endswith(".pdf")
                    or str(item.get("path") or "").lower().endswith(".pdf")
                )
            ),
            {},
        )
        window_pages = _stepwise_pdf_window_pages(request)
        current_step_index = _stepwise_pdf_step_index(request)
        current_start = int(
            latest_pdf_snippet.get("start_page")
            or (1 + current_step_index * window_pages)
        )
        current_end = int(
            latest_pdf_snippet.get("end_page") or (current_start + window_pages - 1)
        )
        next_step_index = current_step_index + 1
        next_start = current_end + 1
        next_end = next_start + window_pages - 1

        resume_files = [
            file_info.public_dict()
            for file_info in files
            if file_info and (file_info.path or file_info.name)
        ]
        for item in resume_files:
            if target_path and str(item.get("path") or "") == target_path:
                item["target"] = True
        original_task = (
            str(workflow_resume_control(request).get("original_task") or "").strip()
            or str(request.task or "").strip()
        )
        resume_request = {
            "task": f"继续当前分步文件任务的下一步：处理 PDF 第 {next_start}-{next_end} 页，并把本段实质分析追加到同一个 DOCX。",
            "session_id": request.session_id,
            "model_mode": request.model_mode,
            "model_id": request.model_id,
            "target_path": target_path,
            "files": resume_files,
            "options": {
                "workflow_checkpoint": {
                    "adapter": "generic_tool_loop",
                    "policy": "confirm_each_step",
                    "step_index": next_step_index,
                    "window_pages": window_pages,
                    "original_task": original_task,
                    "source_path": pdf_file.path if pdf_file and pdf_file.path else "",
                    "target_path": target_path,
                },
                "followup_context": {
                    "kind": "stepwise_task_resume",
                    "source": "koto_stepwise_resume_artifact",
                    "followup_action": "resume",
                    "stepwise": {
                        "policy": "confirm_each_step",
                        "completed_page_range": f"{current_start}-{current_end}",
                        "next_page_range": f"{next_start}-{next_end}",
                        "next_step_index": next_step_index,
                        "original_task": original_task,
                    },
                },
            },
        }
        artifact: Dict[str, Any] = {
            "artifact_type": "koto_stepwise_resume_v1",
            "category": "stepwise_confirmation",
            "title": f"继续处理第 {next_start}-{next_end} 页",
            "summary": f"上一段（第 {current_start}-{current_end} 页）已写入 DOCX。可以继续处理第 {next_start}-{next_end} 页。",
            "suggested_next_step": f"点击继续处理第 {next_start}-{next_end} 页",
            "action_label": f"继续第 {next_start}-{next_end} 页",
            "route": "long_pdf_stepwise_docx_summary",
            "current_step_status": "written",
            "completed_page_range": f"{current_start}-{current_end}",
            "next_page_range": f"{next_start}-{next_end}",
            "next_start_page": next_start,
            "next_end_page": next_end,
            "next_step_index": next_step_index,
            "window_pages": window_pages,
            "original_task": original_task,
            "resume_request": resume_request,
        }
        if target_path:
            artifact["target_path"] = target_path
        if pdf_file and pdf_file.path:
            artifact["source_path"] = pdf_file.path
        return artifact

    def _stepwise_pdf_fallback_paragraphs(
        self,
        request: FileTaskRequest,
        pdf_snippet: Dict[str, Any],
        exc: Exception,
    ) -> List[Dict[str, str]]:
        preview = str(
            pdf_snippet.get("_raw_text") or pdf_snippet.get("preview") or ""
        ).strip()
        pages = [
            int(match.group(1)) for match in re.finditer(r"\[Page\s+(\d+)\]", preview)
        ]
        start_page = int(pdf_snippet.get("start_page") or 0)
        end_page = int(pdf_snippet.get("end_page") or 0)
        if start_page and end_page:
            page_range = (
                f"第 {start_page}-{end_page} 页"
                if start_page != end_page
                else f"第 {start_page} 页"
            )
        elif pages:
            page_range = (
                f"第 {min(pages)}-{max(pages)} 页"
                if min(pages) != max(pages)
                else f"第 {pages[0]} 页"
            )
        else:
            page_range = "当前页窗口"
        insights = self._stepwise_pdf_fallback_insights(preview)
        cleaned_preview = re.sub(r"\[Page\s+\d+\]", " ", preview, flags=re.IGNORECASE)
        cleaned_preview = re.sub(r"\s+", " ", cleaned_preview).strip(" ；;，,")

        def _field(label: str) -> str:
            prefix = f"{label}："
            for item in insights:
                text = str(item or "").strip()
                if text.startswith(prefix):
                    return text[len(prefix) :].strip()
            return ""

        source_name = _compact_line(
            Path(
                str(pdf_snippet.get("source") or pdf_snippet.get("path") or "PDF 文档")
            ).stem,
            160,
        )
        document_value = _field("文档识别") or f"当前页窗来自“{source_name}”。"
        topic_value = _field("段落主题")
        structure_value = _field("结构线索")
        content_value = _field("内容线索")

        supplemental = [
            str(item or "").strip()
            for item in insights
            if item
            and not str(item).startswith(("文档识别：", "段落主题：", "结构线索：", "内容线索：", "来源页码："))
        ]
        if not topic_value:
            topic_seed = (
                content_value
                or (supplemental[0] if supplemental else "")
                or cleaned_preview
            )
            topic_value = _compact_line(topic_seed, 180) or "当前页窗文本较短，主题需结合后续页窗继续确认。"
        if not structure_value:
            structure_seed = "；".join(supplemental[:2])
            structure_value = (
                _compact_line(structure_seed, 220)
                if structure_seed
                else "当前页窗作为本步骤材料，记录可提取的结构与上下文线索，供后续页窗衔接。"
            )
        if not content_value:
            content_seed = cleaned_preview or "当前页窗未提取到足够正文，暂不能形成可靠内容摘要。"
            content_value = _compact_line(content_seed, 260)
        paragraphs = [
            {"text": f"当前页窗摘要（{page_range}）", "style": "Heading 1"},
            {"text": f"文档识别：{document_value}"},
            {"text": f"段落主题：{topic_value}"},
            {"text": f"结构线索：{structure_value}"},
            {"text": f"内容线索：{content_value}"},
            {"text": f"来源页码：{page_range}"},
        ]
        return paragraphs

    def _stepwise_pdf_fallback_insights(self, preview: str) -> List[str]:
        cleaned = re.sub(
            r"\[Page\s+\d+\]", "\n", str(preview or ""), flags=re.IGNORECASE
        )
        raw_lines = [
            re.sub(r"\s+", " ", line).strip(" \t|-") for line in cleaned.splitlines()
        ]

        def _is_running_header(line: str) -> bool:
            compact = re.sub(r"\s+", "", line)
            return bool(
                re.search(
                    r"Annual Report on Digital Technology Application|Case Study in Chinese Museums",
                    line,
                    re.IGNORECASE,
                )
                or "中国博物馆数字技术应用及案例研究年度报告" in compact
                or re.fullmatch(r"(?:SUMMAR|ARTICLE|综|述|篇)", line, flags=re.IGNORECASE)
            )

        def _is_noise_line(line: str) -> bool:
            if not line or len(line) < 2:
                return True
            if line.isdigit() or re.fullmatch(r"\d+\s+\d+", line):
                return True
            if _is_running_header(line):
                return True
            return False

        def _join_pdf_body_lines(source_lines: List[str]) -> List[str]:
            blocks: List[str] = []
            buffer = ""

            def _flush() -> None:
                nonlocal buffer
                text = buffer.strip(" ；;，,")
                if len(text) >= 12:
                    blocks.append(text)
                buffer = ""

            for line in source_lines:
                if _is_noise_line(line):
                    _flush()
                    continue
                if re.fullmatch(r"\d+\.\s+.+", line) and len(line) > 90:
                    _flush()
                    continue
                starts_new = bool(
                    re.match(r"^[一二三四五六七八九十]+、", line)
                    or re.match(r"^\d+[.、]\s*", line)
                    or re.match(r"^《.+》", line)
                    or re.match(r"^表\d+", line)
                )
                if starts_new:
                    _flush()
                    buffer = line
                elif buffer and len(buffer) + len(line) <= 260:
                    separator = "" if re.search(r"[\u4e00-\u9fff]$", buffer) else " "
                    buffer = f"{buffer}{separator}{line}"
                else:
                    _flush()
                    buffer = line
                if re.search(r"[。！？!?]$", line) or len(buffer) >= 220:
                    _flush()
            _flush()

            deduped: List[str] = []
            seen_blocks: set[str] = set()
            for block in blocks:
                key = re.sub(r"\s+", "", block).lower()
                if key in seen_blocks:
                    continue
                seen_blocks.add(key)
                deduped.append(block)
            return deduped

        lines: List[str] = []
        seen: set[str] = set()
        for line in raw_lines:
            if _is_noise_line(line) or len(line) < 4:
                continue
            key = line.lower()
            if key in seen:
                continue
            seen.add(key)
            lines.append(line)
            if len(lines) >= 80:
                break

        annual_title = next(
            (
                line
                for line in raw_lines
                if line
                and (
                    "Annual Report" in line
                    or "年度报告" in line
                    or "中国博物馆数字技术应用及案例研究年度报告" in re.sub(r"\s+", "", line)
                )
            ),
            "",
        )
        section_title = next(
            (
                line
                for line in lines
                if re.match(r"^[一二三四五六七八九十]+、", line)
                or line.startswith("关于")
                or re.match(r"^《.+》", line)
            ),
            "",
        )
        organizer = next(
            (
                line
                for line in lines
                if len(line) <= 120
                and not re.match(r"^\d+[.、]", line)
                and (
                    re.search(
                        r"^(?:主\s*编|执行主编|副\s*主\s*编|专家顾问|编\s*辑|英文翻译|美术编辑)",
                        line,
                    )
                    or "委员会" in line
                    or "中国博物馆协会资助项目" in line
                    or re.search(r"中国博物馆协会.*(?:编|委员会)", line)
                )
            ),
            "",
        )
        editor_lines = [
            line
            for line in lines
            if re.search(r"(?:主\s*编|执行主编|副\s*主\s*编|专家顾问|编辑)", line)
        ][:3]
        toc_lines = [
            line
            for line in lines
            if len(line) <= 50 and re.search(r"(?:目录|引言|综述篇|案例篇|参考文献|作者简介)", line)
        ][:4]
        body_blocks = _join_pdf_body_lines(raw_lines)
        content_lines = [
            line
            for line in body_blocks
            if len(line) >= 18
            and line != annual_title
            and line != section_title
            and not (section_title and line.startswith(section_title))
            and line != organizer
            and line not in editor_lines
            and line not in toc_lines
            and not _is_running_header(line)
            and not re.search(
                r"^(?:主\s*编|执行主编|副\s*主\s*编|专家顾问|编\s*辑|英文翻译|美术编辑)",
                line,
            )
        ][:4]

        insights: List[str] = []
        if annual_title:
            insights.append(f"文档识别：当前页窗来自“{_compact_line(annual_title, 180)}”。")
        if section_title:
            insights.append(f"段落主题：{_compact_line(section_title, 180)}。")
        if organizer and organizer not in {annual_title, section_title}:
            insights.append(f"组织信息：{_compact_line(organizer, 180)}。")
        if editor_lines:
            insights.append(
                "编写线索："
                + "；".join(_compact_line(line, 120) for line in editor_lines)
                + "。"
            )
        if toc_lines:
            insights.append(
                "结构线索：" + "；".join(_compact_line(line, 120) for line in toc_lines) + "。"
            )
        if content_lines:
            insights.append(
                "内容线索："
                + "；".join(_compact_line(line, 180) for line in content_lines)
                + "。"
            )
        if not insights:
            excerpt_lines = [_compact_line(line, 140) for line in lines[:4]]
            if excerpt_lines:
                insights.append("当前页窗可读内容集中在：" + "；".join(excerpt_lines) + "。")
        if not insights:
            insights.append("当前页窗未提取到足够正文，暂不能形成可靠内容摘要。")
        return insights

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
        resolved_classification = resolved_context.classification
        resolved_intent_plan = resolved_context.intent_plan
        resolved_known_tool_gap = resolved_context.known_tool_gap
        workflows = json.dumps(supported_file_workflows(), ensure_ascii=False, indent=2)
        file_list = (
            ", ".join(
                (file_info.path or file_info.name)
                for file_info in files
                if file_info.path or file_info.name
            )
            or "none"
        )
        capability_profiles = build_request_capability_profiles(request)
        skeleton = recipe_skeleton or build_recipe_skeleton(
            request,
            files,
            resolved_classification,
            resolved_intent_plan,
            [],
        )
        known_gap_text = ""
        if resolved_known_tool_gap:
            known_gap_text = (
                "\n已知原生工具缺口：\n"
                + json.dumps(resolved_known_tool_gap, ensure_ascii=False, indent=2)
                + "\n"
            )
        capability_text = ""
        if capability_profiles:
            capability_text = (
                "文件能力概览：" + json.dumps(capability_profiles, ensure_ascii=False) + "\n"
            )
        followup_context = self._followup_context(request)
        financial_chart_docx_guidance = _prompt_financial_chart_docx_guidance(
            self._looks_like_financial_xlsx_docx_chart_report_task(request, files)
        )
        docx_files = [
            self._display_path(file_info.path or file_info.name)
            for file_info in files
            if str(
                file_info.type
                or Path(str(file_info.path or file_info.name)).suffix.lstrip(".")
            ).lower()
            in {"docx", "doc"}
        ]
        docx_compare_annotate_guidance = _prompt_docx_compare_annotate_guidance(
            "compare_docx_and_annotate"
            in resolved_classification.matched_capabilities,
            docx_files,
        )
        followup_guidance = _prompt_followup_guidance(followup_context)
        target_docx = (
            self._display_path(request.target_path)
            or self._first_file_name(files, {"docx"}, target=True)
            or self._first_file_name(files, {"docx"})
            or "当前 DOCX"
        )
        single_docx_annotate_guidance = _prompt_single_docx_annotate_guidance(
            resolved_classification.docx_annotation_request,
            target_docx,
        )
        clear_docx_review_guidance = _prompt_clear_docx_review_guidance(
            (not resolved_classification.docx_annotation_request)
            and self._is_docx_clear_review_request(request),
            target_docx,
        )
        return _build_file_task_system_prompt(
            output_mode_guidance=self._output_mode_guidance(
                resolved_classification
            ),
            intent_plan_guidance=self._intent_plan_guidance(resolved_intent_plan),
            followup_guidance=followup_guidance,
            financial_chart_docx_guidance=financial_chart_docx_guidance,
            docx_compare_annotate_guidance=docx_compare_annotate_guidance,
            clear_docx_review_guidance=clear_docx_review_guidance,
            single_docx_annotate_guidance=single_docx_annotate_guidance,
            execution_brief_schema=self._execution_brief_schema(),
            recipe_skeleton=skeleton,
            file_list=file_list,
            target_path=request.target_path,
            capability_text=capability_text,
            known_gap_text=known_gap_text,
            workflows=workflows,
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
        capability_profiles = build_request_capability_profiles(request)
        followup_context = self._followup_context(request)
        skeleton = recipe_skeleton or build_recipe_skeleton(
            request,
            files,
            resolved_classification,
            resolved_intent_plan,
            [],
        )
        return _build_file_task_messages(
            request=request,
            snippets=snippets,
            files=files,
            classification=resolved_classification,
            intent_plan=resolved_intent_plan,
            known_tool_gap=resolved_known_tool_gap,
            capability_profiles=capability_profiles,
            followup_context=followup_context,
            recipe_skeleton=skeleton,
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
            max_rounds=self._max_rounds,
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
                    file_states_for_changes(file_changes), ensure_ascii=False
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
                return {
                    "passed": False,
                    "status": "quality_gate_failed",
                    "summary": "文件已有变更，但未满足本任务的关键质量门禁。",
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
