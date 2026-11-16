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
4. `file_task_ui_stream.py` is the only owner of canonical phase, status,
   progress, and terminal-state mapping. `app/core/services/file_task_stream.py` sanitizes
   runtime events, persists that canonical state, and may emit both the raw
   event and a derived `ui.message`.
5. `file-task-sse.ts` parses transport frames without touching UI state.
6. `file-task-dispatch.ts` validates event types, deduplicates by run/type/seq,
   and invokes injected handlers.
7. `task-stage-state.ts` is the only frontend projection boundary. For current
   events it consumes canonical `ui_state` without reinterpreting raw payload
   fields. The backend state includes the user-facing title, detail update mode,
   and whether a repair may move the visible stage backwards. The raw event
   mapping is isolated as a compatibility fallback for old or replayed events
   that do not contain the versioned `ui_state` schema.
8. `task-runner.ts` composes injected DOM handlers. The always-visible task
   card uses a five-stage overview plus a bounded, scrollable progress journal;
   the expandable process section retains the complete readable step evidence.
   On terminal outcomes the journal defaults to its latest three entries and
   exposes an explicit expand control. Up to 30 semantic journal entries are
   persisted in task history; raw SSE payloads are not copied into the session.
9. `file-task-status.ts` normalizes terminal state before the runner stores or
   renders `data-task-terminal-status`.

Transport parsing and event dispatch must remain free of DOM access. UI side
effects belong in runner handlers or in explicitly injected post-dispatch
callbacks.

High-frequency canonical stage projections are queued per task card and flushed
once per animation frame. Every semantic event remains ordered in the progress
journal, while the stage overview, primary action, viewport check, and floating
progress surface synchronize only once for that frame. `run.started`, terminal
events, failures, cancellations, and confirmation waits bypass the frame queue
so user-action and outcome states remain immediate.

Task-card responsive behavior follows the width of the AI chat stream, not the
browser viewport. Narrow cards wrap the active-stage detail and stage labels,
stack result actions, and use single-column artifacts. Expanded terminal
journals and execution details have viewport-bounded scroll regions; the
execution summary stays sticky so the user can collapse a long trace without
scrolling back to its beginning. At phone widths the AI panel overlays the
canvas within the available workspace instead of retaining a clipped Split.js
minimum width.

Task-card controls must remain operable without a pointer. Journal expanders
link to their lists through `aria-controls`; native buttons and summaries keep
visible `:focus-visible` rings and compact touch targets; closing a focused card
returns focus to the workspace composer. Re-rendering an unchanged primary
action must preserve its DOM node so keyboard focus is not lost. The terminal
report is a labelled focusable region, and completion scrolling plus reveal
animations respect `prefers-reduced-motion`.

Canonical `ui_state` payloads use schema `koto.file_task_ui_state.v1` and carry:

- `phase`, `title`, `status`, `progress`, and `terminal`
- `detail_mode` (`replace` or `fallback`)
- `allow_regression` for explicit repair transitions
- `progress_explicit` for terminal progress semantics

When the versioned `ui_state` is present, frontend code must not call the
raw-event fallback to overwrite any of these fields. Unversioned historical
`ui_state` is adapted through the compatibility branch so existing task history
keeps its readable file names and repair transitions.

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
