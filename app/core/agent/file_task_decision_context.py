from __future__ import annotations

from typing import Any, Dict, Optional

from app.core.agent.file_task_contract import (
    FileTaskDecisionContext,
    FileTaskExecutionContext,
    FileTaskRequest,
    FileTaskRoutingDecision,
)


def routing_decision_payload(request: FileTaskRequest) -> Dict[str, Any]:
    routing_decision = getattr(request, "routing_decision", None)
    if routing_decision is not None:
        return routing_decision.public_dict()
    options = request.options if isinstance(request.options, dict) else {}
    raw_decision = options.get("workspace_route_intent")
    if isinstance(raw_decision, dict):
        return FileTaskRoutingDecision.from_mapping(raw_decision).public_dict()
    return {}


def build_decision_context_payload(
    execution_context: FileTaskExecutionContext,
    route_payload: Dict[str, Any],
) -> Dict[str, Any]:
    effective_planner = {}
    if any(
        (
            execution_context.effective_planner_policy,
            execution_context.effective_planner_reason,
            execution_context.effective_planner_backend,
        )
    ):
        effective_planner = {
            "policy": execution_context.effective_planner_policy,
            "reason": execution_context.effective_planner_reason,
            "backend": execution_context.effective_planner_backend,
        }
    return FileTaskDecisionContext(
        routing_decision=dict(route_payload or {}),
        classification=execution_context.classification,
        intent_plan=execution_context.intent_plan,
        requirements=execution_context.requirements,
        plan_check=execution_context.plan_check,
        intent_adjudication=dict(execution_context.intent_adjudication or {}),
        effective_planner=effective_planner,
        quick_action_mode=execution_context.quick_action_mode,
        simple_quick_action=execution_context.simple_quick_action,
    ).public_dict()


def trusted_file_task_routing_decision(
    request: FileTaskRequest,
) -> Optional[FileTaskRoutingDecision]:
    routing_decision = getattr(request, "routing_decision", None)
    if routing_decision is None:
        options = request.options if isinstance(request.options, dict) else {}
        raw_decision = options.get("workspace_route_intent")
        if isinstance(raw_decision, dict):
            routing_decision = FileTaskRoutingDecision.from_mapping(raw_decision)
    if routing_decision is None:
        return None
    if routing_decision.route != "file_task":
        return None
    if routing_decision.route_kind and routing_decision.route_kind != "complex_task":
        return None
    if routing_decision.task_type and routing_decision.task_type != "FILE_TASK":
        return None
    if routing_decision.source_task_type in {"CHAT", "WEB_SEARCH"}:
        return None
    if routing_decision.confidence < 0.80:
        return None
    return routing_decision
