# ══════════════════════════════════════════════════════════════
# pipeline_hooks.py — EditorAIPipeline ↔ Hook System Adapter
#
# Bridges the existing EditorAIPipeline (preprocess/postprocess)
# into the hook registry so KotoAgentLoop can use hooks
# instead of hard-calling the pipeline.
#
# This adapter preserves 100% backward compatibility:
# the pipeline logic is untouched, only the call site changes.
# ══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from typing import Any

from app.core.agent.hooks import HookContext, HookPoint, HookRegistry

logger = logging.getLogger(__name__)


def register_pipeline_hooks(registry: HookRegistry) -> None:
    """
    Register EditorAIPipeline as hooks on the given registry.

    - BEFORE_PROMPT_BUILD (priority 50): runs EditorAIPipeline.preprocess()
    - BEFORE_REPLY (priority 50): runs EditorAIPipeline.postprocess()

    Priority 50 so user-registered hooks at default (100) run after.
    """
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
    logger.debug("[PipelineHooks] Registered EditorAIPipeline hooks")


def _preprocess_hook(ctx: HookContext) -> None:
    """
    BEFORE_PROMPT_BUILD hook.

    Reads from ctx.metadata:
        system_instruction, prompt, history
    Reads from ctx.request:
        file_type, output_mode, prompt (raw)

    Writes to ctx.metadata:
        system_instruction, prompt, skill_ids, mask_result, force_local
    """
    try:
        from app.core.editor_ai_pipeline import EditorAIPipeline
    except ImportError:
        logger.debug("[PipelineHooks] EditorAIPipeline not available, skipping preprocess")
        return

    request = ctx.request
    if request is None:
        return

    prompt = ctx.metadata.get("prompt", "")
    system = ctx.metadata.get("system_instruction", "")
    history = ctx.metadata.get("history", [])

    try:
        result = EditorAIPipeline.preprocess(
            prompt=prompt,
            history=history,
            file_type=getattr(request, "file_type", ""),
            output_mode=getattr(request, "output_mode", "edit"),
            base_system_instruction=system,
            user_input_raw=getattr(request, "prompt", prompt),
        )
        ctx.metadata["system_instruction"] = result.system_instruction
        ctx.metadata["prompt"] = result.safe_prompt
        ctx.metadata["skill_ids"] = result.skill_ids
        ctx.metadata["mask_result"] = result.mask_result
        ctx.metadata["force_local"] = result.force_local
    except Exception as e:
        logger.debug("[PipelineHooks] preprocess failed: %s", e)
        # Fallback: legacy inline memory + skill injection
        _fallback_preprocess(ctx)


def _fallback_preprocess(ctx: HookContext) -> None:
    """Legacy fallback when EditorAIPipeline.preprocess fails."""
    request = ctx.request
    prompt = ctx.metadata.get("prompt", "")
    system = ctx.metadata.get("system_instruction", "")
    history = ctx.metadata.get("history", [])
    raw_prompt = getattr(request, "prompt", prompt) if request else prompt
    output_mode = getattr(request, "output_mode", "") if request else ""

    # Memory injection
    try:
        from app.core.app_context import ctx as _app_ctx
        mem_mgr = _app_ctx.memory_manager
        if mem_mgr is not None:
            mem_ctx = mem_mgr.get_context_string(raw_prompt, history=history)
            if mem_ctx:
                ctx.metadata["system_instruction"] = f"{mem_ctx}\n\n{system}"
    except Exception as e:
        logger.debug("[PipelineHooks] Memory injection fallback skipped: %s", e)

    # Skill injection
    try:
        from app.core.skills.skill_auto_matcher import SkillAutoMatcher
        from app.core.skills.skill_manager import SkillManager
        task_type = "CHAT" if output_mode == "chat" else "FILE_GEN"
        temp_ids = SkillAutoMatcher.match(raw_prompt, task_type=task_type)
        system_inst = ctx.metadata.get("system_instruction", system)
        ctx.metadata["system_instruction"] = SkillManager.inject_into_prompt(
            system_inst, task_type=task_type,
            user_input=raw_prompt, temp_skill_ids=temp_ids,
        )
        ctx.metadata["skill_ids"] = temp_ids
    except Exception as e:
        logger.debug("[PipelineHooks] Skill injection fallback skipped: %s", e)


def _postprocess_hook(ctx: HookContext) -> None:
    """
    BEFORE_REPLY hook.

    Reads from ctx:
        reply_text
    Reads from ctx.metadata:
        mask_result, skill_ids, raw_prompt, file_type

    Writes to ctx:
        reply_text
    Writes to ctx.metadata:
        suggestions, validation_action
    """
    try:
        from app.core.editor_ai_pipeline import EditorAIPipeline
    except ImportError:
        return

    mask_result = ctx.metadata.get("mask_result")
    skill_ids = ctx.metadata.get("skill_ids", [])
    raw_prompt = ctx.metadata.get("raw_prompt", "")
    file_type = ctx.metadata.get("file_type", "")

    try:
        result = EditorAIPipeline.postprocess(
            response_text=ctx.reply_text,
            mask_result=mask_result,
            skill_ids=skill_ids,
            user_prompt=raw_prompt,
            file_type=file_type,
        )
        ctx.reply_text = result.text
        ctx.metadata["suggestions"] = result.suggestions
        ctx.metadata["validation_action"] = result.validation_action
    except Exception as e:
        logger.debug("[PipelineHooks] postprocess failed: %s", e)
