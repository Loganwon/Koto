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


def test_recipe_selects_docx_template_fill():
    request = FileTaskRequest(
        task="把客户信息填入这个 Word 合同模板里的占位符，另存为 filled.docx",
        target_path="filled.docx",
        files=[
            FileTaskFile(path="template.docx", name="template.docx", type="docx"),
        ],
    )

    markers = semantic_markers(request.task, file_types={"docx"}, target_file_type="docx")
    match = select_task_recipe(request, request.files, write_intent=True)

    assert markers["docx_template_fill_request"] is True
    assert match is not None
    assert match.recipe.id == "docx_template_fill"
    assert "fill_docx_template" in match.recipe.matched_capabilities


def test_recipe_selects_readonly_multi_file_compare():
    request = FileTaskRequest(
        task="Compare these two files and summarize the differences.",
        files=[
            FileTaskFile(path="old.pdf", name="old.pdf", type="pdf"),
            FileTaskFile(path="new.pdf", name="new.pdf", type="pdf"),
        ],
    )

    match = select_task_recipe(request, request.files, write_intent=False)

    assert match is not None
    assert match.recipe.id == "multi_file_compare_readonly"
    assert match.recipe.requires_write is False
    assert "compare_files" in match.recipe.matched_capabilities


def test_recipe_selects_docx_pdf_export_even_when_source_docx_is_current_target():
    request = FileTaskRequest(
        task="把当前 Word 文档导出为 PDF",
        target_path="report.docx",
        files=[
            FileTaskFile(path="report.docx", name="report.docx", type="docx", target=True),
        ],
    )

    markers = semantic_markers(request.task, file_types={"docx"}, target_file_type="docx")
    match = select_task_recipe(request, request.files, write_intent=True)

    assert markers["docx_pdf_export_request"] is True
    assert match is not None
    assert match.recipe.id == "docx_pdf_export"
    assert match.recipe.matched_capabilities == ("convert_docx_to_pdf",)


def test_recipe_selects_generic_file_format_convert():
    request = FileTaskRequest(
        task="Convert notes.txt to markdown and save it as notes.md.",
        target_path="notes.md",
        files=[
            FileTaskFile(path="notes.txt", name="notes.txt", type="txt"),
        ],
    )

    markers = semantic_markers(request.task, file_types={"txt"}, target_file_type="md")
    match = select_task_recipe(request, request.files, write_intent=True)

    assert markers["file_format_convert_request"] is True
    assert match is not None
    assert match.recipe.id == "file_format_convert"
    assert match.recipe.matched_capabilities == ("convert_file",)


def test_recipe_selects_docx_clear_review_marks_without_annotation_bridge():
    request = FileTaskRequest(
        task="清除这个 Word 文档里的所有批注和修订",
        target_path="reviewed.docx",
        files=[
            FileTaskFile(path="reviewed.docx", name="reviewed.docx", type="docx", target=True),
        ],
    )

    markers = semantic_markers(request.task, file_types={"docx"}, target_file_type="docx")
    match = select_task_recipe(request, request.files, write_intent=True)

    assert markers["docx_clear_review_request"] is True
    assert match is not None
    assert match.recipe.id == "docx_clear_review_marks"
    assert "annotate_file" not in match.recipe.matched_capabilities


def test_recipe_selects_spreadsheet_cell_write():
    request = FileTaskRequest(
        task="Update cell B2 in the Excel worksheet with the sales amount.",
        target_path="sales.xlsx",
        files=[
            FileTaskFile(path="sales.xlsx", name="sales.xlsx", type="xlsx", target=True),
        ],
    )

    markers = semantic_markers(request.task, file_types={"xlsx"}, target_file_type="xlsx")
    match = select_task_recipe(request, request.files, write_intent=True)

    assert markers["spreadsheet_write_request"] is True
    assert match is not None
    assert match.recipe.id == "spreadsheet_cell_write"
    assert "write_sheet_data" in match.recipe.matched_capabilities


def test_recipe_selects_text_selection_replace():
    request = FileTaskRequest(
        task="把选中文本润色后写回这个 Markdown 文件",
        target_path="notes.md",
        files=[
            FileTaskFile(path="notes.md", name="notes.md", type="md", target=True),
        ],
    )

    markers = semantic_markers(request.task, file_types={"md"}, target_file_type="md")
    match = select_task_recipe(request, request.files, write_intent=True)

    assert markers["text_selection_replace_request"] is True
    assert match is not None
    assert match.recipe.id == "text_selection_replace"
    assert "replace_file_selection" in match.recipe.matched_capabilities


def test_recipe_selects_workspace_file_copy():
    request = FileTaskRequest(
        task="Copy this PDF file to archive.pdf.",
        files=[
            FileTaskFile(path="source.pdf", name="source.pdf", type="pdf"),
        ],
        target_path="archive.pdf",
    )

    markers = semantic_markers(request.task, file_types={"pdf"}, target_file_type="pdf")
    match = select_task_recipe(request, request.files, write_intent=True)

    assert markers["file_copy_request"] is True
    assert match is not None
    assert match.recipe.id == "workspace_file_copy"
    assert match.recipe.matched_capabilities == ("copy_file",)


def test_recipe_selects_cross_file_extract_to_file():
    request = FileTaskRequest(
        task="Extract the action items from notes.pdf into action_items.md.",
        files=[
            FileTaskFile(path="notes.pdf", name="notes.pdf", type="pdf"),
        ],
        target_path="action_items.md",
    )

    markers = semantic_markers(request.task, file_types={"pdf", "md"}, target_file_type="md")
    match = select_task_recipe(request, request.files, write_intent=True)

    assert markers["cross_file_extract_request"] is True
    assert match is not None
    assert match.recipe.id == "cross_file_extract_to_file"
    assert "extract_to_file" in match.recipe.matched_capabilities


def test_preserve_existing_table_does_not_route_to_excel_table_transfer():
    request = FileTaskRequest(
        task="请继续优化 report.docx：只追加一句风险声明，保留已有表格不变，保存同一个 DOCX。",
        target_path="report.docx",
        files=[
            FileTaskFile(path="sales.xlsx", name="sales.xlsx", type="xlsx"),
            FileTaskFile(path="report.docx", name="report.docx", type="docx", target=True),
        ],
    )

    markers = semantic_markers(
        request.task,
        file_types={"xlsx", "docx"},
        target_file_type="docx",
    )
    ids = [
        match.recipe.id
        for match in recipe_matches(request, request.files, write_intent=True)
    ]

    assert markers["table_request"] is False
    assert "xlsx_table_to_docx" not in ids


def test_meta_keyword_mentions_do_not_route_to_polish_or_report_recipe():
    request = FileTaskRequest(
        task=(
            "请做一轮连续任务清理验证：分步处理 report.docx，但这一步只追加一句到目标 DOCX 末尾，"
            "保留已有表格不变。任务描述里故意包含总结、检查、润色、继续下一步这些词，"
            "但不要触发快捷动作关键词路由；保存同一个 DOCX。"
        ),
        target_path="report.docx",
        files=[
            FileTaskFile(path="sales.xlsx", name="sales.xlsx", type="xlsx"),
            FileTaskFile(path="notes.docx", name="notes.docx", type="docx"),
            FileTaskFile(path="report.docx", name="report.docx", type="docx", target=True),
        ],
    )

    markers = semantic_markers(
        request.task,
        file_types={"xlsx", "docx"},
        target_file_type="docx",
    )
    ids = [
        match.recipe.id
        for match in recipe_matches(request, request.files, write_intent=True)
    ]

    assert markers["polish_request"] is False
    assert markers["summary_request"] is False
    assert markers["problem_analysis_request"] is False
    assert "long_docx_stepwise_polish_writeback" not in ids
    assert "docx_polish_writeback" not in ids
    assert "docx_report_write" not in ids


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
        "docx_template_fill": {"docx_template_fill_replaces_placeholders"},
        "docx_pdf_export": {"docx_pdf_export_uses_converter"},
        "docx_clear_review_marks": {"docx_clear_review_uses_cleanup_tool"},
        "docx_chart_report": {"docx_chart_request_has_image"},
        "docx_report_write": {"docx_report_has_narrative"},
        "spreadsheet_cell_write": {"spreadsheet_write_has_cells"},
        "workspace_file_copy": {"workspace_file_copy_uses_copy_tool"},
        "cross_file_extract_to_file": {"cross_file_extract_uses_write_tool"},
        "pptx_design_edit_high_quality": {"pptx_design_has_real_design_pass", "pptx_design_styles_text_shapes"},
        "ppt_slide_write": {"ppt_request_has_slide_write"},
        "text_selection_replace": {"text_selection_replace_has_replacement"},
    }

    for recipe_id, criteria in expected_gates.items():
        recipe = recipes[recipe_id]
        actual = {str(gate.get("criterion") or "") for gate in recipe.quality_gates}
        assert criteria.issubset(actual)
