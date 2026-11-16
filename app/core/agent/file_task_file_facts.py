"""Structured file facts used by FileTaskRuntime safety contracts.

This module deliberately does not inspect free-form task text.  It only derives
facts from attached files and explicit target fields, leaving task semantics to
the Agent Kernel.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest


def file_type_from_file_info(file_info: FileTaskFile) -> str:
    explicit = str(getattr(file_info, "type", "") or "").strip().lower().lstrip(".")
    if explicit:
        return explicit
    candidate = str(
        getattr(file_info, "path", "") or getattr(file_info, "name", "") or ""
    )
    return Path(candidate).suffix.lower().lstrip(".")


def request_file_types(files: Sequence[FileTaskFile]) -> set[str]:
    file_types: set[str] = set()
    for file_info in files:
        file_type = file_type_from_file_info(file_info)
        if not file_type:
            continue
        file_types.add(file_type)
        if file_type == "xlsm":
            file_types.add("xlsx")
        elif file_type == "doc":
            file_types.add("docx")
    return file_types


def request_context_files(request: FileTaskRequest) -> list[FileTaskFile]:
    files: list[FileTaskFile] = []
    if isinstance(request.current_file, FileTaskFile):
        files.append(request.current_file)
    files.extend(
        file_info for file_info in request.files if isinstance(file_info, FileTaskFile)
    )
    return files


def request_has_file_type(request: FileTaskRequest, file_type: str) -> bool:
    normalized = str(file_type or "").strip().lower().lstrip(".")
    if normalized == "doc":
        normalized = "docx"
    if not normalized:
        return False

    target_type = Path(str(request.target_path or "")).suffix.lower().lstrip(".")
    if target_type == "doc":
        target_type = "docx"
    if target_type == normalized:
        return True
    return normalized in request_file_types(request_context_files(request))


def request_target_file_type(
    request: FileTaskRequest, files: Sequence[FileTaskFile]
) -> str:
    explicit_target = Path(str(request.target_path or "")).suffix.lstrip(".").lower()
    if explicit_target:
        return explicit_target
    for file_info in files:
        if file_info.target:
            return file_type_from_file_info(file_info)
    return ""


__all__ = [
    "file_type_from_file_info",
    "request_context_files",
    "request_file_types",
    "request_has_file_type",
    "request_target_file_type",
]
