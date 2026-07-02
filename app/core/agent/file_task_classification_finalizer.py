from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence

from app.core.agent.file_task_capability import build_request_capability_profiles
from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskRequest,
)


OutputModeResolver = Callable[
    [
        FileTaskRequest,
        Sequence[FileTaskFile],
    ],
    str,
]


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
    target_file_type = Path(str(request.target_path or "")).suffix.lstrip(".").lower()
    if target_file_type:
        return target_file_type
    for file_info in files:
        if not file_info.target:
            continue
        target_file_type = (
            file_info.type or Path(file_info.path or file_info.name).suffix.lstrip(".")
        ).lower()
        if target_file_type:
            return target_file_type
    return ""


def classification_confidence(
    *,
    diagnostic_request: bool,
    raw_write_intent: bool,
    raw_docx_annotation_request: bool,
) -> float:
    if diagnostic_request:
        return 0.7 if (raw_write_intent or raw_docx_annotation_request) else 0.9
    return 1.0


def build_final_classification(
    *,
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    output_mode_resolver: OutputModeResolver,
    request_kind: str,
    task_family: str,
    operation_kind: str,
    execution_mode: str,
    write_intent: bool,
    diagnostic_request: bool,
    docx_annotation_request: bool,
    advisory_analysis_request: bool,
    readonly_write_negation: bool,
    raw_write_intent: bool,
    raw_docx_annotation_request: bool,
    planner_policy: str,
    planner_reason: str,
    planner_backend: str,
    known_gap_name: str,
    matched_capabilities: list[str],
    reason_codes: list[str],
    selected_recipe_match: Any,
    recipe_candidates: Sequence[Any],
) -> FileTaskClassification:
    output_mode = output_mode_resolver(request, files)
    if readonly_write_negation:
        output_mode = "answer"

    return FileTaskClassification(
        request_kind=request_kind,
        task_family=task_family,
        operation_kind=operation_kind,
        execution_mode=execution_mode,
        output_mode=output_mode,
        write_intent=write_intent,
        diagnostic_request=diagnostic_request,
        docx_annotation_request=docx_annotation_request,
        planner_policy=planner_policy,
        planner_reason=planner_reason,
        planner_backend=planner_backend,
        target_file_type=classification_target_file_type(request, files),
        known_native_tool_gap=known_gap_name,
        file_types=classification_file_types(request),
        matched_capabilities=matched_capabilities,
        reason_codes=reason_codes,
        selected_recipe=(
            selected_recipe_match.recipe.id if selected_recipe_match else ""
        ),
        recipe_candidates=[item.public_dict() for item in recipe_candidates[:5]],
        confidence=classification_confidence(
            diagnostic_request=diagnostic_request,
            raw_write_intent=raw_write_intent,
            raw_docx_annotation_request=raw_docx_annotation_request,
        ),
    )
