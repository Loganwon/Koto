from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.agent.file_task_prompt_sections import (
    followup_guidance as _prompt_followup_guidance,
)


@dataclass(frozen=True)
class FileTaskSystemPromptGuidance:
    followup_guidance: str = ""


def build_file_task_system_prompt_guidance(
    *,
    followup_context: dict[str, Any],
) -> FileTaskSystemPromptGuidance:
    return FileTaskSystemPromptGuidance(
        followup_guidance=_prompt_followup_guidance(followup_context),
    )
