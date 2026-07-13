from __future__ import annotations

from typing import Any, Callable, Sequence

from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskRequest,
)
from app.core.agent.file_task_followup_context import followup_context
from app.core.agent.file_task_system_prompt import build_file_task_system_prompt
from app.core.agent.file_task_system_prompt_guidance import (
    build_file_task_system_prompt_guidance,
)
from app.core.agent.file_task_system_prompt_payload import (
    build_file_task_system_prompt_payload,
)
from app.core.agent.file_task_whitebox import build_recipe_skeleton


def build_file_task_runtime_system_prompt(
    *,
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    classification: FileTaskClassification,
    intent_plan: FileTaskIntentPlan,
    known_tool_gap: dict[str, Any] | None,
    recipe_skeleton: dict[str, Any] | None,
    execution_brief_schema: dict[str, Any],
    output_mode_guidance: Callable[[FileTaskClassification], str],
    intent_plan_guidance: Callable[[FileTaskIntentPlan], str],
    financial_chart_docx_enabled: bool,
    display_path: Callable[[Any], str],
    first_file_name: Callable[..., str],
    current_date: str,
) -> str:
    file_list = list(files)
    skeleton = recipe_skeleton or build_recipe_skeleton(
        request,
        file_list,
        classification,
        intent_plan,
        [],
    )
    prompt_payload = build_file_task_system_prompt_payload(
        request=request,
        files=file_list,
        known_tool_gap=known_tool_gap,
    )
    prompt_guidance = build_file_task_system_prompt_guidance(
        request=request,
        files=file_list,
        classification=classification,
        followup_context=followup_context(request),
        financial_chart_docx_enabled=financial_chart_docx_enabled,
        display_path=display_path,
        first_file_name=first_file_name,
    )
    return build_file_task_system_prompt(
        output_mode_guidance=output_mode_guidance(classification),
        intent_plan_guidance=intent_plan_guidance(intent_plan),
        followup_guidance=prompt_guidance.followup_guidance,
        financial_chart_docx_guidance=prompt_guidance.financial_chart_docx_guidance,
        docx_compare_annotate_guidance=prompt_guidance.docx_compare_annotate_guidance,
        clear_docx_review_guidance=prompt_guidance.clear_docx_review_guidance,
        single_docx_annotate_guidance=prompt_guidance.single_docx_annotate_guidance,
        execution_brief_schema=execution_brief_schema,
        recipe_skeleton=skeleton,
        file_list=prompt_payload.file_list,
        target_path=request.target_path,
        capability_text=prompt_payload.capability_text,
        known_gap_text=prompt_payload.known_gap_text,
        workflows=prompt_payload.workflows,
        current_date=current_date,
    )
