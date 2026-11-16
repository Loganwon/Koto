"""Transport-neutral projection of KernelAgent compatibility steps."""

from __future__ import annotations

from typing import Any, Mapping


def project_agent_step(step: Any) -> tuple[str, dict[str, Any]]:
    """Return one canonical event type/payload without allocating state or IDs.

    A stream delta must have one projection: it cannot also be published as an
    ``agent_step`` or consumers would display the same generated text twice.
    Non-stream steps preserve the existing compatibility payload.
    """
    data = dict(step) if isinstance(step, Mapping) else step.to_dict()
    if data.get("step_type") != "stream":
        return "agent_step", {"data": data}
    metadata = dict(data.get("metadata") or {})
    event_type = str(metadata.pop("event_type", "") or "").strip()
    if not event_type:
        raise ValueError("stream AgentStep requires an event_type")
    return event_type, {**metadata, "content": str(data.get("content") or "")}
