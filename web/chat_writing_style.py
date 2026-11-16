# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""User writing-style projection for chat stream prompts."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any


def build_writing_style_instruction(
    get_memory_manager: Callable[[], Any], logger: logging.Logger
) -> Callable[[str], str]:
    """Create a prompt helper bound to the canonical memory owner."""

    def get_instruction(user_input: str) -> str:
        text = (user_input or "").lower()
        writing_keywords = (
            "写",
            "改写",
            "润色",
            "邮件",
            "报告",
            "总结",
            "write",
            "rewrite",
            "polish",
            "email",
            "report",
            "summary",
        )
        if not any(keyword in text for keyword in writing_keywords):
            return ""

        try:
            manager = get_memory_manager()
            if not manager or not hasattr(manager, "user_profile"):
                return ""
            profile = manager.user_profile.profile or {}
            style = (profile.get("communication_style") or {}).get(
                "writing_style_profile"
            ) or {}
            if not style:
                return ""

            detail = style.get("preferred_detail_level", "moderate")
            formality = style.get("formality", "neutral")
            structure = style.get("structure_preference", "paragraph_first")
            tone_tags = style.get("tone_tags", [])
            return (
                "\n\n## 用户写作偏好\n"
                f"- 正式程度：{formality}\n"
                f"- 详细程度：{detail}\n"
                f"- 结构偏好：{structure}\n"
                f"- 语气标签：{', '.join(tone_tags) if tone_tags else '无'}\n"
                "- 在不影响事实准确性和任务要求的前提下遵循这些偏好。"
            )
        except Exception as exc:
            logger.debug("[StyleProfile] read failed: %s", exc)
            return ""

    return get_instruction
