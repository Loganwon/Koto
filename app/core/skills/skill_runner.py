"""skill_runner.py — Run a skill synchronously inside a nested TaskAgent.

Used by the `call_skill` tool in TaskAgent.  The nested agent gets the skill's
prompt injected as extra system context and has the `search_skills`/`call_skill`
tools suppressed (depth guard via ``_inside_skill_call`` option).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SKILL_TIMEOUT_ROUNDS = 20  # TaskAgent MAX_ROUNDS upper bound (matches task_agent.py)


def _parse_sse(event: Any) -> Optional[Dict[str, Any]]:
    if isinstance(event, dict):
        return event
    if not isinstance(event, str):
        return None
    for line in event.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            payload = json.loads(line[6:])
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def run_sync(
    skill_id: str,
    task_text: str,
    files: List[Dict[str, Any]],
    options: Dict[str, Any],
    model_id: str = "",
    api_key: str = "",
) -> Dict[str, Any]:
    """Execute a skill synchronously, returning the consolidated result.

    1. Resolves skill definition from local SkillManager (90+ built-ins) or
       downloads from CloudSkillRegistry and registers it ephemerally.
    2. Runs a nested TaskAgent with:
       - ``_inside_skill_call=True``  — suppresses call_skill/search_skills tools
       - ``_skill_system_inject``     — the skill's prompt prepended to system
    3. Collects events and returns::

        {"result": str, "file_changes": list, "error": str | None}
    """
    from app.core.skills.skill_manager import SkillManager
    from app.core.skills.cloud_skill_registry import CloudSkillRegistry

    sm = SkillManager.instance()
    skill_def = sm.get_definition(skill_id)

    ephemeral_id: Optional[str] = None
    if skill_def is None:
        # Try cloud registry
        skill_json = CloudSkillRegistry.fetch_skill(skill_id)
        if skill_json:
            ok = CloudSkillRegistry.register_as_ephemeral(skill_id, skill_json)
            if ok:
                skill_def = sm.get_definition(skill_id)
                ephemeral_id = skill_id

    if skill_def is None:
        return {"result": "", "file_changes": [], "error": f"Skill not found: {skill_id}"}

    # Build nested options (depth guard)
    nested_options: Dict[str, Any] = {k: v for k, v in options.items() if k != "_inside_skill_call"}
    nested_options["_inside_skill_call"] = True

    skill_prompt = ""
    try:
        skill_prompt = skill_def.render_prompt()
    except Exception:
        skill_prompt = getattr(skill_def, "prompt", "") or ""
    nested_options["_skill_system_inject"] = skill_prompt

    skill_name = getattr(skill_def, "name", skill_id) or skill_id
    task_with_context = f"[技能: {skill_name}]\n{task_text}"

    result_text = ""
    file_changes: List[Dict[str, Any]] = []
    error: Optional[str] = None

    try:
        from app.core.agent.task_agent import TaskAgent

        agent = TaskAgent(model_id=model_id, api_key=api_key)
        for event in agent.execute(task=task_with_context, files=files, options=nested_options):
            payload = _parse_sse(event)
            if not payload:
                continue
            event_type = str(payload.get("type") or "")
            if event_type == "result":
                data = payload.get("data", "")
                if isinstance(data, str) and data:
                    result_text = data
            elif event_type == "file_change":
                file_changes.append(payload)
            elif event_type == "error":
                error = str(payload.get("text") or payload.get("error") or "")
    except Exception as exc:
        logger.warning("[SkillRunner] skill %s raised: %s", skill_id, exc)
        error = str(exc)
    finally:
        if ephemeral_id:
            try:
                CloudSkillRegistry.cleanup([ephemeral_id])
            except Exception:
                pass

    return {"result": result_text, "file_changes": file_changes, "error": error}
