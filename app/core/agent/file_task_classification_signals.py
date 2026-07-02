from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

from app.core.agent.file_task_capability import matched_native_capability_names
from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_intent_predicates import (
    has_explicit_write_intent,
    has_readonly_write_negation,
    has_write_intent,
    is_advisory_analysis_request,
)
from app.core.agent.file_task_recipes import (
    request_file_types,
    request_target_file_type,
    semantic_markers,
)


DocxRequestPredicate = Callable[[FileTaskRequest], bool]


@dataclass
class FileTaskClassificationSignals:
    matched_capabilities: list[str] = field(default_factory=list)
    advisory_analysis_request: bool = False
    readonly_write_negation: bool = False
    raw_write_intent: bool = False
    write_intent: bool = False
    raw_docx_annotation_request: bool = False
    docx_annotation_request: bool = False
    clear_docx_review_request: bool = False
    docx_compare_annotate_request: bool = False
    semantic: Mapping[str, bool] = field(default_factory=dict)
    file_types: set[str] = field(default_factory=set)
    target_file_type: str = ""
    chart_request: bool = False
    table_request: bool = False
    summary_request: bool = False
    translation_request: bool = False
    polish_request: bool = False
    financial_request: bool = False
    ppt_slide_write_request: bool = False
    ppt_design_request: bool = False
    docx_report_request: bool = False


def build_classification_signals(
    *,
    classification_task: str,
    classification_request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    is_docx_annotation_request: DocxRequestPredicate,
    is_docx_clear_review_request: DocxRequestPredicate,
) -> FileTaskClassificationSignals:
    matched_capabilities = matched_native_capability_names(classification_request)
    advisory_analysis_request = is_advisory_analysis_request(classification_task)
    readonly_write_negation = has_readonly_write_negation(classification_task)
    raw_write_intent = has_explicit_write_intent(classification_task)
    write_intent = has_write_intent(classification_task)
    raw_docx_annotation_request = is_docx_annotation_request(classification_request)
    docx_annotation_request = raw_docx_annotation_request
    clear_docx_review_request = is_docx_clear_review_request(classification_request)
    docx_compare_annotate_request = (
        "compare_docx_and_annotate" in matched_capabilities
    )
    if docx_compare_annotate_request:
        matched_capabilities = [
            name for name in matched_capabilities if name != "annotate_file"
        ]
        docx_annotation_request = False
        raw_docx_annotation_request = False

    file_types = request_file_types(files)
    target_file_type = request_target_file_type(classification_request, files)
    semantic = semantic_markers(
        classification_task,
        file_types=file_types,
        target_file_type=target_file_type,
    )
    if clear_docx_review_request:
        matched_capabilities = [
            name for name in matched_capabilities if name != "annotate_file"
        ]

    return FileTaskClassificationSignals(
        matched_capabilities=matched_capabilities,
        advisory_analysis_request=advisory_analysis_request,
        readonly_write_negation=readonly_write_negation,
        raw_write_intent=raw_write_intent,
        write_intent=write_intent,
        raw_docx_annotation_request=raw_docx_annotation_request,
        docx_annotation_request=docx_annotation_request,
        clear_docx_review_request=clear_docx_review_request,
        docx_compare_annotate_request=docx_compare_annotate_request,
        semantic=semantic,
        file_types=file_types,
        target_file_type=target_file_type,
        chart_request=bool(semantic.get("chart_request", False)),
        table_request=bool(semantic.get("table_request", False)),
        summary_request=bool(semantic.get("summary_request", False)),
        translation_request=bool(semantic.get("translation_request", False)),
        polish_request=bool(semantic.get("polish_request", False)),
        financial_request=bool(semantic.get("financial_request", False)),
        ppt_slide_write_request=bool(
            semantic.get("ppt_slide_write_request", False)
        ),
        ppt_design_request=bool(semantic.get("ppt_design_request", False)),
        docx_report_request=bool(semantic.get("docx_report_request", False)),
    )
