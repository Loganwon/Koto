"""Human-readable plan presentation for file-task tool calls.

Execution policy belongs in ``file_task_runtime``.  These labels and
descriptions are UI-facing explanations, and accepting the runtime as a small
port keeps them independent of orchestration state.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_runtime_utils import _compact_line


def tool_plan_title(tool_name: str) -> str:
    labels = {
        "read_sheet_data": "读取 Excel 表格",
        "inspect_workbook_structure": "检查 Excel 结构",
        "audit_financial_workbook": "审计财务模型",
        "read_docx_content": "读取 Word 内容",
        "parse_file_to_text": "解析文件文本",
        "clear_docx_review_marks": "清除 Word 审阅标记",
        "insert_image_into_docx": "插入 Word 图片",
        "insert_excel_as_docx_table": "写入 Word 表格",
        "write_docx_content": "写入 Word 内容",
        "insert_docx_paragraph": "插入 Word 段落",
        "write_sheet_data": "写入 Excel 单元格",
        "design_pptx_theme_layout": "设计 PPT 主题版式",
        "write_pptx_slides": "更新 PPT 页面",
        "add_pptx_slides": "新增 PPT 页面",
        "create_file": "创建文件",
        "copy_file": "复制文件",
        "read_file_range": "读取文本片段",
        "replace_file_selection": "替换文本选区",
        "compare_files": "对比文件",
        "compare_docx_and_annotate": "对比并标注 Word 差异",
        "extract_to_file": "提取到文件",
        "annotate_file": "添加批注",
        "run_python_code": "运行代码处理",
    }
    return labels.get(tool_name, f"调用工具 {tool_name}")


def tool_plan_description(
    runtime: Any,
    tool_name: str,
    tool_args: Dict[str, Any],
    files: List[FileTaskFile],
    request: FileTaskRequest,
) -> str:
    """Describe a planned tool call without making an execution decision."""
    def display(value: Any) -> str:
        return runtime._display_path(value)

    def first(types: set[str], *, target: bool = False) -> str:
        return runtime._first_file_name(files, types, target=target)

    if tool_name == "read_sheet_data":
        source = display(tool_args.get("path")) or first({"xlsx", "xlsm", "csv"}) or "表格文件"
        sheet = str(tool_args.get("sheet_name") or "").strip()
        rows = str(tool_args.get("max_rows") or "").strip()
        return f"读取 {source} 的表格数据{f'，工作表：{sheet}' if sheet else ''}{f'，最多 {rows} 行' if rows else ''}。"
    if tool_name == "inspect_workbook_structure":
        source = display(tool_args.get("path")) or first({"xlsx", "xlsm"}) or "Excel 文件"
        return f"检查 {source} 的工作表结构、公式分布和外部链接依赖。"
    if tool_name == "audit_financial_workbook":
        source = display(tool_args.get("path")) or first({"xlsx", "xlsm"}) or "财务模型"
        return f"审计 {source} 的三表完整性、外部依赖和关键年份序列红旗。"
    if tool_name == "insert_excel_as_docx_table":
        source = display(tool_args.get("source_path")) or first({"xlsx", "xlsm", "csv"}) or "表格文件"
        target = display(tool_args.get("target_path")) or request.target_path or first({"docx"}, target=True) or "Word 文档"
        table_title = str(tool_args.get("table_title") or "").strip()
        return f"把 {source} 的数据作为真实 Word 表格插入 {display(target) or target}{f'，表题：{table_title}' if table_title else ''}。"
    if tool_name == "insert_image_into_docx":
        target = display(tool_args.get("path")) or request.target_path or first({"docx"}, target=True) or "Word 文档"
        image_path = display(tool_args.get("image_path")) or str(tool_args.get("image_path") or "图片文件").strip() or "图片文件"
        title = str(tool_args.get("title") or "").strip()
        return f"把 {image_path} 作为真实图片插入 {display(target) or target}{f'，图题：{title}' if title else ''}。"
    if tool_name in {"write_docx_content", "insert_docx_paragraph", "clear_docx_review_marks"}:
        target = display(tool_args.get("path")) or request.target_path or first({"docx"}, target=True) or "Word 文档"
        target_text = display(target) or target
        if tool_name == "write_docx_content":
            return f"把生成后的段落写入 {target_text}。"
        if tool_name == "insert_docx_paragraph":
            before = str(tool_args.get("before_heading") or "").strip()
            after = str(tool_args.get("after_heading") or "").strip()
            anchor = f"、位于“{before}”之前" if before else (f"、位于“{after}”之后" if after else "")
            return f"向 {target_text} 插入一个 Word 段落{anchor}。"
        scope = str(tool_args.get("scope") or "comments").strip().lower() or "comments"
        if scope == "all":
            return f"清除 {target_text} 中的批注并接受修订。"
        if scope == "revisions":
            return f"接受并清除 {target_text} 中的修订标记。"
        return f"清除 {target_text} 中的全部批注。"
    if tool_name == "write_sheet_data":
        target = display(tool_args.get("path")) or request.target_path or first({"xlsx", "xlsm"}, target=True) or "Excel 文件"
        sheet = str(tool_args.get("sheet_name") or "").strip()
        return f"把结构化更新写入 {display(target) or target}{f'，工作表：{sheet}' if sheet else ''}。"
    if tool_name == "annotate_file":
        target = display(tool_args.get("path")) or request.target_path or first({"docx", "pdf", "txt", "md"}, target=True) or "目标文件"
        requirement = str(tool_args.get("requirement") or "").strip()
        if requirement:
            return f"按要求为 {display(target) or target} 生成并写回批注：{_compact_line(requirement, 90)}。"
        return f"把结构化批注写入 {display(target) or target}。"
    if tool_name in {"design_pptx_theme_layout", "write_pptx_slides", "add_pptx_slides"}:
        target = display(tool_args.get("path")) or request.target_path or first({"pptx"}, target=True) or "PPT 文件"
        if tool_name == "design_pptx_theme_layout":
            style_brief = str(tool_args.get("style_brief") or "").strip()
            return f"为 {display(target) or target} 套用统一主题、字体、配色和安全版式{f'，风格要求：{style_brief}' if style_brief else ''}。"
        return f"在 {display(target) or target} 中{'新增' if tool_name == 'add_pptx_slides' else '更新'}幻灯片内容。"
    if tool_name == "parse_file_to_text":
        source = display(tool_args.get("path")) or first(set()) or "文件"
        return f"解析 {source} 的文本内容，供后续分析使用。"
    if tool_name == "read_file_range":
        source = display(tool_args.get("path")) or first({"txt", "md", "csv", "json", "py", "js", "html", "css"}) or "文本文件"
        start = str(tool_args.get("start_line") or "1").strip()
        end = str(tool_args.get("end_line") or "").strip()
        return f"读取 {source} 的{'第 ' + start + ' 到 ' + end + ' 行' if end else '从第 ' + start + ' 行开始'}，供后续分析使用。"
    if tool_name == "replace_file_selection":
        target = display(tool_args.get("path")) or request.target_path or first({"txt", "md", "csv", "json", "py", "js", "html", "css"}, target=True) or "文本文件"
        return f"把改写后的选区内容写回 {display(target) or target}。"
    if tool_name == "compare_files":
        raw_paths = str(tool_args.get("file_paths") or "").strip()
        aspect = str(tool_args.get("aspect") or "content").strip()
        return f"对比文件{f'：{raw_paths}' if raw_paths else ''}，比较维度：{aspect}。"
    if tool_name == "run_python_code":
        return "在沙盒中运行代码处理数据，必要时生成图表或中间文件。"
    target = display(tool_args.get("path") or tool_args.get("target_path") or tool_args.get("destination"))
    return f"执行 {tool_name}{f'，目标：{target}' if target else ''}。"
