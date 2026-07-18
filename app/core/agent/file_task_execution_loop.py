# -*- coding: utf-8 -*-
"""The model-and-tool execution phase extracted from ``FileTaskRuntime.run``."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from app.core.agent.file_task_contract import FileTaskEvent, FileTaskToolStreamResult
from app.core.agent.file_task_evidence_guard import sanitize_unverified_readonly_quotes
from app.core.agent.file_task_failure import build_model_execution_failure
from app.core.agent.file_task_financial_report_recovery import recover_financial_report
from app.core.agent.file_task_guard_emission import build_tool_guard_emission
from app.core.agent.file_task_readonly_loop_guard import (
    READONLY_ANSWER_GUARD_PENDING_SUMMARY,
    READONLY_DUPLICATE_GUARD_SUMMARY,
    WRITE_DUPLICATE_STOP_SUMMARY,
    WRITE_DUPLICATE_SUPERVISOR_SUMMARY,
)
from app.core.agent.file_task_readonly_loop_guard import (
    answer_only_round as _readonly_answer_only_round,
)
from app.core.agent.file_task_readonly_loop_guard import (
    discard_answer_only_tool_calls as _readonly_discard_answer_only_tool_calls,
)
from app.core.agent.file_task_readonly_loop_guard import (
    duplicate_guard_tool_payload as _readonly_duplicate_guard_tool_payload,
)
from app.core.agent.file_task_readonly_loop_guard import (
    readonly_duplicate_final_summary as _readonly_duplicate_final_summary,
)
from app.core.agent.file_task_readonly_loop_guard import (
    readonly_duplicate_guard_reminder as _readonly_duplicate_guard_reminder,
)
from app.core.agent.file_task_readonly_loop_guard import (
    should_retry_readonly_answer_guard as _readonly_should_retry_answer_guard,
)
from app.core.agent.file_task_readonly_loop_guard import (
    should_retry_readonly_duplicate_guard as _readonly_should_retry_duplicate_guard,
)
from app.core.agent.file_task_readonly_loop_guard import (
    should_retry_write_duplicate_guard as _readonly_should_retry_write_duplicate_guard,
)
from app.core.agent.file_task_readonly_loop_guard import (
    supervisor_guard_tool_payload as _readonly_supervisor_guard_tool_payload,
)
from app.core.agent.file_task_runtime_utils import _is_error_result, _preview
from app.core.agent.file_task_step_verification import (
    build_supervisor_step_verification_payload as _build_supervisor_step_verification_payload,
)
from app.core.agent.file_task_tool_catalog import (
    is_file_task_tool,
    is_write_tool,
    stringify_result,
    tool_result_preview,
    write_target_for_tool,
)
from app.core.agent.file_task_whitebox import (
    WhiteboxExecutionPlan,
    build_decision_audit,
    extract_whitebox_execution_plan,
    validate_whitebox_plan,
)
from app.core.agent.file_task_workflow_state import supervisor_status_payload
from app.core.agent.tool_design_protocol import (
    build_next_action_artifact,
    extract_tool_gap_from_response,
    merge_tool_gaps,
)

logger = logging.getLogger(__name__)


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


class FileTaskExecutionLoop:
    """Stream the regular whitebox model/tool rounds through a runtime port."""

    def __init__(self, runtime: Any):
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
        workflow_state: Dict[str, Any],
        completion_criteria: List[str],
        write_intent: bool,
        executor: Any,
        max_verify_repair_attempts: int,
        max_write_ops_per_file: int,
    ) -> Iterable[FileTaskEvent]:
        runtime = self._runtime
        execute_step_id = "execute"
        yield ledger.event(
            "step.started",
            {
                "title": "模型规划并调用工具",
                "detail": "模型只能调用 Koto 文件工具目录中的 allowlist 工具。",
                "max_rounds": runtime._max_rounds,
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
        )
        model_request = runtime._initial_model_request(request)
        completed_write_ops: Dict[str, int] = {}
        file_changes: List[Dict[str, Any]] = []
        final_summary = ""
        completed_task = False
        model_failed = False
        execution_failure: Optional[Dict[str, Any]] = None
        readonly_fallback_used = False
        last_tool_batch_signature = ""
        planner_runtime_payload: Dict[str, Any] = {}
        last_tool_gap_signature = ""
        plan_confirmed_emitted = False
        last_execution_brief_signature = ""
        write_guard_injected = False
        readonly_answer_guard_injected = False
        duplicate_supervisor_guard_injected = False
        readonly_duplicate_guard_injected = False
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

        def _result(*, cancelled: bool = False) -> FileTaskExecutionResult:
            return FileTaskExecutionResult(
                cancelled=cancelled,
                execute_step_id=execute_step_id,
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
            )

        repair_round_limit = runtime._max_rounds + max_verify_repair_attempts
        for round_index in range(1, repair_round_limit + 1):
            if runtime._is_cancelled(request):
                yield runtime._cancelled_event(ledger, request)
                return _result(cancelled=True)
            if round_index > runtime._max_rounds and not pending_repair_check_payload:
                break
            answer_only_plan = _readonly_answer_only_round(
                write_intent=write_intent,
                readonly_answer_guard_injected=readonly_answer_guard_injected,
                readonly_duplicate_guard_injected=readonly_duplicate_guard_injected,
                has_context=bool(snippets or readonly_tool_outputs),
                tool_defs=tool_defs,
            )
            answer_only_round = answer_only_plan.enabled
            active_tool_defs = answer_only_plan.tool_defs
            yield ledger.event(
                "model.call.started",
                {
                    "round": round_index,
                    "model_mode": request.model_mode,
                    "model_id": request.model_id,
                    "tool_count": len(active_tool_defs),
                    "message_count": len(messages),
                    "answer_only": answer_only_round,
                },
                step_id=execute_step_id,
            )
            try:
                response = runtime._call_model(
                    request=model_request,
                    messages=messages,
                    system=system,
                    tools=active_tool_defs,
                )
            except Exception as exc:
                logger.warning("[FileTaskRuntime] model call failed: %s", exc)
                execution_failure = build_model_execution_failure(
                    exc,
                    round_index=round_index,
                    model_mode=str(request.model_mode or ""),
                    model_id=str(request.model_id or ""),
                )
                model_failed = True
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
                deterministic_change = (
                    yield from runtime._write_stepwise_pdf_docx_native(
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
                )
                if deterministic_change:
                    file_changes.append(deterministic_change)
                    completed_task = True
                    execution_failure = None
                    model_failed = False
                    final_summary = str(
                        deterministic_change.get("summary")
                        or "模型不可用，已使用 Koto 原生流程写入当前分步结果。"
                    )
                    yield ledger.event(
                        "file.changed", deterministic_change, step_id=execute_step_id
                    )
                    yield ledger.event(
                        "step.result",
                        runtime._build_step_result_payload(
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
                    else runtime._fallback_readonly_summary(
                        request,
                        snippets,
                        context_files,
                        exc,
                    )
                )
                if fallback_summary:
                    readonly_fallback_used = True
                    execution_failure = None
                    model_failed = False
                    completed_task = False
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
                        runtime._build_step_result_payload(
                            title="模型规划并调用工具",
                            summary=fallback_summary,
                            status="failed",
                            round_index=round_index,
                        ),
                        step_id=execute_step_id,
                    )
                else:
                    error_text = str(
                        execution_failure.get("summary") or "模型调用失败。"
                    )
                    failed_step = runtime._build_step_result_payload(
                        title="模型规划并调用工具",
                        summary=error_text,
                        status="failed",
                        round_index=round_index,
                    )
                    failed_step["failure"] = dict(execution_failure)
                    yield ledger.event(
                        "step.result",
                        failed_step,
                        step_id=execute_step_id,
                    )
                break

            if runtime._is_cancelled(request):
                yield runtime._cancelled_event(ledger, request)
                return _result(cancelled=True)

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
            content_text, tool_calls = runtime._normalize_model_response(
                response, active_tool_defs
            )
            answer_only_tool_calls = _readonly_discard_answer_only_tool_calls(
                answer_only=answer_only_round,
                tool_calls=tool_calls,
            )
            tool_calls = answer_only_tool_calls.tool_calls
            discarded_answer_only_tool_calls = answer_only_tool_calls.discarded_count
            if discarded_answer_only_tool_calls:
                # A response coupled to an unavailable tool call is not a
                # trustworthy final answer (for example, "I will write the
                # file" beside a discarded write call). Force the normal
                # readonly-answer guard to request a direct grounded answer.
                content_text = ""
            yield ledger.event(
                "model.call.finished",
                {
                    "round": round_index,
                    "success": True,
                    "model_mode": request.model_mode,
                    "model_id": request.model_id,
                    "tool_call_count": len(tool_calls),
                    "discarded_tool_call_count": discarded_answer_only_tool_calls,
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
            execution_brief, content_text = runtime._extract_execution_brief(
                response, content_text
            )
            tool_execution_brief, tool_calls = (
                runtime._extract_execution_brief_tool_call(tool_calls)
            )
            if tool_execution_brief and not execution_brief:
                execution_brief = tool_execution_brief
            if not write_intent and not tool_calls:
                content_text = sanitize_unverified_readonly_quotes(
                    task=request.task,
                    text=content_text,
                )
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
                        if round_index < runtime._max_rounds:
                            repair_message = runtime._whitebox_plan_repair_message(
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
                        final_summary = str(
                            gate_payload.get("summary") or "白盒计划审查未通过。"
                        )
                        completed_task = False
                        yield ledger.event(
                            "step.result",
                            runtime._build_step_result_payload(
                                title="白盒计划审查",
                                summary=final_summary,
                                status="failed",
                                round_index=round_index,
                            ),
                            step_id=execute_step_id,
                        )
                        break
            if not tool_gap and known_tool_gap and not tool_calls:
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
                gap_runtime = runtime._build_runtime_metadata(
                    terminal_status="tool_gap",
                    readonly_fallback_used=readonly_fallback_used,
                    model_failed=model_failed,
                    planner_payload=planner_runtime_payload,
                )
                next_action_artifact = runtime._with_runtime_context(
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
                    if round_index < runtime._max_rounds:
                        repair_message = runtime._whitebox_plan_repair_message(
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
                        runtime._build_step_result_payload(
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
                    runtime._build_confirmed_plan(
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
                        runtime._build_step_result_payload(
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
                if execution_brief and round_index < runtime._max_rounds:
                    model_request = runtime._request_after_execution_brief(
                        request, model_request, execution_brief
                    )
                    reminder = runtime._execution_brief_continue_message(
                        request, execution_brief
                    )
                    final_summary = (
                        execution_brief.summary
                        or content_text
                        or "已完成任务分析，准备继续执行。"
                    )
                    yield ledger.event(
                        "step.result",
                        runtime._build_step_result_payload(
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
                if execution_plan and round_index < runtime._max_rounds:
                    reminder = runtime._execution_plan_continue_message(
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
                        runtime._build_step_result_payload(
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
                runtime_status = runtime._tool_runtime_status(tool_runtime_outcome)
                awaiting_confirmation = runtime_status == "awaiting_confirmation"
                terminal_write_blocked = runtime_status in {"blocked", "write_blocked"}
                if (
                    write_intent
                    and not file_changes
                    and not awaiting_confirmation
                    and not terminal_write_blocked
                    and not write_guard_injected
                    and round_index < runtime._max_rounds
                ):
                    write_guard_injected = True
                    reminder = runtime._write_retry_message(request, context_files)
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
                        runtime._build_step_result_payload(
                            title="模型规划并调用工具",
                            summary=reminder,
                            status="failed",
                            round_index=round_index,
                        ),
                        step_id=execute_step_id,
                    )
                    continue
                if (
                    write_intent
                    and pending_repair_check_payload
                    and round_index < repair_round_limit
                ):
                    repair_message = runtime._repair_retry_message(
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
                        runtime._build_step_result_payload(
                            title="修复监管",
                            summary=final_summary,
                            status="failed",
                            round_index=round_index,
                            file_changes=file_changes,
                        ),
                        step_id=execute_step_id,
                    )
                    continue
                if write_intent:
                    pending_images = runtime._pending_generated_docx_images(
                        request, context_files, generated_artifacts, file_changes
                    )
                    if pending_images and round_index < runtime._max_rounds:
                        reminder = runtime._generated_docx_image_insert_guard_message(
                            request, context_files, pending_images
                        )
                        yield ledger.event(
                            "tool.finished",
                            {
                                "tool_name": "image_insert_guard",
                                "success": False,
                                "result_preview": reminder,
                                "pending_image_count": len(pending_images),
                            },
                            step_id=execute_step_id,
                        )
                        messages.append({"role": "user", "content": reminder})
                        final_summary = reminder
                        yield ledger.event(
                            "step.result",
                            runtime._build_step_result_payload(
                                title="图表写入核验",
                                summary=reminder,
                                status="failed",
                                round_index=round_index,
                                file_changes=file_changes,
                            ),
                            step_id=execute_step_id,
                        )
                        continue
                    if pending_images:
                        native_changes = yield from runtime._insert_pending_generated_docx_images_native(
                            ledger,
                            request,
                            executor,
                            context_files,
                            pending_images,
                            execute_step_id,
                        )
                        if native_changes:
                            file_changes.extend(native_changes)
                            pending_images = runtime._pending_generated_docx_images(
                                request,
                                context_files,
                                generated_artifacts,
                                file_changes,
                            )
                    last_check_payload = runtime._verify_task(
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
                    if runtime._should_attempt_repair(
                        last_check_payload,
                        round_index=round_index,
                        repair_attempts=repair_attempts,
                    ):
                        repair_attempts += 1
                        repair_runtime = runtime._build_runtime_metadata(
                            terminal_status=str(
                                last_check_payload.get("status") or ""
                            ).strip(),
                            readonly_fallback_used=readonly_fallback_used,
                            model_failed=model_failed,
                            planner_payload=planner_runtime_payload,
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
                            runtime._build_step_result_payload(
                                title="检查执行状态",
                                summary=str(
                                    repair_check_payload.get("summary")
                                    or "检查未通过。"
                                ),
                                status=(
                                    "completed"
                                    if repair_check_payload.get("passed")
                                    else "failed"
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
                        repair_message = runtime._repair_retry_message(
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
                        runtime._build_step_result_payload(
                            title="模型规划并调用工具",
                            summary=runtime._execute_step_summary(
                                round_index=round_index,
                                final_summary=final_summary,
                                model_failed=model_failed,
                                tool_gap=tool_gap,
                                file_changes=file_changes,
                                tool_runtime_outcome=tool_runtime_outcome,
                            ),
                            status=runtime._execute_step_result_status(
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
                if _readonly_should_retry_answer_guard(
                    content_text=content_text,
                    has_context=bool(snippets or readonly_tool_outputs),
                    readonly_answer_guard_injected=readonly_answer_guard_injected,
                    round_index=round_index,
                    max_rounds=runtime._max_rounds,
                ):
                    readonly_answer_guard_injected = True
                    reminder = runtime._readonly_answer_required_message(
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
                    final_summary = READONLY_ANSWER_GUARD_PENDING_SUMMARY
                    yield ledger.event(
                        "step.result",
                        runtime._build_step_result_payload(
                            title="模型规划并调用工具",
                            summary=final_summary,
                            status="pending",
                            round_index=round_index,
                        ),
                        step_id=execute_step_id,
                    )
                    continue
                readonly_context_fallback = (
                    ""
                    if content_text
                    else runtime._readonly_context_summary(
                        request, snippets, readonly_tool_outputs
                    )
                )
                final_summary = (
                    content_text
                    or readonly_context_fallback
                    or "已读取上下文，但模型未生成可见分析结果。"
                )
                if readonly_context_fallback and not write_intent:
                    readonly_fallback_used = True
                    completed_task = False
                else:
                    completed_task = not write_intent or bool(file_changes)
                yield ledger.event(
                    "step.result",
                    runtime._build_step_result_payload(
                        title="模型规划并调用工具",
                        summary=runtime._execute_step_summary(
                            round_index=round_index,
                            final_summary=final_summary,
                            model_failed=model_failed,
                            tool_gap=tool_gap,
                            file_changes=file_changes,
                            tool_runtime_outcome=tool_runtime_outcome,
                        ),
                        status=runtime._execute_step_result_status(
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

            batch_signature = runtime._tool_batch_signature(tool_calls)
            if batch_signature and batch_signature == last_tool_batch_signature:
                if not write_intent:
                    guard_summary = READONLY_DUPLICATE_GUARD_SUMMARY
                    if _readonly_should_retry_duplicate_guard(
                        readonly_duplicate_guard_injected=readonly_duplicate_guard_injected,
                        round_index=round_index,
                        max_rounds=runtime._max_rounds,
                    ):
                        readonly_duplicate_guard_injected = True
                        source_lines = runtime._readonly_context_source_lines(
                            snippets, readonly_tool_outputs, limit=5
                        )
                        reminder = _readonly_duplicate_guard_reminder(
                            task=request.task,
                            source_lines=source_lines,
                        )
                        final_summary = guard_summary
                        messages.append({"role": "user", "content": reminder})
                        continue
                    readonly_context_fallback = runtime._readonly_context_summary(
                        request, snippets, readonly_tool_outputs
                    )
                    final_summary = _readonly_duplicate_final_summary(
                        context_summary=readonly_context_fallback,
                        content_text=content_text,
                    )
                    if readonly_context_fallback and not content_text:
                        readonly_fallback_used = True
                        completed_task = False
                    else:
                        completed_task = True
                    yield ledger.event(
                        "step.result",
                        runtime._build_step_result_payload(
                            title="模型规划并调用工具",
                            summary=final_summary,
                            status="success",
                            round_index=round_index,
                            file_changes=file_changes,
                        ),
                        step_id=execute_step_id,
                    )
                    break
                if _readonly_should_retry_write_duplicate_guard(
                    write_intent=write_intent,
                    has_file_changes=bool(file_changes),
                    duplicate_supervisor_guard_injected=duplicate_supervisor_guard_injected,
                    round_index=round_index,
                    max_rounds=runtime._max_rounds,
                ):
                    duplicate_supervisor_guard_injected = True
                    final_summary = WRITE_DUPLICATE_SUPERVISOR_SUMMARY
                    reminder = runtime._duplicate_supervisor_retry_message(
                        request,
                        context_files,
                        classification,
                        intent_plan,
                        tool_calls,
                    )
                    yield ledger.event(
                        "tool.finished",
                        _readonly_supervisor_guard_tool_payload(reminder),
                        step_id=execute_step_id,
                    )
                    yield ledger.event(
                        "step.result",
                        runtime._build_step_result_payload(
                            title="监管纠偏",
                            summary=final_summary,
                            status="failed",
                            round_index=round_index,
                            file_changes=file_changes,
                        ),
                        step_id=execute_step_id,
                    )
                    messages.append({"role": "user", "content": reminder})
                    continue
                final_summary = WRITE_DUPLICATE_STOP_SUMMARY
                yield ledger.event(
                    "tool.finished",
                    _readonly_duplicate_guard_tool_payload(final_summary),
                    step_id=execute_step_id,
                )
                yield ledger.event(
                    "step.result",
                    runtime._build_step_result_payload(
                        title="模型规划并调用工具",
                        summary=final_summary,
                        status="failed",
                        round_index=round_index,
                        file_changes=file_changes,
                    ),
                    step_id=execute_step_id,
                )
                break
            last_tool_batch_signature = batch_signature

            for tool_index, tool_call in enumerate(tool_calls, start=1):
                if runtime._is_cancelled(request):
                    yield runtime._cancelled_event(ledger, request)
                    return _result(cancelled=True)
                tool_name = str(tool_call.get("name") or "").strip()
                tool_args = dict(tool_call.get("args") or {})
                tool_args = runtime._repair_tool_args_for_context(
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
                        summary=(f"准备调用 {tool_name}，监管层保持主线和工具边界。"),
                        active_step_id=(
                            "write_output"
                            if tool_stage == "writing"
                            else "model_reasoning"
                        ),
                        completed_step_ids=["read_context"],
                        file_changes=file_changes,
                    ),
                    step_id=current_step_id,
                )

                if not is_file_task_tool(tool_name):
                    error_text = f"工具 {tool_name or '<empty>'} 不在 Koto 文件任务 allowlist 中。"
                    guard = build_tool_guard_emission(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        tool_call_id=tool_call_id,
                        result_preview=error_text,
                        feedback_content=runtime._tool_feedback_for_model(
                            tool_name or "invalid_tool",
                            tool_args,
                            {"error": error_text},
                            success=False,
                            invalid=True,
                        ),
                        round_index=round_index,
                        tool_index=tool_index,
                        success=False,
                        blocked=True,
                        message_tool_name=tool_name or "invalid_tool",
                        include_blocked_in_finished=False,
                    )
                    yield ledger.event(
                        "tool.finished",
                        guard.tool_finished_payload,
                        step_id=current_step_id,
                    )
                    yield ledger.event(
                        "supervisor.step_verified",
                        guard.step_verified_payload,
                        step_id=current_step_id,
                    )
                    messages.append(guard.function_message)
                    continue

                exposed_tool_names = {
                    str(definition.get("name") or "").strip()
                    for definition in tool_defs
                    if str(definition.get("name") or "").strip()
                }
                if exposed_tool_names and tool_name not in exposed_tool_names:
                    error_text = runtime._recipe_tool_block_message(
                        tool_name,
                        classification,
                        exposed_tool_names,
                    )
                    guard = build_tool_guard_emission(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        tool_call_id=tool_call_id,
                        result_preview=error_text,
                        feedback_content=runtime._tool_feedback_for_model(
                            tool_name,
                            tool_args,
                            {"error": error_text},
                            success=False,
                            blocked=True,
                        ),
                        round_index=round_index,
                        tool_index=tool_index,
                        success=False,
                        blocked=True,
                    )
                    yield ledger.event(
                        "tool.finished",
                        guard.tool_finished_payload,
                        step_id=current_step_id,
                    )
                    yield ledger.event(
                        "supervisor.step_verified",
                        guard.step_verified_payload,
                        step_id=current_step_id,
                    )
                    messages.append(guard.function_message)
                    continue

                if (
                    is_write_tool(tool_name)
                    and tool_name != "run_python_code"
                    and (not write_intent or classification.output_mode != "write")
                ):
                    block_text = runtime._readonly_write_tool_block_message(
                        tool_name,
                        request,
                        classification.output_mode,
                    )
                    guard = build_tool_guard_emission(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        tool_call_id=tool_call_id,
                        result_preview=block_text,
                        feedback_content=runtime._tool_feedback_for_model(
                            tool_name,
                            tool_args,
                            {"error": block_text},
                            success=False,
                            blocked=True,
                        ),
                        round_index=round_index,
                        tool_index=tool_index,
                        success=False,
                        blocked=True,
                    )
                    yield ledger.event(
                        "tool.finished",
                        guard.tool_finished_payload,
                        step_id=current_step_id,
                    )
                    yield ledger.event(
                        "supervisor.step_verified",
                        guard.step_verified_payload,
                        step_id=current_step_id,
                    )
                    messages.append(guard.function_message)
                    continue

                if tool_name == "run_python_code" and (
                    not write_intent or classification.output_mode != "write"
                ):
                    block_text = runtime._readonly_run_python_write_block_message(
                        tool_args,
                        request,
                        classification.output_mode,
                    )
                    if block_text:
                        guard = build_tool_guard_emission(
                            tool_name=tool_name,
                            tool_args=tool_args,
                            tool_call_id=tool_call_id,
                            result_preview=block_text,
                            feedback_content=runtime._tool_feedback_for_model(
                                tool_name,
                                tool_args,
                                {"error": block_text},
                                success=False,
                                blocked=True,
                            ),
                            round_index=round_index,
                            tool_index=tool_index,
                            success=False,
                            blocked=True,
                        )
                        yield ledger.event(
                            "tool.finished",
                            guard.tool_finished_payload,
                            step_id=current_step_id,
                        )
                        yield ledger.event(
                            "supervisor.step_verified",
                            guard.step_verified_payload,
                            step_id=current_step_id,
                        )
                        messages.append(guard.function_message)
                        continue

                source_write_block = runtime._protected_source_write_block_message(
                    tool_name,
                    tool_args,
                    request,
                    context_files,
                )
                if source_write_block:
                    guard = build_tool_guard_emission(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        tool_call_id=tool_call_id,
                        result_preview=source_write_block,
                        feedback_content=runtime._tool_feedback_for_model(
                            tool_name,
                            tool_args,
                            {"error": source_write_block},
                            success=False,
                            blocked=True,
                        ),
                        round_index=round_index,
                        tool_index=tool_index,
                        success=False,
                        blocked=True,
                    )
                    yield ledger.event(
                        "tool.finished",
                        guard.tool_finished_payload,
                        step_id=current_step_id,
                    )
                    yield ledger.event(
                        "supervisor.step_verified",
                        guard.step_verified_payload,
                        step_id=current_step_id,
                    )
                    messages.append(guard.function_message)
                    continue

                local_docx_edit_block = runtime._local_docx_edit_block_message(
                    request,
                    tool_name,
                    tool_args,
                )
                if local_docx_edit_block:
                    guard = build_tool_guard_emission(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        tool_call_id=tool_call_id,
                        result_preview=local_docx_edit_block,
                        feedback_content=runtime._tool_feedback_for_model(
                            tool_name,
                            tool_args,
                            {"error": local_docx_edit_block},
                            success=False,
                            blocked=True,
                        ),
                        round_index=round_index,
                        tool_index=tool_index,
                        success=False,
                        blocked=True,
                        event_tool_name="supervisor_guard",
                    )
                    yield ledger.event(
                        "tool.finished",
                        guard.tool_finished_payload,
                        step_id=current_step_id,
                    )
                    yield ledger.event(
                        "supervisor.step_verified",
                        guard.step_verified_payload,
                        step_id=current_step_id,
                    )
                    messages.append(guard.function_message)
                    continue

                if is_write_tool(tool_name) and tool_name != "run_python_code":
                    target = write_target_for_tool(tool_name, tool_args)
                    write_key = runtime._write_dedupe_key_for_tool(tool_name, tool_args)
                    target_key = runtime._write_dedupe_key_for_target(target)
                    target_was_locked_by_code = (
                        bool(target_key)
                        and completed_write_ops.get(target_key, 0)
                        >= max_write_ops_per_file
                    )
                    same_write_was_completed = (
                        completed_write_ops.get(write_key, 0) >= max_write_ops_per_file
                    )
                    if target_was_locked_by_code or same_write_was_completed:
                        skip_text = f"{tool_name} 已成功写入过 {target or '同一目标'}，本次跳过以避免重复覆盖。"
                        guard = build_tool_guard_emission(
                            tool_name=tool_name,
                            tool_args=tool_args,
                            tool_call_id=tool_call_id,
                            result_preview=skip_text,
                            feedback_content=runtime._tool_feedback_for_model(
                                tool_name,
                                tool_args,
                                {"summary": skip_text},
                                success=True,
                                skipped=True,
                            ),
                            round_index=round_index,
                            tool_index=tool_index,
                            success=True,
                            blocked=False,
                            skipped=True,
                        )
                        yield ledger.event(
                            "tool.finished",
                            guard.tool_finished_payload,
                            step_id=current_step_id,
                        )
                        yield ledger.event(
                            "supervisor.step_verified",
                            guard.step_verified_payload,
                            step_id=current_step_id,
                        )
                        messages.append(guard.function_message)
                        continue

                stepwise_write_block = runtime._stepwise_docx_write_block_message(
                    request,
                    snippets,
                    recipe_skeleton,
                    tool_name,
                    tool_args,
                )
                if stepwise_write_block:
                    guard = build_tool_guard_emission(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        tool_call_id=tool_call_id,
                        result_preview=stepwise_write_block,
                        feedback_content=runtime._tool_feedback_for_model(
                            tool_name,
                            tool_args,
                            {"error": stepwise_write_block},
                            success=False,
                            blocked=True,
                        ),
                        round_index=round_index,
                        tool_index=tool_index,
                        success=False,
                        blocked=True,
                        event_tool_name="supervisor_guard",
                    )
                    yield ledger.event(
                        "tool.finished",
                        guard.tool_finished_payload,
                        step_id=current_step_id,
                    )
                    yield ledger.event(
                        "supervisor.step_verified",
                        guard.step_verified_payload,
                        step_id=current_step_id,
                    )
                    messages.append(guard.function_message)
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

                blocked_message = runtime._blocked_run_python_message(
                    tool_name, tool_args, request, context_files
                )
                if blocked_message:
                    guard = build_tool_guard_emission(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        tool_call_id=tool_call_id,
                        result_preview=blocked_message,
                        feedback_content=runtime._tool_feedback_for_model(
                            tool_name,
                            tool_args,
                            {"error": blocked_message},
                            success=False,
                            blocked=True,
                        ),
                        round_index=round_index,
                        tool_index=tool_index,
                        success=False,
                        blocked=True,
                    )
                    yield ledger.event(
                        "tool.finished",
                        guard.tool_finished_payload,
                        step_id=current_step_id,
                    )
                    yield ledger.event(
                        "supervisor.step_verified",
                        guard.step_verified_payload,
                        step_id=current_step_id,
                    )
                    messages.append(guard.function_message)
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
                        result = yield from runtime._consume_streaming_tool_result(
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

                if runtime._is_cancelled(request):
                    yield runtime._cancelled_event(ledger, request)
                    return _result(cancelled=True)

                recovery_artifacts: List[Dict[str, Any]] = []
                recovery_changes: List[Dict[str, Any]] = []
                recovery_message = ""
                if tool_name == "run_python_code" and success:
                    # A provider can report that its chart script succeeded while
                    # producing neither a marker nor a discoverable image.  Do
                    # not spend the remaining model rounds searching temporary
                    # folders: create the two data-driven recovery charts now so
                    # the next round can finish the requested DOCX insertion.
                    primary_artifacts = runtime._tool_artifacts(tool_name, result)
                    recovery_args = runtime._financial_chart_recovery_tool_args(
                        request,
                        context_files,
                        tool_args,
                        primary_artifacts,
                    )
                    if recovery_args:
                        yield ledger.event(
                            "code.started",
                            {
                                "code": str(recovery_args.get("code") or ""),
                                "financial_chart_recovery": True,
                            },
                            step_id=current_step_id,
                        )
                        try:
                            recovery_result = executor("run_python_code", recovery_args)
                            if isinstance(recovery_result, FileTaskToolStreamResult):
                                recovery_result = (
                                    yield from runtime._consume_streaming_tool_result(
                                        ledger,
                                        step_id=current_step_id,
                                        stream_result=recovery_result,
                                    )
                                )
                            recovery_success = not _is_error_result(recovery_result)
                        except Exception as exc:
                            recovery_result = f"Error: {exc}"
                            recovery_success = False
                            logger.warning(
                                "[FileTaskRuntime] financial chart recovery failed: %s",
                                exc,
                            )
                        recovery_model_result = runtime._tool_result_for_model(
                            "run_python_code", recovery_result
                        )
                        recovery_result_text = stringify_result(recovery_model_result)
                        recovery_artifacts = runtime._tool_artifacts(
                            "run_python_code", recovery_result
                        )
                        if recovery_success and recovery_artifacts:
                            recovery_changes = runtime._extract_file_changes(
                                "run_python_code", recovery_args, recovery_result
                            )
                            recovery_message = (
                                "运行时已补齐并验证财务图表图片。下一步必须继续写入目标 DOCX："
                                + ", ".join(
                                    str(item.get("path") or item.get("name") or "")
                                    for item in recovery_artifacts
                                    if isinstance(item, dict)
                                )
                                + "；请先写入分析正文和数据表，再逐张调用 insert_image_into_docx。"
                            )
                        yield ledger.event(
                            "code.output",
                            {
                                "text": runtime._code_output_preview(
                                    "run_python_code",
                                    recovery_result,
                                    recovery_result_text,
                                ),
                                "stream": "stdout" if recovery_success else "stderr",
                                "financial_chart_recovery": True,
                            },
                            step_id=current_step_id,
                        )
                        yield ledger.event(
                            "code.finished",
                            {
                                "success": recovery_success,
                                "financial_chart_recovery": True,
                            },
                            step_id=current_step_id,
                        )

                model_result = runtime._tool_result_for_model(tool_name, result)
                current_tool_runtime_outcome = runtime._extract_tool_runtime_outcome(
                    result
                )
                if current_tool_runtime_outcome:
                    tool_runtime_outcome = current_tool_runtime_outcome
                    artifact = current_tool_runtime_outcome.get("next_action_artifact")
                    if isinstance(artifact, dict):
                        next_action_artifact = artifact
                runtime_status = runtime._tool_runtime_status(
                    current_tool_runtime_outcome
                )
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
                artifacts = runtime._tool_artifacts(tool_name, result)
                if recovery_artifacts:
                    artifacts = [*artifacts, *recovery_artifacts]
                if tool_name == "run_python_code":
                    yield ledger.event(
                        "code.output",
                        {
                            "text": runtime._code_output_preview(
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
                        runtime._remember_generated_artifacts(
                            generated_artifacts, artifacts
                        )
                yield ledger.event(
                    "tool.finished", tool_finished_payload, step_id=current_step_id
                )

                if recovery_message:
                    model_result = (
                        f"{stringify_result(model_result)}\n{recovery_message}"
                    )
                messages.append(
                    {
                        "role": "function",
                        "name": tool_name,
                        "tool_call_id": tool_call_id,
                        "content": runtime._tool_feedback_for_model(
                            tool_name,
                            tool_args,
                            model_result,
                            success=success,
                            blocked=runtime_blocked,
                        ),
                    }
                )

                extracted_changes = runtime._extract_file_changes(
                    tool_name, tool_args, result
                )
                if recovery_changes:
                    extracted_changes = [*extracted_changes, *recovery_changes]
                if success and tool_name == "run_python_code":
                    # Python may already have modified the same target that a
                    # later dedicated writer proposes. Count the emitted file
                    # changes so a second writer cannot append/overwrite it.
                    for change in extracted_changes:
                        if not isinstance(change, dict):
                            continue
                        metadata = change.get("metadata")
                        metadata = metadata if isinstance(metadata, dict) else {}
                        changed_path = str(
                            change.get("file") or metadata.get("path") or ""
                        ).strip()
                        write_key = runtime._write_dedupe_key_for_target(changed_path)
                        if write_key:
                            completed_write_ops[write_key] = max(
                                completed_write_ops.get(write_key, 0), 1
                            )
                if (
                    success
                    and is_write_tool(tool_name)
                    and tool_name != "run_python_code"
                ):
                    write_key = runtime._write_dedupe_key_for_tool(tool_name, tool_args)
                    completed_write_ops[write_key] = (
                        completed_write_ops.get(write_key, 0) + 1
                    )

                if extracted_changes:
                    repair_attempts = 0
                    pending_repair_check_payload = None
                for change in extracted_changes:
                    file_changes.append(change)
                    yield ledger.event("file.changed", change, step_id=current_step_id)
                yield ledger.event(
                    "supervisor.step_verified",
                    _build_supervisor_step_verification_payload(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        success=success,
                        blocked=runtime_blocked,
                        summary=tool_finished_payload.get("result_preview"),
                        round_index=round_index,
                        tool_index=tool_index,
                        file_changes=extracted_changes,
                        artifacts=artifacts,
                    ),
                    step_id=current_step_id,
                )

            execute_round_summary = runtime._execute_step_summary(
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
                runtime._build_step_result_payload(
                    title="模型工具执行完成",
                    summary=execute_round_summary,
                    status=runtime._execute_step_result_status(
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
            if runtime._tool_runtime_status(tool_runtime_outcome) in {
                "blocked",
                "write_blocked",
            }:
                final_summary = execute_round_summary
                completed_task = False
                break
            if write_intent and file_changes and not tool_gap:
                pending_images = runtime._pending_generated_docx_images(
                    request, context_files, generated_artifacts, file_changes
                )
                if pending_images and round_index < runtime._max_rounds:
                    reminder = runtime._generated_docx_image_insert_guard_message(
                        request, context_files, pending_images
                    )
                    yield ledger.event(
                        "tool.finished",
                        {
                            "tool_name": "image_insert_guard",
                            "success": False,
                            "result_preview": reminder,
                            "pending_image_count": len(pending_images),
                        },
                        step_id=execute_step_id,
                    )
                    messages.append({"role": "user", "content": reminder})
                    final_summary = reminder
                    yield ledger.event(
                        "step.result",
                        runtime._build_step_result_payload(
                            title="图表写入核验",
                            summary=reminder,
                            status="failed",
                            round_index=round_index,
                            file_changes=file_changes,
                        ),
                        step_id=execute_step_id,
                    )
                    continue
                if pending_images:
                    native_changes = (
                        yield from runtime._insert_pending_generated_docx_images_native(
                            ledger,
                            request,
                            executor,
                            context_files,
                            pending_images,
                            execute_step_id,
                        )
                    )
                    if native_changes:
                        file_changes.extend(native_changes)
                        pending_images = runtime._pending_generated_docx_images(
                            request,
                            context_files,
                            generated_artifacts,
                            file_changes,
                        )
                last_check_payload = runtime._verify_task(
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
                if runtime._should_attempt_repair(
                    last_check_payload,
                    round_index=round_index,
                    repair_attempts=repair_attempts,
                ):
                    repair_attempts += 1
                    repair_runtime = runtime._build_runtime_metadata(
                        terminal_status=str(
                            last_check_payload.get("status") or ""
                        ).strip(),
                        readonly_fallback_used=readonly_fallback_used,
                        model_failed=model_failed,
                        planner_payload=planner_runtime_payload,
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
                        runtime._build_step_result_payload(
                            title="检查执行状态",
                            summary=str(
                                repair_check_payload.get("summary") or "检查未通过。"
                            ),
                            status=(
                                "completed"
                                if repair_check_payload.get("passed")
                                else "failed"
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
                    repair_message = runtime._repair_retry_message(
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
                and round_index < runtime._max_rounds
                and runtime._should_prompt_for_write_after_tool_round(
                    request, context_files, tool_calls, round_index
                )
            ):
                write_guard_injected = True
                reminder = runtime._write_retry_message(request, context_files)
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
            deterministic_change = yield from runtime._write_stepwise_pdf_docx_native(
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
                    runtime._build_step_result_payload(
                        title="原生分步兜底写入",
                        summary=final_summary,
                        status="completed",
                        file_changes=file_changes,
                    ),
                    step_id=execute_step_id,
                )

        if write_intent and not file_changes:
            financial_recovery = yield from recover_financial_report(
                runtime,
                ledger,
                request,
                executor,
                context_files,
                recipe_skeleton,
                step_id=execute_step_id,
            )
            if financial_recovery.attempted:
                file_changes.extend(financial_recovery.file_changes)
                generated_artifacts.extend(financial_recovery.artifacts)
                final_summary = financial_recovery.summary or final_summary
                completed_task = bool(financial_recovery.completed)
                last_check_payload = None
                if financial_recovery.file_changes:
                    execution_failure = None
                    model_failed = False
                yield ledger.event(
                    "step.result",
                    runtime._build_step_result_payload(
                        title="财务报告原生恢复",
                        summary=final_summary,
                        status="completed" if completed_task else "failed",
                        file_changes=file_changes,
                    ),
                    step_id=execute_step_id,
                )

        if not write_intent and not str(final_summary or "").strip():
            final_summary = runtime._readonly_context_summary(
                request, snippets, readonly_tool_outputs
            )
            if final_summary:
                readonly_fallback_used = True
                completed_task = False

        return _result()
