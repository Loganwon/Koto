from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_recipes import FileTaskRecipeMatch, recipe_matches


@dataclass
class FileTaskClassificationRecipes:
    candidates: list[FileTaskRecipeMatch] = field(default_factory=list)
    selected: FileTaskRecipeMatch | None = None
    matched_capabilities: list[str] = field(default_factory=list)
    execution_mode: str = "generic_tool_loop"
    reason_codes: list[str] = field(default_factory=list)


def recipe_request_for_classification(
    *,
    classification_request: FileTaskRequest,
    classification_task: str,
    stepwise_pdf_docx_resume: bool,
) -> FileTaskRequest:
    if not stepwise_pdf_docx_resume:
        return classification_request

    return FileTaskRequest(
        task=(f"{classification_task}\n" "分步 长PDF DOCX 总结 每一步写入并等待确认"),
        run_id=classification_request.run_id,
        session_id=classification_request.session_id,
        files=classification_request.files,
        current_file=classification_request.current_file,
        selection=classification_request.selection,
        selection_source=classification_request.selection_source,
        target_path=classification_request.target_path,
        model_mode=classification_request.model_mode,
        model_id=classification_request.model_id,
        history=classification_request.history,
        options=classification_request.options,
        routing_decision=classification_request.routing_decision,
    )


def apply_recipe_classification(
    *,
    classification_request: FileTaskRequest,
    classification_task: str,
    files: Sequence[FileTaskFile],
    write_intent: bool,
    stepwise_pdf_docx_resume: bool,
    matched_capabilities: list[str],
    execution_mode: str,
    reason_codes: list[str],
) -> FileTaskClassificationRecipes:
    recipe_match_request = recipe_request_for_classification(
        classification_request=classification_request,
        classification_task=classification_task,
        stepwise_pdf_docx_resume=stepwise_pdf_docx_resume,
    )
    candidates = recipe_matches(recipe_match_request, files, write_intent=write_intent)
    selected = candidates[0] if candidates else None
    capabilities = list(matched_capabilities or [])
    reasons = list(reason_codes or [])
    resolved_execution_mode = execution_mode

    if selected:
        reasons.extend(selected.reason_codes)
        for capability in selected.recipe.matched_capabilities:
            if capability not in capabilities:
                capabilities.append(capability)
        if selected.recipe.execution_mode != "generic_tool_loop":
            resolved_execution_mode = selected.recipe.execution_mode
        if len(candidates) > 1:
            reasons.extend(
                f"recipe_candidate:{item.recipe.id}" for item in candidates[1:4]
            )

    return FileTaskClassificationRecipes(
        candidates=list(candidates),
        selected=selected,
        matched_capabilities=capabilities,
        execution_mode=resolved_execution_mode,
        reason_codes=reasons,
    )
