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
4. `file_task_ui_stream.py` is the only owner of event-to-UI-state mapping.
   `web/file_task_stream.py` sanitizes runtime events, persists that canonical
   state, and may emit both the raw event and a derived `ui.message`.
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

## Terminal Event Contract

An active file task ends exactly once:

- `run.finished` carries both successful and failed outcomes. Consumers inspect
  `completed_task`, `runtime.terminal_status`, and the optional structured
  `failure` object.
- `run.cancelled` is reserved for an explicit cancellation.

The Web stream boundary stops consuming producer events immediately after the
first terminal frame. A producer exception before terminal is converted into
one failed `run.finished` frame through the same sanitization, artifact, summary,
and persistence path. Duplicate terminal frames and events emitted after a
terminal frame are discarded rather than rewriting finished task state.

`run.error` is retired from the file-task protocol. Transport or client failures
may still use the generic local `error` handler, but backend file-task producers
must convert execution failures into a failed `run.finished` payload.
The unused `multi_target.*` transport branch is also retired; multi-file work is
represented inside the normal plan, tool, file-change, check, and run events.

## Terminal Status Groups

The frontend must normalize terminal status before deciding UI state.

- Done: `completed`, `complete`, `success`, `succeeded`, `verified`, `done`
- Waiting: `awaiting_confirmation`, `waiting`, `pending`
- Failed: `blocked`, `failed`, `failure`, `error`, `write_blocked`,
  `tool_gap`, `write_not_performed`, `model_unavailable`, `model_error`,
  `context_summary_fallback`, `quality_gate_failed`
- Cancelled: `cancelled`, `canceled`
- Special: `plan_checked` is failed only when `completed_task` is false.

Process rows should not infer confirmation waits from supervisor warnings or
plan checks. Only waiting statuses and explicit resume artifacts should render a
continue-confirm action.

`needs_attention` and `no_file_change` are historical persisted aliases only.
They may be translated at session/artifact-read boundaries, but must not be
emitted by active runtime, stream, or frontend task code.

## Supervisor Audit Display

`supervisor_audit` can appear on multiple lifecycle events. Process rows should
render it compactly. Full details belong in:

- blocked/intervention states
- final completion report

This prevents repeated policy text from looking like repeated user confirmation
gates.

## Verified artifact writes

`run_python_code` must not treat a printed marker as proof of a write. When a
request has a target artifact, Koto stages the target at `TASK_TARGET_PATH`
(available as both a Python global and an environment variable), executes the
code against that sandbox path, fingerprints the result, and only then syncs it
to the workspace. A `KOTO_CREATED` or `KOTO_MODIFIED` marker for an unchanged
target is a tool failure, not a `file.changed` event.

Quality gates inspect the produced file, not only tool summaries. Current
structural checks include real spreadsheet formulas and charts, native PPTX
charts/timeline shapes, and native DOCX tables. Numeric duration phrases such
as “90 天行动计划” must not be parsed as requested item counts, and source file
names in a multi-source clause must not be reclassified as output artifacts.
