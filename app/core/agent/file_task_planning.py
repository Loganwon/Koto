# -*- coding: utf-8 -*-
"""Classification, planning, and plan-audit stage for file tasks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional

from app.core.agent.file_task_classification import (
    build_decision_context_payload,
    routing_decision_payload as _decision_context_routing_decision_payload,
)
from app.core.agent.file_task_completion_contract import build_completion_contract
from app.core.agent.file_task_doc_annotate_fallback import (
    apply_doc_annotate_bridge_fallback,
)
from app.core.agent.file_task_doc_annotate_request import (
    docx_annotation_has_request_contract as _doc_annotate_has_request_contract,
)
from app.core.agent.file_task_supervisor_audit import build_supervisor_audit
from app.core.agent.file_task_tool_catalog import supported_file_workflows
from app.core.agent.file_task_whitebox import build_recipe_skeleton
from app.core.agent.file_task_workflow_state import (
    build_workflow_state,
    supervisor_status_payload,
)


@dataclass
class FileTaskPlanResult:
    terminal: bool
    context_files: List[Any]
    known_tool_gap: Any
    execution_context: Any
    classification: Any
    intent_plan: Any
    requirements: Any
    plan_check: Any
    quick_action_mode: str
    simple_quick_action: bool
    write_intent: bool
    bridge_execution_mode: bool
    tool_defs: List[Dict[str, Any]]
    executor: Any
    recipe_skeleton: Dict[str, Any]
    completion_contract_payload: Dict[str, Any]
    completion_criteria: List[str]
    workflow_state: Dict[str, Any]
    constraint_audit: Dict[str, Any]
    supervisor_audit_payload: Dict[str, Any]
    classification_payload: Dict[str, Any]
    intent_plan_payload: Dict[str, Any]
    requirements_payload: Dict[str, Any]
    plan_check_payload: Dict[str, Any]
    decision_context_payload: Dict[str, Any]


class FileTaskPlanningPhase:
    """Stream plan construction and plan-check events through a runtime port."""

    def __init__(self, runtime: Any):
        self._runtime = runtime

    def stream(
        self,
        *,
        ledger: Any,
        request: Any,
        mark_phase: Callable[[str], None],
        performance_snapshot: Callable[..., Dict[str, Any]],
    ) -> Iterable[Any]:
        runtime = self._runtime
        context_files = runtime._context_files(request)
        mark_phase("context_files")
        base_classification = runtime._classify_request(request, context_files)
        mark_phase("classification")
        intent_adjudication = runtime._adjudicate_intent_if_needed(
            request, context_files, base_classification
        )
        mark_phase("intent_adjudication")
        classification = runtime._apply_intent_adjudication(
            request, context_files, base_classification, intent_adjudication
        )
        classification = runtime._normalize_mainline_contract(
            request, context_files, classification
        )
        mark_phase("classification_normalization")

        execution_context = runtime._build_execution_context(
            request,
            context_files,
            classification=classification,
            intent_adjudication=intent_adjudication,
            quick_action_mode=runtime._quick_action_mode(request),
        )
        mark_phase("execution_context")
        known_tool_gap = execution_context.known_tool_gap
        classification = execution_context.classification
        intent_plan = execution_context.intent_plan
        requirements = execution_context.requirements
        plan_check = execution_context.plan_check
        quick_action_mode = execution_context.quick_action_mode
        simple_quick_action = execution_context.simple_quick_action
        write_intent = execution_context.write_intent
        bridge_fallback = apply_doc_annotate_bridge_fallback(
            request=request,
            files=context_files,
            classification=classification,
            write_intent=write_intent,
            docx_annotation_has_contract=_doc_annotate_has_request_contract,
        )
        classification = bridge_fallback.classification
        write_intent = bridge_fallback.write_intent
        bridge_execution_mode = classification.execution_mode == "doc_annotate_bridge"

        def _result(*, terminal: bool = False) -> FileTaskPlanResult:
            return FileTaskPlanResult(
                terminal=terminal,
                context_files=context_files,
                known_tool_gap=known_tool_gap,
                execution_context=execution_context,
                classification=classification,
                intent_plan=intent_plan,
                requirements=requirements,
                plan_check=plan_check,
                quick_action_mode=quick_action_mode,
                simple_quick_action=simple_quick_action,
                write_intent=write_intent,
                bridge_execution_mode=bridge_execution_mode,
                tool_defs=tool_defs,
                executor=executor,
                recipe_skeleton=recipe_skeleton,
                completion_contract_payload=completion_contract_payload,
                completion_criteria=completion_criteria,
                workflow_state=workflow_state,
                constraint_audit=constraint_audit,
                supervisor_audit_payload=supervisor_audit_payload,
                classification_payload=classification_payload,
                intent_plan_payload=intent_plan_payload,
                requirements_payload=requirements_payload,
                plan_check_payload=plan_check_payload,
                decision_context_payload=decision_context_payload,
            )

        if bridge_execution_mode:
            tool_defs = []
            executor = None
        else:
            gateway = runtime._build_tool_gateway(request, context_files)
            tool_defs = runtime._tool_defs_for_classification(
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
        constraint_audit = runtime._constraint_audit(
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
        mark_phase("plan_materialization")

        classification_payload = classification.public_dict()
        intent_plan_payload = intent_plan.public_dict()
        requirements_payload = requirements.public_dict()
        plan_check_payload = plan_check.public_dict()
        routing_decision_payload = _decision_context_routing_decision_payload(request)
        decision_context_payload = build_decision_context_payload(
            execution_context,
            routing_decision_payload,
        )
        plan_runtime = runtime._build_runtime_metadata(
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
        plan_runtime["performance"] = performance_snapshot()

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
                "performance": performance_snapshot(),
                **classification_payload,
                "intent_plan": intent_plan_payload,
                "decision_context": decision_context_payload,
                **(
                    {"routing_decision": routing_decision_payload}
                    if routing_decision_payload
                    else {}
                ),
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

        if runtime._is_cancelled(request):
            yield runtime._cancelled_event(ledger, request)
            return _result(terminal=True)

        if not simple_quick_action:
            yield ledger.event(
                "task.classified",
                {
                    **execution_context.public_dict(),
                    "decision_context": decision_context_payload,
                    "workflow_state": workflow_state,
                    "supervisor_audit": supervisor_audit_payload,
                    "performance": performance_snapshot(),
                    **(
                        {"routing_decision": routing_decision_payload}
                        if routing_decision_payload
                        else {}
                    ),
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
                "decision_context": decision_context_payload,
                "workflow_state": workflow_state,
                "supervisor_audit": supervisor_audit_payload,
                "performance": performance_snapshot(),
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
            blocked_runtime = {
                **plan_runtime,
                "terminal_status": "blocked",
            }
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
                runtime._build_step_result_payload(
                    title="监管检查",
                    summary=supervisor_audit.summary,
                    status="failed",
                    runtime=blocked_runtime,
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
                    "runtime": blocked_runtime,
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
            return _result(terminal=True)

        if not plan_check.passed:
            yield ledger.event(
                "step.result",
                runtime._build_step_result_payload(
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
            return _result(terminal=True)

        plan_steps = intent_plan.dynamic_steps or runtime._build_plan(
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
                    "summary": runtime._plan_summary(request, context_files, write_intent),
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

        return _result()
