from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Sequence

from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_review_intent import (
    COMPARE_MARKERS,
    has_any_marker,
    has_explicit_docx_review_intent,
)


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


_CHART_PATTERN = re.compile(
    r"(?:图表|做成图|绘图|画图|画.{0,4}图|可视化|图片|"
    r"统计图|折线图|柱状图|饼图|散点图|曲线图|"
    r"chart|plot|graph|image)",
    re.IGNORECASE,
)
_PROBLEM_PATTERN = re.compile(r"(?:问题|风险|缺陷|异常|分析|审计|检查|issue|risk|problem|analy[sz]e|audit)", re.IGNORECASE)
_TABLE_PATTERN = re.compile(r"(?:表格|工作表|数据表|sheet|table|spreadsheet)", re.IGNORECASE)
_TABLE_PRESERVE_PATTERN = re.compile(
    r"(?:保留|保持).{0,24}(?:已有|现有|原有|当前).{0,16}(?:表格|工作表|数据表|table).{0,16}(?:不变|不修改|不要改|原样)"
    r"|(?:preserve|keep).{0,32}(?:existing|current|original).{0,24}(?:table|sheet|spreadsheet)",
    re.IGNORECASE,
)
_TABLE_OUTPUT_PATTERN = re.compile(
    r"(?:把|将|加入|写入|插入|添加|放入|复制|生成|创建|输出|包含|包括|附上).{0,40}(?:表格|工作表|数据表|sheet|table|spreadsheet)"
    r"|(?:表格|工作表|数据表|sheet|table|spreadsheet).{0,40}(?:加入|写入|插入|添加|追加|放入|复制|生成|创建|输出|包含|包括|附上)"
    r"|(?:add|insert|copy|include|write|put|create|generate|output).{0,40}(?:table|sheet|spreadsheet)",
    re.IGNORECASE,
)
_SUMMARY_PATTERN = re.compile(r"(?:总结|摘要|概括|提炼|要点|summary|summari[sz]e|brief)", re.IGNORECASE)
_TRANSLATION_PATTERN = re.compile(r"(?:翻译|译成|译为|translate|translation)", re.IGNORECASE)
_POLISH_PATTERN = re.compile(
    r"(?:请|帮我|帮忙|需要|要求|直接|对|把|将|给).{0,20}(?:润色|改写|重写|优化表达)"
    r"|(?:润色|改写|重写|优化表达).{0,36}(?:文档|文件|文章|内容|段落|文本|表达|语句|译稿|docx|word|写回|保存)"
    r"|(?:please|help|need|directly|can you).{0,24}(?:polish|rewrite|humanise|humanize)"
    r"|(?:polish|rewrite|humanise|humanize).{0,36}(?:document|file|content|text|paragraph|draft|translation|write back|save)",
    re.IGNORECASE,
)
_PPT_WRITE_PATTERN = re.compile(r"(?:新增|添加|加入|生成|写入|放入|插入|补充|扩写|更新|修改|编辑|润色|优化|页|幻灯片|add|append|insert|write|update|edit|slide)", re.IGNORECASE)
_PPT_DESIGN_PATTERN = re.compile(
    r"(?:"
    r"(?:pptx?|幻灯片|演示文稿|slides?|presentation|deck).{0,36}(?:风格|主题|版式|母版|模板|美化|排版|配色|视觉|设计|漂亮|好看|精美|高级|专业|beautiful|polished|design|theme|layout|template)"
    r"|(?:风格|主题|版式|母版|模板|美化|排版|配色|视觉|设计|漂亮|好看|精美|高级|专业|beautiful|polished|design|theme|layout|template).{0,36}(?:pptx?|幻灯片|演示文稿|slides?|presentation|deck)"
    r")",
    re.IGNORECASE,
)
_REPORT_PATTERN = re.compile(r"(?:报告|结论|清单|analysis|\breport\b(?!\s*\.))", re.IGNORECASE)
_CONTRACT_PATTERN = re.compile(r"(?:合同|协议|条款|contract|agreement|msa|sow|terms?)", re.IGNORECASE)
_DOCX_TEMPLATE_FILL_PATTERN = re.compile(
    r"(?:模板|占位符|字段|表单|套打|填充|填写|填入|template|placeholder|mail merge|form).{0,48}(?:docx|word|文档|合同|模板)"
    r"|(?:docx|word|文档|合同|模板).{0,48}(?:模板|占位符|字段|表单|套打|填充|填写|填入|template|placeholder|mail merge|form)",
    re.IGNORECASE,
)
_DOCX_PDF_EXPORT_PATTERN = re.compile(
    r"(?:docx|doc|word|文档).{0,48}(?:转成|转换为|导出为|另存为|保存为|输出为|convert|export|save as).{0,24}(?:pdf)"
    r"|(?:转成|转换为|导出为|另存为|保存为|输出为|convert|export|save as).{0,48}(?:pdf).{0,32}(?:docx|doc|word|文档)?",
    re.IGNORECASE,
)
_FILE_FORMAT_CONVERT_PATTERN = re.compile(
    r"(?:转换|转成|转换为|导出为|另存为|保存为|输出为|convert|export|save as).{0,64}"
    r"(?:pdf|docx?|word|txt|text|md|markdown|html|xlsx?|excel|csv|pptx?|powerpoint|png|jpe?g|webp|bmp|gif)"
    r"|(?:pdf|docx?|word|txt|text|md|markdown|html|xlsx?|excel|csv|pptx?|powerpoint|png|jpe?g|webp|bmp|gif).{0,64}"
    r"(?:格式|format).{0,24}(?:转换|转成|导出|另存|保存|convert|export|save)",
    re.IGNORECASE,
)
_DOCX_CLEAR_REVIEW_PATTERN = re.compile(
    r"(?:清除|清空|删除|移除|去掉|接受|accept|remove|clear|delete).{0,32}(?:批注|注释|评论|修订|审阅|comments?|annotations?|tracked changes|revisions?)"
    r"|(?:批注|注释|评论|修订|审阅|comments?|annotations?|tracked changes|revisions?).{0,32}(?:清除|清空|删除|移除|去掉|接受|accept|remove|clear|delete)",
    re.IGNORECASE,
)
_SPREADSHEET_WRITE_PATTERN = re.compile(
    r"(?:写入|填入|填充|更新|修改|设置|替换|录入|write|fill|update|set|replace).{0,40}(?:单元格|表格|工作表|sheet|cell|cells|xlsx|excel)"
    r"|(?:单元格|表格|工作表|sheet|cell|cells|xlsx|excel).{0,40}(?:写入|填入|填充|更新|修改|设置|替换|录入|write|fill|update|set|replace)",
    re.IGNORECASE,
)
_SPREADSHEET_CELL_REF_WRITE_PATTERN = re.compile(
    r"(?:写入|填入|填充|更新|修改|设置|替换|录入|write|fill|update|set|replace).{0,60}[A-Z]{1,3}\d{1,7}",
    re.IGNORECASE,
)
_TEXT_SELECTION_REPLACE_PATTERN = re.compile(
    r"(?:选区|选中文本|这一段|这段|selected text|selection).{0,40}(?:替换|改写|润色|翻译|写回|replace|rewrite|polish|translate|write back)"
    r"|(?:替换|改写|润色|翻译|写回|replace|rewrite|polish|translate|write back).{0,40}(?:选区|选中文本|这一段|这段|selected text|selection)",
    re.IGNORECASE,
)
_FILE_COPY_PATTERN = re.compile(
    r"(?:复制|拷贝|另存一份|创建副本|copy|duplicate).{0,48}(?:文件|文档|表格|演示稿|pdf|docx?|xlsx?|pptx?|txt|md|csv|json|file)"
    r"|(?:文件|文档|表格|演示稿|pdf|docx?|xlsx?|pptx?|txt|md|csv|json|file).{0,48}(?:复制|拷贝|另存一份|创建副本|copy|duplicate)",
    re.IGNORECASE,
)
_CROSS_FILE_EXTRACT_PATTERN = re.compile(
    r"(?:提取|抽取|摘取|extract).{0,64}(?:到|写入|保存到|输出到|into|to).{0,40}(?:文件|文档|表格|docx?|xlsx?|pptx?|txt|md|csv|json|file)"
    r"|(?:从|from).{0,48}(?:提取|抽取|摘取|extract).{0,64}(?:到|写入|保存到|输出到|into|to)",
    re.IGNORECASE,
)
_DOCX_WRITE_PATTERN = re.compile(r"(?:加入|写入|插入|添加|放入|append|insert|write).{0,16}(?:docx|word|文档)", re.IGNORECASE)
_DOCX_CREATE_PATTERN = re.compile(r"(?:创建|新建|生成|产出|输出|记录到|整理成|create|generate|output|record|write).{0,20}(?:docx|word|文档)", re.IGNORECASE)
_STEPWISE_PATTERN = re.compile(
    r"(?:每完成一步|每一步(?:完成)?后|分步|一步一步|拆分成很多个小任务|继续下一步|等我(?:来说)?继续|确认后继续|等待(?:我|用户)?确认|step[- ]?by[- ]?step|stepwise|each step|wait for (?:my )?confirmation|continue next step)",
    re.IGNORECASE,
)
_LONG_DOCUMENT_PATTERN = re.compile(r"(?:非常长|很长|大量内容|整篇|全文|长文|long|large)", re.IGNORECASE)
_META_KEYWORD_CLAUSE_PATTERN = re.compile(
    r"(?:任务描述|提示词|这句话|本句|文本|需求).{0,24}(?:故意|刻意)?(?:包含|包括|提到|写了).{0,100}(?:这些词|这些字|关键词|词语|字样)"
    r"|(?:prompt|task|request|sentence).{0,32}(?:intentionally|deliberately)?.{0,24}(?:contains?|mentions?).{0,100}(?:keywords?|words?|phrases?)",
    re.IGNORECASE,
)
_KEYWORD_ROUTE_NEGATION_PATTERN = re.compile(
    r"(?:不要|别|不得|不应|不能).{0,80}(?:关键词|快捷动作|路由|分流|触发|shortcut|keyword|route)"
    r"|(?:do not|don't|dont|without|should not|must not).{0,80}(?:keyword|shortcut|route|trigger)",
    re.IGNORECASE,
)


def _semantic_task_text(task: str) -> str:
    text = str(task or "")
    text = _META_KEYWORD_CLAUSE_PATTERN.sub(" ", text)
    text = _KEYWORD_ROUTE_NEGATION_PATTERN.sub(" ", text)
    return text


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
    text = _semantic_task_text(str(task or ""))
    lowered = text.lower()
    known_file_types = set(file_types or set())
    docx_write_phrase = bool(_DOCX_WRITE_PATTERN.search(text))
    docx_create_phrase = bool(_DOCX_CREATE_PATTERN.search(text))
    mentions_docx = any(marker in lowered for marker in ("docx", "word", "文档"))
    has_docx_output_target = target_file_type in {"docx", "doc"} or docx_write_phrase or docx_create_phrase
    has_docx_target = has_docx_output_target or "docx" in known_file_types
    has_ppt = "pptx" in known_file_types or any(marker in lowered for marker in ("ppt", "pptx", "幻灯片", "演示文稿", "slides", "presentation", "deck"))
    table_mentioned = bool(_TABLE_PATTERN.search(text))
    table_preserve_only = bool(_TABLE_PRESERVE_PATTERN.search(text)) and not bool(
        _TABLE_OUTPUT_PATTERN.search(text)
    )
    financial_request = bool(
        re.search(r"(?:财务|财务模型|预测|报表|收入|利润|销售|台账|流水)", text, re.IGNORECASE)
        or re.search(r"\b(?:financial|finance|sales|revenue|p&l|p/l)\b", lowered)
    )
    markers = {
        "chart_request": bool(_CHART_PATTERN.search(text)),
        "problem_analysis_request": bool(_PROBLEM_PATTERN.search(text)),
        "financial_request": financial_request,
        "table_request": table_mentioned and not table_preserve_only,
        "summary_request": bool(_SUMMARY_PATTERN.search(text)),
        "translation_request": bool(_TRANSLATION_PATTERN.search(text)),
        "polish_request": bool(_POLISH_PATTERN.search(text)),
        "ppt_request": has_ppt,
        "ppt_slide_write_request": has_ppt and bool(_PPT_WRITE_PATTERN.search(text)),
        "ppt_design_request": has_ppt and bool(_PPT_DESIGN_PATTERN.search(text)),
        "docx_template_fill_request": bool(_DOCX_TEMPLATE_FILL_PATTERN.search(text)),
        "docx_pdf_export_request": bool(_DOCX_PDF_EXPORT_PATTERN.search(text)),
        "file_format_convert_request": bool(_FILE_FORMAT_CONVERT_PATTERN.search(text)),
        "docx_clear_review_request": bool(_DOCX_CLEAR_REVIEW_PATTERN.search(text)),
        "spreadsheet_write_request": bool(
            _SPREADSHEET_WRITE_PATTERN.search(text)
            or _SPREADSHEET_CELL_REF_WRITE_PATTERN.search(text)
        ),
        "text_selection_replace_request": bool(_TEXT_SELECTION_REPLACE_PATTERN.search(text)),
        "file_copy_request": bool(_FILE_COPY_PATTERN.search(text)),
        "cross_file_extract_request": bool(_CROSS_FILE_EXTRACT_PATTERN.search(text)),
        "docx_target": has_docx_target,
        "docx_output_target": has_docx_output_target,
        "docx_write_phrase": docx_write_phrase,
        "docx_create_phrase": docx_create_phrase,
        "stepwise_confirmation_request": bool(_STEPWISE_PATTERN.search(text)),
        "long_document_request": bool(_LONG_DOCUMENT_PATTERN.search(text)),
        "contract_request": bool(_CONTRACT_PATTERN.search(text)),
        "pdf_source": "pdf" in known_file_types or "pdf" in lowered,
        "mentions_docx": mentions_docx,
    }
    markers["docx_report_request"] = has_docx_target and (
        markers["summary_request"]
        or markers["problem_analysis_request"]
        or markers["chart_request"]
        or bool(_REPORT_PATTERN.search(text))
    )
    markers["docx_compare_request"] = has_any_marker(text, COMPARE_MARKERS)
    markers["docx_compare_annotate_request"] = (
        has_docx_target
        and markers["docx_compare_request"]
        and has_explicit_docx_review_intent(text)
    )
    markers["docx_review_request"] = (
        has_docx_target
        and has_explicit_docx_review_intent(text)
        and not markers["docx_compare_request"]
    )
    markers["pdf_docx_review_request"] = (
        "pdf" in known_file_types
        and has_docx_target
        and bool(markers["docx_review_request"])
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
        id="docx_contract_compare_review",
        task_family="contract_review",
        write_operation_kind="compare_annotate",
        read_operation_kind="compare",
        execution_mode="generic_tool_loop",
        priority=150,
        required_file_types=("docx",),
        target_file_types=("docx",),
        required_markers=(
            "docx_compare_annotate_request",
            "contract_request",
            "docx_target",
        ),
        requires_write=True,
        matched_capabilities=(
            "plan_docx_compare_annotations",
            "write_docx_comments",
            "compare_docx_and_annotate",
        ),
        plan_steps=(
            {
                "id": "compare",
                "title": "对比两版合同",
                "description": "比较两份合同 DOCX 的条款变化，定位可写回目标合同原文的新增、删除和修改处。",
            },
            {
                "id": "annotate",
                "title": "写入合同差异批注",
                "description": "由 AI 生成差异、风险和建议措辞，再作为 Word 原生批注写入目标合同原文。",
            },
            {
                "id": "risk_summary",
                "title": "总结风险关注点",
                "description": "在对话框中汇总付款、违约、终止、责任等高关注变化。",
            },
            {
                "id": "check",
                "title": "核验结果",
                "description": "确认目标合同已产生真实差异批注和风险摘要。",
            },
        ),
        success_criteria=(
            "必须比较两份合同 DOCX，而不是审校单个合同",
            "差异批注必须写入用户指定或默认目标合同原文，不得创建独立对比文档",
            "对话框总结必须说明关键风险关注点",
            "目标 DOCX 必须产生 annotations_added > 0 的 file.changed",
        ),
        quality_gates=(
            {
                "criterion": "docx_contract_compare_has_annotations",
                "any_operation": (
                    "write_docx_comments",
                    "compare_docx_and_annotate",
                ),
                "metric": "annotations_added",
                "minimum": 1,
                "priority": "critical",
                "detail": "合同对比审阅必须写入真实差异批注；当前批注数：{actual}。",
            },
        ),
    ),
    FileTaskRecipe(
        id="docx_compare_annotation",
        task_family="compare",
        write_operation_kind="compare_annotate",
        read_operation_kind="compare",
        execution_mode="generic_tool_loop",
        priority=140,
        required_file_types=("docx",),
        target_file_types=("docx",),
        required_markers=("docx_compare_annotate_request", "docx_target"),
        requires_write=True,
        matched_capabilities=(
            "plan_docx_compare_annotations",
            "write_docx_comments",
            "compare_docx_and_annotate",
        ),
        plan_steps=(
            {
                "id": "compare",
                "title": "对比两份 DOCX",
                "description": "比较两份 Word 文档正文差异，确定可写回目标文档原文的差异片段。",
            },
            {
                "id": "annotate",
                "title": "写入差异批注",
                "description": "由 AI 生成差异说明，再作为 Word 原生批注写入用户指定的目标 DOCX 原文。",
            },
            {
                "id": "check",
                "title": "核验批注",
                "description": "确认目标 DOCX 已产生真实差异批注。",
            },
        ),
        success_criteria=(
            "必须比较两份 DOCX，而不是审校单个文档",
            "批注必须写入用户指定或默认目标 DOCX 原文，不得创建独立对比文档",
            "目标 DOCX 必须产生 annotations_added > 0 的 file.changed",
        ),
        quality_gates=(
            {
                "criterion": "docx_compare_has_difference_annotations",
                "any_operation": (
                    "write_docx_comments",
                    "compare_docx_and_annotate",
                ),
                "metric": "annotations_added",
                "minimum": 1,
                "priority": "critical",
                "detail": "DOCX 对比标注任务必须写入真实差异批注；当前批注数：{actual}。",
            },
        ),
    ),
    FileTaskRecipe(
        id="multi_file_compare_readonly",
        task_family="compare",
        write_operation_kind="compare",
        read_operation_kind="compare",
        priority=78,
        any_file_types=("docx", "xlsx", "pptx", "pdf", "txt", "md", "csv", "json"),
        required_markers=("docx_compare_request",),
        requires_write=False,
        matched_capabilities=("compare_files",),
        plan_steps=(
            {"id": "compare", "title": "对比文件", "description": "读取多份文件并输出结构化差异、相同点和重点结论。"},
            {"id": "answer", "title": "返回对比结论", "description": "只在对话中回答，不写回文件，除非用户明确要求产出文件。"},
        ),
        success_criteria=("只读对比任务必须调用 compare_files 或读取明确文件上下文", "不得在未请求写入时修改源文件"),
    ),
    FileTaskRecipe(
        id="docx_template_fill",
        task_family="template_fill",
        write_operation_kind="fill_template",
        priority=116,
        any_file_types=("docx", "doc"),
        target_file_types=("docx", "doc"),
        required_markers=("docx_template_fill_request", "docx_target"),
        forbidden_markers=("table_request",),
        requires_write=True,
        matched_capabilities=("read_docx_content", "fill_docx_template"),
        plan_steps=(
            {"id": "inspect", "title": "识别模板字段", "description": "读取 DOCX 模板，确认需要替换的占位符和字段来源。"},
            {"id": "fill", "title": "填充 Word 模板", "description": "调用模板填充工具替换真实 DOCX 占位符，可按用户要求写入新文件或原文件。"},
            {"id": "check", "title": "核验填充结果", "description": "确认目标 DOCX 产生字段替换差异和真实文件变更。"},
        ),
        success_criteria=("必须调用 fill_docx_template 填充真实 Word 模板", "目标 DOCX 必须产生占位符替换差异"),
        quality_gates=(
            {
                "criterion": "docx_template_fill_replaces_placeholders",
                "operation": "fill_docx_template",
                "metric": "placeholders_replaced",
                "minimum": 1,
                "priority": "critical",
                "detail": "Word 模板填充必须替换至少 1 个占位符；当前替换数：{actual}。",
            },
        ),
    ),
    FileTaskRecipe(
        id="docx_pdf_export",
        task_family="convert",
        write_operation_kind="convert",
        priority=112,
        any_file_types=("docx", "doc"),
        required_markers=("docx_pdf_export_request", "docx_target"),
        requires_write=True,
        matched_capabilities=("convert_docx_to_pdf",),
        plan_steps=(
            {"id": "convert", "title": "转换 Word 为 PDF", "description": "使用本地可用转换器将 DOCX/DOC 导出为 PDF。"},
            {"id": "check", "title": "核验 PDF 输出", "description": "确认产生 PDF 文件变更或明确报告本地转换器缺失。"},
        ),
        success_criteria=("必须调用 convert_docx_to_pdf 生成 PDF 文件", "如果本机缺少转换器，必须返回可恢复的阻塞原因"),
        quality_gates=(
            {
                "criterion": "docx_pdf_export_uses_converter",
                "operation": "convert_docx_to_pdf",
                "priority": "critical",
                "detail": "Word 转 PDF 任务必须调用 DOCX 转 PDF 工具；当前操作：{operations}。",
            },
        ),
    ),
    FileTaskRecipe(
        id="docx_clear_review_marks",
        task_family="review_cleanup",
        write_operation_kind="clear_review_marks",
        priority=110,
        any_file_types=("docx", "doc"),
        target_file_types=("docx", "doc"),
        required_markers=("docx_clear_review_request", "docx_target"),
        requires_write=True,
        matched_capabilities=("clear_docx_review_marks",),
        plan_steps=(
            {"id": "clear", "title": "清除审阅标记", "description": "按用户要求清除 Word 批注、修订或全部审阅痕迹。"},
            {"id": "check", "title": "核验清理结果", "description": "确认 DOCX 已执行清理工具并返回清理范围。"},
        ),
        success_criteria=("清除批注/修订任务必须使用 clear_docx_review_marks", "不得误调用 annotate_file 生成新批注"),
        quality_gates=(
            {
                "criterion": "docx_clear_review_uses_cleanup_tool",
                "operation": "clear_docx_review_marks",
                "priority": "critical",
                "detail": "清除 Word 审阅标记必须调用清理工具；当前操作：{operations}。",
            },
        ),
    ),
    FileTaskRecipe(
        id="file_format_convert",
        task_family="convert",
        write_operation_kind="convert",
        priority=82,
        any_file_types=(
            "docx",
            "doc",
            "pdf",
            "txt",
            "md",
            "markdown",
            "xlsx",
            "xls",
            "csv",
            "pptx",
            "ppt",
            "jpg",
            "jpeg",
            "png",
            "webp",
            "bmp",
            "gif",
        ),
        required_markers=("file_format_convert_request",),
        requires_write=True,
        matched_capabilities=("convert_file",),
        plan_steps=(
            {"id": "convert", "title": "转换文件格式", "description": "按用户指定目标格式调用通用转换工具生成输出文件。"},
            {"id": "check", "title": "核验转换输出", "description": "确认产生目标格式文件，或明确报告不支持的格式组合/本地依赖缺失。"},
        ),
        success_criteria=("必须调用 convert_file 生成目标格式文件", "不支持的格式组合必须返回可恢复的阻塞原因"),
        quality_gates=(
            {
                "criterion": "file_format_convert_uses_converter",
                "operation": "convert_file",
                "priority": "critical",
                "detail": "格式转换任务必须调用通用转换工具；当前操作：{operations}。",
            },
        ),
    ),
    FileTaskRecipe(
        id="pdf_docx_review_bridge",
        task_family="annotate",
        write_operation_kind="annotate",
        read_operation_kind="read",
        execution_mode="doc_annotate_bridge",
        priority=132,
        required_file_types=("pdf", "docx"),
        target_file_types=("docx",),
        required_markers=("pdf_docx_review_request", "docx_target"),
        requires_write=True,
        matched_capabilities=("read_docx_content", "annotate_file"),
        plan_steps=(
            {"id": "review", "title": "生成对照审校建议", "description": "读取 PDF 对照来源和 DOCX 文稿，生成可定位的 Word 审校建议。"},
            {"id": "write", "title": "写回 Word 修订", "description": "将可定位的审校建议写回目标 DOCX。"},
            {"id": "check", "title": "核验输出", "description": "确认目标 DOCX 已产生真实审校标记。"},
        ),
        success_criteria=("目标 DOCX 必须产生真实审校标记", "审校建议必须锚定到目标 DOCX 中存在的原文片段"),
        quality_gates=(
            {
                "criterion": "docx_review_bridge_has_annotations",
                "operation": "annotate_file",
                "metric": "annotations_added",
                "minimum": 1,
                "priority": "critical",
                "detail": "DOCX 审校桥接必须至少写回 1 条可核验审校标记；当前写回数：{actual}。",
            },
        ),
    ),
    FileTaskRecipe(
        id="single_docx_review_bridge",
        task_family="annotate",
        write_operation_kind="annotate",
        read_operation_kind="read",
        execution_mode="doc_annotate_bridge",
        priority=88,
        any_file_types=("docx", "doc"),
        target_file_types=("docx",),
        required_markers=("docx_review_request", "docx_target"),
        requires_write=True,
        matched_capabilities=("read_docx_content", "annotate_file"),
        success_criteria=("目标 DOCX 必须产生真实审校标记", "不得把普通润色写回误判为批注审校"),
        quality_gates=(
            {
                "criterion": "single_docx_review_has_annotations",
                "operation": "annotate_file",
                "metric": "annotations_added",
                "minimum": 1,
                "priority": "critical",
                "detail": "单 DOCX 审校任务必须至少写回 1 条可核验审校标记；当前写回数：{actual}。",
            },
        ),
    ),
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
        execution_mode="generic_tool_loop",
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
        id="spreadsheet_cell_write",
        task_family="spreadsheet",
        write_operation_kind="write_cells",
        priority=76,
        any_file_types=("xlsx", "xlsm", "csv"),
        target_file_types=("xlsx", "xlsm", "csv"),
        required_markers=("spreadsheet_write_request",),
        forbidden_markers=("chart_request", "docx_report_request", "docx_output_target"),
        requires_write=True,
        matched_capabilities=("read_sheet_data", "write_sheet_data"),
        success_criteria=("表格修改任务必须写入真实单元格", "目标表格产生 cells_written > 0 的 file.changed"),
        quality_gates=(
            {
                "criterion": "spreadsheet_write_has_cells",
                "operation": "write_sheet_data",
                "metric": "cells_written",
                "minimum": 1,
                "priority": "critical",
                "detail": "表格写入任务必须更新至少 1 个单元格；当前写入数：{actual}。",
            },
        ),
    ),
    FileTaskRecipe(
        id="workspace_file_copy",
        task_family="workspace",
        write_operation_kind="copy_file",
        priority=74,
        any_file_types=("docx", "xlsx", "pptx", "pdf", "txt", "md", "csv", "json"),
        required_markers=("file_copy_request",),
        requires_write=True,
        matched_capabilities=("copy_file",),
        success_criteria=("文件复制任务必须调用 copy_file 产生目标副本", "不得把复制任务降级为只读说明"),
        quality_gates=(
            {
                "criterion": "workspace_file_copy_uses_copy_tool",
                "operation": "copy_file",
                "priority": "critical",
                "detail": "文件复制任务必须调用 copy_file；当前操作：{operations}。",
            },
        ),
    ),
    FileTaskRecipe(
        id="cross_file_extract_to_file",
        task_family="extract",
        write_operation_kind="extract_to_file",
        priority=73,
        any_file_types=("docx", "xlsx", "pptx", "pdf", "txt", "md", "csv", "json"),
        required_markers=("cross_file_extract_request",),
        requires_write=True,
        matched_capabilities=("parse_file_to_text", "extract_to_file"),
        success_criteria=("跨文件提取任务必须把抽取结果写入目标文件", "不得只在对话中输出而不落盘"),
        quality_gates=(
            {
                "criterion": "cross_file_extract_uses_write_tool",
                "operation": "extract_to_file",
                "priority": "critical",
                "detail": "跨文件提取任务必须调用 extract_to_file；当前操作：{operations}。",
            },
        ),
    ),
    FileTaskRecipe(
        id="docx_report_table_write",
        task_family="summarize",
        write_operation_kind="write",
        priority=88,
        target_file_types=("docx", "doc"),
        required_markers=("docx_report_request", "docx_target", "table_request"),
        requires_write=True,
        matched_capabilities=(
            "parse_file_to_text",
            "read_sheet_data",
            "insert_excel_as_docx_table",
            "write_docx_content",
        ),
        success_criteria=(
            "DOCX 报告/分析任务必须写入可读文本结构",
            "涉及表格或预算核验时必须在目标 DOCX 中保留可核验表格/段落",
            "目标 DOCX 产生 file.changed 事件",
        ),
        quality_gates=(
            {
                "criterion": "docx_report_has_narrative",
                "operation": "write_docx_content",
                "metric": "paragraphs_written",
                "minimum": 3,
                "priority": "high",
                "detail": "DOCX 报告/分析任务应写入可读文本结构；当前段落写入数：{actual}。",
            },
            {
                "criterion": "docx_table_request_has_table",
                "operation": "insert_excel_as_docx_table",
                "metric": "rows_written",
                "minimum": 1,
                "priority": "high",
                "detail": "用户要求表格进入 Word；当前表格写入行数：{actual}。",
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
        forbidden_markers=("table_request",),
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
        id="text_selection_replace",
        task_family="text_edit",
        write_operation_kind="replace_selection",
        priority=68,
        any_file_types=("txt", "md", "text", "csv", "json", "py", "js", "html", "css"),
        required_markers=("text_selection_replace_request",),
        requires_write=True,
        matched_capabilities=("read_file_range", "replace_file_selection"),
        success_criteria=("文本选区修改必须精确替换用户选中的原文", "目标文本文件产生 replacements_made > 0 的 file.changed"),
        quality_gates=(
            {
                "criterion": "text_selection_replace_has_replacement",
                "operation": "replace_file_selection",
                "metric": "replacements_made",
                "minimum": 1,
                "priority": "critical",
                "detail": "文本选区替换必须至少替换 1 处原文；当前替换数：{actual}。",
            },
        ),
    ),
    FileTaskRecipe(
        id="long_docx_stepwise_polish_writeback",
        task_family="polish",
        write_operation_kind="stepwise_polish_write",
        read_operation_kind="stepwise_read",
        execution_mode="long_docx_stepwise_polish_writeback",
        priority=126,
        any_file_types=("docx", "doc"),
        target_file_types=("docx", "doc"),
        required_markers=("polish_request", "stepwise_confirmation_request", "docx_target"),
        requires_write=True,
        matched_capabilities=("read_docx_content", "rewrite_docx_paragraph_window"),
        plan_steps=(
            {"id": "context", "title": "读取当前段落窗口", "description": "按段落窗口读取 DOCX 当前步骤内容，不一次性润色全文。"},
            {"id": "polish", "title": "润色并写回 DOCX", "description": "只润色当前段落窗口，保留文档其余内容。"},
            {"id": "pause", "title": "等待确认", "description": "写回成功后暂停，等待用户说继续再处理下一段。"},
            {"id": "check", "title": "核验结果", "description": "确认当前段落窗口已写回，并给出下一步入口。"},
        ),
        success_criteria=("每一步只处理当前段落窗口", "目标 DOCX 产生真实文本写回", "写回后进入等待确认状态", "续跑必须沿用同一 DOCX 和下一段落窗口"),
        quality_gates=(
            {
                "criterion": "stepwise_docx_polish_has_writeback",
                "operation": "rewrite_docx_paragraph_window",
                "metric": "paragraphs_rewritten",
                "minimum": 1,
                "priority": "critical",
                "detail": "分步 DOCX 润色每一步都必须写回段落；当前写回段落数：{actual}。",
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

    # Boost stepwise resume: if followup_context signals a stepwise continuation,
    # force the stepwise markers to be present
    options = request.options if isinstance(request.options, dict) else {}
    followup = options.get("followup_context") if isinstance(options.get("followup_context"), dict) else {}
    if followup.get("kind") == "stepwise_task_resume":
        markers["stepwise_confirmation_request"] = True
        markers["long_document_request"] = True
        markers["summary_request"] = True

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
