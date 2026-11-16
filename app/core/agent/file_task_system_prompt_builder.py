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
from app.core.agent.kernel import build_tool_usage_instruction


def build_file_task_runtime_system_prompt(
    *,
    request: FileTaskRequest,
    files: Sequence[FileTaskFile],
    classification: FileTaskClassification,
    intent_plan: FileTaskIntentPlan,
    known_tool_gap: dict[str, Any] | None,
    recipe_skeleton: dict[str, Any] | None,
    output_mode_guidance: Callable[[FileTaskClassification], str],
    intent_plan_guidance: Callable[[FileTaskIntentPlan], str],
    current_date: str,
    tool_definitions: Sequence[dict[str, Any]] | None = None,
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
        followup_context=followup_context(request),
    )
    prompt = build_file_task_system_prompt(
        output_mode_guidance=output_mode_guidance(classification),
        intent_plan_guidance=intent_plan_guidance(intent_plan),
        followup_guidance=prompt_guidance.followup_guidance,
        recipe_skeleton=skeleton,
        file_list=prompt_payload.file_list,
        target_path=request.target_path,
        capability_text=prompt_payload.capability_text,
        known_gap_text=prompt_payload.known_gap_text,
        workflows=prompt_payload.workflows,
        current_date=current_date,
    )
    if tool_definitions is not None:
        prompt = f"{prompt}\n\n{build_tool_usage_instruction(tool_definitions)}"
    return prompt
