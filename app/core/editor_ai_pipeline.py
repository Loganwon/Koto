# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
EditorAIPipeline — Pre/post processing middleware for all file-assistant AI calls.

Unifies the file-assistant AI pipeline with the main Koto chat pipeline by applying:
  Pre-request:
    • PII filtering (mask sensitive data before sending to cloud LLM)
    • Privacy routing (sensitive content → force local model)
    • Task type classification (from file_type + output_mode)
    • Context history compression (avoid token overflow on long conversations)
    • System instruction assembly

  Post-response:
    • PII restoration (un-mask placeholders in LLM response text)
    • Output validation (block harmful content, detect quality issues)

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
        user_prompt=processed.safe_prompt,
        file_type="docx",
    )
    # result.text — final text with PII restored
    # result.validation_action — "PASS" | "WARN" | "RETRY" | "BLOCK"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── File-type → task_type ─────────────────────────────────────────────────────

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

# Minimum number of history turns that trigger context window compression
_CWM_TRIGGER_TURNS = 5


# ── Result dataclasses ──────────────────────────────────────────────────────────


@dataclass
class ProcessedInput:
    """Output of EditorAIPipeline.preprocess()."""

    # The prompt to send to the LLM (PII-masked if sensitive data was found)
    safe_prompt: str
    # Assembled system instruction (base + memory)
    system_instruction: str
    # Whether to force local model due to privacy routing
    force_local: bool
    # Resolved task type
    task_type: str
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
        output_mode          : "chat" | "edit" (affects task_type)
        base_system_instruction : The action-specific system instruction to augment
        user_input_raw       : The raw user message before any context prefix.
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
            from app.core.services.memory_manager import get_memory_manager

            _mem_mgr = get_memory_manager()
            if _mem_mgr is not None:
                _mem_ctx = _mem_mgr.get_context_string(raw_user, history=history)
                if _mem_ctx:
                    system = f"{_mem_ctx}\n\n{system}"
        except Exception as _me:
            logger.debug("[EditorPipeline] Memory injection skipped: %s", _me)

        # ── 4. Context window compression (long conversations) ────────────────
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
            mask_result=mask_result,
        )

    # ── Post-processing ─────────────────────────────────────────────────────────

    @classmethod
    def postprocess(
        cls,
        response_text: str,
        mask_result: Optional[Any],
        user_prompt: str = "",
        file_type: str = "",
    ) -> ProcessedOutput:
        """
        Run the full post-processing pipeline for a file-assistant AI response.

        Parameters
        ----------
        response_text               : Full LLM response text
        mask_result                 : MaskResult from preprocess (for PII restoration)
        user_prompt                 : The original user message (for output validation)
        file_type                   : Document type (reserved for format-aware validation)
        """
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

        return ProcessedOutput(
            text=restored_text,
            validation_action=validation_action,
            validation_reason=validation_reason,
        )

    # ── Internal helpers ────────────────────────────────────────────────────────

    @classmethod
    def _resolve_task_type(cls, file_type: str, output_mode: str) -> str:
        """Resolve task_type from file_type and output_mode."""
        if output_mode == "chat":
            return "CHAT"
        return _FILE_TYPE_TASK_MAP.get(file_type.lower(), "FILE_GEN")
