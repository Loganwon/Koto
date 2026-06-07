import json

from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskRequest,
)
from app.core.agent.file_task_runtime import FileTaskRuntime
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


def test_file_task_runtime_continues_after_local_execution_plan_and_audits_decision():
    class FakeModelClient:
        def __init__(self):
            self.calls = 0

        def call(self, **kwargs):
            self.calls += 1
            messages = kwargs["messages"]
            if any(message.get("role") == "function" and message.get("name") == "write_docx_content" for message in messages):
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
                                        {"text": "第二段用于满足报告型 DOCX 的质量门。"},
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
            return json.dumps({"completed": True, "summary": "report.docx 已完成更新。"}, ensure_ascii=False)
        raise AssertionError(f"unexpected tool call: {tool_name}")

    events = list(
        FileTaskRuntime(tool_executor=fake_executor, model_client=FakeModelClient(), max_rounds=4).run(
            FileTaskRequest(
                task="把总结写入 report.docx",
                run_id="whitebox_local_once",
                target_path="report.docx",
                model_mode="local",
                files=[FileTaskFile(path="report.docx", name="report.docx", type="docx", target=True)],
            )
        )
    )

    assert any(event.type == "plan.proposed" for event in events)
    assert any(event.type == "plan.gated" and event.payload["passed"] for event in events)
    decision = next(event for event in events if event.type == "decision.made")
    assert decision.payload["audited_tool_name"] == "write_docx_content"
    assert "必须产生真实文件变更" in decision.payload["why"]
    assert any(event.type == "file.changed" for event in events)
    assert events[-1].payload["completed_task"] is True
    assert events[-1].payload["workflow_version"] == "whitebox_workflow_v2"
