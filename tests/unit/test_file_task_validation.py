from __future__ import annotations

from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskPlanCheck,
    FileTaskRequest,
)
from app.core.agent.file_task_runtime import FileTaskRuntime
from app.core.agent.file_task_validation import (
    build_file_task_requirements,
    validate_file_task_plan,
)


def test_build_file_task_requirements_marks_docx_clear_review_request_as_clear_review():
    request = FileTaskRequest(
        task="将 docx 里面的标注都移除",
        target_path="draft.docx",
        files=[FileTaskFile(path="draft.docx", name="draft.docx", type="docx", target=True)],
    )
    classification = FileTaskClassification(
        operation_kind="write",
        output_mode="write",
        write_intent=True,
        target_file_type="docx",
        matched_capabilities=["clear_docx_review_marks"],
    )

    requirements = build_file_task_requirements(request, classification)

    assert requirements.requested_operation == "clear_review"
    assert requirements.write_required is True
    assert "clear_docx_review_marks" in requirements.required_capabilities
    assert "annotate_file" in requirements.forbidden_capabilities


def test_validate_file_task_plan_flags_clear_review_annotation_mismatch():
    requirements = build_file_task_requirements(
        FileTaskRequest(task="删除 docx 里面所有标注", target_path="draft.docx"),
        FileTaskClassification(
            operation_kind="write",
            output_mode="write",
            write_intent=True,
            target_file_type="docx",
        ),
    )
    classification = FileTaskClassification(
        operation_kind="annotate",
        output_mode="write",
        write_intent=True,
        docx_annotation_request=True,
        matched_capabilities=["annotate_file"],
        target_file_type="docx",
    )
    intent_plan = FileTaskIntentPlan(output_mode="write", write_intent=True)

    plan_check = validate_file_task_plan(requirements, classification, intent_plan)

    assert plan_check.passed is False
    assert plan_check.status == "replan"
    assert "clear_review_misclassified_as_annotation" in plan_check.violations
    assert "clear_review_allows_annotate_file" in plan_check.violations


def test_file_task_runtime_emits_plan_checked_before_plan_created():
    responses = iter([
        {
            "content": "已总结当前文档重点。",
            "tool_calls": [],
        }
    ])

    def fake_model(**kwargs):
        return next(responses)

    events = list(
        FileTaskRuntime(tool_executor=lambda name, args: "", model_client=fake_model).run(
            FileTaskRequest(
                task="总结这个文件",
                run_id="plan_checked_demo",
                files=[FileTaskFile(path="notes.md", name="notes.md", type="md", content="alpha beta", target=True)],
            )
        )
    )

    event_types = [event.type for event in events]
    assert "plan.checked" in event_types
    assert event_types.index("plan.checked") < event_types.index("plan.created")
    plan_checked = next(event for event in events if event.type == "plan.checked")
    assert plan_checked.payload["passed"] is True
    assert plan_checked.payload["status"] == "pass"
    assert plan_checked.payload["requirements"]["requested_operation"] == "read"


def test_file_task_runtime_stops_when_plan_check_fails(monkeypatch):
    def fake_model(**kwargs):
        raise AssertionError("model should not be called when plan check fails")

    def fake_plan_check(requirements, classification, intent_plan):
        return FileTaskPlanCheck(
            passed=False,
            status="replan",
            summary="规划检查未通过：计划与任务要求不匹配。",
            violations=["forced_test_failure"],
        )

    monkeypatch.setattr("app.core.agent.file_task_runtime.validate_file_task_plan", fake_plan_check)

    events = list(
        FileTaskRuntime(tool_executor=lambda name, args: "", model_client=fake_model).run(
            FileTaskRequest(
                task="总结这个文件",
                run_id="plan_check_fail_demo",
                files=[FileTaskFile(path="notes.md", name="notes.md", type="md", content="alpha beta", target=True)],
            )
        )
    )

    event_types = [event.type for event in events]
    assert "plan.checked" in event_types
    assert "plan.created" not in event_types
    assert "step.started" not in event_types
    plan_checked = next(event for event in events if event.type == "plan.checked")
    run_finished = next(event for event in events if event.type == "run.finished")
    assert plan_checked.payload["passed"] is False
    assert plan_checked.payload["status"] == "replan"
    assert run_finished.payload["completed_task"] is False
    assert run_finished.payload["summary"] == "规划检查未通过：计划与任务要求不匹配。"


def test_file_task_runtime_emits_plan_checked_for_doc_annotate_bridge_path(monkeypatch):
    import app.core.agent.file_task_doc_annotate_bridge as bridge
    from app.core.agent.file_task_contract import FileTaskLedger

    def fake_stream(request, *, workspace_root="", gemini_client=None):
        ledger = FileTaskLedger(request.run_id)
        yield ledger.event("run.started", {"task": request.task, "mode": "doc_annotate_bridge"})
        yield ledger.event("run.finished", {"summary": "ok", "completed_task": True, "mode": "doc_annotate_bridge"})

    monkeypatch.setattr(bridge, "stream_request", fake_stream)

    def model_must_not_run(**kwargs):
        raise AssertionError("model should not run")

    events = list(
        FileTaskRuntime(
            tool_executor=lambda name, args: "",
            model_client=model_must_not_run,
        ).run(
            FileTaskRequest(
                task="将你觉得写得不好的地方批注出来",
                run_id="bridge_plan_checked_demo",
                files=[FileTaskFile(path="doc.docx", name="doc.docx", type="docx", target=True)],
            )
        )
    )

    event_types = [event.type for event in events]
    assert "plan.checked" in event_types
    plan_checked = next(event for event in events if event.type == "plan.checked")
    assert plan_checked.payload["passed"] is True
    assert plan_checked.payload["routing"] == "doc_annotate_bridge"
    assert event_types.index("plan.checked") < event_types.index("run.started")


def test_file_task_runtime_emits_plan_checked_for_simple_quick_action_path():
    def fake_model(**kwargs):
        return {"content": "已总结。", "tool_calls": []}

    events = list(
        FileTaskRuntime(tool_executor=lambda name, args: "", model_client=fake_model).run(
            FileTaskRequest(
                task="请总结当前文件内容",
                run_id="quick_action_plan_checked_demo",
                options={"quick_action_mode": "simple"},
                files=[FileTaskFile(path="notes.txt", name="notes.txt", type="txt", content="alpha beta", target=True)],
            )
        )
    )

    event_types = [event.type for event in events]
    assert "plan.checked" in event_types
    assert "task.classified" not in event_types
    plan_checked = next(event for event in events if event.type == "plan.checked")
    assert plan_checked.payload["passed"] is True
    assert plan_checked.payload["quick_action_bypass"] is True