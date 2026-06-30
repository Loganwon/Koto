import json

from app.core.agent.file_task_completion_contract import build_completion_contract
from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskRequest,
)
from app.core.agent.file_task_runtime import FileTaskRuntime
from app.core.agent.file_task_supervisor_audit import build_supervisor_audit
from app.core.agent.file_task_validation import (
    build_file_task_requirements,
    validate_file_task_plan,
)
from app.core.agent.file_task_whitebox import (
    build_recipe_skeleton,
    extract_whitebox_execution_plan,
    validate_whitebox_plan,
)


def test_whitebox_plan_extracts_and_gates_tool_calls():
    request = FileTaskRequest(
        task="把分析结论写入 report.docx",
        target_path="report.docx",
        files=[FileTaskFile(path="report.docx", type="docx", target=True)],
        model_mode="local",
    )
    classification = FileTaskClassification(
        task_family="summarize",
        operation_kind="write",
        output_mode="write",
        write_intent=True,
        target_file_type="docx",
    )
    intent_plan = FileTaskIntentPlan(
        intent_type="summarize",
        output_mode="write",
        write_intent=True,
        recommended_strategy="write_through",
    )
    skeleton = build_recipe_skeleton(
        request,
        request.files,
        classification,
        intent_plan,
        [
            {"name": "parse_file_to_text"},
            {"name": "write_docx_content"},
            {"name": "verify_task_completion"},
        ],
    )

    plan = extract_whitebox_execution_plan(
        {
            "execution_plan": {
                "goal": "完成真实 DOCX 写入",
                "plan_summary": "读取后写入并核验",
                "steps": [
                    {
                        "id": "write",
                        "tool": "write_docx_content",
                        "why": "用户要求把结果写入 Word，不能只返回文本。",
                        "expected_result": "目标 DOCX 产生 file.changed。",
                    }
                ],
            }
        }
    )

    assert plan is not None
    assert validate_whitebox_plan(plan, skeleton)["passed"] is True

    blocked = validate_whitebox_plan(
        plan,
        skeleton,
        tool_calls=[{"name": "unknown_tool", "args": {}}],
    )
    assert blocked["passed"] is False
    assert "tool_call_1_not_allowed:unknown_tool" in blocked["violations"]


def test_whitebox_gate_does_not_warn_missing_plan_when_tools_are_valid():
    request = FileTaskRequest(
        task="把分析结论写入 report.docx",
        target_path="report.docx",
        files=[FileTaskFile(path="report.docx", type="docx", target=True)],
        model_mode="local",
    )
    classification = FileTaskClassification(
        task_family="summarize",
        operation_kind="write",
        output_mode="write",
        write_intent=True,
        target_file_type="docx",
    )
    intent_plan = FileTaskIntentPlan(
        intent_type="summarize",
        output_mode="write",
        write_intent=True,
        recommended_strategy="write_through",
    )
    skeleton = build_recipe_skeleton(
        request,
        request.files,
        classification,
        intent_plan,
        [{"name": "write_docx_content"}],
    )

    gate = validate_whitebox_plan(
        None,
        skeleton,
        tool_calls=[{"name": "write_docx_content", "args": {"path": "report.docx"}}],
    )

    assert gate["passed"] is True
    assert "model_execution_plan_missing" not in gate["warnings"]


def test_completion_contract_unifies_complex_task_decomposition_and_gates():
    request = FileTaskRequest(
        task="读取 sales.xlsx，生成财务问题清单和图表写入 report.docx",
        target_path="report.docx",
        files=[
            FileTaskFile(path="sales.xlsx", type="xlsx"),
            FileTaskFile(path="report.docx", type="docx", target=True),
        ],
        model_mode="local",
    )
    classification = FileTaskClassification(
        task_family="financial_report",
        operation_kind="analyze_visualize_write",
        output_mode="write",
        write_intent=True,
        target_file_type="docx",
        selected_recipe="financial_xlsx_docx_report",
    )
    intent_plan = FileTaskIntentPlan(
        intent_type="financial_report",
        output_mode="write",
        write_intent=True,
        recommended_strategy="write_through",
    )
    skeleton = build_recipe_skeleton(
        request,
        request.files,
        classification,
        intent_plan,
        [
            {"name": "parse_file_to_text"},
            {"name": "run_python_code"},
            {"name": "write_docx_content"},
            {"name": "insert_image_into_docx"},
            {"name": "verify_task_completion"},
        ],
    )
    requirements = build_file_task_requirements(request, classification)

    contract = build_completion_contract(
        request,
        request.files,
        classification,
        intent_plan,
        requirements,
        skeleton,
    )
    payload = contract.public_dict()

    assert payload["contract_id"] == "financial_xlsx_docx_report"
    assert payload["complexity"] == "complex"
    assert payload["decomposition_strategy"] == "multi_source_plan_then_execute"
    assert payload["write_required"] is True
    assert "write_docx_content" in payload["required_operations"]
    assert "insert_image_into_docx" in payload["required_operations"]
    assert any(
        checkpoint["id"] == "write_output"
        and "file.changed" in checkpoint["must_observe"]
        for checkpoint in payload["checkpoints"]
    )
    assert "最终质量门必须全部通过" in contract.success_criteria()


def test_supervisor_audit_warns_on_low_confidence_without_blocking():
    request = FileTaskRequest(
        task="帮我看看这个文件",
        files=[FileTaskFile(path="draft.docx", type="docx")],
    )
    classification = FileTaskClassification(
        task_family="analyze",
        operation_kind="read",
        output_mode="answer",
        write_intent=False,
        confidence=0.42,
    )
    intent_plan = FileTaskIntentPlan(
        intent_type="analyze",
        output_mode="answer",
        write_intent=False,
        confidence=0.42,
    )
    requirements = build_file_task_requirements(request, classification)

    audit = build_supervisor_audit(
        request=request,
        files=request.files,
        classification=classification,
        intent_plan=intent_plan,
        requirements=requirements,
        plan_check=validate_file_task_plan(requirements, classification, intent_plan),
        constraint_audit={"status": "clear", "conflicts": []},
    ).public_dict()

    assert audit["status"] == "warning"
    assert audit["execution_allowed"] is True
    assert "low_classification_confidence" in audit["reason_codes"]
    assert audit["warnings"]


def test_supervisor_audit_blocks_ambiguous_write_target():
    request = FileTaskRequest(
        task="把总结写入 Word",
        files=[
            FileTaskFile(path="a.docx", type="docx"),
            FileTaskFile(path="b.docx", type="docx"),
        ],
    )
    classification = FileTaskClassification(
        task_family="summarize",
        operation_kind="write",
        output_mode="write",
        write_intent=True,
        target_file_type="docx",
        confidence=0.91,
    )
    intent_plan = FileTaskIntentPlan(
        intent_type="summarize",
        output_mode="write",
        write_intent=True,
        confidence=0.91,
    )
    requirements = build_file_task_requirements(request, classification)

    audit = build_supervisor_audit(
        request=request,
        files=request.files,
        classification=classification,
        intent_plan=intent_plan,
        requirements=requirements,
        plan_check=validate_file_task_plan(requirements, classification, intent_plan),
        constraint_audit={"status": "clear", "conflicts": []},
    ).public_dict()

    assert audit["status"] == "blocked"
    assert audit["execution_allowed"] is False
    assert "ambiguous_write_target:docx" in audit["reason_codes"]
    assert any("指定" in item for item in audit["required_actions"])


def test_file_task_runtime_continues_after_local_execution_plan_and_audits_decision():
    class FakeModelClient:
        def __init__(self):
            self.calls = 0

        def call(self, **kwargs):
            self.calls += 1
            messages = kwargs["messages"]
            if any(
                message.get("role") == "function"
                and message.get("name") == "write_docx_content"
                for message in messages
            ):
                return {"content": "已完成写入。", "tool_calls": []}
            if "已收到 execution_plan" in str(messages[-1].get("content")):
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "write_report",
                            "name": "write_docx_content",
                            "args": {
                                "path": "report.docx",
                                "paragraphs": json.dumps(
                                    [
                                        {"text": "本地模型按白盒计划写入。"},
                                        {
                                            "text": "第二段用于满足报告型 DOCX 的质量门。"
                                        },
                                        {"text": "第三段记录完成检查依据。"},
                                    ],
                                    ensure_ascii=False,
                                ),
                            },
                        }
                    ],
                }
            return {
                "content": "",
                "execution_plan": {
                    "goal": "把总结写入 report.docx",
                    "plan_summary": "先确认任务骨架，再调用写入工具。",
                    "steps": [
                        {
                            "id": "write",
                            "title": "写入 Word",
                            "tool": "write_docx_content",
                            "why": "用户明确要求写入目标 Word，必须产生真实文件变更。",
                            "expected_result": "write_docx_content 返回 paragraphs_written。",
                        }
                    ],
                },
                "tool_calls": [],
            }

    def fake_executor(tool_name, args):
        if tool_name == "parse_file_to_text":
            return "已有文档内容。"
        if tool_name == "write_docx_content":
            return json.dumps(
                {
                    "success": True,
                    "path": args["path"],
                    "file_type": "docx",
                    "operation": "write_docx_content",
                    "summary": "已写入 3 个段落到 Word 文档",
                    "change_type": "modify",
                    "paragraphs_written": 3,
                },
                ensure_ascii=False,
            )
        if tool_name == "verify_task_completion":
            return json.dumps(
                {"completed": True, "summary": "report.docx 已完成更新。"},
                ensure_ascii=False,
            )
        raise AssertionError(f"unexpected tool call: {tool_name}")

    events = list(
        FileTaskRuntime(
            tool_executor=fake_executor, model_client=FakeModelClient(), max_rounds=4
        ).run(
            FileTaskRequest(
                task="把总结写入 report.docx",
                run_id="whitebox_local_once",
                target_path="report.docx",
                model_mode="local",
                files=[
                    FileTaskFile(
                        path="report.docx", name="report.docx", type="docx", target=True
                    )
                ],
            )
        )
    )

    assert any(event.type == "plan.proposed" for event in events)
    assert any(
        event.type == "plan.gated" and event.payload["passed"] for event in events
    )
    model_started = [event for event in events if event.type == "model.call.started"]
    model_finished = [event for event in events if event.type == "model.call.finished"]
    assert model_started
    assert model_finished
    assert model_started[0].payload["round"] == 1
    assert model_finished[0].payload["success"] is True
    assert "tool_call_count" in model_finished[-1].payload
    decision = next(event for event in events if event.type == "decision.made")
    assert decision.payload["audited_tool_name"] == "write_docx_content"
    assert "必须产生真实文件变更" in decision.payload["why"]
    assert any(event.type == "file.changed" for event in events)
    run_started = next(event for event in events if event.type == "run.started")
    assert run_started.payload["completion_contract"]["write_required"] is True
    plan_checked = next(event for event in events if event.type == "plan.checked")
    assert plan_checked.payload["completion_contract"]["contract_id"]
    check_started = next(event for event in events if event.type == "check.started")
    assert check_started.payload["criteria"]
    assert events[-1].payload["completed_task"] is True
    assert events[-1].payload["workflow_version"] == "whitebox_workflow_v2"
    assert events[-1].payload["completion_contract"]["write_required"] is True
