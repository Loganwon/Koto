# ══════════════════════════════════════════════════════════════
# hooks.py — Hook Registry
#
# Provides a lightweight plugin system for the agent loop.
# Hooks fire at well-defined points in the agent lifecycle:
#
#   before_prompt_build  – modify messages before sending to LLM
#   before_tool_call     – intercept / validate tool calls
#   after_tool_call      – post-process tool results
#   before_reply         – transform or filter final reply text
#   agent_end            – cleanup, metrics, logging
#
# Each hook is an async-compatible callable. Hooks registered
# with a lower `priority` number run first (default 100).
# ══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class HookPoint(Enum):
    BEFORE_PROMPT_BUILD = "before_prompt_build"
    BEFORE_TOOL_CALL = "before_tool_call"
    AFTER_TOOL_CALL = "after_tool_call"
    BEFORE_REPLY = "before_reply"
    AGENT_END = "agent_end"


@dataclass
class HookEntry:
    """A registered hook callback."""
    name: str
    point: HookPoint
    fn: Callable
    priority: int = 100
    enabled: bool = True


class HookContext:
    """
    Mutable context passed to hook callbacks.

    Hooks can read/write fields to influence the agent loop.
    Each hook point uses a subset of these fields.
    """
    def __init__(self, **kwargs: Any):
        self.messages: List[Dict[str, str]] = kwargs.get("messages", [])
        self.tool_call: Optional[Dict[str, Any]] = kwargs.get("tool_call")
        self.tool_result: Optional[str] = kwargs.get("tool_result")
        self.reply_text: str = kwargs.get("reply_text", "")
        self.metadata: Dict[str, Any] = kwargs.get("metadata", {})
        self.request: Any = kwargs.get("request")  # AgentRequest
        self.skip: bool = False        # set True to skip the operation
        self.abort_reason: str = ""    # set non-empty to abort the run
        self.extra: Dict[str, Any] = {}


class HookRegistry:
    """
    Central hook registry.

    Usage:
        registry = HookRegistry()
        registry.register("pii_filter", HookPoint.BEFORE_PROMPT_BUILD, my_fn)
        ctx = HookContext(messages=[...])
        registry.fire(HookPoint.BEFORE_PROMPT_BUILD, ctx)
        # ctx.messages may have been modified by hooks
    """

    def __init__(self) -> None:
        self._hooks: Dict[HookPoint, List[HookEntry]] = {p: [] for p in HookPoint}

    def register(self, name: str, point: HookPoint, fn: Callable,
                 priority: int = 100) -> None:
        entry = HookEntry(name=name, point=point, fn=fn, priority=priority)
        self._hooks[point].append(entry)
        self._hooks[point].sort(key=lambda e: e.priority)
        logger.debug("Hook registered: %s @ %s (priority=%d)", name, point.value, priority)

    def unregister(self, name: str) -> None:
        for point in HookPoint:
            self._hooks[point] = [e for e in self._hooks[point] if e.name != name]

    def fire(self, point: HookPoint, ctx: HookContext) -> HookContext:
        """Synchronously fire all hooks at the given point."""
        for entry in self._hooks[point]:
            if not entry.enabled:
                continue
            try:
                entry.fn(ctx)
            except Exception:
                logger.exception("Hook %s raised at %s", entry.name, point.value)
            if ctx.abort_reason:
                logger.warning("Hook %s aborted run: %s", entry.name, ctx.abort_reason)
                break
        return ctx

    def list_hooks(self, point: Optional[HookPoint] = None) -> List[Dict[str, Any]]:
        """List registered hooks (for debugging)."""
        result = []
        points = [point] if point else list(HookPoint)
        for p in points:
            for e in self._hooks[p]:
                result.append({
                    "name": e.name, "point": p.value,
                    "priority": e.priority, "enabled": e.enabled,
                })
        return result

    def clear(self) -> None:
        for p in HookPoint:
            self._hooks[p].clear()


# ── Global default registry ────────────────────────────────────────────────

_default_registry: Optional[HookRegistry] = None


def get_default_registry() -> HookRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = HookRegistry()
    return _default_registry
