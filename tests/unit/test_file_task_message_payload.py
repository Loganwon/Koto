import json

from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskRequest,
)
from app.core.agent.file_task_message_payload import build_file_task_runtime_messages


def _message_context(messages):
    content = messages[-1]["content"]
    return json.loads(content.split("上下文如下：\n", 1)[1])


def test_file_task_runtime_messages_include_derived_payloads():
    request = FileTaskRequest(
        task="继续优化上一轮结果",
        target_path="draft.docx",
        files=[FileTaskFile(path="draft.docx", name="draft.docx", type="docx")],
        options={
            "followup_context": {
                "kind": "review_last_task",
                "followup_action": "improve",
                "previous_task_family": "annotate",
            }
        },
    )
    classification = FileTaskClassification(
        output_mode="write",
        write_intent=True,
    )

    messages = build_file_task_runtime_messages(
        request=request,
        snippets=[{"source": "draft.docx", "text": "片段"}],
        files=request.files,
        classification=classification,
        intent_plan=FileTaskIntentPlan(intent_type="edit_file"),
        known_tool_gap={"missing": "native_docx"},
        recipe_skeleton=None,
        execution_brief_schema={"type": "object"},
    )

    context = _message_context(messages)
    assert context["file_capability_profiles"]
    assert context["followup_context"]["followup_action"] == "improve"
    assert context["known_native_tool_gap"] == {"missing": "native_docx"}
    assert context["recipe_skeleton"]["version"]
    assert context["execution_brief_schema"] == {"type": "object"}


def test_file_task_runtime_messages_preserve_supplied_recipe_skeleton():
    request = FileTaskRequest(task="总结文件")
    skeleton = {"version": "custom", "recipe_id": "provided"}

    messages = build_file_task_runtime_messages(
        request=request,
        snippets=[],
        files=[],
        classification=FileTaskClassification(),
        intent_plan=FileTaskIntentPlan(),
        known_tool_gap=None,
        recipe_skeleton=skeleton,
        execution_brief_schema={},
    )

    context = _message_context(messages)
    assert context["recipe_skeleton"] is not skeleton
    assert context["recipe_skeleton"] == skeleton
