from __future__ import annotations

from typing import Any, Sequence

from app.core.agent.file_task_capability import build_request_capability_profiles
from app.core.agent.file_task_contract import (
    FileTaskClassification,
    FileTaskFile,
    FileTaskIntentPlan,
    FileTaskRequest,
)
from app.core.agent.file_task_followup_context import followup_context
from app.core.agent.file_task_messages import build_file_task_messages
from app.core.agent.file_task_whitebox import build_recipe_skeleton


def build_file_task_runtime_messages(
    *,
    request: FileTaskRequest,
    snippets: list[dict[str, Any]],
    files: Sequence[FileTaskFile],
    classification: FileTaskClassification,
    intent_plan: FileTaskIntentPlan,
    known_tool_gap: dict[str, Any] | None,
    recipe_skeleton: dict[str, Any] | None,
    execution_brief_schema: dict[str, Any],
) -> list[dict[str, Any]]:
    skeleton = recipe_skeleton or build_recipe_skeleton(
        request,
        list(files),
        classification,
        intent_plan,
        [],
    )
    return build_file_task_messages(
        request=request,
        snippets=snippets,
        files=list(files),
        classification=classification,
        intent_plan=intent_plan,
        known_tool_gap=known_tool_gap,
        capability_profiles=build_request_capability_profiles(request),
        followup_context=followup_context(request),
        recipe_skeleton=skeleton,
        execution_brief_schema=execution_brief_schema,
    )
