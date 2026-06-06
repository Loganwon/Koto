from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_recipes import TASK_RECIPES, recipe_matches, select_task_recipe, semantic_markers


def test_recipe_selects_financial_xlsx_docx_report_over_generic_docx_chart():
    request = FileTaskRequest(
        task="分析这个xlsx财务数据的问题，并将数据做成图，然后把问题和图加入docx",
        target_path="report.docx",
        files=[
            FileTaskFile(path="financial.xlsx", name="financial.xlsx", type="xlsx"),
            FileTaskFile(path="report.docx", name="report.docx", type="docx", target=True),
        ],
    )

    match = select_task_recipe(request, request.files, write_intent=True)
    candidates = recipe_matches(request, request.files, write_intent=True)

    assert match is not None
    assert match.recipe.id == "financial_xlsx_docx_report"
    assert candidates[0].recipe.id == "financial_xlsx_docx_report"
    assert any(item.recipe.id == "docx_chart_report" for item in candidates)


def test_recipe_selects_excel_table_transfer_when_no_analysis_or_chart_requested():
    request = FileTaskRequest(
        task="把 xlsx 表格加入 docx",
        target_path="report.docx",
        files=[
            FileTaskFile(path="sales.xlsx", name="sales.xlsx", type="xlsx"),
            FileTaskFile(path="report.docx", name="report.docx", type="docx", target=True),
        ],
    )

    match = select_task_recipe(request, request.files, write_intent=True)

    assert match is not None
    assert match.recipe.id == "xlsx_table_to_docx"
    assert match.recipe.quality_gates[0]["criterion"] == "docx_table_request_has_table"


def test_semantic_markers_understand_docx_report_without_target_path():
    markers = semantic_markers(
        "总结这个 PDF 并写入 Word 文档",
        file_types={"pdf", "docx"},
        target_file_type="",
    )

    assert markers["summary_request"] is True
    assert markers["docx_target"] is True
    assert markers["docx_report_request"] is True


def test_recipe_guides_long_pdf_stepwise_docx_summary_without_hard_route():
    request = FileTaskRequest(
        task="这是一篇非常长的pdf，分步总结整篇文章，创建一个docx记录每一步发现，每完成一步等我继续。",
        files=[FileTaskFile(path="museum.pdf", name="museum.pdf", type="pdf")],
    )

    match = select_task_recipe(request, request.files, write_intent=True)

    assert match is not None
    assert match.recipe.id == "long_pdf_stepwise_docx_summary"
    assert match.recipe.execution_mode == "generic_tool_loop"
    assert match.recipe.quality_gates[0]["operation"] == "write_docx_content"


def test_recipe_selects_high_quality_pptx_design_for_beautify_request():
    request = FileTaskRequest(
        task="把这个 PPT 编辑得好看一点，做成专业高级的汇报风格",
        target_path="deck.pptx",
        files=[FileTaskFile(path="deck.pptx", name="deck.pptx", type="pptx", target=True)],
    )

    markers = semantic_markers(request.task, file_types={"pptx"}, target_file_type="pptx")
    match = select_task_recipe(request, request.files, write_intent=True)

    assert markers["ppt_request"] is True
    assert markers["ppt_design_request"] is True
    assert markers["ppt_slide_write_request"] is True
    assert match is not None
    assert match.recipe.id == "pptx_design_edit_high_quality"
    assert "design_pptx_theme_layout" in match.recipe.matched_capabilities


def test_quality_gated_file_task_recipes_cover_common_working_file_outputs():
    recipes = {recipe.id: recipe for recipe in TASK_RECIPES}
    expected_gates = {
        "long_pdf_stepwise_docx_summary": {"stepwise_docx_has_step_notes"},
        "financial_xlsx_docx_report": {"financial_report_has_narrative", "financial_report_has_real_chart_image"},
        "xlsx_table_to_docx": {"docx_table_request_has_table"},
        "docx_chart_report": {"docx_chart_request_has_image"},
        "docx_report_write": {"docx_report_has_narrative"},
        "pptx_design_edit_high_quality": {"pptx_design_has_real_design_pass", "pptx_design_styles_text_shapes"},
        "ppt_slide_write": {"ppt_request_has_slide_write"},
    }

    for recipe_id, criteria in expected_gates.items():
        recipe = recipes[recipe_id]
        actual = {str(gate.get("criterion") or "") for gate in recipe.quality_gates}
        assert criteria.issubset(actual)
