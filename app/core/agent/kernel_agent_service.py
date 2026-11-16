"""Application-facing helpers for the single KernelAgent runtime.

HTTP blueprints, background jobs, and message transports must depend on this
module instead of owning their own Agent instance or model/tool loop.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Iterable

from app.core.agent.factory import create_agent, create_local_agent
from app.core.agent.types import AgentStepType

_agent_instances: dict[tuple[Any, ...], Any] = {}
_agent_lock = threading.Lock()
_history_lock = threading.RLock()
_chats_dir = Path(__file__).resolve().parents[3] / "chats"


def get_kernel_agent(
    *,
    local: bool = False,
    model_id: str | None = None,
    tool_profile: str = "core",
    addon_tool_names: Iterable[str] = (),
) -> Any:
    """Return the Agent for one explicit runtime configuration.

    This facade is the sole lifecycle owner for production Agent instances.
    Different provider/tool configurations are cached separately while every
    caller still uses the same Kernel execution path.
    """

    addon_names = tuple(dict.fromkeys(str(name) for name in addon_tool_names))
    key = ("local" if local else "cloud", model_id or "", tool_profile, addon_names)
    cached = _agent_instances.get(key)
    if cached is not None:
        return cached
    with _agent_lock:
        cached = _agent_instances.get(key)
        if cached is not None:
            return cached
        if local:
            kwargs = {
                "tool_profile": tool_profile,
                "addon_tool_names": addon_names,
            }
            if model_id:
                kwargs["model"] = model_id
            cached = create_local_agent(**kwargs)
        else:
            kwargs = {
                "tool_profile": tool_profile,
                "addon_tool_names": addon_names,
            }
            if model_id:
                kwargs["model_id"] = model_id
            cached = create_agent(**kwargs)
        _agent_instances[key] = cached
        return cached


def reset_kernel_agent_for_tests() -> None:
    """Clear the cached facade instance without changing runtime state."""

    with _agent_lock:
        _agent_instances.clear()


def run_kernel_agent_collect(
    message: str,
    *,
    history: Iterable[dict[str, Any]] | None = None,
    session_id: str | None = None,
    task_type: str | None = None,
    record_task: bool = True,
) -> dict[str, Any]:
    """Run KernelAgent once and collect its compatibility ``AgentStep`` output."""

    steps_payload: list[dict[str, Any]] = []
    final_answer = ""
    status = "failed"
    error = ""
    for step in get_kernel_agent().run(
        input_text=message,
        history=list(history or []),
        session_id=session_id,
        task_type=task_type,
        record_task=record_task,
    ):
        step_data = step.to_dict()
        steps_payload.append(step_data)
        if step.step_type == AgentStepType.ANSWER:
            final_answer = step.content or ""
            validation = dict(step.metadata.get("validation") or {})
            rejected = bool(
                validation.get("blocked")
                or validation.get("exhausted")
                or validation.get("accepted") is False
                or step.metadata.get("state") in {"failed", "blocked", "cancelled"}
            )
            status = (
                "cancelled"
                if step.metadata.get("state") == "cancelled"
                else ("failed" if rejected else "success")
            )
            error = final_answer if rejected else ""
        elif step.step_type == AgentStepType.ERROR:
            final_answer = step.content or "任务未完成。"
            status = (
                "cancelled" if step.metadata.get("state") == "cancelled" else "failed"
            )
            error = final_answer
    if not final_answer and steps_payload:
        final_answer = str(steps_payload[-1].get("content") or "")
    result = {
        "status": status,
        "answer": final_answer,
        "result": final_answer,
        "steps": steps_payload,
    }
    if status != "success":
        result["error"] = error or "Agent 未返回完成结果。"
    return result


def _history_path(session_id: str) -> Path:
    clean = str(session_id or "").strip()
    if not clean:
        raise ValueError("session_id is required")
    filename = clean if clean.endswith(".json") else f"{clean}.json"
    safe_name = Path(filename).name
    _chats_dir.mkdir(parents=True, exist_ok=True)
    return _chats_dir / safe_name


def load_kernel_history(
    session_id: str,
    *,
    max_turns: int = 30,
    token_budget: int = 4096,
) -> list[dict[str, str]]:
    """Load bounded history for non-HTTP transports such as Telegram."""

    try:
        path = _history_path(session_id)
    except ValueError:
        return []
    if not path.exists():
        return []
    with _history_lock:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return []
    if not isinstance(raw, list):
        return []
    converted: list[dict[str, str]] = []
    for item in raw[-max(1, int(max_turns)) :]:
        if not isinstance(item, dict):
            continue
        parts = item.get("parts")
        content = parts[0] if isinstance(parts, list) and parts else item.get("content")
        converted.append(
            {
                "role": str(item.get("role") or "user"),
                "content": str(content or ""),
            }
        )
    selected: list[dict[str, str]] = []
    used = 0
    for item in reversed(converted):
        estimate = max(1, len(item["content"]) // 4)
        if selected and used + estimate > max(1, int(token_budget)):
            break
        selected.insert(0, item)
        used += estimate
    return selected


def save_kernel_history(session_id: str, user_text: str, answer_text: str) -> None:
    """Append one user/assistant turn for a non-HTTP Kernel transport."""

    path = _history_path(session_id)
    with _history_lock:
        history: list[dict[str, Any]] = []
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    history = loaded
            except (OSError, ValueError, TypeError):
                history = []
        history.extend(
            (
                {"role": "user", "parts": [str(user_text or "")]},
                {"role": "model", "parts": [str(answer_text or "")]},
            )
        )
        path.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


__all__ = [
    "get_kernel_agent",
    "load_kernel_history",
    "reset_kernel_agent_for_tests",
    "run_kernel_agent_collect",
    "save_kernel_history",
]
