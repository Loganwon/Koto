from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from app.core.agent import file_task_doc_annotate_boundary
from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskRequest,
)


DocxAnnotationContractPredicate = Callable[
    [FileTaskRequest, Sequence[FileTaskFile], FileTaskClassification],
    bool,
]


@dataclass
class DocAnnotateBridgeFallback:
    classification: FileTaskClassification
    write_intent: bool = False


def apply_doc_annotate_bridge_fallback(
    *,
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    classification: FileTaskClassification,
    write_intent: bool,
    docx_annotation_has_contract: DocxAnnotationContractPredicate,
) -> DocAnnotateBridgeFallback:
    if classification.execution_mode == "doc_annotate_bridge":
        return DocAnnotateBridgeFallback(
            classification=classification,
            write_intent=write_intent,
        )
    if not file_task_doc_annotate_boundary.should_use_bridge_execution(request):
        return DocAnnotateBridgeFallback(
            classification=classification,
            write_intent=write_intent,
        )
    if not docx_annotation_has_contract(request, files, classification):
        return DocAnnotateBridgeFallback(
            classification=classification,
            write_intent=write_intent,
        )

    classification.execution_mode = "doc_annotate_bridge"
    classification.task_family = "annotate"
    classification.operation_kind = "annotate"
    classification.output_mode = "write"
    classification.write_intent = True
    classification.docx_annotation_request = True
    if "annotate_file" not in classification.matched_capabilities:
        classification.matched_capabilities.append("annotate_file")
    if "read_docx_content" not in classification.matched_capabilities:
        classification.matched_capabilities.append("read_docx_content")
    if not classification.selected_recipe:
        classification.selected_recipe = (
            file_task_doc_annotate_boundary.bridge_recipe_id(request)
        )
    classification.reason_codes.append("doc_annotate_bridge_execution_fallback")
    return DocAnnotateBridgeFallback(classification=classification, write_intent=True)
