"""EditorAIPipeline adapter for the document-agent hook registry."""

from __future__ import annotations

import logging

from app.core.agent.hooks import HookContext, HookPoint, HookRegistry

logger = logging.getLogger(__name__)


def register_pipeline_hooks(registry: HookRegistry) -> None:
    """Register preprocessing and postprocessing hooks for document requests."""
    registry.register(
        "editor_pipeline_preprocess",
        HookPoint.BEFORE_PROMPT_BUILD,
        _preprocess_hook,
        priority=50,
    )
    registry.register(
        "editor_pipeline_postprocess",
        HookPoint.BEFORE_REPLY,
        _postprocess_hook,
        priority=50,
    )


def _preprocess_hook(ctx: HookContext) -> None:
    try:
        from app.core.editor_ai_pipeline import EditorAIPipeline
    except ImportError:
        logger.debug("EditorAIPipeline unavailable; skipping preprocess hook")
        return

    request = ctx.request
    if request is None:
        return

    prompt = ctx.metadata.get("prompt", "")
    system_instruction = ctx.metadata.get("system_instruction", "")
    history = ctx.metadata.get("history", [])
    try:
        result = EditorAIPipeline.preprocess(
            prompt=prompt,
            history=history,
            file_type=getattr(request, "file_type", ""),
            output_mode=getattr(request, "output_mode", "edit"),
            base_system_instruction=system_instruction,
            user_input_raw=getattr(request, "prompt", prompt),
        )
    except Exception as exc:
        logger.debug("Editor pipeline preprocess failed: %s", exc)
        _fallback_preprocess(ctx)
        return

    ctx.metadata["system_instruction"] = result.system_instruction
    ctx.metadata["prompt"] = result.safe_prompt
    ctx.metadata["skill_ids"] = result.skill_ids
    ctx.metadata["mask_result"] = result.mask_result
    ctx.metadata["force_local"] = result.force_local


def _fallback_preprocess(ctx: HookContext) -> None:
    request = ctx.request
    prompt = ctx.metadata.get("prompt", "")
    system_instruction = ctx.metadata.get("system_instruction", "")
    history = ctx.metadata.get("history", [])
    raw_prompt = getattr(request, "prompt", prompt) if request else prompt
    output_mode = getattr(request, "output_mode", "") if request else ""

    try:
        from app.core.app_context import ctx as app_context

        memory_manager = app_context.memory_manager
        if memory_manager is not None:
            memory_context = memory_manager.get_context_string(
                raw_prompt,
                history=history,
            )
            if memory_context:
                ctx.metadata["system_instruction"] = (
                    f"{memory_context}\n\n{system_instruction}"
                )
    except Exception as exc:
        logger.debug("Memory fallback injection skipped: %s", exc)

    try:
        from app.core.skills.skill_auto_matcher import SkillAutoMatcher
        from app.core.skills.skill_manager import SkillManager

        task_type = "CHAT" if output_mode == "chat" else "FILE_GEN"
        skill_ids = SkillAutoMatcher.match(raw_prompt, task_type=task_type)
        ctx.metadata["system_instruction"] = SkillManager.inject_into_prompt(
            ctx.metadata.get("system_instruction", system_instruction),
            task_type=task_type,
            user_input=raw_prompt,
            temp_skill_ids=skill_ids,
        )
        ctx.metadata["skill_ids"] = skill_ids
    except Exception as exc:
        logger.debug("Skill fallback injection skipped: %s", exc)


def _postprocess_hook(ctx: HookContext) -> None:
    try:
        from app.core.editor_ai_pipeline import EditorAIPipeline
    except ImportError:
        return

    try:
        result = EditorAIPipeline.postprocess(
            response_text=ctx.reply_text,
            mask_result=ctx.metadata.get("mask_result"),
            skill_ids=ctx.metadata.get("skill_ids", []),
            user_prompt=ctx.metadata.get("raw_prompt", ""),
            file_type=ctx.metadata.get("file_type", ""),
        )
    except Exception as exc:
        logger.debug("Editor pipeline postprocess failed: %s", exc)
        return

    ctx.reply_text = result.text
    ctx.metadata["suggestions"] = result.suggestions
    ctx.metadata["validation_action"] = result.validation_action
