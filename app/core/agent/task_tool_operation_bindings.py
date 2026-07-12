"""Explicit operation bindings exposed to the file-task tool registry.

The imports stay inside the factory so ``task_tools`` can import this module
without forming an import-time cycle.  The registry receives only the stable,
registered operation surface instead of the complete implementation module.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any


def build_task_tool_operations() -> Any:
    """Return exactly the module-level operations declared by the registry."""
    from app.core.agent.task_tools import (
        add_pptx_slides,
        audit_financial_workbook,
        clear_docx_review_marks,
        compare_docx_and_annotate,
        compare_files,
        convert_docx_to_pdf,
        convert_file,
        copy_file,
        design_pptx_theme_layout,
        extract_to_file,
        fill_docx_template,
        insert_docx_paragraph,
        insert_excel_as_docx_table,
        insert_image_into_docx,
        inspect_workbook_structure,
        list_conversions,
        list_workspace_files,
        llm_extract,
        llm_transform,
        open_file_in_editor,
        parse_file_to_text,
        plan_docx_compare_annotations,
        read_docx_content,
        read_file_range,
        read_sheet_data,
        replace_file_selection,
        verify_task_completion,
        write_docx_comments,
        write_docx_content,
        write_pptx_slides,
        write_sheet_data,
    )

    return SimpleNamespace(
        add_pptx_slides=add_pptx_slides,
        audit_financial_workbook=audit_financial_workbook,
        clear_docx_review_marks=clear_docx_review_marks,
        compare_docx_and_annotate=compare_docx_and_annotate,
        compare_files=compare_files,
        convert_docx_to_pdf=convert_docx_to_pdf,
        convert_file=convert_file,
        copy_file=copy_file,
        design_pptx_theme_layout=design_pptx_theme_layout,
        extract_to_file=extract_to_file,
        fill_docx_template=fill_docx_template,
        insert_docx_paragraph=insert_docx_paragraph,
        insert_excel_as_docx_table=insert_excel_as_docx_table,
        insert_image_into_docx=insert_image_into_docx,
        inspect_workbook_structure=inspect_workbook_structure,
        list_conversions=list_conversions,
        list_workspace_files=list_workspace_files,
        llm_extract=llm_extract,
        llm_transform=llm_transform,
        open_file_in_editor=open_file_in_editor,
        parse_file_to_text=parse_file_to_text,
        plan_docx_compare_annotations=plan_docx_compare_annotations,
        read_docx_content=read_docx_content,
        read_file_range=read_file_range,
        read_sheet_data=read_sheet_data,
        replace_file_selection=replace_file_selection,
        verify_task_completion=verify_task_completion,
        write_docx_comments=write_docx_comments,
        write_docx_content=write_docx_content,
        write_pptx_slides=write_pptx_slides,
        write_sheet_data=write_sheet_data,
    )
