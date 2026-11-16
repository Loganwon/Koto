from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_file_task_request_parses_workspace_routing_decision() -> None:
    from app.core.agent.file_task_contract import FileTaskRequest

    request = FileTaskRequest.from_mapping(
        {
            "task": "总结这个文件",
            "options": {
                "workspace_route_intent": {
                    "route_kind": "complex_task",
                    "route": "file_task",
                    "task_type": "FILE_TASK",
                    "confidence": 0.91,
                    "route_source": "model_primary_intent",
                    "workflow_candidates": ["file_summary"],
                    "requires_adjudication": False,
                }
            },
        }
    )

    assert request.routing_decision is not None
    assert request.routing_decision.route == "file_task"
    assert request.routing_decision.confidence == 0.91
    assert request.routing_decision.public_dict()["candidate_workflows"] == [
        "file_summary"
    ]


def test_routing_decision_is_context_not_a_second_model_route() -> None:
    planning = (ROOT / "app/core/agent/file_task_planning.py").read_text(
        encoding="utf-8"
    )
    decision = (ROOT / "app/core/agent/file_task_decision_context.py").read_text(
        encoding="utf-8"
    )

    assert "_adjudicate_intent_if_needed" not in planning
    assert "def build_decision_context_payload(" in decision
    assert "def trusted_file_task_routing_decision(" in decision


def test_workspace_payload_exposes_top_level_routing_decision() -> None:
    source = (ROOT / "web/src/workspace/task-dispatcher.ts").read_text(encoding="utf-8")
    routing = (ROOT / "web/src/workspace/task-routing-decision.ts").read_text(
        encoding="utf-8"
    )

    assert "export function normalizeFileTaskRoutingDecision(" in routing
    assert "routing_decision: routingDecision" in source
    assert "explicitTaskPayload.routing_decision = explicitRoutingDecision;" in source


def test_runtime_decision_context_groups_deterministic_plan_data() -> None:
    from app.core.agent.file_task_contract import (
        FileTaskClassification,
        FileTaskExecutionContext,
        FileTaskIntentPlan,
        FileTaskPlanCheck,
        FileTaskRequirementSet,
    )
    from app.core.agent.file_task_decision_context import build_decision_context_payload

    context = FileTaskExecutionContext(
        classification=FileTaskClassification(task_family="analyze"),
        intent_plan=FileTaskIntentPlan(recommended_strategy="answer_only"),
        requirements=FileTaskRequirementSet(requested_operation="read"),
        plan_check=FileTaskPlanCheck(passed=True),
        effective_planner_policy="kernel_only",
        effective_planner_backend="kernel",
    )
    payload = build_decision_context_payload(context, {"route": "file_task"})

    assert payload["classification"]["task_family"] == "analyze"
    assert payload["plan_check"]["passed"] is True
