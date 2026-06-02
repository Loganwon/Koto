# ══════════════════════════════════════════════════════════════
# lifecycle.py — Agent Run Lifecycle & Event Types
#
# Inspired by OpenClaw's agent lifecycle model:
#   queued → running → streaming/tool_exec → succeeded | failed | cancelled
#
# Every agent run emits a typed stream of AgentEvent objects.
# Consumers (socket_handler, SSE endpoints, tests) iterate these
# events and map them to their own transport format.
# ══════════════════════════════════════════════════════════════
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

# ── Run States ─────────────────────────────────────────────────────────────


class RunState(Enum):
    """Lifecycle states for an agent run."""

    QUEUED = "queued"
    RUNNING = "running"
    STREAMING = "streaming"
    TOOL_EXEC = "tool_exec"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"

    @property
    def is_terminal(self) -> bool:
        return self in (
            RunState.SUCCEEDED,
            RunState.FAILED,
            RunState.CANCELLED,
            RunState.TIMED_OUT,
        )


# ── Agent Request ──────────────────────────────────────────────────────────


@dataclass
class AgentRequest:
    """Input to KotoAgentLoop.run()."""

    prompt: str
    session_id: str = ""
    file_type: str = ""
    file_name: str = ""
    context: str = ""  # document context
    selection: str = ""  # pinned selection text
    has_selection: bool = False
    history: List[Dict[str, str]] = field(default_factory=list)
    output_mode: str = "inline"  # "inline" | "chat"
    model_mode: str = "auto"  # "auto" | "local"
    language: str = ""  # "python" | "r" | "" (text mode)
    csv_data: str = ""  # CSV table data
    action_type: str = ""  # "polish" | "translate" | etc.
    action_system_prompt: str = ""  # pre-built prompt from FloatingToolbar
    live_doc: bool = False  # stream tokens to document in parallel
    live_mode: str = (
        "replace"  # "replace" (overwrite selection) | "append" (insert at cursor)
    )
    extra: Dict[str, Any] = field(default_factory=dict)


# ── Agent Events (the stream protocol) ────────────────────────────────────


class EventType(Enum):
    """All event types emitted by the agent loop."""

    # Lifecycle
    LIFECYCLE_START = "lifecycle_start"
    LIFECYCLE_END = "lifecycle_end"
    LIFECYCLE_ERROR = "lifecycle_error"
    QUEUE_POSITION = "queue_position"

    # Phases (high-level progress)
    PHASE = "phase"

    # Streaming text
    STREAM_CHUNK = "stream_chunk"
    STREAM_BLOCK = "stream_block"

    # Tool execution
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"

    # Proposals (document edits)
    PROPOSAL = "proposal"
    DOC_TOOL_CALL = "doc_tool_call"

    # Thinking / planning
    THOUGHT = "thought"
    PLAN = "plan"
    STEP_START = "step_start"
    STEP_PROGRESS = "step_progress"
    STEP_DONE = "step_done"
    STEP_ERROR = "step_error"

    # Skill suggestions
    SKILL_SUGGESTIONS = "skill_suggestions"

    # RAG info
    RAG_INFO = "rag_info"

    # Final result
    TASK_COMPLETE = "task_complete"

    # Error
    ERROR = "error"

    # Status message
    STATUS_MESSAGE = "status_message"

    # Code execution result
    CODE_RESULT = "code_result"

    # Live document streaming
    LIVE_DOC_COMMIT = "live_doc_commit"


@dataclass
class AgentEvent:
    """A single event emitted during an agent run."""

    type: EventType
    data: Dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def __repr__(self) -> str:
        return f"AgentEvent({self.type.value}, keys={list(self.data.keys())})"


# ── Event constructors (ergonomic helpers) ─────────────────────────────────


def evt_lifecycle_start(run_id: str, session_id: str = "") -> AgentEvent:
    return AgentEvent(
        EventType.LIFECYCLE_START,
        {
            "run_id": run_id,
            "session_id": session_id,
            "state": RunState.RUNNING.value,
        },
    )


def evt_lifecycle_end(run_id: str, state: RunState = RunState.SUCCEEDED) -> AgentEvent:
    return AgentEvent(
        EventType.LIFECYCLE_END,
        {
            "run_id": run_id,
            "state": state.value,
        },
    )


def evt_lifecycle_error(run_id: str, error: str) -> AgentEvent:
    return AgentEvent(
        EventType.LIFECYCLE_ERROR,
        {
            "run_id": run_id,
            "state": RunState.FAILED.value,
            "error": error,
        },
    )


def evt_queue_position(position: int, estimated_wait: float = 0) -> AgentEvent:
    return AgentEvent(
        EventType.QUEUE_POSITION,
        {
            "position": position,
            "estimated_wait": estimated_wait,
        },
    )


def evt_phase(phases: List[Dict], current: str, status: str = "running") -> AgentEvent:
    return AgentEvent(
        EventType.PHASE,
        {
            "phases": phases,
            "current": current,
            "status": status,
        },
    )


def evt_stream_chunk(
    chunk: str,
    live_doc: bool = False,
    live_mode: str = "replace",
    request_id: str = "",
) -> AgentEvent:
    return AgentEvent(
        EventType.STREAM_CHUNK,
        {
            "chunk": chunk,
            "live_doc": live_doc,
            "live_mode": live_mode,
            "request_id": request_id,
        },
    )


def evt_stream_block(text: str) -> AgentEvent:
    return AgentEvent(EventType.STREAM_BLOCK, {"text": text})


def evt_live_doc_commit(
    full_text: str,
    live_mode: str = "replace",
    original_selection: str = "",
    request_id: str = "",
) -> AgentEvent:
    return AgentEvent(
        EventType.LIVE_DOC_COMMIT,
        {
            "full_text": full_text,
            "live_mode": live_mode,
            "original_selection": original_selection,
            "request_id": request_id,
        },
    )


def evt_tool_call(tool_call: Dict[str, Any]) -> AgentEvent:
    return AgentEvent(EventType.TOOL_CALL, {"tool_call": tool_call})


def evt_tool_result(tool_name: str, result_preview: str) -> AgentEvent:
    return AgentEvent(
        EventType.TOOL_RESULT,
        {
            "tool_name": tool_name,
            "result_preview": result_preview[:500],
        },
    )


def evt_proposal(proposals: List[Dict], summary: str = "") -> AgentEvent:
    return AgentEvent(
        EventType.PROPOSAL,
        {
            "proposals": proposals,
            "summary": summary,
        },
    )


def evt_doc_tool_call(tc: Dict[str, Any]) -> AgentEvent:
    return AgentEvent(EventType.DOC_TOOL_CALL, tc)


def evt_thought(text: str) -> AgentEvent:
    return AgentEvent(EventType.THOUGHT, {"text": text})


def evt_plan(steps: List[Dict]) -> AgentEvent:
    return AgentEvent(EventType.PLAN, {"steps": steps})


def evt_step_start(step_id: str, text: str) -> AgentEvent:
    return AgentEvent(EventType.STEP_START, {"step_id": step_id, "text": text})


def evt_step_progress(step_id: str, detail: str) -> AgentEvent:
    return AgentEvent(EventType.STEP_PROGRESS, {"step_id": step_id, "detail": detail})


def evt_step_done(step_id: str, text: str) -> AgentEvent:
    return AgentEvent(EventType.STEP_DONE, {"step_id": step_id, "text": text})


def evt_step_error(step_id: str, error: str) -> AgentEvent:
    return AgentEvent(EventType.STEP_ERROR, {"step_id": step_id, "error": error})


def evt_skill_suggestions(suggestions: List[Dict]) -> AgentEvent:
    return AgentEvent(EventType.SKILL_SUGGESTIONS, {"suggestions": suggestions})


def evt_rag_info(total_chunks: int, retrieved_chunks: int) -> AgentEvent:
    return AgentEvent(
        EventType.RAG_INFO,
        {
            "total_chunks": total_chunks,
            "retrieved_chunks": retrieved_chunks,
        },
    )


def evt_task_complete(
    result: str = "", has_proposals: bool = False, error: str = ""
) -> AgentEvent:
    d: Dict[str, Any] = {"result": result, "has_proposals": has_proposals}
    if error:
        d["error"] = error
    return AgentEvent(EventType.TASK_COMPLETE, d)


def evt_error(text: str) -> AgentEvent:
    return AgentEvent(EventType.ERROR, {"text": text})


def evt_status_message(text: str, is_error: bool = False) -> AgentEvent:
    return AgentEvent(
        EventType.STATUS_MESSAGE,
        {
            "text": text,
            "is_error": is_error,
        },
    )


def evt_code_result(result: Dict[str, Any]) -> AgentEvent:
    return AgentEvent(EventType.CODE_RESULT, result)


# ── Run metadata ───────────────────────────────────────────────────────────


@dataclass
class RunMetadata:
    """Tracks a single agent run's metadata."""

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    session_id: str = ""
    state: RunState = RunState.QUEUED
    started_at: float = 0.0
    ended_at: float = 0.0
    model: str = ""
    token_count: int = 0
    error: str = ""

    def start(self) -> None:
        self.state = RunState.RUNNING
        self.started_at = time.time()

    def finish(self, state: RunState = RunState.SUCCEEDED, error: str = "") -> None:
        self.state = state
        self.ended_at = time.time()
        self.error = error

    @property
    def elapsed(self) -> float:
        if self.ended_at:
            return self.ended_at - self.started_at
        if self.started_at:
            return time.time() - self.started_at
        return 0.0
