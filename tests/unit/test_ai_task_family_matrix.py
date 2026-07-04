from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.core.agent.file_task_completion_contract import build_completion_contract
from app.core.agent.file_task_contract import (
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskRequest,
)
from app.core.agent.file_task_recipes import recipe_by_id
from app.core.agent.file_task_runtime import FileTaskRuntime
from app.core.agent.file_task_validation import build_file_task_requirements
from app.core.agent.file_task_whitebox import build_recipe_skeleton


TOOL_DEFS = [
    {"name": "parse_file_to_text"},
    {"name": "read_docx_content"},
    {"name": "write_docx_content"},
    {"name": "write_docx_comments"},
    {"name": "compare_docx_and_annotate"},
    {"name": "fill_docx_template"},
    {"name": "convert_docx_to_pdf"},
    {"name": "convert_file"},
    {"name": "clear_docx_review_marks"},
    {"name": "inspect_workbook_structure"},
    {"name": "audit_financial_workbook"},
    {"name": "read_sheet_data"},
    {"name": "write_sheet_data"},
    {"name": "insert_excel_as_docx_table"},
    {"name": "run_python_code"},
    {"name": "insert_image_into_docx"},
    {"name": "copy_file"},
    {"name": "extract_to_file"},
    {"name": "design_pptx_theme_layout"},
    {"name": "add_pptx_slides"},
    {"name": "write_pptx_slides"},
    {"name": "read_file_range"},
    {"name": "replace_file_selection"},
    {"name": "rewrite_docx_paragraph_window"},
    {"name": "verify_task_completion"},
]


@dataclass(frozen=True)
class MatrixFile:
    path: str
    file_type: str
    target: bool = False


@dataclass(frozen=True)
class MatrixCase:
    label: str
    task: str
    expected_recipe: str
    files: tuple[MatrixFile, ...]
    target_path: str = ""
    write_required: bool = True


TASK_FAMILY_CASES = (
    MatrixCase(
        label="contract_compare_review",
        task="对比这两份合同，找出变化并标注出来，同时总结风险点",
        expected_recipe="docx_contract_compare_review",
        target_path="new_contract.docx",
        files=(
            MatrixFile("old_contract.docx", "docx"),
            MatrixFile("new_contract.docx", "docx", target=True),
        ),
    ),
    MatrixCase(
        label="docx_compare_annotation",
        task="对比这两份 DOCX 文档，找出差异并标注出来",
        expected_recipe="docx_compare_annotation",
        target_path="new.docx",
        files=(
            MatrixFile("old.docx", "docx"),
            MatrixFile("new.docx", "docx", target=True),
        ),
    ),
    MatrixCase(
        label="readonly_multi_file_compare",
        task="Compare these two PDFs and summarize the differences.",
        expected_recipe="multi_file_compare_readonly",
        write_required=False,
        files=(MatrixFile("old.pdf", "pdf"), MatrixFile("new.pdf", "pdf")),
    ),
    MatrixCase(
        label="docx_template_fill",
        task="把客户信息填入这个 Word 合同模板里的占位符，另存为 filled.docx",
        expected_recipe="docx_template_fill",
        target_path="filled.docx",
        files=(MatrixFile("template.docx", "docx"),),
    ),
    MatrixCase(
        label="docx_pdf_export",
        task="把当前 Word 文档导出为 PDF",
        expected_recipe="docx_pdf_export",
        target_path="report.docx",
        files=(MatrixFile("report.docx", "docx", target=True),),
    ),
    MatrixCase(
        label="docx_clear_review",
        task="清除这个 Word 文档里的所有批注和修订",
        expected_recipe="docx_clear_review_marks",
        target_path="reviewed.docx",
        files=(MatrixFile("reviewed.docx", "docx", target=True),),
    ),
    MatrixCase(
        label="format_convert",
        task="Convert notes.txt to markdown and save it as notes.md.",
        expected_recipe="file_format_convert",
        target_path="notes.md",
        files=(MatrixFile("notes.txt", "txt"),),
    ),
    MatrixCase(
        label="financial_xlsx_docx_report",
        task="分析这个 xlsx 财务数据的问题，并将数据做成图，然后把问题和图加入 docx",
        expected_recipe="financial_xlsx_docx_report",
        target_path="report.docx",
        files=(
            MatrixFile("financial.xlsx", "xlsx"),
            MatrixFile("report.docx", "docx", target=True),
        ),
    ),
    MatrixCase(
        label="xlsx_table_to_docx",
        task="把 xlsx 表格加入 docx",
        expected_recipe="xlsx_table_to_docx",
        target_path="report.docx",
        files=(
            MatrixFile("sales.xlsx", "xlsx"),
            MatrixFile("report.docx", "docx", target=True),
        ),
    ),
    MatrixCase(
        label="docx_chart_report",
        task="把数据做成图表并加入这个 Word 文档",
        expected_recipe="docx_chart_report",
        target_path="report.docx",
        files=(MatrixFile("report.docx", "docx", target=True),),
    ),
    MatrixCase(
        label="spreadsheet_cell_write",
        task="Update cell B2 in the Excel worksheet with the sales amount.",
        expected_recipe="spreadsheet_cell_write",
        target_path="sales.xlsx",
        files=(MatrixFile("sales.xlsx", "xlsx", target=True),),
    ),
    MatrixCase(
        label="workspace_file_copy",
        task="Copy this PDF file to archive.pdf.",
        expected_recipe="workspace_file_copy",
        target_path="archive.pdf",
        files=(MatrixFile("source.pdf", "pdf"),),
    ),
    MatrixCase(
        label="cross_file_extract",
        task="Extract the action items from notes.pdf into action_items.md.",
        expected_recipe="cross_file_extract_to_file",
        target_path="action_items.md",
        files=(MatrixFile("notes.pdf", "pdf"),),
    ),
    MatrixCase(
        label="docx_report_table_write",
        task=(
            "请完整读取 service_agreement_v1.docx、service_agreement_v2.docx、"
            "renewal_budget.xlsx 和目标报告 service_agreement_full_test.docx，"
            "核验条款差异、预算一致性表、风险矩阵和谈判建议是否完整覆盖，"
            "必须写回当前目标 DOCX，不要修改另外三个源文件。"
        ),
        expected_recipe="docx_report_table_write",
        target_path="service_agreement_full_test.docx",
        files=(
            MatrixFile("service_agreement_v1.docx", "docx"),
            MatrixFile("service_agreement_v2.docx", "docx"),
            MatrixFile("renewal_budget.xlsx", "xlsx"),
            MatrixFile("service_agreement_full_test.docx", "docx", target=True),
        ),
    ),
    MatrixCase(
        label="docx_report_write",
        task="总结这个 PDF 并写入 Word 文档",
        expected_recipe="docx_report_write",
        target_path="summary.docx",
        files=(MatrixFile("source.pdf", "pdf"), MatrixFile("summary.docx", "docx", target=True)),
    ),
    MatrixCase(
        label="pptx_design",
        task="把这个 PPT 编辑得好看一点，做成专业高级的汇报风格",
        expected_recipe="pptx_design_edit_high_quality",
        target_path="deck.pptx",
        files=(MatrixFile("deck.pptx", "pptx", target=True),),
    ),
    MatrixCase(
        label="ppt_slide_write",
        task="给这个 PPT 新增一页总结关键发现",
        expected_recipe="ppt_slide_write",
        target_path="deck.pptx",
        files=(MatrixFile("deck.pptx", "pptx", target=True),),
    ),
    MatrixCase(
        label="text_selection_replace",
        task="把选中文本润色后写回这个 Markdown 文件",
        expected_recipe="text_selection_replace",
        target_path="notes.md",
        files=(MatrixFile("notes.md", "md", target=True),),
    ),
    MatrixCase(
        label="long_pdf_stepwise_docx_summary",
        task="这是一篇非常长的 pdf，分步总结整篇文章，创建一个 docx 记录每一步发现，每完成一步等我继续。",
        expected_recipe="long_pdf_stepwise_docx_summary",
        target_path="summary.docx",
        files=(MatrixFile("museum.pdf", "pdf"),),
    ),
    MatrixCase(
        label="long_docx_stepwise_polish",
        task="这份 DOCX 很长，请分步润色，每完成一步等我继续。",
        expected_recipe="long_docx_stepwise_polish_writeback",
        target_path="draft.docx",
        files=(MatrixFile("draft.docx", "docx", target=True),),
    ),
    MatrixCase(
        label="docx_polish",
        task="润色这份 Word 文档并保存",
        expected_recipe="docx_polish_writeback",
        target_path="draft.docx",
        files=(MatrixFile("draft.docx", "docx", target=True),),
    ),
    MatrixCase(
        label="translate_writeback",
        task="把这份英文合同翻译成中文，写回 Word 文档",
        expected_recipe="translate_writeback",
        target_path="contract.docx",
        files=(MatrixFile("contract.docx", "docx", target=True),),
    ),
)


def _request(case: MatrixCase) -> FileTaskRequest:
    return FileTaskRequest(
        task=case.task,
        target_path=case.target_path,
        files=[
            FileTaskFile(
                path=item.path,
                name=item.path,
                type=item.file_type,
                target=item.target,
            )
            for item in case.files
        ],
    )


@pytest.mark.parametrize("case", TASK_FAMILY_CASES, ids=[case.label for case in TASK_FAMILY_CASES])
def test_ai_task_family_matrix_classifies_to_expected_contract(case: MatrixCase) -> None:
    request = _request(case)
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "")

    classification = runtime._classify_request(request, request.files)

    assert classification.selected_recipe == case.expected_recipe
    assert classification.write_intent is case.write_required
    assert classification.output_mode == ("write" if case.write_required else "answer")
    if case.write_required:
        assert "write_intent" in classification.reason_codes
        assert classification.task_family != "analyze"


@pytest.mark.parametrize(
    "case",
    [case for case in TASK_FAMILY_CASES if case.write_required],
    ids=[case.label for case in TASK_FAMILY_CASES if case.write_required],
)
def test_ai_task_family_matrix_builds_non_empty_write_contract(case: MatrixCase) -> None:
    request = _request(case)
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "")
    classification = runtime._classify_request(request, request.files)
    intent_plan = FileTaskIntentPlan(
        intent_type=classification.task_family,
        output_mode=classification.output_mode,
        write_intent=classification.write_intent,
        recommended_strategy="write_through",
    )
    requirements = build_file_task_requirements(request, classification)
    skeleton = build_recipe_skeleton(
        request,
        request.files,
        classification,
        intent_plan,
        TOOL_DEFS,
    )
    contract = build_completion_contract(
        request,
        request.files,
        classification,
        intent_plan,
        requirements,
        skeleton,
    )
    payload = contract.public_dict()
    recipe = recipe_by_id(case.expected_recipe)

    assert payload["contract_id"] == case.expected_recipe
    assert payload["write_required"] is True
    assert payload["required_operations"]
    assert any(
        checkpoint["id"] == "write_output"
        and "file.changed" in checkpoint["must_observe"]
        for checkpoint in payload["checkpoints"]
    )
    if recipe and recipe.quality_gates:
        assert payload["quality_gates"]
        assert payload["required_operations"] != ["file.changed"]


def test_ai_task_family_matrix_preserves_readonly_guards() -> None:
    runtime = FileTaskRuntime(tool_executor=lambda name, args: "")
    request = FileTaskRequest(
        task="看看这个 PPT 的设计有没有问题，先不要改",
        files=[FileTaskFile(path="deck.pptx", name="deck.pptx", type="pptx")],
    )

    classification = runtime._classify_request(request, request.files)

    assert classification.output_mode == "answer"
    assert classification.write_intent is False
    assert classification.selected_recipe != "pptx_design_edit_high_quality"
