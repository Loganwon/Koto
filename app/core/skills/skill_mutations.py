"""Canonical state mutations for installed Skills.

HTTP blueprints may expose different URLs for the workspace and marketplace,
but changing a Skill must always persist the same state and emit the same
side effects.  Keeping that policy here prevents route-specific behaviour.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def set_skill_enabled(skill_id: str, enabled: bool) -> bool:
    """Persist one Skill's enabled state and notify the shared integrations."""
    from app.core.skills.skill_manager import SkillManager

    if not SkillManager.set_enabled(skill_id, enabled):
        return False

    if enabled:
        try:
            from app.core.skills.skill_affinity import SkillAffinityTracker

            SkillAffinityTracker.get_instance().record_activation(skill_id)
        except Exception:
            logger.warning("Skill affinity update failed", exc_info=True)

    try:
        from app.core.hooks.hook_manager import HookContext, get_hook_manager

        get_hook_manager().fire_on_skill_change(
            skill_id,
            enabled,
            HookContext(task_type="skill_toggle", skill_id=skill_id),
        )
    except Exception:
        logger.warning("Skill-change hook failed", exc_info=True)

    return True


def disable_all_non_system_skills() -> list[str]:
    """Disable every user-controllable Skill through the canonical mutation."""
    from app.core.skills.skill_manager import SkillManager

    SkillManager._ensure_init()
    disabled: list[str] = []
    for skill_id, state in SkillManager._registry.items():
        if state.get("skill_nature") == "system" or not state.get("enabled", False):
            continue
        if set_skill_enabled(skill_id, False):
            disabled.append(skill_id)
    return disabled
