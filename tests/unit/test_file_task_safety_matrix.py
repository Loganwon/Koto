from __future__ import annotations

import pytest

from app.core.agent.file_task_completion_contract import build_completion_contract
from app.core.agent.file_task_contract import (
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskRequest,
)
from app.core.agent.file_task_runtime import FileTaskRuntime
from app.core.agent.file_task_validation import build_file_task_requirements
from app.core.agent.file_task_whitebox import build_recipe_skeleton


@pytest.mark.parametrize(
    ("task", "target", "file_type", "write_required"),
    [
        ("Compare these two PDFs and summarize the differences.", "", "pdf", False),
        ("把当前 Word 文档导出为 PDF", "report.pdf", "docx", True),
        ("Copy this PDF file to archive.pdf.", "archive.pdf", "pdf", True),
        ("给这个 PPT 新增一页总结关键发现", "deck.pptx", "pptx", True),
        ("把选中文本润色后写回这个 Markdown 文件", "notes.md", "md", True),
        ("看看这个 PPT 的设计有没有问题，先不要改", "", "pptx", False),
    ],
)
def test_file_task_safety_matrix_does_not_project_semantic_recipes(
    task: str,
    target: str,
    file_type: str,
    write_required: bool,
) -> None:
    request = FileTaskRequest(
        task=task,
        target_path=target,
        files=[
            FileTaskFile(
                path=f"source.{file_type}",
                name=f"source.{file_type}",
                type=file_type,
                target=bool(target and target.endswith(file_type)),
            )
        ],
    )
    classification = FileTaskRuntime()._classify_request(request, request.files)

    assert classification.selected_recipe == ""
    assert classification.recipe_candidates == []
    assert classification.write_required is write_required
    assert classification.output_mode == ("write" if write_required else "answer")


def test_generic_write_contract_requires_observable_file_change() -> None:
    request = FileTaskRequest(
        task="把选中文本润色后写回这个 Markdown 文件",
        target_path="notes.md",
        files=[FileTaskFile(path="notes.md", type="md", target=True)],
    )
    runtime = FileTaskRuntime()
    classification = runtime._classify_request(request, request.files)
    intent_plan = FileTaskIntentPlan(
        intent_type=classification.task_family,
        output_mode=classification.output_mode,
        write_required=classification.write_required,
    )
    requirements = build_file_task_requirements(request, classification)
    skeleton = build_recipe_skeleton(
        request,
        request.files,
        classification,
        intent_plan,
        [{"name": "replace_file_selection"}, {"name": "verify_task_completion"}],
    )
    contract = build_completion_contract(
        request,
        request.files,
        classification,
        intent_plan,
        requirements,
        skeleton,
    ).public_dict()

    assert contract["contract_id"] == "kernel_generic_file_task"
    assert contract["write_required"] is True
    assert "file.changed" in contract["required_operations"]
    assert not contract["quality_gates"]
