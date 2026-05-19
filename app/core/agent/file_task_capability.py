from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_tool_catalog import file_task_tool_specs, is_file_task_tool, is_write_tool
from app.core.agent.tool_design_protocol import (
    STANDARD_FILE_CHANGE_RETURNS,
    TOOL_DESIGN_PROTOCOL,
    build_tool_gap,
)


_NATIVE_SUPPORTED_FILE_TYPES: Set[str] = {
    file_type
    for spec in file_task_tool_specs()
    for file_type in spec.file_types
    if file_type and (spec.name != "read_file_range" or file_type in {"txt", "md", "markdown", "text"})
}

_PPTX_DESIGN_TASK_PATTERNS = (
    re.compile(r"(?:pptx?|幻灯片|演示文稿|slides?|presentation).{0,32}(?:风格|主题|主体|版式|母版|模板|美化|排版|配色|视觉|设计)", re.IGNORECASE),
    re.compile(r"(?:风格|主题|主体|版式|母版|模板|美化|排版|配色|视觉|设计).{0,32}(?:pptx?|幻灯片|演示文稿|slides?|presentation)", re.IGNORECASE),
    re.compile(r"\b(?:theme|layout|template|slide master|master slide|visual style|deck design|presentation design)\b", re.IGNORECASE),
)

_XLSX_TO_DOCX_TASK_PATTERNS = (
    re.compile(r"(?:excel|xlsx|表格|工作表).{0,24}(?:加入|插入|写入|计入|同步|导入).{0,24}(?:word|docx|文档)", re.IGNORECASE),
    re.compile(r"(?:word|docx|文档).{0,24}(?:加入|插入|写入|计入|同步|导入).{0,24}(?:excel|xlsx|表格|工作表)", re.IGNORECASE),
    re.compile(r"\b(?:excel|xlsx|spreadsheet|sheet).{0,32}\b(?:word|docx)\b", re.IGNORECASE),
    re.compile(r"\b(?:word|docx).{0,32}\b(?:excel|xlsx|spreadsheet|sheet)\b", re.IGNORECASE),
)

_CHART_TO_DOCX_TASK_PATTERNS = (
    re.compile(r"(?:图表|可视化|绘图|画图|画.{0,4}图|图片|chart|plot|graph|image).{0,32}(?:加入|插入|写入|放入|嵌入).{0,24}(?:word|docx|文档)", re.IGNORECASE),
    re.compile(r"(?:word|docx|文档).{0,24}(?:加入|插入|写入|放入|嵌入).{0,32}(?:图表|可视化|绘图|画图|画.{0,4}图|图片|chart|plot|graph|image)", re.IGNORECASE),
)

_CHART_TASK_PATTERNS = (
    re.compile(r"\b(?:chart|plot|graph|visuali[sz]e|dashboard)\b", re.IGNORECASE),
    re.compile(r"(?:图表|可视化|绘图|画图|画.{0,4}图|统计图|柱状图|折线图|饼图|仪表盘)", re.IGNORECASE),
)

_COMPARE_TASK_PATTERNS = (
    re.compile(r"\b(?:compare|comparison|diff|difference|merge review)\b", re.IGNORECASE),
    re.compile(r"(?:对比|比较|差异|不同点|相同点|比对)", re.IGNORECASE),
)

_ANNOTATE_TASK_PATTERNS = (
    re.compile(r"\b(?:annotate|annotation|comment|review note|markup)\b", re.IGNORECASE),
    re.compile(r"(?:批注|注释|评论|审阅意见|标注)", re.IGNORECASE),
)

_CLEAR_DOCX_REVIEW_TASK_PATTERNS = (
    re.compile(
        r"(?:删除|移除|去掉|清除|清空|取消|消除|remove|delete|clear).{0,12}(?:所有|全部|整篇|整个|全部的)?(?:.{0,8})?(?:批注|标注|评论|注释|评注|修订|审阅标记|修改痕迹|comments?|review marks?|tracked changes?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:所有|全部|整篇|整个)?(?:.{0,8})?(?:批注|标注|评论|注释|评注|修订|审阅标记|修改痕迹|comments?|review marks?|tracked changes?).{0,12}(?:删除|移除|去掉|清除|清空|取消|消除|remove|delete|clear)",
        re.IGNORECASE,
    ),
)

_PPTX_ADD_SLIDES_TASK_PATTERNS = (
    re.compile(r"(?:pptx?|slides?|幻灯片|演示文稿).{0,24}(?:新增|添加|补充|生成|插入).{0,12}(?:页|slide|slides?)", re.IGNORECASE),
    re.compile(r"(?:总结|概述|结论).{0,18}(?:新增|添加|补充).{0,12}(?:页|slide|slides?)", re.IGNORECASE),
)

_PPTX_UPDATE_SLIDES_TASK_PATTERNS = (
    re.compile(r"(?:pptx?|slides?|幻灯片|演示文稿).{0,24}(?:修改|更新|改写|替换|润色).{0,18}(?:内容|文字|文本|slide)", re.IGNORECASE),
    re.compile(r"(?:修改|更新|改写|替换|润色).{0,24}(?:pptx?|slides?|幻灯片|演示文稿)", re.IGNORECASE),
    re.compile(r"(?:pptx?|slides?|幻灯片|演示文稿).{0,24}(?:补充|充实|扩写|完善).{0,18}(?:内容|文字|文本|slide|页)", re.IGNORECASE),
    re.compile(r"(?:每一页|每页|逐页|各页).{0,24}(?:补充|充实|扩写|完善).{0,18}(?:内容|文字|文本)?", re.IGNORECASE),
)

_CAPABILITY_PROFILE_VERSION = "koto_file_capability_v1"
_DOCUMENT_FORMATS = {"docx", "pdf"}
_SPREADSHEET_FORMATS = {"xlsx", "xlsm", "csv"}
_PRESENTATION_FORMATS = {"pptx"}
_IMAGE_FORMATS = {"png", "jpg", "jpeg", "gif", "bmp", "webp", "svg", "image"}
_TEXT_FORMATS = {"txt", "md", "markdown", "text"}
_CODE_FORMATS = {
    "py", "js", "ts", "json", "html", "css", "xml", "sh", "bash", "yaml", "yml",
    "c", "cpp", "h", "hpp", "java", "rb", "go", "rs", "cs", "php", "swift",
    "kt", "r", "sql", "toml", "ini", "cfg", "conf", "code",
}
_AUDIO_FORMATS = {"mp3", "wav", "flac", "aac", "ogg", "m4a", "wma", "opus", "ape", "audio"}
_VIDEO_FORMATS = {"mp4", "mov", "wmv", "avi", "m4v", "mkv", "flv", "webm", "asf", "mpg", "mpeg", "video"}
_FORMAT_ALIASES = {
    "markdown": "md",
    "jpeg": "jpg",
}
_FORMAT_LABELS: Dict[str, str] = {
    "docx": "Word 文档",
    "pdf": "PDF 文档",
    "xlsx": "Excel 工作簿",
    "xlsm": "Excel 宏工作簿",
    "csv": "CSV 表格",
    "pptx": "PowerPoint 演示文稿",
    "txt": "文本文件",
    "md": "Markdown 文档",
    "json": "JSON 文件",
    "html": "HTML 文件",
    "png": "图片",
    "jpg": "图片",
    "image": "图片",
}
_DERIVED_ONLY_WRITE_TOOLS = {"create_file", "copy_file", "extract_to_file"}


@dataclass(frozen=True)
class NativeCapabilitySpec:
    name: str
    tool_name: str
    summary: str
    why_missing: str
    description: str
    rationale: str
    parameters: Dict[str, Any]
    all_file_types: tuple[str, ...] = ()
    any_file_types: tuple[str, ...] = ()
    task_patterns: tuple[re.Pattern[str], ...] = ()
    min_files: int = 0
    allow_without_files: bool = False


_NATIVE_CAPABILITY_MATRIX: tuple[NativeCapabilitySpec, ...] = (
    NativeCapabilitySpec(
        name="insert_image_into_docx",
        tool_name="insert_image_into_docx",
        summary="当前缺少把图表或图片真实插入 DOCX 的 Koto 原生工具。",
        why_missing="任务要求把可视化结果落回 Word；没有专门插图能力时，模型容易停留在生成图片或写一段描述文本，无法稳定完成真实写入。",
        description="把 PNG/JPG 等图片作为真实 Word 图片插入现有 DOCX，并返回标准 file-change payload。",
        rationale="用户要的是 DOCX 里的真实图表，而不是图片说明文字或单独导出的图片文件。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目标 Word/DOCX 文件路径"},
                "image_path": {"type": "string", "description": "来源图片路径"},
                "title": {"type": "string", "description": "可选图题"},
                "caption": {"type": "string", "description": "可选图注"},
                "width_inches": {"type": "number", "description": "可选插图宽度（英寸）"},
            },
            "required": ["path", "image_path"],
        },
        any_file_types=("docx",),
        task_patterns=_CHART_TO_DOCX_TASK_PATTERNS,
    ),
    NativeCapabilitySpec(
        name="insert_excel_as_docx_table",
        tool_name="insert_excel_as_docx_table",
        summary="当前缺少把 Excel/表格数据作为真实 Word 表格写入 DOCX 的 Koto 原生工具。",
        why_missing="任务需要跨文件读取表格并写回 DOCX；没有对应能力时，模型只能停留在读取或总结阶段，无法稳定完成真实写入。",
        description="把 Excel 工作表数据作为真实 Word 表格插入现有 DOCX，并返回标准 file-change payload。",
        rationale="用户要求的是把结构化表格真实写入 Word，而不是生成一段文本摘要。",
        parameters={
            "type": "object",
            "properties": {
                "source_path": {"type": "string", "description": "来源 Excel/XLSX 文件路径"},
                "target_path": {"type": "string", "description": "目标 Word/DOCX 文件路径"},
                "sheet_name": {"type": "string", "description": "可选工作表名"},
                "table_title": {"type": "string", "description": "可选表题"},
            },
            "required": ["source_path", "target_path"],
        },
        all_file_types=("docx", "xlsx"),
        task_patterns=_XLSX_TO_DOCX_TASK_PATTERNS,
    ),
    NativeCapabilitySpec(
        name="design_pptx_theme_layout",
        tool_name="design_pptx_theme_layout",
        summary="当前缺少能够为 PPTX 应用整体主题、母版、配色和版式的 Koto 原生工具。",
        why_missing="现有 PPTX 工具只覆盖读取文本、改写文本和新增幻灯片，不能稳定编辑主题、母版、版式、配色和整体视觉风格。",
        description="为现有 PPTX 套用统一主题、字体、配色、版式密度和基础形状样式，并返回标准 file-change payload。",
        rationale="用户要求的是整体视觉设计，不是文本内容编辑；需要一个格式感知的 PPTX 设计工具来真实写回文件。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目标 PPTX 文件路径"},
                "style_brief": {"type": "string", "description": "用户希望的视觉风格或业务场景"},
                "palette": {"type": "array", "items": {"type": "string"}, "description": "可选品牌色或主题色"},
                "density": {"type": "string", "description": "内容密度：compact / balanced / spacious"},
            },
            "required": ["path"],
        },
        all_file_types=("pptx",),
        task_patterns=_PPTX_DESIGN_TASK_PATTERNS,
    ),
    NativeCapabilitySpec(
        name="add_pptx_slides",
        tool_name="add_pptx_slides",
        summary="当前缺少在现有 PPTX 中新增总结页或补充页的 Koto 原生工具。",
        why_missing="任务要求在现有 PPTX 中追加新的页面结构；如果没有新增幻灯片能力，模型只能停留在建议文本，无法把结果真正写回文件。",
        description="在现有 PPTX 中新增标题页或标题+内容页，并返回标准 file-change payload。",
        rationale="用户要求补充新的幻灯片页面，而不是只改写现有页文本。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目标 PPTX 文件路径"},
                "slides": {"type": "array", "description": "新增幻灯片定义列表"},
            },
            "required": ["path", "slides"],
        },
        all_file_types=("pptx",),
        task_patterns=_PPTX_ADD_SLIDES_TASK_PATTERNS,
    ),
    NativeCapabilitySpec(
        name="write_pptx_slides",
        tool_name="write_pptx_slides",
        summary="当前缺少更新现有 PPTX 页面文本内容的 Koto 原生工具。",
        why_missing="任务要求改写现有页的文字内容；没有对应写入能力时，模型无法把改动落回现有幻灯片。",
        description="更新现有 PPTX 页面的标题和正文文本，并返回标准 file-change payload。",
        rationale="用户要的是修改现有页内容，不是新增页面或只输出建议文本。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目标 PPTX 文件路径"},
                "slides": {"type": "array", "description": "需要更新的幻灯片内容列表"},
            },
            "required": ["path", "slides"],
        },
        all_file_types=("pptx",),
        task_patterns=_PPTX_UPDATE_SLIDES_TASK_PATTERNS,
    ),
    NativeCapabilitySpec(
        name="compare_files",
        tool_name="compare_files",
        summary="当前缺少对多份文件进行结构化差异比较的 Koto 原生工具。",
        why_missing="任务要求读取并比较多份文件的内容、相同点与不同点；没有专门比较工具时，模型容易丢失差异结构或上下文对应。",
        description="对多份文件进行结构化比较，输出差异、相同点和重点结论。",
        rationale="用户需要的是跨文件对比视图，而不是逐个文件的独立总结。",
        parameters={
            "type": "object",
            "properties": {
                "file_paths": {"type": "array", "items": {"type": "string"}, "description": "待比较文件路径列表"},
                "aspect": {"type": "string", "description": "比较维度，如 content/structure/style"},
            },
            "required": ["file_paths"],
        },
        task_patterns=_COMPARE_TASK_PATTERNS,
        min_files=2,
    ),
    NativeCapabilitySpec(
        name="clear_docx_review_marks",
        tool_name="clear_docx_review_marks",
        summary="当前缺少清除 DOCX 批注和审阅标记的 Koto 原生工具。",
        why_missing="用户要求把 Word 文档里的批注或修订真正移除；没有专门清理能力时，模型会误走生成批注的路径，或只能停留在解释层。",
        description="清除 DOCX 里的批注，或按 scope 清除批注并接受修订，并返回标准 file-change payload。",
        rationale="用户要的是把现有审阅痕迹从 Word 文档里去掉，而不是再生成一轮新的批注。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目标 DOCX 文件路径"},
                "scope": {"type": "string", "description": "清理范围：comments / revisions / all；默认 comments"},
            },
            "required": ["path"],
        },
        any_file_types=("docx",),
        task_patterns=_CLEAR_DOCX_REVIEW_TASK_PATTERNS,
    ),
    NativeCapabilitySpec(
        name="annotate_file",
        tool_name="annotate_file",
        summary="当前缺少为文档添加结构化批注/标注的 Koto 原生工具。",
        why_missing="任务要求把审阅意见写回文档；没有批注能力时，模型只能生成独立文本，无法形成真实审阅结果。",
        description="在文档中按范围写入批注、标注或审阅意见，并返回标准 file-change payload。",
        rationale="用户需要真实的审阅批注，而不是外部文本说明。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目标文件路径"},
                "annotations": {"type": "array", "description": "批注范围和内容定义"},
            },
            "required": ["path", "annotations"],
        },
        any_file_types=("docx", "pdf", "txt", "md"),
        task_patterns=_ANNOTATE_TASK_PATTERNS,
    ),
    NativeCapabilitySpec(
        name="run_python_code",
        tool_name="run_python_code",
        summary="当前缺少用于复杂数据处理、图表生成和批量转换的 Koto 沙盒 Python 工具。",
        why_missing="任务要求通过代码做计算、可视化或批量处理；没有沙盒执行能力时，模型无法稳定完成真实数据处理和产物生成。",
        description="在 Koto 沙盒中运行 Python 代码处理数据、生成图表或派生文件，并返回标准 file-change payload/图像产物。",
        rationale="这类任务本质上依赖受控代码执行，而不是单轮文本生成。",
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "待执行的 Python 代码"},
                "timeout": {"type": "integer", "description": "超时时间（秒）"},
            },
            "required": ["code"],
        },
        task_patterns=_CHART_TASK_PATTERNS,
        allow_without_files=True,
    ),
)


def build_file_capability_profile(
    *,
    file_type: str = "",
    path: str = "",
    name: str = "",
) -> Dict[str, Any]:
    explicit_type = str(file_type or "").strip().lower().lstrip(".")
    format_name = _normalized_capability_format(explicit_type, path, name)
    family = _capability_family(format_name, explicit_type)
    tool_names = _capability_tool_names(format_name, family)
    write_tool_names = [
        tool_name
        for tool_name in tool_names
        if tool_name != "run_python_code" and is_write_tool(tool_name)
    ]
    workspace = _workspace_capability_surface(format_name, family)
    task = _task_capability_surface(format_name, family, tool_names, write_tool_names)
    ocr_mode = _ocr_mode(format_name, family)
    return {
        "version": _CAPABILITY_PROFILE_VERSION,
        "format": format_name,
        "family": family,
        "label": _capability_label(format_name, family),
        "workspace": workspace,
        "task": task,
        "ocr_mode": ocr_mode,
        "actions": _primary_actions(workspace, task, ocr_mode),
        "tool_names": tool_names,
        "write_tool_names": write_tool_names,
        "notes": _capability_notes(format_name, family),
    }


def build_request_capability_profiles(request: FileTaskRequest) -> List[Dict[str, Any]]:
    profiles: List[Dict[str, Any]] = []
    index_by_key: Dict[str, int] = {}

    def _upsert_profile(
        role: str,
        *,
        file_info: Optional[FileTaskFile] = None,
        path: str = "",
        name: str = "",
        file_type: str = "",
        target: bool = False,
    ) -> None:
        raw_path = str(path or (file_info.path if file_info else "") or "").strip()
        raw_name = str(name or (file_info.name if file_info else "") or "").strip()
        raw_type = str(file_type or (file_info.type if file_info else "") or "").strip()
        key = str(raw_path or raw_name or f"{raw_type}:{role}" or role).strip().lower()
        if not key:
            return
        if key in index_by_key:
            existing = profiles[index_by_key[key]]
            if role not in existing["roles"]:
                existing["roles"].append(role)
            existing["target"] = bool(existing.get("target") or target)
            return

        profile = build_file_capability_profile(file_type=raw_type, path=raw_path, name=raw_name)
        profile["path"] = raw_path
        profile["name"] = raw_name
        profile["roles"] = [role]
        profile["target"] = bool(target)
        profiles.append(profile)
        index_by_key[key] = len(profiles) - 1

    if request.current_file is not None:
        _upsert_profile(
            "current_file",
            file_info=request.current_file,
            target=bool(request.current_file.target or request.current_file.path == request.target_path),
        )

    for file_info in request.files:
        _upsert_profile(
            "file",
            file_info=file_info,
            target=bool(file_info.target or file_info.path == request.target_path),
        )

    if request.target_path:
        target_name = Path(str(request.target_path)).name
        _upsert_profile(
            "target_path",
            path=request.target_path,
            name=target_name,
            target=True,
        )

    return profiles


def native_tool_gap_for_request(request: FileTaskRequest) -> Optional[Dict[str, Any]]:
    """Return a known Koto-native capability gap for otherwise supported files."""
    for capability in matched_native_capability_specs(request):
        if _has_native_tool(capability.tool_name):
            continue
        return _build_native_tool_gap(capability)
    return None


def _has_native_tool(tool_name: str) -> bool:
    return is_file_task_tool(tool_name)


def matched_native_capability_specs(request: FileTaskRequest) -> List[NativeCapabilitySpec]:
    task_text = str(request.task or "").strip()
    file_types = _request_file_types(request)
    file_count = _request_file_count(request)
    matched: List[NativeCapabilitySpec] = []
    for capability in _NATIVE_CAPABILITY_MATRIX:
        if not _capability_matches_request(capability, task_text, file_types, file_count):
            continue
        matched.append(capability)
    return matched


def matched_native_capability_names(request: FileTaskRequest) -> List[str]:
    return [capability.name for capability in matched_native_capability_specs(request)]


def _capability_matches_request(
    capability: NativeCapabilitySpec,
    task_text: str,
    file_types: Set[str],
    file_count: int,
) -> bool:
    if capability.name == "annotate_file":
        from app.core.agent import file_task_doc_annotate_bridge

        if file_task_doc_annotate_bridge.looks_like_docx_review_clear_request(task_text):
            return False
    if capability.task_patterns and not any(pattern.search(task_text) for pattern in capability.task_patterns):
        return False
    if capability.all_file_types and not set(capability.all_file_types).issubset(file_types):
        return False
    if capability.any_file_types and not set(capability.any_file_types).intersection(file_types):
        return False
    if not capability.allow_without_files and not file_types:
        return False
    if capability.min_files and file_count < capability.min_files:
        return False
    return True


def _request_file_count(request: FileTaskRequest) -> int:
    count = len(request.files)
    if request.current_file is not None:
        count += 1
    if request.target_path and not _request_file_types(request):
        count += 1
    return count


def _build_native_tool_gap(capability: NativeCapabilitySpec) -> Dict[str, Any]:
    tool_gap = build_tool_gap(
        summary=capability.summary,
        missing_capability=capability.name,
        why_missing=capability.why_missing,
        suggested_next_step=(
            f"用 {TOOL_DESIGN_PROTOCOL} 生成最小工具规格，经实现、测试并加入 allowlist 后重新执行这个 {capability.name} 任务。"
        ),
        proposed_tool={
            "name": capability.tool_name,
            "description": capability.description,
            "parameters": capability.parameters,
            "returns": STANDARD_FILE_CHANGE_RETURNS,
            "rationale": capability.rationale,
            "implementation_notes": [
                "保持能力边界最小化，只实现当前任务真正缺失的原生能力。",
                "所有写入必须在 Koto 沙箱副本中完成，并返回标准 file.changed payload。",
            ],
            "safety_constraints": [
                "不得伪造已经写入或已经完成。",
                "失败时必须返回错误，不得静默降级为纯文本建议。",
            ],
            "acceptance_tests": [
                "工具执行后目标文件可以重新打开。",
                "运行结果必须产生标准 file.changed 事件。",
            ],
        },
    )
    assert tool_gap is not None
    return tool_gap


def _request_file_types(request: FileTaskRequest) -> Set[str]:
    file_types: Set[str] = set()
    if request.current_file is not None:
        file_types.update(_file_type_candidates(request.current_file))
    for file_info in request.files:
        file_types.update(_file_type_candidates(file_info))
    if request.target_path:
        suffix = Path(str(request.target_path)).suffix.lstrip(".").lower()
        if suffix:
            file_types.add(suffix)
    return file_types


def _file_type_candidates(file_info: FileTaskFile) -> Iterable[str]:
    if file_info.type:
        yield str(file_info.type).strip().lower().lstrip(".")
    if file_info.path:
        suffix = Path(str(file_info.path)).suffix.lstrip(".").lower()
        if suffix:
            yield suffix
    if file_info.name:
        suffix = Path(str(file_info.name)).suffix.lstrip(".").lower()
        if suffix:
            yield suffix


def _looks_like_pptx_design_task(task: str) -> bool:
    task_text = str(task or "").strip()
    if not task_text:
        return False
    return any(pattern.search(task_text) for pattern in _PPTX_DESIGN_TASK_PATTERNS)


def _normalized_capability_format(explicit_type: str, path: str, name: str) -> str:
    for candidate in (path, name):
        suffix = Path(str(candidate or "")).suffix.lstrip(".").lower()
        if suffix:
            return _FORMAT_ALIASES.get(suffix, suffix)
    if explicit_type:
        return _FORMAT_ALIASES.get(explicit_type, explicit_type)
    return "unknown"


def _capability_family(format_name: str, explicit_type: str) -> str:
    if format_name in _DOCUMENT_FORMATS:
        return "document"
    if format_name in _SPREADSHEET_FORMATS:
        return "spreadsheet"
    if format_name in _PRESENTATION_FORMATS:
        return "presentation"
    if format_name in _IMAGE_FORMATS or explicit_type == "image":
        return "image"
    if format_name in _TEXT_FORMATS or explicit_type == "text":
        return "text"
    if format_name in _CODE_FORMATS or explicit_type == "code":
        return "code"
    if format_name in _AUDIO_FORMATS or explicit_type == "audio":
        return "audio"
    if format_name in _VIDEO_FORMATS or explicit_type == "video":
        return "video"
    if explicit_type:
        return explicit_type
    return "unknown"


def _capability_label(format_name: str, family: str) -> str:
    if format_name in _FORMAT_LABELS:
        return _FORMAT_LABELS[format_name]
    family_labels = {
        "document": "文档",
        "spreadsheet": "表格",
        "presentation": "演示文稿",
        "text": "文本文件",
        "code": "代码文件",
        "image": "图片",
        "audio": "音频文件",
        "video": "视频文件",
        "unknown": "文件",
    }
    if format_name and format_name not in {"unknown", "text", "code", "image"}:
        return f"{format_name.upper()} 文件"
    return family_labels.get(family, "文件")


def _capability_tool_names(format_name: str, family: str) -> List[str]:
    names = {
        spec.name
        for spec in file_task_tool_specs()
        if spec.file_types and format_name in spec.file_types
    }
    if family in {"document", "spreadsheet", "presentation", "text", "code"} or format_name == "pdf":
        names.add("run_python_code")
    return sorted(names)


def _workspace_capability_surface(format_name: str, family: str) -> Dict[str, Any]:
    if format_name == "docx":
        return {
            "open_mode": "native",
            "edit_mode": "native",
            "selection_mode": "structured",
            "progressive_loading": True,
        }
    if format_name in {"xlsx", "xlsm"}:
        return {
            "open_mode": "native",
            "edit_mode": "native",
            "selection_mode": "structured",
            "progressive_loading": False,
        }
    if format_name == "csv":
        return {
            "open_mode": "unsupported",
            "edit_mode": "none",
            "selection_mode": "text",
            "progressive_loading": False,
        }
    if format_name == "pptx":
        return {
            "open_mode": "native",
            "edit_mode": "native",
            "selection_mode": "slide_text",
            "progressive_loading": False,
        }
    if format_name == "pdf":
        return {
            "open_mode": "native",
            "edit_mode": "annotate_only",
            "selection_mode": "page_text",
            "progressive_loading": False,
        }
    if family in {"text", "code"}:
        return {
            "open_mode": "native",
            "edit_mode": "native",
            "selection_mode": "text",
            "progressive_loading": False,
        }
    if family == "image":
        return {
            "open_mode": "native",
            "edit_mode": "none",
            "selection_mode": "none",
            "progressive_loading": False,
        }
    return {
        "open_mode": "unsupported",
        "edit_mode": "none",
        "selection_mode": "none",
        "progressive_loading": False,
    }


def _task_capability_surface(
    format_name: str,
    family: str,
    tool_names: Sequence[str],
    write_tool_names: Sequence[str],
) -> Dict[str, Any]:
    read_tool_names = [
        spec.name
        for spec in file_task_tool_specs()
        if spec.read_only and spec.file_types and format_name in spec.file_types
    ]
    file_specific_write_tools = [
        tool_name for tool_name in write_tool_names if tool_name not in _DERIVED_ONLY_WRITE_TOOLS
    ]
    read_support = "native" if read_tool_names else "none"
    if file_specific_write_tools:
        if format_name == "pdf" or set(file_specific_write_tools) == {"annotate_file"}:
            write_support = "best_effort"
        else:
            write_support = "native"
    elif write_tool_names:
        write_support = "derived_only"
    else:
        write_support = "none"

    if format_name == "pdf":
        analysis_mode = "native_with_ocr"
    elif read_support == "native":
        analysis_mode = "native"
    elif family == "image":
        analysis_mode = "sidecar_only"
    elif family in {"audio", "video"}:
        analysis_mode = "metadata_only"
    else:
        analysis_mode = "none"

    if format_name == "pdf" and "annotate_file" in tool_names:
        annotation_support = "best_effort"
    elif "annotate_file" in tool_names:
        annotation_support = "native"
    else:
        annotation_support = "none"

    return {
        "read_support": read_support,
        "analysis_mode": analysis_mode,
        "write_support": write_support,
        "compare_support": "native" if "compare_files" in tool_names else "none",
        "annotation_support": annotation_support,
        "sandbox_support": "available" if "run_python_code" in tool_names else "none",
    }


def _ocr_mode(format_name: str, family: str) -> str:
    if format_name == "pdf":
        return "fallback"
    if family == "image":
        return "auxiliary"
    return "none"


def _capability_notes(format_name: str, family: str) -> List[str]:
    notes: List[str] = []
    if format_name == "pdf":
        notes.append("扫描 PDF 仅在常规文本提取不足时触发 OCR 回退。")
    if format_name == "pptx":
        notes.append("含嵌入视频的 PPTX 当前会在打开前直接拒绝。")
    if format_name == "csv":
        notes.append("CSV 目前在 file-task 工具层可读写，但 workspace 直接打开仍未纳入主编辑器路径。")
    if family == "image":
        notes.append("图片 OCR 当前仍通过截图/剪贴板侧路能力提供，尚未统一接入文件任务主路径。")
    if family in {"audio", "video"}:
        notes.append("音视频目前更适合走元信息、转录或摘要能力，尚未纳入主文件编辑路径。")
    return notes


def _primary_actions(workspace: Dict[str, Any], task: Dict[str, Any], ocr_mode: str) -> List[str]:
    actions: List[str] = []
    if workspace.get("open_mode") != "unsupported":
        actions.append("preview")
    if workspace.get("edit_mode") == "native":
        actions.append("edit")
    if task.get("analysis_mode") not in {"none", "metadata_only", "sidecar_only"}:
        actions.append("analyze")
    if task.get("compare_support") == "native":
        actions.append("compare")
    if task.get("annotation_support") != "none" or workspace.get("edit_mode") == "annotate_only":
        actions.append("annotate")
    if ocr_mode == "first_class":
        actions.append("ocr")
    if task.get("sandbox_support") == "available":
        actions.append("sandbox")
    return actions