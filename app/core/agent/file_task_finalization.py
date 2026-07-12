# -*- coding: utf-8 -*-
"""Terminal verification and completion-event emission for file tasks."""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Iterable, List, Optional

from app.core.agent.file_task_contract import FileTaskEvent
from app.core.agent.file_task_terminal_report import (
    apply_terminal_check_overrides,
    build_terminal_run_summary,
    terminal_completed_task,
)
from app.core.agent.file_task_workflow_state import (
    attach_workflow_checkpoint,
    supervisor_status_payload,
)

logger = logging.getLogger(__name__)


class FileTaskFinalizationPhase:
    """Run terminal verification through a FileTaskRuntime port."""

    def __init__(self, runtime: Any):
        self._runtime = runtime

    def stream(
        self,
        *,
        ledger: Any,
        request: Any,
        executor: Any,
        snippets: List[Dict[str, Any]],
        context_files: List[Any],
        classification: Any,
        classification_payload: Dict[str, Any],
        completion_contract_payload: Dict[str, Any],
        completion_criteria: List[str],
        recipe_skeleton: Dict[str, Any],
        workflow_state: Dict[str, Any],
        write_intent: bool,
        quick_action_mode: str,
        file_changes: List[Dict[str, Any]],
        final_summary: str,
        completed_task: bool,
        model_failed: bool,
        readonly_fallback_used: bool,
        planner_runtime_payload: Dict[str, Any],
        last_check_payload: Optional[Dict[str, Any]],
        tool_gap: Optional[Dict[str, Any]],
        next_action_artifact: Optional[Dict[str, Any]],
        tool_runtime_outcome: Optional[Dict[str, Any]],
        generated_artifacts: List[Dict[str, Any]],
        readonly_tool_outputs: List[Dict[str, Any]],
        performance_snapshot: Callable[..., Dict[str, Any]],
    ) -> Iterable[FileTaskEvent]:
        runtime = self._runtime
        check_step_id = "check"
        if runtime._is_cancelled(request):
            yield runtime._cancelled_event(ledger, request)
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
            else runtime._verify_task(
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
        missing_read_refs = runtime._unsatisfied_explicit_read_file_references(
            request, snippets, readonly_tool_outputs
        )
        check_payload = apply_terminal_check_overrides(
            check_payload=check_payload,
            write_intent=write_intent,
            file_changes=file_changes,
            final_summary=final_summary,
            output_mode=classification.output_mode,
            tool_gap=tool_gap,
            snippets=snippets,
            readonly_tool_outputs=readonly_tool_outputs,
            requires_file_context=runtime._readonly_task_requires_file_context(
                request, context_files
            ),
            missing_read_refs=missing_read_refs,
        )
        pending_generated_images = runtime._pending_generated_docx_images(
            request, context_files, generated_artifacts, file_changes
        )
        if write_intent and pending_generated_images:
            check_payload = runtime._generated_docx_image_quality_failure(
                check_payload,
                pending_generated_images,
            )
        stepwise_artifact = runtime._stepwise_docx_wait_artifact(
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
        terminal_runtime = runtime._build_runtime_metadata(
            terminal_status=str(check_payload.get("status") or "").strip(),
            readonly_fallback_used=readonly_fallback_used,
            model_failed=model_failed,
            planner_payload=planner_runtime_payload,
        )
        terminal_runtime["performance"] = performance_snapshot(total=True)
        check_payload["runtime"] = terminal_runtime
        check_payload["performance"] = terminal_runtime["performance"]

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
            runtime._build_step_result_payload(
                title="检查执行状态",
                summary=str(check_payload.get("summary") or "检查完成。"),
                status=runtime._check_step_result_status(check_payload),
                runtime=terminal_runtime,
                passed=check_payload.get("passed"),
                file_changes=file_changes,
                next_action_artifact=check_payload.get("next_action_artifact")
                or next_action_artifact,
            ),
            step_id=check_step_id,
        )
        run_summary = build_terminal_run_summary(
            check_payload=check_payload,
            final_summary=final_summary,
            write_intent=write_intent,
            tool_gap=tool_gap,
            selected_recipe=str(classification_payload.get("selected_recipe") or ""),
            file_changes=file_changes,
        )
        # === v2: AI supervisor verification ===
        supervisor_result = None
        if runtime._task_supervisor is not None:
            try:
                supervisor_result = runtime._task_supervisor.verify(
                    plan=recipe_skeleton,
                    step_results=file_changes + readonly_tool_outputs,
                    completion_criteria=completion_criteria,
                    output_text=final_summary or str(check_payload.get("summary") or ""),
                )
                if supervisor_result is not None:
                    yield ledger.event(
                        "supervisor.verified",
                        {
                            "passed": supervisor_result.passed,
                            "stage": supervisor_result.stage,
                            "score": supervisor_result.score,
                            "report": supervisor_result.report,
                            "issues": supervisor_result.issues,
                            "fix_suggestions": supervisor_result.fix_suggestions,
                        },
                        step_id=check_step_id,
                    )
            except Exception as exc:
                logger.warning("[FileTaskRuntime] supervisor verification failed: %s", exc)

        is_text_quick_action = bool(quick_action_mode and quick_action_mode in ("simple", "polish", "translate", "summary", "rewrite", "continue", "check"))
        if is_text_quick_action and not file_changes:
            result_text = str(check_payload.get("summary") or final_summary or run_summary or "").strip()
            if result_text:
                run_payload_base = {
                    "can_insert": True,
                    "action_type": quick_action_mode,
                    "result_text": result_text,
                }
            else:
                run_payload_base = {}
        else:
            run_payload_base = {}

        run_payload = {
            **run_payload_base,
            "task": request.task,
            "mode": "whitebox_v1",
            "summary": run_summary,
            "completed_task": terminal_completed_task(
                check_payload=check_payload,
                completed_task=completed_task,
                write_intent=write_intent,
                file_changes=file_changes,
            ),
            "context": runtime._public_context_snippets(snippets[:8]),
            "file_changes": file_changes,
            "runtime": terminal_runtime,
            "performance": terminal_runtime["performance"],
            "quick_action_mode": quick_action_mode,
        }
        if not is_text_quick_action:
            run_payload.update({
                "workflow_version": recipe_skeleton.get("version"),
                "workflow_state": workflow_state,
                "recipe_skeleton": recipe_skeleton,
                "completion_contract": completion_contract_payload,
                **classification_payload,
            })
        if not is_text_quick_action:
            if tool_gap:
                run_payload["tool_gap"] = tool_gap
            if next_action_artifact:
                run_payload["next_action_artifact"] = next_action_artifact
        yield ledger.event("run.finished", run_payload)
