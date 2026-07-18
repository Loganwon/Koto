from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_file_task_request_parses_workspace_route_intent_as_routing_decision():
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
                    "reason": "file context is present",
                    "workflow_candidates": ["file_summary", "docx_review"],
                    "requires_adjudication": False,
                    "tool_path": "file_task.runtime.summary",
                    "display_label": "文件总结",
                    "steps": [
                        {"label": "读取文件", "tool_name": "read_file"},
                        {"title": "生成摘要", "description": "输出要点"},
                    ],
                }
            },
        }
    )

    assert request.routing_decision is not None
    assert request.routing_decision.route == "file_task"
    assert request.routing_decision.route_kind == "complex_task"
    assert request.routing_decision.task_type == "FILE_TASK"
    assert request.routing_decision.confidence == 0.91
    public = request.routing_decision.public_dict()
    assert public["route_source"] == "model_primary_intent"
    assert public["candidate_workflows"] == ["file_summary", "docx_review"]
    assert public["requires_adjudication"] is False
    assert public["final_tool_path"] == "file_task.runtime.summary"
    assert public["frontend_label"] == "文件总结"
    assert public["plan_steps"][0]["label"] == "读取文件"
    assert public["plan_steps"][0]["tool"] == "read_file"


def test_trusted_file_task_route_skips_default_adjudicator(monkeypatch):
    import app.core.agent.file_task_intent_adjudicator as adjudicator_module
    import app.core.agent.file_task_runtime as runtime_module
    from app.core.agent.file_task_contract import (
        FileTaskClassification,
        FileTaskFile,
        FileTaskRequest,
    )
    from app.core.agent.file_task_runtime import FileTaskRuntime

    original_adjudicator = runtime_module._intent_adjudicator_adjudicate_if_needed

    def guarded_adjudicator(**kwargs):
        request = kwargs["request"]
        if request.routing_decision is None:
            raise AssertionError("trusted route should provide routing_decision")
        return original_adjudicator(**kwargs)

    monkeypatch.setattr(
        runtime_module,
        "_intent_adjudicator_adjudicate_if_needed",
        guarded_adjudicator,
    )
    monkeypatch.setattr(
        adjudicator_module,
        "task_classifier_fast_path",
        lambda _request: (_ for _ in ()).throw(
            AssertionError("TaskClassifier fast path should not run for trusted route")
        ),
    )

    def fail_model(**_kwargs):
        raise AssertionError(
            "AI intent adjudicator should not run for non-ambiguous trusted route"
        )

    request = FileTaskRequest.from_mapping(
        {
            "task": "总结这个文件",
            "files": [{"path": "report.pdf", "name": "report.pdf", "type": "pdf"}],
            "options": {
                "enable_ai_intent_adjudicator": True,
                "workspace_route_intent": {
                    "route_kind": "complex_task",
                    "route": "file_task",
                    "task_type": "FILE_TASK",
                    "confidence": 0.9,
                    "reason": "model selected file task",
                },
            },
        }
    )
    runtime = FileTaskRuntime(model_client=fail_model)

    adjudication = runtime._adjudicate_intent_if_needed(
        request,
        [FileTaskFile(path="report.pdf", name="report.pdf", type="pdf")],
        FileTaskClassification(),
    )

    assert adjudication["source"] == "workspace_route_decision"
    assert adjudication["status"] == "trusted_file_task_route"
    assert adjudication["route"] == "file_task"


def test_trusted_file_task_route_still_adjudicates_ambiguous_write_intent():
    from app.core.agent.file_task_contract import (
        FileTaskClassification,
        FileTaskFile,
        FileTaskRequest,
    )
    from app.core.agent.file_task_intent_adjudicator import (
        should_adjudicate_trusted_route,
    )
    from app.core.agent.file_task_runtime import FileTaskRuntime

    request = FileTaskRequest.from_mapping(
        {
            "task": "优化这个文件的表达",
            "files": [{"path": "draft.docx", "name": "draft.docx", "type": "docx"}],
            "target_path": "draft.docx",
            "options": {
                "enable_ai_intent_adjudicator": True,
                "output_mode": "answer",
                "workspace_route_intent": {
                    "route_kind": "complex_task",
                    "route": "file_task",
                    "task_type": "FILE_TASK",
                    "confidence": 0.93,
                },
            },
        }
    )
    classification = FileTaskClassification(write_intent=True)

    runtime = FileTaskRuntime()

    assert should_adjudicate_trusted_route(
        request,
        [FileTaskFile(path="draft.docx", name="draft.docx", type="docx")],
        classification,
        should_adjudicate=runtime._should_adjudicate_intent,
    )


def test_forced_ai_intent_adjudicator_bypasses_local_classifier_fast_path(
    monkeypatch,
):
    import app.core.agent.file_task_intent_adjudicator as adjudicator_module
    from app.core.agent.file_task_contract import (
        FileTaskClassification,
        FileTaskRequest,
    )

    monkeypatch.setattr(
        adjudicator_module,
        "task_classifier_fast_path",
        lambda _request: (_ for _ in ()).throw(
            AssertionError("forced AI adjudication must bypass the local fast path")
        ),
    )
    model_calls = []

    def call_model(**kwargs):
        model_calls.append(kwargs)
        return {
            "content": (
                '{"intent":"create_file","confidence":0.95,'
                '"should_write":true,"needs_clarification":false}'
            )
        }

    result = adjudicator_module.adjudicate_intent_if_needed(
        request=FileTaskRequest(
            task="Create a new Word report without modifying the source file.",
            options={"enable_ai_intent_adjudicator": True},
        ),
        files=[],
        classification=FileTaskClassification(write_intent=True),
        should_adjudicate=lambda _request, _files, _classification: True,
        call_model=call_model,
        logger=adjudicator_module.logging.getLogger(__name__),
    )

    assert result["source"] == "ai_intent_adjudicator"
    assert result["status"] == "ok"
    assert result["intent"] == "create_file"
    assert len(model_calls) == 1


def test_workspace_file_task_payload_exposes_top_level_routing_decision():
    source = (ROOT / "web/src/workspace/task-dispatcher.ts").read_text(encoding="utf-8")
    routing = (ROOT / "web/src/workspace/task-routing-decision.ts").read_text(
        encoding="utf-8"
    )

    assert "export function normalizeFileTaskRoutingDecision(" in routing
    assert "routing_decision: routingDecision" in source
    assert "explicitTaskPayload.routing_decision = explicitRoutingDecision;" in source
    assert "normalized.candidate_workflows = candidateWorkflows;" in routing
    assert (
        "normalized.requires_adjudication = !!source.requires_adjudication;" in routing
    )
    assert "normalized.frontend_label = frontendLabel;" in routing
    assert "normalized.plan_steps = planSteps;" in routing


def test_runtime_decision_context_groups_route_classification_and_plan():
    from app.core.agent.file_task_contract import (
        FileTaskClassification,
        FileTaskExecutionContext,
        FileTaskIntentPlan,
        FileTaskPlanCheck,
        FileTaskRequirementSet,
    )
    from app.core.agent.file_task_decision_context import build_decision_context_payload

    context = FileTaskExecutionContext(
        classification=FileTaskClassification(
            task_family="analyze",
            operation_kind="read",
            output_mode="answer",
            confidence=0.88,
        ),
        intent_plan=FileTaskIntentPlan(recommended_strategy="answer_only"),
        requirements=FileTaskRequirementSet(requested_operation="read"),
        plan_check=FileTaskPlanCheck(passed=True),
        intent_adjudication={"source": "workspace_route_decision"},
        effective_planner_policy="native_only",
        effective_planner_reason="file_task_native_only",
        effective_planner_backend="native",
        quick_action_mode="",
        simple_quick_action=False,
    )

    payload = build_decision_context_payload(
        context,
        {
            "route": "file_task",
            "route_kind": "complex_task",
            "task_type": "FILE_TASK",
            "confidence": 0.9,
        },
    )

    assert payload["version"] == "file_task_decision_context_v1"
    assert payload["routing_decision"]["route"] == "file_task"
    assert payload["classification"]["task_family"] == "analyze"
    assert payload["intent_plan"]["recommended_strategy"] == "answer_only"
    assert payload["requirements"]["requested_operation"] == "read"
    assert payload["plan_check"]["passed"] is True
    assert payload["effective_planner"]["policy"] == "native_only"


def test_workspace_lifecycle_payload_expands_decision_context_for_consumers():
    run_context = (ROOT / "web/src/workspace/task-run-context.ts").read_text(
        encoding="utf-8"
    )
    lifecycle_payload = (
        ROOT / "web/src/workspace/task-lifecycle-payload.ts"
    ).read_text(encoding="utf-8")
    dispatcher = (ROOT / "web/src/workspace/task-dispatcher.ts").read_text(
        encoding="utf-8"
    )
    workbench = (ROOT / "web/src/workspace/task-workbench.ts").read_text(
        encoding="utf-8"
    )

    assert "const decisionContext = data.decision_context" in lifecycle_payload
    assert "decisionContext?.classification" in lifecycle_payload
    assert "'routing_decision'," in lifecycle_payload
    assert "normalizedTaskLifecyclePayload(payload)" in run_context
    assert "card.dataset.taskRoutingDecision = encodeURIComponent(" in run_context
    assert "JSON.stringify(routingDecision)," in run_context
    assert "metadata.route_intent = JSON.parse(decodeURIComponent" in dispatcher
    assert "const routeIntent = data.route_intent" in workbench
