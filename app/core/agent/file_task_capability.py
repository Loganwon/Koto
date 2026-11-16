from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.toolkits.foundation.catalog import (
    file_task_tool_specs,
    is_write_tool,
)

_NATIVE_SUPPORTED_FILE_TYPES: Set[str] = {
    file_type
    for spec in file_task_tool_specs()
    for file_type in spec.file_types
    if file_type
    and (
        spec.name != "read_file_range" or file_type in {"txt", "md", "markdown", "text"}
    )
}

_CAPABILITY_PROFILE_VERSION = "koto_file_capability_v1"
_DOCUMENT_FORMATS = {"docx", "pdf"}
_SPREADSHEET_FORMATS = {"xlsx", "xlsm", "csv"}
_PRESENTATION_FORMATS = {"pptx"}
_IMAGE_FORMATS = {"png", "jpg", "jpeg", "gif", "bmp", "webp", "svg", "image"}
_TEXT_FORMATS = {"txt", "md", "markdown", "text"}
_CODE_FORMATS = {
    "py",
    "js",
    "ts",
    "json",
    "html",
    "css",
    "xml",
    "sh",
    "bash",
    "yaml",
    "yml",
    "c",
    "cpp",
    "h",
    "hpp",
    "java",
    "rb",
    "go",
    "rs",
    "cs",
    "php",
    "swift",
    "kt",
    "r",
    "sql",
    "toml",
    "ini",
    "cfg",
    "conf",
    "code",
}
_AUDIO_FORMATS = {
    "mp3",
    "wav",
    "flac",
    "aac",
    "ogg",
    "m4a",
    "wma",
    "opus",
    "ape",
    "audio",
}
_VIDEO_FORMATS = {
    "mp4",
    "mov",
    "wmv",
    "avi",
    "m4v",
    "mkv",
    "flv",
    "webm",
    "asf",
    "mpg",
    "mpeg",
    "video",
}
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
_DERIVED_ONLY_WRITE_TOOLS = {"create_file", "copy_file"}


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

        profile = build_file_capability_profile(
            file_type=raw_type, path=raw_path, name=raw_name
        )
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
            target=bool(
                request.current_file.target
                or request.current_file.path == request.target_path
            ),
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
    if (
        family in {"document", "spreadsheet", "presentation", "text", "code"}
        or format_name == "pdf"
    ):
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
        tool_name
        for tool_name in write_tool_names
        if tool_name not in _DERIVED_ONLY_WRITE_TOOLS
    ]
    read_support = "native" if read_tool_names else "none"
    if file_specific_write_tools:
        if format_name == "pdf":
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

    if format_name == "docx" and "write_docx_comments" in tool_names:
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
        notes.append(
            "CSV 目前在 file-task 工具层可读写，但 workspace 直接打开仍未纳入主编辑器路径。"
        )
    if family == "image":
        notes.append(
            "图片 OCR 当前仍通过截图/剪贴板侧路能力提供，尚未统一接入文件任务主路径。"
        )
    if family in {"audio", "video"}:
        notes.append(
            "音视频目前更适合走元信息、转录或摘要能力，尚未纳入主文件编辑路径。"
        )
    return notes


def _primary_actions(
    workspace: Dict[str, Any], task: Dict[str, Any], ocr_mode: str
) -> List[str]:
    actions: List[str] = []
    if workspace.get("open_mode") != "unsupported":
        actions.append("preview")
    if workspace.get("edit_mode") == "native":
        actions.append("edit")
    if task.get("analysis_mode") not in {"none", "metadata_only", "sidecar_only"}:
        actions.append("analyze")
    if task.get("compare_support") == "native":
        actions.append("compare")
    if (
        task.get("annotation_support") != "none"
        or workspace.get("edit_mode") == "annotate_only"
    ):
        actions.append("annotate")
    if ocr_mode == "first_class":
        actions.append("ocr")
    if task.get("sandbox_support") == "available":
        actions.append("sandbox")
    return actions
