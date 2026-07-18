# -*- coding: utf-8 -*-
"""Tool registry metadata kept separate from task operation implementations."""

from __future__ import annotations

from typing import Any, Dict, List


def build_task_tool_definitions(plugin: Any, operations: Any) -> List[Dict[str, Any]]:
    tools = [
        {
            "name": "read_sheet_data",
            "func": operations.read_sheet_data,
            "description": (
                "Read spreadsheet (xlsx) cells as structured JSON with headers and rows. "
                "Args: path (str), sheet_name (str, optional), max_rows (int, default 500). "
                "If the sheet name is unknown, omit sheet_name instead of guessing Sheet1. "
                "Returns: {sheet, headers, rows, row_count}"
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                    "sheet_name": {"type": "STRING"},
                    "max_rows": {"type": "INTEGER"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "inspect_workbook_structure",
            "func": operations.inspect_workbook_structure,
            "description": (
                "Inspect an Excel workbook before analysis. "
                "Returns sheet names, sampled rows, detected year headers, formula counts, and external-link hints. "
                "Use this first when the workbook structure, formulas, or sheet completeness are unknown. "
                "Args: path (str), sample_rows_per_sheet (int, default 6), max_formula_examples_per_sheet (int, default 8)."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                    "sample_rows_per_sheet": {"type": "INTEGER"},
                    "max_formula_examples_per_sheet": {"type": "INTEGER"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "audit_financial_workbook",
            "func": operations.audit_financial_workbook,
            "description": (
                "Audit a financial workbook for common model red flags before making business judgments. "
                "Checks core statement presence, external dependencies, and year-series gaps inside line items. "
                "Use for budgets, forecasts, financial models, and report-review tasks. "
                "Args: path (str), sample_rows_per_sheet (int, default 4), max_formula_examples_per_sheet (int, default 6), max_findings (int, default 12)."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                    "sample_rows_per_sheet": {"type": "INTEGER"},
                    "max_formula_examples_per_sheet": {"type": "INTEGER"},
                    "max_findings": {"type": "INTEGER"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "write_sheet_data",
            "func": operations.write_sheet_data,
            "description": (
                "Write cells to a spreadsheet (xlsx). Creates a backup before writing. "
                "Args: path (str), sheet_name (str, optional), "
                "updates (JSON string of [{row, col, value}, ...]). "
                "Row and col are 1-indexed."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                    "sheet_name": {"type": "STRING"},
                    "updates": {"type": "STRING"},
                },
                "required": ["path", "updates"],
            },
        },
        {
            "name": "read_docx_content",
            "func": operations.read_docx_content,
            "description": (
                "Read DOCX document paragraphs and tables as structured JSON with text/style info. "
                "Args: path (str), max_chars (int, default 24000). "
                "Returns: {paragraphs, tables, total_paragraphs, total_tables}"
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                    "max_chars": {"type": "INTEGER"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "parse_file_to_text",
            "func": operations.parse_file_to_text,
            "description": (
                "Parse any supported file (DOCX/XLSX/PPTX/PDF/TXT/CSV) to plain text. "
                "Use this for a quick overview or staged reading of file contents. "
                "For PDFs, pass start_page/end_page to read a page window. "
                "For large DOCX/PPTX/XLSX, pass window_unit='paragraph'|'slide'|'sheet' "
                "with start/end or sheet_index to read one workflow window. "
                "Args: path (str), max_chars (int, default 60000), start_page/end_page, "
                "window_unit, start, end, sheet_index. "
                "Returns: plain text string."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                    "max_chars": {"type": "INTEGER"},
                    "start_page": {"type": "INTEGER"},
                    "end_page": {"type": "INTEGER"},
                    "window_unit": {"type": "STRING"},
                    "start": {"type": "INTEGER"},
                    "end": {"type": "INTEGER"},
                    "sheet_index": {"type": "INTEGER"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "run_python_code",
            "func": plugin._run_python_code,
            "description": (
                "Execute Python code in a secure sandbox. "
                "Use for data processing, calculations, chart generation. "
                "Has access to pandas, openpyxl, matplotlib, numpy. "
                "Current task files are mirrored into the sandbox working directory under their file names, "
                "prefer TASK_SANDBOX_FILE_PATHS for attached-file edits, and keep TASK_FILE_PATHS only for compatibility fallback. "
                "When the request has a target file, create or modify TASK_TARGET_PATH inside the sandbox "
                "(available both as a Python global and os.environ['TASK_TARGET_PATH']); "
                "Koto verifies and syncs it to the real workspace target. Do not write the host absolute target directly. "
                "Args: code (str), timeout (int, default 30). "
                "Returns: stdout + stderr."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "code": {"type": "STRING"},
                    "timeout": {"type": "INTEGER"},
                },
                "required": ["code"],
            },
        },
        {
            "name": "list_workspace_files",
            "func": operations.list_workspace_files,
            "description": (
                "List files in the workspace directory. "
                "Args: path (str, relative subdir), recursive (bool). "
                "Returns: JSON array of {name, type, size}."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                    "recursive": {"type": "BOOLEAN"},
                },
                "required": [],
            },
        },
        {
            "name": "open_file_in_editor",
            "func": operations.open_file_in_editor,
            "description": (
                "Open a file in the frontend editor so the user can view it. "
                "Use this when the user asks to open, view, show, or navigate to a file. "
                "Do NOT use for reading content — use parse_file_to_text for that. "
                "Args: path (str, file path relative to workspace)."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "copy_file",
            "func": operations.copy_file,
            "description": (
                "Copy a file within the workspace. "
                "Args: source (str), destination (str). Both relative to workspace."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "source": {"type": "STRING"},
                    "destination": {"type": "STRING"},
                },
                "required": ["source", "destination"],
            },
        },
        {
            "name": "create_file",
            "func": plugin._create_file,
            "description": (
                "Create a new file in the workspace with given content. "
                "Args: path (str, relative), content (str)."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                    "content": {"type": "STRING"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "llm_extract",
            "func": operations.llm_extract,
            "description": (
                "Use AI to extract structured data from text. "
                "Args: text (str — the source text), "
                "fields (str — comma-separated field names to extract), "
                "instructions (str, optional — extra guidance). "
                "Returns: JSON object with extracted values."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "text": {"type": "STRING"},
                    "fields": {"type": "STRING"},
                    "instructions": {"type": "STRING"},
                },
                "required": ["text", "fields"],
            },
        },
        {
            "name": "llm_transform",
            "func": operations.llm_transform,
            "description": (
                "Use AI to transform/rewrite text according to an instruction. "
                "Args: text (str), instruction (str). "
                "Returns: transformed text."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "text": {"type": "STRING"},
                    "instruction": {"type": "STRING"},
                },
                "required": ["text", "instruction"],
            },
        },
        # ── New tools for DocAgent ─────────────────────────────────────
        {
            "name": "compare_files",
            "func": operations.compare_files,
            "description": (
                "Compare multiple files for similarities and differences. "
                "Args: file_paths (str — comma-separated file paths), "
                "aspect (str — 'content' or 'structure', default 'content'). "
                "Returns: JSON with similarity scores and specific differences."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "file_paths": {"type": "STRING"},
                    "aspect": {"type": "STRING"},
                },
                "required": ["file_paths"],
            },
        },
        {
            "name": "compare_docx_and_annotate",
            "func": operations.compare_docx_and_annotate,
            "description": (
                "Compare two DOCX files and write Word-native comments marking the differences. "
                "Use this when the user attaches two Word documents and asks to compare, find differences, "
                "or mark/annotate the differences. This is cross-file comparison, not single-document review. "
                "Set target_path to the document where comments should be inserted; if the user says original/current document, target_path must be that file. "
                "Args: original_path (str), revised_path (str), target_path (str optional write target), "
                "max_differences (int, default 80). Returns a standard file-change payload with annotations_added."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "original_path": {"type": "STRING"},
                    "revised_path": {"type": "STRING"},
                    "target_path": {"type": "STRING"},
                    "max_differences": {"type": "INTEGER"},
                },
                "required": ["original_path", "revised_path"],
            },
        },
        {
            "name": "plan_docx_compare_annotations",
            "func": operations.plan_docx_compare_annotations,
            "description": (
                "Read-only DOCX comparison planner. Compare two DOCX files and return target-document anchors plus default difference notes. "
                "Use this first when the user wants AI-written Word comments on the original/target contract. "
                "Then call write_docx_comments with model-authored comments_json to write comments into the existing target DOCX. "
                "Args: original_path (str), revised_path (str), target_path (str: document to receive comments), max_differences (int)."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "original_path": {"type": "STRING"},
                    "revised_path": {"type": "STRING"},
                    "target_path": {"type": "STRING"},
                    "max_differences": {"type": "INTEGER"},
                },
                "required": ["original_path", "revised_path", "target_path"],
            },
        },
        {
            "name": "write_docx_comments",
            "func": operations.write_docx_comments,
            "description": (
                "Write Word-native comments into an existing DOCX in place. "
                "Use after plan_docx_compare_annotations when the model has written concise comments such as '另一版为... 本版为... 风险... 建议...'. "
                "comments_json can be an array object or JSON string of {原文片段 or anchor, 批注内容 or comment, optional 批注标签/reason}. "
                "The 原文片段/anchor must be exact text from the target DOCX; this tool does not create a separate comparison document. "
                "Args: path (str target DOCX), comments_json (str), source_path (str optional), compare_path (str optional), differences_detected (int optional)."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                    "comments_json": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "原文片段": {"type": "STRING"},
                                "批注内容": {"type": "STRING"},
                                "anchor": {"type": "STRING"},
                                "comment": {"type": "STRING"},
                                "批注标签": {"type": "STRING"},
                                "reason": {"type": "STRING"},
                            },
                        },
                    },
                    "source_path": {"type": "STRING"},
                    "compare_path": {"type": "STRING"},
                    "differences_detected": {"type": "INTEGER"},
                },
                "required": ["path", "comments_json"],
            },
        },
        {
            "name": "extract_to_file",
            "func": operations.extract_to_file,
            "description": (
                "Extract data from one file and inject into another. "
                "Use for cross-file operations like 'copy data from Excel to Word'. "
                "Args: source_path (str), target_path (str), "
                "extract_query (str — what to extract), "
                "insert_position (str — 'start'/'end'/'cursor', default 'end'). "
                "Returns: JSON with change details."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "source_path": {"type": "STRING"},
                    "target_path": {"type": "STRING"},
                    "extract_query": {"type": "STRING"},
                    "insert_position": {"type": "STRING"},
                },
                "required": ["source_path", "target_path", "extract_query"],
            },
        },
        {
            "name": "annotate_file",
            "func": plugin._annotate_file,
            "description": (
                "Add annotations or highlights to a file. "
                "For explicit annotations, pass annotations as a JSON array of "
                "[{range_start, range_end, comment, color}]. "
                "For DOCX AI review/comment tasks, pass requirement (str) and keep annotations empty so the native Word comment tool can analyze, locate, and write back comments in place with streaming progress. "
                "Optional args: model_id (str). Returns: JSON or a streaming native-tool result."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                    "annotations": {"type": "STRING"},
                    "requirement": {"type": "STRING"},
                    "model_id": {"type": "STRING"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "clear_docx_review_marks",
            "func": operations.clear_docx_review_marks,
            "description": (
                "Clear review comments from a DOCX file, or remove comments and accept tracked changes by scope. "
                "Args: path (str), scope (str: comments/revisions/all; default comments). "
                "Use this for requests like '删除全部批注', '清空修订', or '去掉审阅标记'. "
                "Returns: JSON with standard file-change metadata."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                    "scope": {"type": "STRING"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "verify_task_completion",
            "func": operations.verify_task_completion,
            "description": (
                "Verify whether a file task was completed successfully based on structured file-change metadata. "
                "Args: task_description (str), "
                "file_states (JSON array of [{path, exists, modified, preview}]), "
                "file_changes (JSON array of structured file.changed payloads, optional), "
                "target_path (expected write target, optional), "
                "model_mode (optional: auto/local). "
                "Returns: JSON with {completed, confidence, summary, remaining_steps}."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "task_description": {"type": "STRING"},
                    "file_states": {"type": "STRING"},
                    "file_changes": {"type": "STRING"},
                    "target_path": {"type": "STRING"},
                    "model_mode": {"type": "STRING"},
                },
                "required": ["task_description"],
            },
        },
        {
            "name": "read_file_range",
            "func": operations.read_file_range,
            "description": (
                "Read a specific range of lines from a text file. "
                "Args: path (str), start_line (int, 1-indexed), end_line (int). "
                "Returns: the specified lines as text."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                    "start_line": {"type": "INTEGER"},
                    "end_line": {"type": "INTEGER"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "replace_file_selection",
            "func": operations.replace_file_selection,
            "description": (
                "Replace an exact selected text span in an existing text-like file. "
                "Use for TXT/MD/CSV/JSON/code selection rewrite tasks when the user asks to apply the edited text back to the file. "
                "It creates a backup before writing and returns a standard file-change payload. "
                "Args: path (str), original_selection (str), new_content (str), occurrence (int, optional, 1-indexed)."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                    "original_selection": {"type": "STRING"},
                    "new_content": {"type": "STRING"},
                    "occurrence": {"type": "INTEGER"},
                },
                "required": ["path", "original_selection", "new_content"],
            },
        },
        {
            "name": "write_docx_content",
            "func": operations.write_docx_content,
            "description": (
                "Create a DOCX or append new paragraphs to its end; this never replaces existing paragraphs. "
                "Do not use it for localized edits/replacements in an existing DOCX. "
                "Args: path (str), paragraphs (JSON array of [{text, style}]). "
                "Returns: JSON with operation result."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                    "paragraphs": {"type": "STRING"},
                },
                "required": ["path", "paragraphs"],
            },
        },
        {
            "name": "insert_docx_paragraph",
            "func": operations.insert_docx_paragraph,
            "description": (
                "Insert one paragraph into an existing DOCX without rewriting existing content or tables. "
                "Use for local edits like appending one sentence to a section while preserving existing tables. "
                "Args: path (str), text (str), after_heading (optional), before_heading (optional), style (optional). "
                "When adding to the end of a section, set before_heading to the next section heading."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                    "text": {"type": "STRING"},
                    "after_heading": {"type": "STRING"},
                    "before_heading": {"type": "STRING"},
                    "style": {"type": "STRING"},
                },
                "required": ["path", "text"],
            },
        },
        {
            "name": "fill_docx_template",
            "func": operations.fill_docx_template,
            "description": (
                "Fill placeholders in a DOCX template using structured JSON data. "
                "Use for mail merge, contract templates, offer letters, forms, and report templates. "
                "Replaces {{field}} and {field}; can write in place or to target_path. "
                "Args: path (str), data (JSON object string), target_path (optional), placeholder_style (optional). "
                "Returns a standard file-change payload with docx_template_fields diff."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                    "data": {"type": "STRING"},
                    "target_path": {"type": "STRING"},
                    "placeholder_style": {"type": "STRING"},
                },
                "required": ["path", "data"],
            },
        },
        {
            "name": "convert_docx_to_pdf",
            "func": operations.convert_docx_to_pdf,
            "description": (
                "Convert a DOCX/DOC file to PDF using the best available local converter "
                "(docx2pdf, Microsoft Word COM, or LibreOffice/soffice). "
                "Use when the user asks to export, save, or send a Word document as PDF. "
                "Args: path (str), target_path (optional .pdf). "
                "Returns a standard file-change payload when conversion succeeds, or a clear blocked result when no converter is installed."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                    "target_path": {"type": "STRING"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "convert_file",
            "func": operations.convert_file,
            "description": (
                "Convert a workspace file to another supported format using Koto's general converter. "
                "Use for TXT/MD/DOCX/PDF/XLSX/CSV/PPTX/image format conversion when no more specific tool applies. "
                "Args: file_path (str), target_format (str like pdf, docx, md, csv, png), output_path (optional). "
                "Returns a standard file-change payload when conversion succeeds, or a clear blocked result if unsupported."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "file_path": {"type": "STRING"},
                    "target_format": {"type": "STRING"},
                    "output_path": {"type": "STRING"},
                },
                "required": ["file_path", "target_format"],
            },
        },
        {
            "name": "list_conversions",
            "func": operations.list_conversions,
            "description": (
                "List supported source and target format conversions. "
                "Use before convert_file when the user asks what formats are supported or the conversion path is uncertain. "
                "Args: file_ext (optional source extension or alias like pdf, docx, csv)."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "file_ext": {"type": "STRING"},
                },
                "required": [],
            },
        },
        {
            "name": "insert_image_into_docx",
            "func": operations.insert_image_into_docx,
            "description": (
                "Append an image or chart into a DOCX file as a real inline picture. "
                "Use this when the task is '把图表/图片加入 Word / DOCX'. "
                "Args: path (docx), image_path (png/jpg/etc), title (optional), "
                "caption (optional), width_inches (optional, default 6.5)."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                    "image_path": {"type": "STRING"},
                    "title": {"type": "STRING"},
                    "caption": {"type": "STRING"},
                    "width_inches": {"type": "NUMBER"},
                },
                "required": ["path", "image_path"],
            },
        },
        {
            "name": "insert_excel_as_docx_table",
            "func": operations.insert_excel_as_docx_table,
            "description": (
                "Read an Excel sheet and append it to a DOCX file as a real Word table. "
                "Use this when the task is '把 Excel 数据加入 Word / 新建表格'. "
                "Args: source_path (xlsx), target_path (docx), sheet_name (optional), "
                "table_title (optional), max_rows (optional, default 200), "
                "sort_by (optional column name), sort_order ('desc' or 'asc'), "
                "columns (optional JSON array or comma-separated column names). "
                "For a financial analysis report, set financial_compact=true to select key P&L rows, format percentages/numbers, and produce a readable five-column table. "
                "For requests like top 3 by Revenue, set sort_by='Revenue', sort_order='desc', max_rows=3. "
                "If the sheet name is unknown, omit sheet_name instead of guessing Sheet1."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "source_path": {"type": "STRING"},
                    "target_path": {"type": "STRING"},
                    "sheet_name": {"type": "STRING"},
                    "table_title": {"type": "STRING"},
                    "max_rows": {"type": "INTEGER"},
                    "sort_by": {"type": "STRING"},
                    "sort_order": {"type": "STRING"},
                    "columns": {"type": "STRING"},
                    "financial_compact": {"type": "BOOLEAN"},
                },
                "required": ["source_path", "target_path"],
            },
        },
        {
            "name": "design_pptx_theme_layout",
            "func": operations.design_pptx_theme_layout,
            "description": (
                "Apply a professional visual theme and layout pass to an existing PPTX file. "
                "Use for tasks asking to make a PPT beautiful, polished, professional, high-end, designed, themed, "
                "formatted, visually consistent, or better laid out. "
                "It preserves existing slide count and content unless the user explicitly asks otherwise, styles titles/body text, "
                "applies coherent background/accent colors, adds restrained visual furniture, and adjusts title/body placeholders "
                "to a safe grid so text remains readable. "
                "For presentation quality, call this after content edits/additions when the user asks for a good-looking deck. "
                "Args: path (str), style_brief (str, optional), theme (object/json/string, optional), "
                "palette (array/object/json, optional), typography (object/json/string, optional), "
                "density (compact/balanced/spacious, optional), preserve_content (bool, default true). "
                "Returns: standard Koto file-change payload with slides_designed, text_shapes_styled, theme_name, "
                "layout_strategy, and any layout_warnings for verification."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                    "style_brief": {"type": "STRING"},
                    "theme": {"type": "STRING"},
                    "palette": {"type": "STRING"},
                    "typography": {"type": "STRING"},
                    "density": {"type": "STRING"},
                    "preserve_content": {"type": "BOOLEAN"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "write_pptx_slides",
            "func": operations.write_pptx_slides,
            "description": (
                "Modify text content in an existing PPTX file. "
                "Use to update slide text, titles, or bullet points in-place. "
                "For high-quality deck editing, first read the existing PPTX context, make targeted text edits, "
                "then call design_pptx_theme_layout if the user asks for polish, beauty, style, or professional layout. "
                "Args: path (str — PPTX file path), "
                "updates (JSON array of [{slide_index (0-based), shape_name or shape_index, text}]). "
                "Returns: JSON with slides_updated count."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                    "updates": {"type": "STRING"},
                },
                "required": ["path", "updates"],
            },
        },
        {
            "name": "add_pptx_slides",
            "func": operations.add_pptx_slides,
            "description": (
                "Add new slides to an existing PPTX file. "
                "Use concise titles and skimmable bullet lines; after adding slides, call design_pptx_theme_layout "
                "when the deck should look polished, beautiful, professional, or visually unified. "
                "Args: path (str — PPTX file path), "
                "slides (JSON array/list of [{title, content (string or bullet list), layout_index (optional, default 1)}]). "
                "Returns: JSON with slides_added count and new total."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING"},
                    "slides": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "title": {"type": "STRING"},
                                "content": {"type": "STRING"},
                                "bullets": {
                                    "type": "ARRAY",
                                    "items": {"type": "STRING"},
                                },
                                "layout_index": {"type": "INTEGER"},
                            },
                        },
                    },
                },
                "required": ["path", "slides"],
            },
        },
    ]

    # editor_live_update requires socketio — only register if available
    if plugin._socketio:
        tools.append(
            {
                "name": "editor_live_update",
                "func": plugin._editor_live_update,
                "description": (
                    "Push live cell/text updates to the frontend editor. "
                    "Args: type (str — 'set_cell'|'set_cells'|'set_html'|'insert_text'), "
                    "plus type-specific kwargs."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "type": {"type": "STRING"},
                    },
                    "required": ["type"],
                },
            }
        )

    return tools
