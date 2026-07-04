# Koto AI Task Event Contract

This document records the current file-task event boundary used by the
workspace UI and backend stream. It is intentionally small: the goal is to keep
status handling stable while the larger runtime and renderer are split up.

## Main Path

1. `task-dispatcher.ts` first resolves obvious workspace routes locally:
   direct system/chat routes go to `/api/chat/stream`, and obvious file-context
   requests go straight to the file-task stream.
2. Ambiguous workspace input may call `/api/workspace/ai/route-intent`; the
   backend also has deterministic fast paths before model routing.
3. File tasks are streamed through `/api/editor/ai/task-stream`.
4. `web/file_task_stream.py` sanitizes runtime events, persists progress, and
   may emit both the raw event and a derived `ui.message`.
5. `file-task-sse.ts` parses transport frames without touching UI state.
6. `file-task-dispatch.ts` validates event types, deduplicates by run/type/seq,
   and invokes injected handlers.
7. `task-runner.ts` owns DOM handlers and injects task state plus the workbench
   notification callback into the dispatcher.
8. `file-task-status.ts` normalizes terminal state before the runner stores or
   renders `data-task-terminal-status`.

Transport parsing and event dispatch must remain free of DOM access. UI side
effects belong in runner handlers or in explicitly injected post-dispatch
callbacks.

## Terminal Status Groups

The frontend must normalize terminal status before deciding UI state.

- Done: `completed`, `complete`, `success`, `succeeded`, `verified`, `done`
- Waiting: `awaiting_confirmation`, `waiting`, `needs_attention`, `pending`
- Failed: `blocked`, `failed`, `failure`, `error`, `write_blocked`,
  `tool_gap`, `no_file_change`, `model_unavailable`, `quality_gate_failed`
- Cancelled: `cancelled`, `canceled`
- Special: `plan_checked` is failed only when `completed_task` is false.

Process rows should not infer confirmation waits from supervisor warnings or
plan checks. Only waiting statuses and explicit resume artifacts should render a
continue-confirm action.

## Supervisor Audit Display

`supervisor_audit` can appear on multiple lifecycle events. Process rows should
render it compactly. Full details belong in:

- blocked/intervention states
- final completion report

This prevents repeated policy text from looking like repeated user confirmation
gates.
