from __future__ import annotations

from pathlib import Path
from typing import Sequence

from app.core.agent.file_task_capability import build_request_capability_profiles
from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskRequest,
)


def classification_file_types(request: FileTaskRequest) -> list[str]:
    return sorted(
        {
            str(profile.get("format") or "").strip().lower()
            for profile in build_request_capability_profiles(request)
            if str(profile.get("format") or "").strip()
        }
    )


def classification_target_file_type(
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
) -> str:
    from app.core.agent.file_task_file_facts import request_target_file_type

    return request_target_file_type(request, files)


def classification_confidence(
    *,
    diagnostic_request: bool,
    raw_write_signal: bool,
) -> float:
    if diagnostic_request:
        return 0.7 if raw_write_signal else 0.9
    return 1.0


def build_final_classification(
    *,
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    request_kind: str,
    task_family: str,
    operation_kind: str,
    execution_mode: str,
    output_mode: str,
    write_authorized: bool,
    write_required: bool,
    diagnostic_request: bool,
    raw_write_signal: bool,
    planner_policy: str,
    planner_reason: str,
    planner_backend: str,
    known_gap_name: str,
    reason_codes: list[str],
) -> FileTaskClassification:
    return FileTaskClassification(
        request_kind=request_kind,
        task_family=task_family,
        operation_kind=operation_kind,
        execution_mode=execution_mode,
        output_mode=output_mode,
        write_authorized=write_authorized,
        write_required=write_required,
        diagnostic_request=diagnostic_request,
        planner_policy=planner_policy,
        planner_reason=planner_reason,
        planner_backend=planner_backend,
        target_file_type=classification_target_file_type(request, files),
        known_native_tool_gap=known_gap_name,
        file_types=classification_file_types(request),
        reason_codes=reason_codes,
        selected_recipe="",
        recipe_candidates=[],
        confidence=classification_confidence(
            diagnostic_request=diagnostic_request,
            raw_write_signal=raw_write_signal,
        ),
    )
