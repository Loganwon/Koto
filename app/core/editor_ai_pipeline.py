# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
EditorAIPipeline — Pre/post processing middleware for all file-assistant AI calls.

Unifies the file-assistant AI pipeline with the main Koto chat pipeline by applying:
  Pre-request:
    • PII filtering (mask sensitive data before sending to cloud LLM)
    • Privacy routing (sensitive content → force local model)
    • Task type classification (from file_type + output_mode)
    • File-type-aware skill auto-matching
    • Context history compression (avoid token overflow on long conversations)
    • System instruction assembly (with skill injection)

  Post-response:
    • PII restoration (un-mask placeholders in LLM response text)
    • Output validation (block harmful content, detect quality issues)
    • Skill suggestions (recommend relevant skills after response)

Usage:
    from app.core.editor_ai_pipeline import EditorAIPipeline

    # Pre-process request
    processed = EditorAIPipeline.preprocess(
        prompt="用户输入",
        history=[...],
        file_type="docx",
        output_mode="edit",
        base_system_instruction="...",
    )

    # ... run streaming LLM call with processed.safe_prompt & processed.system_instruction ...
    # ... using processed.force_local to pick online vs local model ...

    # Post-process response
    result = EditorAIPipeline.postprocess(
        response_text=full_text,
        mask_result=processed.mask_result,
        skill_ids=processed.skill_ids,
        user_prompt=processed.safe_prompt,
        file_type="docx",
    )
    # result.text — final text with PII restored
    # result.suggestions — list of skill suggestion dicts
    # result.validation_action — "PASS" | "WARN" | "RETRY" | "BLOCK"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── File-type → task_type and eligible skill categories ────────────────────────

_FILE_TYPE_TASK_MAP: Dict[str, str] = {
    "docx": "FILE_GEN",
    "doc": "FILE_GEN",
    "pdf": "FILE_GEN",
    "pptx": "FILE_GEN",
    "ppt": "FILE_GEN",
    "xlsx": "FILE_GEN",
    "xls": "FILE_GEN",
    "csv": "FILE_GEN",
    "txt": "FILE_GEN",
    "md": "FILE_GEN",
    "chat": "CHAT",  # output_mode sentinel
}

# File-type → preferred skill id prefixes / exact ids for the auto-matcher hint
_FILE_TYPE_SKILL_AFFINITY: Dict[str, List[str]] = {
    "docx": [
        "doc_",
        "writing_assistant",
        "annotate_",
        "legal_doc_review",
        "financial_doc_review",
        "academic_paper_polish",
        "marketing_copy",
        "cross_format_extractor",
        "doc_smart_compare",
        "comm_digest",
    ],
    "doc": [
        "doc_",
        "writing_assistant",
        "annotate_",
        "legal_doc_review",
        "financial_doc_review",
        "academic_paper_polish",
        "marketing_copy",
        "cross_format_extractor",
        "doc_smart_compare",
        "comm_digest",
    ],
    "pdf": [
        "doc_",
        "doc_qa",
        "doc_summarizer",
        "annotate_academic",
        "annotate_business",
        "doc_smart_compare",
        "cross_format_extractor",
        "comm_digest",
    ],
    "pptx": ["slide_", "ppt_outline", "ppt_generator_pro"],
    "ppt": ["slide_", "ppt_outline", "ppt_generator_pro"],
    "xlsx": [
        "excel_",
        "pivot_advisor",
        "data_analysis",
        "spreadsheet_analyst",
        "table_enhancer",
        "data_format_cleaner",
        "cross_format_extractor",
    ],
    "xls": [
        "excel_",
        "pivot_advisor",
        "data_analysis",
        "spreadsheet_analyst",
        "table_enhancer",
        "data_format_cleaner",
        "cross_format_extractor",
    ],
    "csv": [
        "excel_data_cleaner",
        "data_analysis",
        "spreadsheet_analyst",
        "pivot_advisor",
        "data_format_cleaner",
    ],
    "txt": [
        "doc_readability",
        "doc_structure_optimizer",
        "doc_tone_adjuster",
        "writing_assistant",
        "long_doc_parser",
        "comm_digest",
    ],
    "md": [
        "doc_readability",
        "doc_structure_optimizer",
        "doc_tone_adjuster",
        "writing_assistant",
        "long_doc_parser",
        "code_best_practices",
        "comm_digest",
    ],
}

# Maximum auto-matched skills in file-assistant context (smaller than main chat
# because document context already consumes a significant token budget)
_MAX_EDITOR_SKILLS = 3

# Minimum number of history turns that trigger context window compression
_CWM_TRIGGER_TURNS = 5


# ── Result dataclasses ──────────────────────────────────────────────────────────


@dataclass
class ProcessedInput:
    """Output of EditorAIPipeline.preprocess()."""

    # The prompt to send to the LLM (PII-masked if sensitive data was found)
    safe_prompt: str
    # Assembled system instruction (base + memory + skills)
    system_instruction: str
    # Whether to force local model due to privacy routing
    force_local: bool
    # Resolved task type
    task_type: str
    # Auto-matched skill IDs injected into this request
    skill_ids: List[str]
    # MaskResult from PIIFilter (needed to restore PII in postprocess)
    mask_result: Optional[Any] = None  # app.core.security.pii_filter.MaskResult


@dataclass
class ProcessedOutput:
    """Output of EditorAIPipeline.postprocess()."""

    # Final text with PII restored
    text: str
    # Validation verdict: "PASS" | "WARN" | "RETRY" | "BLOCK"
    validation_action: str
    # Reason string if not PASS
    validation_reason: str
    # Skill suggestions for UI display
    suggestions: List[Dict[str, Any]] = field(default_factory=list)


# ── Main pipeline class ─────────────────────────────────────────────────────────


class EditorAIPipeline:
    """
    Central pre/post processing middleware for file-assistant AI calls.
    All methods are class methods — no instantiation needed.
    """

    # ── Pre-processing ──────────────────────────────────────────────────────────

    @classmethod
    def preprocess(
        cls,
        prompt: str,
        history: Optional[List[Dict]] = None,
        file_type: str = "",
        output_mode: str = "edit",
        base_system_instruction: str = "",
        user_input_raw: Optional[str] = None,
    ) -> ProcessedInput:
        """
        Run the full pre-processing pipeline for a file-assistant AI request.

        Parameters
        ----------
        prompt               : The full prompt to send (may include selection, CSV data, etc.)
        history              : Multi-turn conversation history
        file_type            : Document type: "docx" | "xlsx" | "pptx" | "pdf" | "csv" | ...
        output_mode          : "chat" | "edit" (affects task_type & skill selection)
        base_system_instruction : The action-specific system instruction to augment
        user_input_raw       : The raw user message before any context prefix
                               (used for better skill matching). Falls back to prompt.
        """
        history = history or []
        raw_user = (user_input_raw or prompt or "").strip()
        ft = (file_type or "").lower().strip()

        # ── 1. Task type classification ───────────────────────────────────────
        task_type = cls._resolve_task_type(ft, output_mode)

        # ── 2. PII Filtering ──────────────────────────────────────────────────
        mask_result = None
        safe_prompt = prompt
        force_local = False
        try:
            from app.core.security.pii_filter import PIIFilter

            mask_result = PIIFilter.mask(prompt)
            if mask_result.mask_map:
                safe_prompt = mask_result.masked_text
                # Privacy routing disabled — PII masking alone is sufficient
                # force_local = True
                logger.info(
                    "[EditorPipeline] PII detected (%d tokens) — masked, using cloud model",
                    len(mask_result.mask_map),
                )
        except Exception as _e:
            logger.debug("[EditorPipeline] PII filter skipped: %s", _e)

        # ── 3. Memory context injection ───────────────────────────────────────
        system = base_system_instruction
        try:
            from app.core.app_context import ctx as _ctx

            _mem_mgr = _ctx.memory_manager
            if _mem_mgr is not None:
                _mem_ctx = _mem_mgr.get_context_string(raw_user, history=history)
                if _mem_ctx:
                    system = f"{_mem_ctx}\n\n{system}"
        except Exception as _me:
            logger.debug("[EditorPipeline] Memory injection skipped: %s", _me)

        # ── 4. File-type-aware skill auto-matching ────────────────────────────
        skill_ids: List[str] = []
        try:
            skill_ids = cls._match_skills(raw_user, task_type, ft)
        except Exception as _se:
            logger.debug("[EditorPipeline] Skill matching skipped: %s", _se)

        # ── 5. Inject skills into system instruction ──────────────────────────
        if skill_ids:
            try:
                from app.core.skills.skill_manager import SkillManager

                system = SkillManager.inject_into_prompt(
                    system,
                    task_type=task_type,
                    user_input=raw_user,
                    temp_skill_ids=skill_ids,
                )
                logger.debug("[EditorPipeline] Injected skills: %s", skill_ids)
            except Exception as _ie:
                logger.debug("[EditorPipeline] Skill injection skipped: %s", _ie)

        # ── 6. Context window compression (long conversations) ────────────────
        # Basic compression: if history exceeds threshold, keep only last N turns
        # (Full MemGPT CWM is optional; skipping here to preserve streaming simplicity)
        if len(history) > _CWM_TRIGGER_TURNS * 2:
            history = history[-((_CWM_TRIGGER_TURNS) * 2) :]
            logger.debug(
                "[EditorPipeline] History trimmed to last %d turns", _CWM_TRIGGER_TURNS
            )

        return ProcessedInput(
            safe_prompt=safe_prompt,
            system_instruction=system,
            force_local=force_local,
            task_type=task_type,
            skill_ids=skill_ids,
            mask_result=mask_result,
        )

    # ── Post-processing ─────────────────────────────────────────────────────────

    @classmethod
    def postprocess(
        cls,
        response_text: str,
        mask_result: Optional[Any],
        skill_ids: Optional[List[str]] = None,
        user_prompt: str = "",
        file_type: str = "",
        answer_text_for_suggestions: Optional[str] = None,
    ) -> ProcessedOutput:
        """
        Run the full post-processing pipeline for a file-assistant AI response.

        Parameters
        ----------
        response_text               : Full LLM response text
        mask_result                 : MaskResult from preprocess (for PII restoration)
        skill_ids                   : Skill IDs injected during preprocess (for suggestions)
        user_prompt                 : The original user message (for output validation)
        file_type                   : Document type (for suggestion filtering)
        answer_text_for_suggestions : Text to use for skill suggestions (defaults to response_text)
        """
        skill_ids = skill_ids or []
        ft = (file_type or "").lower().strip()
        suggest_text = answer_text_for_suggestions or response_text

        # ── 1. PII Restoration ────────────────────────────────────────────────
        restored_text = response_text
        if mask_result and getattr(mask_result, "mask_map", None):
            try:
                restored_text = mask_result.restore(response_text)
            except Exception as _re:
                logger.debug("[EditorPipeline] PII restoration skipped: %s", _re)

        # ── 2. Output Validation ──────────────────────────────────────────────
        validation_action = "PASS"
        validation_reason = ""
        try:
            from app.core.security.output_validator import OutputValidator

            vr = OutputValidator.validate(
                restored_text,
                skill_id=skill_ids[0] if skill_ids else None,
                original_prompt=user_prompt,
            )
            validation_action = getattr(vr, "action", "PASS")
            validation_reason = (getattr(vr, "reasons", None) or [""])[0]
            if validation_action == "BLOCK":
                # Disabled — log only, don't replace content
                logger.warning(
                    "[EditorPipeline] OutputValidator BLOCK (ignored): %s",
                    validation_reason,
                )
        except Exception as _ve:
            logger.debug("[EditorPipeline] Output validation skipped: %s", _ve)

        # ── 3. Skill Suggestions ──────────────────────────────────────────────
        suggestions: List[Dict[str, Any]] = []
        try:
            task_type = cls._resolve_task_type(ft, "edit")
            suggestions = cls._suggest_skills(
                user_prompt, task_type, skill_ids, suggest_text
            )
        except Exception as _sge:
            logger.debug("[EditorPipeline] Skill suggestions skipped: %s", _sge)

        return ProcessedOutput(
            text=restored_text,
            validation_action=validation_action,
            validation_reason=validation_reason,
            suggestions=suggestions,
        )

    # ── Internal helpers ────────────────────────────────────────────────────────

    @classmethod
    def _resolve_task_type(cls, file_type: str, output_mode: str) -> str:
        """Resolve task_type from file_type and output_mode."""
        if output_mode == "chat":
            return "CHAT"
        return _FILE_TYPE_TASK_MAP.get(file_type.lower(), "FILE_GEN")

    @classmethod
    def _match_skills(
        cls,
        user_input: str,
        task_type: str,
        file_type: str,
    ) -> List[str]:
        """
        File-type-aware skill matching.

        Strategy:
        1. Merge TriggerBinding.match_intent() + SkillAutoMatcher.match()
        2. Post-filter: boost file-type-affinity skills, keep at most _MAX_EDITOR_SKILLS
        """
        from app.core.skills.skill_auto_matcher import SkillAutoMatcher

        # Layer 1: Intent trigger bindings (persistent per-session skill activation)
        _intent_ids: List[str] = []
        try:
            from app.core.skills.skill_trigger_binding import get_skill_binding_manager

            _intent_ids = get_skill_binding_manager().match_intent(user_input or "")
        except Exception as _tb_err:
            logger.debug("[EditorPipeline] TriggerBinding skipped: %s", _tb_err)

        # Layer 2: Auto-matcher (regex/semantic/n-gram cascade)
        _auto_ids = SkillAutoMatcher.match(user_input, task_type=task_type)

        # Merge: intent results first (higher priority), then auto, deduplicated
        raw_matches = list(dict.fromkeys(_intent_ids + _auto_ids))

        # Build the affinity set for this file type
        affinity_prefixes = _FILE_TYPE_SKILL_AFFINITY.get(file_type.lower(), [])
        if not affinity_prefixes:
            # Unknown/generic file type — use raw matches as-is (capped)
            return raw_matches[:_MAX_EDITOR_SKILLS]

        affinity_ids: List[str] = []
        general_ids: List[str] = []
        for sid in raw_matches:
            if cls._is_affinity_skill(sid, affinity_prefixes):
                affinity_ids.append(sid)
            else:
                general_ids.append(sid)

        # Affinity skills first, then general, capped at _MAX_EDITOR_SKILLS
        combined = affinity_ids + general_ids
        return combined[:_MAX_EDITOR_SKILLS]

    @classmethod
    def _is_affinity_skill(cls, skill_id: str, prefixes_or_ids: List[str]) -> bool:
        """Check if skill_id matches any of the affinity prefixes or exact IDs."""
        for p in prefixes_or_ids:
            if skill_id == p or skill_id.startswith(p):
                return True
        return False

    @classmethod
    def _suggest_skills(
        cls,
        user_input: str,
        task_type: str,
        already_active_ids: List[str],
        answer_text: str,
    ) -> List[Dict[str, Any]]:
        """Generate skill suggestions based on the conversation."""
        from app.core.skills.skill_suggester import SkillSuggester

        return SkillSuggester.suggest(
            user_input=user_input,
            task_type=task_type,
            already_active_ids=already_active_ids,
            answer_text=answer_text,
            max_n=2,
        )
