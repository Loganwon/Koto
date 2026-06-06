from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Sequence

from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest


@dataclass(frozen=True)
class FileTaskRecipe:
    id: str
    task_family: str
    write_operation_kind: str
    read_operation_kind: str = "read"
    execution_mode: str = "generic_tool_loop"
    priority: int = 50
    required_file_types: tuple[str, ...] = ()
    any_file_types: tuple[str, ...] = ()
    target_file_types: tuple[str, ...] = ()
    required_markers: tuple[str, ...] = ()
    forbidden_markers: tuple[str, ...] = ()
    requires_write: bool = False
    matched_capabilities: tuple[str, ...] = ()
    plan_steps: tuple[Dict[str, str], ...] = ()
    success_criteria: tuple[str, ...] = ()
    quality_gates: tuple[Dict[str, Any], ...] = ()


@dataclass(frozen=True)
class FileTaskRecipeMatch:
    recipe: FileTaskRecipe
    score: int
    reason_codes: List[str] = field(default_factory=list)
    markers: Dict[str, bool] = field(default_factory=dict)

    def public_dict(self) -> Dict[str, Any]:
        return {
            "recipe_id": self.recipe.id,
            "score": self.score,
            "task_family": self.recipe.task_family,
            "operation_kind": self.recipe.write_operation_kind,
            "reason_codes": [item for item in self.reason_codes if item],
        }


_CHART_PATTERN = re.compile(r"(?:图表|做成图|绘图|画图|画.{0,4}图|可视化|图片|chart|plot|graph|image)", re.IGNORECASE)
_PROBLEM_PATTERN = re.compile(r"(?:问题|风险|缺陷|异常|分析|审计|检查|issue|risk|problem|analy[sz]e|audit)", re.IGNORECASE)
_TABLE_PATTERN = re.compile(r"(?:表格|工作表|数据表|sheet|table|spreadsheet)", re.IGNORECASE)
_SUMMARY_PATTERN = re.compile(r"(?:总结|摘要|概括|提炼|要点|summary|summari[sz]e|brief)", re.IGNORECASE)
_TRANSLATION_PATTERN = re.compile(r"(?:翻译|译成|译为|translate|translation)", re.IGNORECASE)
_POLISH_PATTERN = re.compile(r"(?:润色|改写|重写|优化表达|polish|rewrite|humanise|humanize)", re.IGNORECASE)
_PPT_WRITE_PATTERN = re.compile(r"(?:新增|添加|加入|生成|写入|放入|插入|补充|扩写|更新|修改|编辑|润色|优化|页|幻灯片|add|append|insert|write|update|edit|slide)", re.IGNORECASE)
_PPT_DESIGN_PATTERN = re.compile(
    r"(?:"
    r"(?:pptx?|幻灯片|演示文稿|slides?|presentation|deck).{0,36}(?:风格|主题|版式|母版|模板|美化|排版|配色|视觉|设计|漂亮|好看|精美|高级|专业|beautiful|polished|design|theme|layout|template)"
    r"|(?:风格|主题|版式|母版|模板|美化|排版|配色|视觉|设计|漂亮|好看|精美|高级|专业|beautiful|polished|design|theme|layout|template).{0,36}(?:pptx?|幻灯片|演示文稿|slides?|presentation|deck)"
    r")",
    re.IGNORECASE,
)
_REPORT_PATTERN = re.compile(r"(?:报告|结论|清单|analysis|\breport\b(?!\s*\.))", re.IGNORECASE)
_DOCX_WRITE_PATTERN = re.compile(r"(?:加入|写入|插入|添加|放入|append|insert|write).{0,16}(?:docx|word|文档)", re.IGNORECASE)
_DOCX_CREATE_PATTERN = re.compile(r"(?:创建|新建|生成|产出|输出|记录到|整理成|create|generate|output|record|write).{0,20}(?:docx|word|文档)", re.IGNORECASE)
_STEPWISE_PATTERN = re.compile(
    r"(?:每完成一步|每一步(?:完成)?后|分步|一步一步|拆分成很多个小任务|继续下一步|等我(?:来说)?继续|确认后继续|等待(?:我|用户)?确认|step[- ]?by[- ]?step|stepwise|each step|wait for (?:my )?confirmation|continue next step)",
    re.IGNORECASE,
)
_LONG_DOCUMENT_PATTERN = re.compile(r"(?:非常长|很长|大量内容|整篇|全文|长文|long|large)", re.IGNORECASE)


def request_file_types(files: Sequence[FileTaskFile]) -> set[str]:
    file_types: set[str] = set()
    for file_info in files:
        file_type = str(file_info.type or Path(str(file_info.path or file_info.name)).suffix.lstrip(".")).lower().strip()
        if file_type:
            file_types.add(file_type)
            if file_type == "xlsm":
                file_types.add("xlsx")
            elif file_type == "doc":
                file_types.add("docx")
    return file_types


def request_target_file_type(request: FileTaskRequest, files: Sequence[FileTaskFile]) -> str:
    target_type = Path(str(request.target_path or "")).suffix.lstrip(".").lower().strip()
    if target_type:
        return target_type
    for file_info in files:
        if not file_info.target:
            continue
        candidate = str(file_info.type or Path(str(file_info.path or file_info.name)).suffix.lstrip(".")).lower().strip()
        if candidate:
            return candidate
    return ""


def semantic_markers(task: str, *, file_types: set[str] | None = None, target_file_type: str = "") -> Dict[str, bool]:
    text = str(task or "")
    lowered = text.lower()
    known_file_types = set(file_types or set())
    docx_write_phrase = bool(_DOCX_WRITE_PATTERN.search(text))
    docx_create_phrase = bool(_DOCX_CREATE_PATTERN.search(text))
    mentions_docx = any(marker in lowered for marker in ("docx", "word", "文档"))
    has_docx_target = target_file_type in {"docx", "doc"} or "docx" in known_file_types or docx_write_phrase or docx_create_phrase
    has_ppt = "pptx" in known_file_types or any(marker in lowered for marker in ("ppt", "pptx", "幻灯片", "演示文稿", "slides", "presentation", "deck"))
    markers = {
        "chart_request": bool(_CHART_PATTERN.search(text)),
        "problem_analysis_request": bool(_PROBLEM_PATTERN.search(text)),
        "financial_request": any(marker in lowered for marker in ("财务", "预测", "financial", "模型", "报表", "收入", "利润", "p&l", "pl")),
        "table_request": bool(_TABLE_PATTERN.search(text)),
        "summary_request": bool(_SUMMARY_PATTERN.search(text)),
        "translation_request": bool(_TRANSLATION_PATTERN.search(text)),
        "polish_request": bool(_POLISH_PATTERN.search(text)),
        "ppt_request": has_ppt,
        "ppt_slide_write_request": has_ppt and bool(_PPT_WRITE_PATTERN.search(text)),
        "ppt_design_request": has_ppt and bool(_PPT_DESIGN_PATTERN.search(text)),
        "docx_target": has_docx_target,
        "docx_write_phrase": docx_write_phrase,
        "docx_create_phrase": docx_create_phrase,
        "stepwise_confirmation_request": bool(_STEPWISE_PATTERN.search(text)),
        "long_document_request": bool(_LONG_DOCUMENT_PATTERN.search(text)),
        "pdf_source": "pdf" in known_file_types or "pdf" in lowered,
        "mentions_docx": mentions_docx,
    }
    markers["docx_report_request"] = has_docx_target and (
        markers["summary_request"]
        or markers["problem_analysis_request"]
        or markers["chart_request"]
        or bool(_REPORT_PATTERN.search(text))
    )
    markers["financial_xlsx_docx_chart_report"] = (
        "xlsx" in known_file_types
        and has_docx_target
        and markers["financial_request"]
        and markers["chart_request"]
        and markers["problem_analysis_request"]
    )
    return markers


TASK_RECIPES: tuple[FileTaskRecipe, ...] = (
    FileTaskRecipe(
        id="long_pdf_stepwise_docx_summary",
        task_family="summarize",
        write_operation_kind="stepwise_write",
        read_operation_kind="stepwise_read",
        execution_mode="generic_tool_loop",
        priority=125,
        any_file_types=("pdf",),
        target_file_types=("docx", "doc"),
        required_markers=("pdf_source", "summary_request", "stepwise_confirmation_request", "docx_target"),
        requires_write=True,
        matched_capabilities=("parse_file_to_text", "write_docx_content"),
        plan_steps=(
            {"id": "context", "title": "读取当前分段", "description": "按页窗口读取 PDF 当前步骤内容，不一次性吞全文。"},
            {"id": "write_docx", "title": "更新分步 DOCX", "description": "把当前页窗的正文摘要、关键发现和来源页码写入目标 DOCX。"},
            {"id": "pause", "title": "等待确认", "description": "写入成功后暂停，等待用户说继续再处理下一段。"},
            {"id": "check", "title": "核验结果", "description": "确认本步骤已产生 DOCX 文件变更，并给出下一步入口。"},
        ),
        success_criteria=("每一步必须先更新 DOCX 再等待确认", "目标 DOCX 产生 file.changed 事件", "DOCX 正文只包含当前页窗的实质解析，不包含等待继续或下一步计划", "续跑必须沿用同一 PDF、同一 DOCX 和下一页窗口"),
        quality_gates=(
            {
                "criterion": "stepwise_docx_has_step_notes",
                "operation": "write_docx_content",
                "metric": "paragraphs_written",
                "minimum": 4,
                "priority": "critical",
                "detail": "分步总结任务每一步都必须写入 DOCX；当前段落写入数：{actual}。",
            },
        ),
    ),
    FileTaskRecipe(
        id="financial_xlsx_docx_report",
        task_family="financial_report",
        write_operation_kind="analyze_visualize_write",
        read_operation_kind="analyze_visualize",
        execution_mode="financial_xlsx_docx_report",
        priority=120,
        required_file_types=("xlsx", "docx"),
        target_file_types=("docx", "doc"),
        required_markers=("financial_request", "chart_request", "problem_analysis_request", "docx_target"),
        requires_write=True,
        matched_capabilities=("inspect_workbook_structure", "audit_financial_workbook", "run_python_code", "write_docx_content", "insert_image_into_docx"),
        plan_steps=(
            {"id": "context", "title": "读取财务模型", "description": "检查工作簿结构、外部链接、公式和关键工作表。"},
            {"id": "execute", "title": "生成图表和问题清单", "description": "抽取关键年份指标，生成真实图表，并整理财务模型问题。"},
            {"id": "write_docx", "title": "写入 Word", "description": "先写入分析结论和问题清单，再插入真实图表图片。"},
            {"id": "check", "title": "核验结果", "description": "确认目标 DOCX 已产生文本和图片变更。"},
        ),
        success_criteria=("目标 DOCX 产生 file.changed 事件", "问题清单作为可读段落写入 DOCX", "图表作为真实图片插入 DOCX"),
        quality_gates=(
            {
                "criterion": "financial_report_has_narrative",
                "operation": "write_docx_content",
                "metric": "paragraphs_written",
                "minimum": 8,
                "priority": "critical",
                "detail": "财务图表报告应写入结构化分析段落；当前段落写入数：{actual}。",
            },
            {
                "criterion": "financial_report_has_real_chart_image",
                "operation": "insert_image_into_docx",
                "metric": "images_inserted",
                "minimum": 1,
                "priority": "critical",
                "detail": "财务图表报告必须插入真实图表图片；当前图片写入数：{actual}。",
            },
        ),
    ),
    FileTaskRecipe(
        id="xlsx_table_to_docx",
        task_family="table_transfer",
        write_operation_kind="write_table",
        priority=90,
        required_file_types=("xlsx", "docx"),
        target_file_types=("docx", "doc"),
        required_markers=("table_request", "docx_target"),
        forbidden_markers=("problem_analysis_request", "chart_request"),
        requires_write=True,
        matched_capabilities=("inspect_workbook_structure", "read_sheet_data", "insert_excel_as_docx_table"),
        success_criteria=("Excel 数据必须作为真实 Word 表格写入", "目标 DOCX 产生 file.changed 事件"),
        quality_gates=(
            {
                "criterion": "docx_table_request_has_table",
                "operation": "insert_excel_as_docx_table",
                "metric": "rows_written",
                "minimum": 1,
                "priority": "high",
                "detail": "用户要求表格数据进入 Word；当前表格写入行数：{actual}。",
            },
        ),
    ),
    FileTaskRecipe(
        id="docx_chart_report",
        task_family="visualize",
        write_operation_kind="visualize_write",
        priority=75,
        target_file_types=("docx", "doc"),
        required_markers=("chart_request", "docx_target"),
        requires_write=True,
        matched_capabilities=("run_python_code", "write_docx_content", "insert_image_into_docx"),
        success_criteria=("图表必须作为真实图片进入 DOCX", "目标 DOCX 产生 file.changed 事件"),
        quality_gates=(
            {
                "criterion": "docx_chart_request_has_image",
                "operation": "insert_image_into_docx",
                "metric": "images_inserted",
                "minimum": 1,
                "priority": "critical",
                "detail": "用户要求图表/图片进入 Word；当前图片写入数：{actual}。",
            },
        ),
    ),
    FileTaskRecipe(
        id="docx_report_write",
        task_family="summarize",
        write_operation_kind="write",
        priority=70,
        target_file_types=("docx", "doc"),
        required_markers=("docx_report_request", "docx_target"),
        requires_write=True,
        matched_capabilities=("parse_file_to_text", "write_docx_content"),
        success_criteria=("DOCX 报告/分析任务必须写入可读文本结构", "目标 DOCX 产生 file.changed 事件"),
        quality_gates=(
            {
                "criterion": "docx_report_has_narrative",
                "operation": "write_docx_content",
                "metric": "paragraphs_written",
                "minimum": 3,
                "priority": "high",
                "detail": "DOCX 报告/分析任务应写入可读文本结构；当前段落写入数：{actual}。",
            },
        ),
    ),
    FileTaskRecipe(
        id="pptx_design_edit_high_quality",
        task_family="presentation",
        write_operation_kind="design_slides",
        read_operation_kind="read",
        priority=118,
        any_file_types=("pptx",),
        required_markers=("ppt_design_request",),
        requires_write=True,
        matched_capabilities=("parse_file_to_text", "design_pptx_theme_layout"),
        plan_steps=(
            {"id": "context", "title": "读取原 PPT", "description": "先提取现有页标题、正文和页数，识别内容密度与设计风险。"},
            {"id": "design", "title": "应用专业版式", "description": "用统一主题、字体、配色、标题层级和安全占位网格美化 PPT，保留原内容。"},
            {"id": "check", "title": "核验结果", "description": "确认 PPTX 真实写回、页数未异常变化，并报告设计页数、主题和布局提示。"},
        ),
        success_criteria=(
            "PPTX 美化/设计任务必须调用真实 PPTX 设计工具并产生 file.changed 事件",
            "美化已有 PPT 时必须保留原有页数和文字内容，除非用户明确要求新增或删除页面",
            "设计结果应包含统一主题、字体、配色、标题层级和安全版式，不得只输出设计建议文本",
            "核验信息应报告 slides_designed、theme_name、layout_strategy 等可检查字段",
        ),
        quality_gates=(
            {
                "criterion": "pptx_design_has_real_design_pass",
                "operation": "design_pptx_theme_layout",
                "metric": "slides_designed",
                "minimum": 1,
                "priority": "critical",
                "detail": "PPT 美化/设计任务必须真实处理幻灯片；当前设计页数：{actual}。",
            },
            {
                "criterion": "pptx_design_styles_text_shapes",
                "operation": "design_pptx_theme_layout",
                "metric": "text_shapes_styled",
                "minimum": 1,
                "priority": "high",
                "detail": "PPT 设计任务应统一文字样式；当前已处理文本形状数：{actual}。",
            },
        ),
    ),
    FileTaskRecipe(
        id="ppt_slide_write",
        task_family="presentation",
        write_operation_kind="write_slides",
        priority=80,
        any_file_types=("pptx",),
        required_markers=("ppt_slide_write_request",),
        requires_write=True,
        matched_capabilities=("parse_file_to_text", "add_pptx_slides", "write_pptx_slides", "design_pptx_theme_layout"),
        success_criteria=("PPT 任务必须产生幻灯片写入、更新或设计操作", "目标 PPTX 产生 file.changed 事件"),
        quality_gates=(
            {
                "criterion": "ppt_request_has_slide_write",
                "any_operation": ("add_pptx_slides", "write_pptx_slides", "design_pptx_theme_layout"),
                "priority": "critical",
                "detail": "PPT 任务应产生幻灯片写入/更新操作；当前操作：{operations}。",
            },
        ),
    ),
    FileTaskRecipe(
        id="docx_polish_writeback",
        task_family="polish",
        write_operation_kind="write",
        priority=72,
        target_file_types=("docx", "doc"),
        required_markers=("polish_request", "docx_target"),
        requires_write=True,
        matched_capabilities=("read_docx_content", "write_docx_content"),
        success_criteria=("润色结果必须写回目标 DOCX", "目标文档产生真实文本变更"),
    ),
    FileTaskRecipe(
        id="translate_writeback",
        task_family="translate",
        write_operation_kind="write",
        priority=65,
        required_markers=("translation_request",),
        requires_write=True,
        matched_capabilities=("parse_file_to_text", "write_docx_content", "create_file"),
        success_criteria=("翻译结果必须写入用户指定目标", "不得只输出说明文字代替文件结果"),
    ),
)


def recipe_matches(
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    *,
    write_intent: bool = False,
) -> List[FileTaskRecipeMatch]:
    file_types = request_file_types(files)
    target_type = request_target_file_type(request, files)
    markers = semantic_markers(request.task, file_types=file_types, target_file_type=target_type)
    matches: List[FileTaskRecipeMatch] = []
    for recipe in TASK_RECIPES:
        if recipe.requires_write and not write_intent:
            continue
        if recipe.required_file_types and not set(recipe.required_file_types).issubset(file_types):
            continue
        if recipe.any_file_types and not set(recipe.any_file_types).intersection(file_types):
            continue
        if recipe.target_file_types and target_type and target_type not in set(recipe.target_file_types):
            continue
        if recipe.target_file_types and not target_type and "docx_target" not in recipe.required_markers:
            continue
        if any(not markers.get(marker, False) for marker in recipe.required_markers):
            continue
        if any(markers.get(marker, False) for marker in recipe.forbidden_markers):
            continue

        score = recipe.priority + (len(recipe.required_file_types) * 4) + (len(recipe.required_markers) * 5)
        if target_type in set(recipe.target_file_types):
            score += 8
        if set(recipe.matched_capabilities):
            score += min(10, len(recipe.matched_capabilities))
        reason_codes = [f"recipe:{recipe.id}"]
        reason_codes.extend(f"recipe_marker:{marker}" for marker in recipe.required_markers if markers.get(marker))
        matches.append(FileTaskRecipeMatch(recipe=recipe, score=score, reason_codes=reason_codes, markers=markers))
    return sorted(matches, key=lambda item: item.score, reverse=True)


def select_task_recipe(
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    *,
    write_intent: bool = False,
) -> FileTaskRecipeMatch | None:
    matches = recipe_matches(request, files, write_intent=write_intent)
    return matches[0] if matches else None


def recipe_by_id(recipe_id: str) -> FileTaskRecipe | None:
    clean = str(recipe_id or "").strip()
    for recipe in TASK_RECIPES:
        if recipe.id == clean:
            return recipe
    return None
