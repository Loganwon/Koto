from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

from app.core.agent.file_task_classification_flow import (
    FileTaskClassificationFlow,
    build_classification_flow,
)
from app.core.agent.file_task_classification_signals import (
    DocxRequestPredicate,
    FileTaskClassificationSignals,
    build_classification_signals,
)
from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest

DiagnosticPredicate = Callable[[str], bool]


@dataclass
class FileTaskClassificationPipelineState:
    classification_task: str = ""
    classification_request: FileTaskRequest | None = None
    signals: FileTaskClassificationSignals = field(
        default_factory=FileTaskClassificationSignals
    )
    flow: FileTaskClassificationFlow = field(default_factory=FileTaskClassificationFlow)
    planner_policy: str = ""
    planner_reason: str = ""
    planner_backend: str = ""
    diagnostic_request: bool = False


def build_classification_pipeline_state(
    *,
    classification_task: str,
    classification_request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    followup_context: Mapping[str, object],
    resume_control: Mapping[str, object],
    planner_policy: str,
    planner_reason: str,
    planner_backend: str,
    is_docx_annotation_request: DocxRequestPredicate,
    is_docx_clear_review_request: DocxRequestPredicate,
    is_diagnostic_request: DiagnosticPredicate,
) -> FileTaskClassificationPipelineState:
    signals = build_classification_signals(
        classification_task=classification_task,
        classification_request=classification_request,
        files=files,
        is_docx_annotation_request=is_docx_annotation_request,
        is_docx_clear_review_request=is_docx_clear_review_request,
    )
    flow = build_classification_flow(
        followup_context=followup_context,
        resume_control=resume_control,
        semantic=signals.semantic,
        file_types=signals.file_types,
        target_file_type=signals.target_file_type,
    )
    return FileTaskClassificationPipelineState(
        classification_task=classification_task,
        classification_request=classification_request,
        signals=signals,
        flow=flow,
        planner_policy=planner_policy,
        planner_reason=planner_reason,
        planner_backend=planner_backend,
        diagnostic_request=is_diagnostic_request(classification_task),
    )
