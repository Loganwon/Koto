from __future__ import annotations

from app.core.agent.file_task_completion_contract import build_completion_contract
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


def test_build_file_task_requirements_keeps_docx_clear_review_on_generic_write_contract():
    request = FileTaskRequest(
        task="将 docx 里面的标注都移除",
        target_path="draft.docx",
        files=[
            FileTaskFile(path="draft.docx", name="draft.docx", type="docx", target=True)
        ],
    )
    classification = FileTaskClassification(
        operation_kind="write",
        output_mode="write",
        write_required=True,
        target_file_type="docx",
    )

    requirements = build_file_task_requirements(request, classification)

    assert requirements.requested_operation == "write"
    assert requirements.write_required is True
    assert requirements.required_capabilities == []
    assert requirements.forbidden_capabilities == []


def test_hybrid_contract_allows_optional_write_without_requiring_file_change():
    request = FileTaskRequest(
        task="分析这份演示文稿并按需优化",
        target_path="deck.pptx",
        files=[FileTaskFile(path="deck.pptx", type="pptx", target=True)],
    )
    classification = FileTaskClassification(
        operation_kind="hybrid",
        output_mode="hybrid",
        write_authorized=True,
        write_required=False,
        target_file_type="pptx",
    )
    intent_plan = FileTaskIntentPlan(
        output_mode="hybrid",
        write_authorized=True,
        write_required=False,
        can_apply=True,
    )

    requirements = build_file_task_requirements(request, classification)
    plan_check = validate_file_task_plan(requirements, classification, intent_plan)
    completion = build_completion_contract(
        request,
        request.files,
        classification,
        intent_plan,
        requirements,
        {},
    )

    assert requirements.requested_operation == "hybrid"
    assert requirements.write_authorized is True
    assert requirements.write_required is False
    assert requirements.reason_codes == ["write_optional"]
    assert "read_only_request" not in requirements.reason_codes
    assert plan_check.passed is True
    assert completion.write_authorized is True
    assert completion.write_required is False
    assert "不应误触发写入工具" not in completion.success_criteria()
    assert any("文件变更不是任务完成" in item for item in completion.success_criteria())
    assert all("只读任务" not in item for item in completion.acceptance_criteria)


def test_answer_contract_remains_strictly_read_only():
    request = FileTaskRequest(task="总结这个文件")
    classification = FileTaskClassification(output_mode="answer")
    intent_plan = FileTaskIntentPlan(output_mode="answer")

    requirements = build_file_task_requirements(request, classification)
    completion = build_completion_contract(
        request,
        [],
        classification,
        intent_plan,
        requirements,
        {},
    )

    assert requirements.write_authorized is False
    assert requirements.reason_codes == ["read_only_request"]
    assert completion.write_authorized is False
    assert "不应误触发写入工具" in completion.success_criteria()


def test_validate_file_task_plan_ignores_legacy_annotation_label():
    requirements = build_file_task_requirements(
        FileTaskRequest(task="删除 docx 里面所有标注", target_path="draft.docx"),
        FileTaskClassification(
            operation_kind="write",
            output_mode="write",
            write_required=True,
            target_file_type="docx",
        ),
    )
    classification = FileTaskClassification(
        operation_kind="annotate",
        output_mode="write",
        write_required=True,
        target_file_type="docx",
    )
    intent_plan = FileTaskIntentPlan(output_mode="write", write_required=True)

    plan_check = validate_file_task_plan(requirements, classification, intent_plan)

    assert plan_check.passed is True
    assert plan_check.status == "pass"
    assert plan_check.violations == []


def test_file_task_runtime_emits_plan_checked_before_plan_created():
    responses = iter(
        [
            {
                "content": "已总结当前文档重点。",
                "tool_calls": [],
            }
        ]
    )

    def fake_model(**kwargs):
        return next(responses)

    events = list(
        FileTaskRuntime(
            tool_executor=lambda name, args: "", model_client=fake_model
        ).run(
            FileTaskRequest(
                task="总结这个文件",
                run_id="plan_checked_demo",
                files=[
                    FileTaskFile(
                        path="notes.md",
                        name="notes.md",
                        type="md",
                        content="alpha beta",
                        target=True,
                    )
                ],
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

    monkeypatch.setattr(
        "app.core.agent.runtime.plan_phase.validate_file_task_plan",
        fake_plan_check,
    )

    events = list(
        FileTaskRuntime(
            tool_executor=lambda name, args: "", model_client=fake_model
        ).run(
            FileTaskRequest(
                task="总结这个文件",
                run_id="plan_check_fail_demo",
                files=[
                    FileTaskFile(
                        path="notes.md",
                        name="notes.md",
                        type="md",
                        content="alpha beta",
                        target=True,
                    )
                ],
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


def test_file_task_runtime_stops_for_preflight_target_conflict():
    def model_must_not_run(**kwargs):
        raise AssertionError("model should not run when target selection is ambiguous")

    events = list(
        FileTaskRuntime(
            tool_executor=lambda name, args: "",
            model_client=model_must_not_run,
        ).run(
            FileTaskRequest(
                task="把总结写入 Word",
                run_id="preflight_target_conflict_demo",
                files=[
                    FileTaskFile(path="a.docx", name="a.docx", type="docx"),
                    FileTaskFile(path="b.docx", name="b.docx", type="docx"),
                ],
            )
        )
    )

    run_finished = next(event for event in events if event.type == "run.finished")
    assert run_finished.payload["runtime"]["terminal_status"] == "blocked"
    assert run_finished.payload["completed_task"] is False
    assert (
        "ambiguous_target:docx" in run_finished.payload["constraint_audit"]["conflicts"]
    )
    assert (
        "constraint_conflict:ambiguous_target:docx"
        in run_finished.payload["supervisor_audit"]["reason_codes"]
    )


def test_file_task_runtime_emits_plan_checked_for_simple_quick_action_path():
    def fake_model(**kwargs):
        return {"content": "已总结。", "tool_calls": []}

    events = list(
        FileTaskRuntime(
            tool_executor=lambda name, args: "", model_client=fake_model
        ).run(
            FileTaskRequest(
                task="请总结当前文件内容",
                run_id="quick_action_plan_checked_demo",
                options={"quick_action_mode": "simple"},
                files=[
                    FileTaskFile(
                        path="notes.txt",
                        name="notes.txt",
                        type="txt",
                        content="alpha beta",
                        target=True,
                    )
                ],
            )
        )
    )

    event_types = [event.type for event in events]
    assert "plan.checked" in event_types
    assert "task.classified" not in event_types
    plan_checked = next(event for event in events if event.type == "plan.checked")
    assert plan_checked.payload["passed"] is True
    assert plan_checked.payload["quick_action_bypass"] is True
