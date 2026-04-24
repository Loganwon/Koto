# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
DocEventEmitter — WebSocket Event Emitter for DocAgent
======================================================

Provides a unified interface for emitting document processing events
to the frontend via WebSocket. Maps DocAgent events to specific
WebSocket events for real-time progress tracking and change visualization.

Usage::

    from app.core.agent.doc_event_emitter import DocEventEmitter

    emitter = DocEventEmitter(socketio, sid, namespace="/doc")

    # Emit events directly
    emitter.emit_plan(plan)
    emitter.emit_file_change(change)

    # Or process DocEvent objects
    for event in agent.run(task):
        emitter.emit(event)
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.agent.doc_agent import DocEvent, FileChange
    from app.core.tasks.task_planner import Plan, PlanStep

logger = logging.getLogger(__name__)


class DocEventEmitter:
    """
    Unified WebSocket event emitter for document processing.

    Maps DocAgent events to frontend-consumable WebSocket events
    with consistent structure and error handling.
    """

    # Event type mapping: DocEventType -> WebSocket event name
    EVENT_MAP = {
        "plan_start": "doc_plan_start",
        "plan_created": "doc_plan_created",
        "step_start": "doc_step_start",
        "step_progress": "doc_step_progress",
        "step_done": "doc_step_done",
        "step_error": "doc_step_error",
        "tool_call": "doc_tool_call",
        "tool_result": "doc_tool_result",
        "file_change": "doc_file_change",
        "highlight": "doc_highlight",
        "user_confirm": "doc_user_confirm",
        "replan": "doc_replan",
        "thought": "agent_stream_chunk",  # Reuse existing streaming event
        "stream_chunk": "agent_stream_chunk",
        "verification": "doc_verification",
        "task_complete": "agent_task_complete",
        "error": "doc_error",
    }

    def __init__(
        self,
        socketio: Any,
        sid: str,
        namespace: str = "/doc",
    ):
        """
        Initialize the event emitter.

        Args:
            socketio: Flask-SocketIO instance
            sid: Session ID to emit to
            namespace: WebSocket namespace (default: /doc)
        """
        self._socketio = socketio
        self._sid = sid
        self._namespace = namespace
        self._task_id: Optional[str] = None

    def set_task_id(self, task_id: str):
        """Set current task ID for all subsequent events."""
        self._task_id = task_id

    # ── Generic Event Emitter ──────────────────────────────────────────────

    def emit(self, event: "DocEvent"):
        """
        Emit a DocEvent to the frontend.

        Automatically maps the event type to the appropriate
        WebSocket event name and formats the payload.
        """
        event_type = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
        ws_event = self.EVENT_MAP.get(event_type, f"doc_{event_type}")

        payload = {
            "task_id": event.task_id or self._task_id,
            "step_id": event.step_id,
            "timestamp": event.timestamp,
            **event.data,
        }

        # Special handling for thought/stream events
        if event_type in ("thought", "stream_chunk"):
            text = event.data.get("text", "")
            if text:
                payload = {"chunk": text}

        self._emit(ws_event, payload)

    def _emit(self, event: str, data: Dict[str, Any]):
        """Internal emit with error handling."""
        try:
            self._socketio.emit(
                event,
                data,
                namespace=self._namespace,
                to=self._sid,
            )
        except Exception as e:
            logger.warning("[DocEventEmitter] Failed to emit %s: %s", event, e)

    # ── Specific Event Emitters ────────────────────────────────────────────

    def emit_plan(self, plan: "Plan"):
        """
        Emit plan created event with step summaries.

        Transforms the full Plan object into a frontend-friendly format.
        """
        steps = []
        for i, step in enumerate(plan.steps):
            steps.append({
                "step_id": getattr(step, "step_id", step.name if hasattr(step, "name") else f"step_{i}"),
                "name": step.name if hasattr(step, "name") else f"Step {i+1}",
                "description": step.description if hasattr(step, "description") else "",
                "step_type": step.step_type if hasattr(step, "step_type") else "generic",
                "require_approval": getattr(step, "require_approval", False),
                "estimated_seconds": getattr(step, "timeout_seconds", 60),
            })

        self._emit("doc_plan_created", {
            "task_id": plan.task_id if hasattr(plan, "task_id") else self._task_id,
            "original_request": plan.original_request if hasattr(plan, "original_request") else "",
            "steps": steps,
            "total_steps": len(steps),
            "estimated_time": sum(s.get("estimated_seconds", 60) for s in steps),
        })

    def emit_step_start(self, step_id: str, name: str, description: str = ""):
        """Emit step start event."""
        self._emit("doc_step_start", {
            "task_id": self._task_id,
            "step_id": step_id,
            "name": name,
            "description": description,
            "progress": 0,
            "timestamp": time.time(),
        })

    def emit_step_progress(self, step_id: str, progress: int, message: str = ""):
        """Emit step progress update (0-100)."""
        self._emit("doc_step_progress", {
            "task_id": self._task_id,
            "step_id": step_id,
            "progress": min(100, max(0, progress)),
            "message": message,
            "timestamp": time.time(),
        })

    def emit_step_done(self, step_id: str, summary: str = ""):
        """Emit step completion event."""
        self._emit("doc_step_done", {
            "task_id": self._task_id,
            "step_id": step_id,
            "summary": summary,
            "progress": 100,
            "timestamp": time.time(),
        })

    def emit_step_error(self, step_id: str, error: str):
        """Emit step error event."""
        self._emit("doc_step_error", {
            "task_id": self._task_id,
            "step_id": step_id,
            "error": error,
            "timestamp": time.time(),
        })

    def emit_file_change(self, change: "FileChange"):
        """
        Emit file change event for frontend highlighting.

        Args:
            change: FileChange object with change details
        """
        highlight_color = {
            "add": "green",
            "modify": "yellow",
            "delete": "red",
        }.get(change.change_type, "blue")

        self._emit("doc_file_change", {
            "task_id": self._task_id,
            "step_id": change.step_id,
            "file_path": change.file_path,
            "change_type": change.change_type,
            "range": [change.range_start, change.range_end],
            "original": change.original[:500] if change.original else "",
            "modified": change.modified[:500] if change.modified else "",
            "highlight_color": highlight_color,
            "timestamp": change.timestamp,
        })

    def emit_highlight(
        self,
        file_path: str,
        ranges: List[Dict[str, Any]],
        auto_scroll: bool = True,
    ):
        """
        Emit highlight instruction for the editor.

        Args:
            file_path: Path to the file to highlight in
            ranges: List of {start, end, color, comment} dicts
            auto_scroll: Whether to scroll to the highlighted area
        """
        self._emit("doc_highlight", {
            "task_id": self._task_id,
            "file_path": file_path,
            "ranges": ranges,
            "auto_scroll": auto_scroll,
            "timestamp": time.time(),
        })

    def emit_tool_call(self, step_id: str, tool_name: str, tool_args: Dict[str, Any]):
        """Emit tool call event."""
        self._emit("doc_tool_call", {
            "task_id": self._task_id,
            "step_id": step_id,
            "tool_name": tool_name,
            "tool_args": tool_args,
            "timestamp": time.time(),
        })

    def emit_tool_result(self, step_id: str, tool_name: str, result_preview: str):
        """Emit tool result event."""
        self._emit("doc_tool_result", {
            "task_id": self._task_id,
            "step_id": step_id,
            "tool_name": tool_name,
            "result_preview": result_preview[:500],
            "timestamp": time.time(),
        })

    def request_confirmation(
        self,
        step_id: str,
        description: str,
        pending_changes: List[Dict[str, Any]],
    ):
        """
        Request user confirmation before proceeding.

        The frontend should show a confirmation dialog and emit
        'doc_user_confirm_response' with {step_id, approved: bool}.
        """
        self._emit("doc_user_confirm", {
            "task_id": self._task_id,
            "step_id": step_id,
            "description": description,
            "pending_changes": pending_changes,
            "timestamp": time.time(),
        })

    def emit_replan(self, reason: str, new_steps: List[Dict[str, Any]]):
        """Emit replan notification."""
        self._emit("doc_replan", {
            "task_id": self._task_id,
            "reason": reason,
            "new_steps": new_steps,
            "timestamp": time.time(),
        })

    def emit_thought(self, text: str):
        """Emit agent thinking/reasoning text (streams to chat)."""
        self._emit("agent_stream_chunk", {"chunk": text})

    def emit_verification(self, status: str, summary: str):
        """Emit task verification result."""
        self._emit("doc_verification", {
            "task_id": self._task_id,
            "status": status,
            "summary": summary,
            "timestamp": time.time(),
        })

    def emit_complete(
        self,
        summary: str,
        changes_made: int = 0,
        elapsed_seconds: float = 0,
    ):
        """Emit task completion event."""
        self._emit("agent_task_complete", {
            "task_id": self._task_id,
            "full_text": summary,
            "changes_made": changes_made,
            "elapsed_seconds": elapsed_seconds,
            "timestamp": time.time(),
        })

    def emit_error(self, message: str):
        """Emit error event."""
        self._emit("doc_error", {
            "task_id": self._task_id,
            "message": message,
            "timestamp": time.time(),
        })


# ============================================================================
# Factory function
# ============================================================================


def create_emitter(
    socketio: Any,
    sid: str,
    namespace: str = "/doc",
    task_id: Optional[str] = None,
) -> DocEventEmitter:
    """
    Factory function to create a DocEventEmitter.

    Args:
        socketio: Flask-SocketIO instance
        sid: Session ID
        namespace: WebSocket namespace
        task_id: Optional task ID to set initially

    Returns:
        Configured DocEventEmitter instance
    """
    emitter = DocEventEmitter(socketio, sid, namespace)
    if task_id:
        emitter.set_task_id(task_id)
    return emitter
