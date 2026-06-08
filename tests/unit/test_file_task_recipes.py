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


def test_recipe_selects_financial_report_for_sales_ledger_followup():
    request = FileTaskRequest(
        task="将新的销售台账也加入分析，并且做成图，内容也加入docx",
        target_path="report.docx",
        files=[
            FileTaskFile(path="financial.xlsx", name="雷鸟创新-financial model.xlsx", type="xlsx"),
            FileTaskFile(path="sales.xlsx", name="销售台账.xlsx", type="xlsx"),
            FileTaskFile(path="report.docx", name="雷鸟访谈问题.docx", type="docx", target=True),
        ],
    )

    match = select_task_recipe(request, request.files, write_intent=True)

    assert match is not None
    assert match.recipe.id == "financial_xlsx_docx_report"


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


def test_excel_table_transfer_does_not_pick_generic_docx_report_gate():
    request = FileTaskRequest(
        task="Create a DOCX report from this Excel table. Keep the real table in Word and write a short summary before the table.",
        target_path="report.docx",
        files=[
            FileTaskFile(path="sales.xlsx", name="sales.xlsx", type="xlsx"),
            FileTaskFile(path="report.docx", name="report.docx", type="docx", target=True),
        ],
    )

    ids = [
        match.recipe.id
        for match in recipe_matches(request, request.files, write_intent=True)
    ]

    assert "xlsx_table_to_docx" in ids
    assert "docx_report_write" not in ids


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


def test_recipe_selects_docx_compare_annotation_over_single_docx_review():
    request = FileTaskRequest(
        task="对比这两份文件，找出他们有区别的地方标注出来",
        target_path="new.docx",
        files=[
            FileTaskFile(path="old.docx", name="old.docx", type="docx"),
            FileTaskFile(path="new.docx", name="new.docx", type="docx", target=True),
        ],
    )

    markers = semantic_markers(
        request.task,
        file_types={"docx"},
        target_file_type="docx",
    )
    candidates = recipe_matches(request, request.files, write_intent=True)
    match = select_task_recipe(request, request.files, write_intent=True)

    assert markers["docx_compare_annotate_request"] is True
    assert markers["docx_review_request"] is False
    assert match is not None
    assert match.recipe.id == "docx_compare_annotation"
    assert candidates[0].recipe.id == "docx_compare_annotation"
    assert all(item.recipe.id != "single_docx_review_bridge" for item in candidates)


def test_recipe_selects_contract_compare_review_over_plain_docx_compare():
    request = FileTaskRequest(
        task="对比这两份合同，找出变化并标注出来，同时总结风险点",
        target_path="new_contract.docx",
        files=[
            FileTaskFile(path="old_contract.docx", name="old_contract.docx", type="docx"),
            FileTaskFile(
                path="new_contract.docx",
                name="new_contract.docx",
                type="docx",
                target=True,
            ),
        ],
    )

    markers = semantic_markers(
        request.task,
        file_types={"docx"},
        target_file_type="docx",
    )
    candidates = recipe_matches(request, request.files, write_intent=True)
    match = select_task_recipe(request, request.files, write_intent=True)

    assert markers["contract_request"] is True
    assert markers["docx_compare_annotate_request"] is True
    assert match is not None
    assert match.recipe.id == "docx_contract_compare_review"
    assert candidates[0].recipe.id == "docx_contract_compare_review"


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
        "docx_contract_compare_review": {"docx_contract_compare_has_annotations"},
        "docx_compare_annotation": {"docx_compare_has_difference_annotations"},
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
