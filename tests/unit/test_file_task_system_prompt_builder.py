from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskRequest,
)
from app.core.agent.file_task_system_prompt_builder import (
    build_file_task_runtime_system_prompt,
)


def _display_path(value):
    return str(value or "").replace("\\", "/").rstrip("/").split("/")[-1]


def _first_file_name(files, types, *, target=False):
    for file_info in files:
        file_type = (file_info.type or "").lower()
        if target and not file_info.target:
            continue
        if types and file_type not in types:
            continue
        return file_info.name or _display_path(file_info.path)
    return ""


def test_runtime_system_prompt_builder_preserves_prompt_sections():
    request = FileTaskRequest(
        task="继续优化上一轮批注，并把财务图表加入 docx",
        target_path="report.docx",
        files=[
            FileTaskFile(path="forecast.xlsx", name="forecast.xlsx", type="xlsx"),
            FileTaskFile(
                path="report.docx", name="report.docx", type="docx", target=True
            ),
        ],
        options={
            "followup_context": {
                "kind": "review_last_task",
                "followup_action": "improve",
            }
        },
    )
    classification = FileTaskClassification(
        output_mode="write",
        write_intent=True,
        docx_annotation_request=True,
    )

    prompt = build_file_task_runtime_system_prompt(
        request=request,
        files=request.files,
        classification=classification,
        intent_plan=FileTaskIntentPlan(intent_type="edit_file"),
        known_tool_gap={"missing": "native"},
        recipe_skeleton={"version": "custom", "recipe_id": "provided"},
        execution_brief_schema={"type": "object"},
        output_mode_guidance=lambda incoming: f"mode={incoming.output_mode}\n",
        intent_plan_guidance=lambda incoming: f"intent={incoming.intent_type}\n",
        financial_chart_docx_enabled=True,
        display_path=_display_path,
        first_file_name=_first_file_name,
        current_date="2026-06-30",
    )

    assert "当前日期：2026-06-30" in prompt
    assert "mode=write" in prompt
    assert "intent=edit_file" in prompt
    assert "继续优化" in prompt
    assert "Excel 财务预测图表写入 DOCX 任务规则" in prompt
    assert "DOCX 审校/批注任务规则" in prompt
    assert "已知原生工具缺口" in prompt
    assert '"recipe_id": "provided"' in prompt


def test_runtime_system_prompt_builder_builds_recipe_skeleton_when_missing():
    request = FileTaskRequest(task="总结文件")

    prompt = build_file_task_runtime_system_prompt(
        request=request,
        files=[],
        classification=FileTaskClassification(),
        intent_plan=FileTaskIntentPlan(),
        known_tool_gap=None,
        recipe_skeleton=None,
        execution_brief_schema={},
        output_mode_guidance=lambda _classification: "",
        intent_plan_guidance=lambda _intent_plan: "",
        financial_chart_docx_enabled=False,
        display_path=_display_path,
        first_file_name=_first_file_name,
        current_date="",
    )

    assert "白盒任务骨架" in prompt
    assert '"version"' in prompt
    assert "显式文件：none" in prompt
