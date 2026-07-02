from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.core.agent.file_task_capability import build_request_capability_profiles
from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_tool_catalog import supported_file_workflows


@dataclass(frozen=True)
class FileTaskSystemPromptPayload:
    file_list: str = "none"
    capability_text: str = ""
    known_gap_text: str = ""
    workflows: str = ""


def build_file_task_system_prompt_payload(
    *,
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    known_tool_gap: Mapping[str, Any] | None,
) -> FileTaskSystemPromptPayload:
    capability_profiles = build_request_capability_profiles(request)
    return FileTaskSystemPromptPayload(
        file_list=explicit_file_list(files),
        capability_text=capability_profiles_text(capability_profiles),
        known_gap_text=known_tool_gap_text(known_tool_gap),
        workflows=json.dumps(
            supported_file_workflows(),
            ensure_ascii=False,
            indent=2,
        ),
    )


def explicit_file_list(files: Sequence[FileTaskFile]) -> str:
    return (
        ", ".join(
            (file_info.path or file_info.name)
            for file_info in files
            if file_info.path or file_info.name
        )
        or "none"
    )


def capability_profiles_text(capability_profiles: Sequence[Mapping[str, Any]]) -> str:
    if not capability_profiles:
        return ""
    return "文件能力概览：" + json.dumps(
        list(capability_profiles),
        ensure_ascii=False,
    ) + "\n"


def known_tool_gap_text(known_tool_gap: Mapping[str, Any] | None) -> str:
    if not known_tool_gap:
        return ""
    return (
        "\n已知原生工具缺口：\n"
        + json.dumps(dict(known_tool_gap), ensure_ascii=False, indent=2)
        + "\n"
    )
