import json

from app.core.agent.file_task_completion_contract import build_completion_contract
from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskRequest,
)
from app.core.agent.file_task_preflight_policy import build_preflight_constraint_audit
from app.core.agent.file_task_runtime import FileTaskRuntime
from app.core.agent.file_task_supervisor_audit import build_supervisor_audit
from app.core.agent.file_task_validation import (
    build_file_task_requirements,
    validate_file_task_plan,
)
from app.core.agent.file_task_whitebox import build_recipe_skeleton


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
        write_required=True,
        target_file_type="docx",
        selected_recipe="financial_xlsx_docx_report",
    )
    intent_plan = FileTaskIntentPlan(
        intent_type="financial_report",
        output_mode="write",
        write_required=True,
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

    assert payload["contract_id"] == "kernel_generic_file_task"
    assert payload["complexity"] == "complex"
    assert payload["decomposition_strategy"] == "multi_source_plan_then_execute"
    assert payload["write_required"] is True
    assert "file.changed" in payload["required_operations"]
    assert any(
        checkpoint["id"] == "write_output"
        and "file.changed" in checkpoint["must_observe"]
        for checkpoint in payload["checkpoints"]
    )
    assert "必须产生真实 file.changed 事件" in contract.success_criteria()


def test_supervisor_audit_warns_on_low_confidence_without_blocking():
    request = FileTaskRequest(
        task="帮我看看这个文件",
        files=[FileTaskFile(path="draft.docx", type="docx")],
    )
    classification = FileTaskClassification(
        task_family="analyze",
        operation_kind="read",
        output_mode="answer",
        write_required=False,
        confidence=0.42,
    )
    intent_plan = FileTaskIntentPlan(
        intent_type="analyze",
        output_mode="answer",
        write_required=False,
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
    assert any("显式上下文" in item for item in audit["execution_constraints"])
    assert audit["user_actions"] == []


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
        write_required=True,
        target_file_type="docx",
        confidence=0.91,
    )
    intent_plan = FileTaskIntentPlan(
        intent_type="summarize",
        output_mode="write",
        write_required=True,
        confidence=0.91,
    )
    requirements = build_file_task_requirements(request, classification)
    constraint_audit = build_preflight_constraint_audit(
        request=request,
        files=request.files,
        classification=classification,
        intent_plan=intent_plan,
        requirements=requirements,
        recipe_skeleton={"recipe_id": "generic_file_task"},
    )

    audit = build_supervisor_audit(
        request=request,
        files=request.files,
        classification=classification,
        intent_plan=intent_plan,
        requirements=requirements,
        plan_check=validate_file_task_plan(requirements, classification, intent_plan),
        constraint_audit=constraint_audit,
    ).public_dict()

    assert audit["status"] == "blocked"
    assert audit["execution_allowed"] is False
    assert "ambiguous_target:docx" in constraint_audit["conflicts"]
    assert "constraint_conflict:ambiguous_target:docx" in audit["reason_codes"]
    assert any("指定" in item for item in audit["required_actions"])
    assert any("指定" in item for item in audit["user_actions"])
    assert audit["execution_constraints"] == []


def test_supervisor_audit_allows_explicit_new_docx_target_with_multiple_sources():
    request = FileTaskRequest(
        task="分析这个财务预测，找出数据问题并将数据做成图，然后创建一个docx将问题和图加入docx",
        target_path="report.docx",
        files=[
            FileTaskFile(path="financial_model_clean.xlsx", type="xlsx"),
            FileTaskFile(path="supporting_data.xlsx", type="xlsx"),
        ],
    )
    runtime = FileTaskRuntime()
    classification = runtime._classify_request(request, request.files)
    intent_plan = FileTaskIntentPlan(
        intent_type="financial_report",
        output_mode="write",
        write_required=True,
        confidence=classification.confidence,
    )
    requirements = build_file_task_requirements(request, classification)
    constraint_audit = runtime._constraint_audit(
        request,
        request.files,
        classification,
        intent_plan,
        requirements,
        {"recipe_id": "financial_xlsx_docx_report"},
    )

    audit = build_supervisor_audit(
        request=request,
        files=request.files,
        classification=classification,
        intent_plan=intent_plan,
        requirements=requirements,
        plan_check=validate_file_task_plan(requirements, classification, intent_plan),
        constraint_audit=constraint_audit,
    ).public_dict()

    assert classification.target_file_type == "docx"
    assert requirements.target_file_type == "docx"
    assert constraint_audit["status"] == "clear"
    assert "new_artifact_target_required" in constraint_audit["hard_constraints"]
    assert (
        "explicit_or_unambiguous_target_required"
        not in constraint_audit["hard_constraints"]
    )
    assert "ambiguous_target:xlsx" not in constraint_audit["conflicts"]
    assert audit["status"] == "clear"
    assert audit["execution_allowed"] is True


def test_supervisor_audit_allows_readonly_analysis_with_multiple_docx_contexts():
    request = FileTaskRequest(
        task="分析这个一级市场投资报告，告诉我有什么风险和投资机会",
        files=[
            FileTaskFile(path="a.docx", type="docx"),
            FileTaskFile(path="b.docx", type="docx"),
        ],
    )
    classification = FileTaskClassification(
        task_family="analyze",
        operation_kind="read",
        output_mode="answer",
        write_required=False,
        target_file_type="docx",
        confidence=0.96,
    )
    intent_plan = FileTaskIntentPlan(
        intent_type="analyze",
        output_mode="answer",
        write_required=False,
        confidence=0.96,
    )
    requirements = build_file_task_requirements(request, classification)
    runtime = FileTaskRuntime()
    constraint_audit = runtime._constraint_audit(
        request,
        request.files,
        classification,
        intent_plan,
        requirements,
        {"recipe_id": "generic_file_task"},
    )

    audit = build_supervisor_audit(
        request=request,
        files=request.files,
        classification=classification,
        intent_plan=intent_plan,
        requirements=requirements,
        plan_check=validate_file_task_plan(requirements, classification, intent_plan),
        constraint_audit=constraint_audit,
    ).public_dict()

    assert constraint_audit["status"] == "clear"
    assert not constraint_audit["conflicts"]
    assert audit["status"] == "clear"
    assert audit["execution_allowed"] is True


def test_supervisor_audit_does_not_request_confirmation_for_optional_apply_analysis():
    request = FileTaskRequest(
        task="分析这个文章内容，看看有没有值得优化的论点",
        files=[
            FileTaskFile(
                path="essay.docx", name="essay.docx", type="docx", target=True
            ),
        ],
    )
    classification = FileTaskClassification(
        task_family="analyze",
        operation_kind="read",
        output_mode="hybrid",
        write_required=False,
        target_file_type="docx",
        confidence=0.93,
    )
    intent_plan = FileTaskIntentPlan(
        intent_type="analyze",
        output_mode="hybrid",
        write_required=False,
        can_apply=True,
        requires_confirmation=False,
        recommended_strategy="analyze_then_optional_apply",
        confidence=0.93,
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

    combined_text = " ".join(
        str(item)
        for key in (
            "warnings",
            "required_actions",
            "execution_constraints",
            "user_actions",
        )
        for item in audit.get(key, [])
    )
    assert audit["status"] == "clear"
    assert audit["execution_allowed"] is True
    assert audit["review_recommended"] is False
    assert "confirmation_required" not in audit["reason_codes"]
    assert "确认" not in combined_text
    assert "授权" not in combined_text
    assert "写入" not in combined_text


def test_file_task_runtime_uses_kernel_tool_loop_with_deterministic_plan():
    class FakeModelClient:
        def __init__(self):
            self.calls = 0

        def call(self, **kwargs):
            self.calls += 1
            messages = kwargs["messages"]
            if any(
                message.get("role") == "tool"
                and message.get("name") == "write_docx_content"
                for message in messages
            ):
                return {"content": "已完成写入。", "tool_calls": []}
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
                                    {"text": "Kernel 主链写入。"},
                                    {"text": "第二段用于满足报告型 DOCX 的质量门。"},
                                    {"text": "第三段记录完成检查依据。"},
                                ],
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
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

    assert not any(event.type == "plan.proposed" for event in events)
    assert not any(event.type == "plan.gated" for event in events)
    assert not any(event.type == "decision.made" for event in events)
    assert any(event.type == "file.changed" for event in events)
    run_started = next(event for event in events if event.type == "run.started")
    assert run_started.payload["completion_contract"]["write_required"] is True
    plan_checked = next(event for event in events if event.type == "plan.checked")
    assert plan_checked.payload["completion_contract"]["contract_id"]
    check_started = next(event for event in events if event.type == "check.started")
    assert check_started.payload["criteria"]
    assert events[-1].payload["completed_task"] is True
    assert events[-1].payload["completion_contract"]["write_required"] is True
