# Removed legacy workspace frontend

Koto has one product shell: `/`, rendered by `web/templates/index.html` and
implemented from `web/src/` TypeScript source. The browser loads the generated
`web/static/js/build/workspace-bundle.js` asset.

Do not restore these removed files as compatibility shims:

| Removed path | Current source owner |
| --- | --- |
| `web/src/workspace/ (已迁移至模块化工作区)` | `web/src/workspace/*` modules, bundled by `web/src/bundles/workspace.ts` |
| `web/static/js/workspace-ai-task.js` | `web/src/workspace/task-runner.ts` and `task-dispatcher.ts` |
| `web/static/js/workspace-ai-task-refresh.js` | `web/src/workspace/task-runner.ts` direct lifecycle refresh handling |
| `web/static/js/workspace-ai-transport.js` | `web/src/workspace/task-stream-transport.ts` and `task-direct-chat.ts` |
| `web/static/js/workspace-ai-results.js` | `web/src/workspace/results.ts` and `task-final-report.ts` |
| `web/static/js/workspace-ai-quick-actions.js` | `web/src/workspace/quick-actions.ts` |
| `web/static/js/workspace-ai-conversation.js` | `web/src/workspace/conversation.ts` |
| `web/static/js/workspace-task-dispatcher.js` | `web/src/workspace/task-dispatcher.ts` |
| `web/static/js/workspace-task-workbench.js` | `web/src/workspace/task-workbench.ts` |
| `web/templates/workspace_assistant.html` | `web/templates/index.html` |
| `web/src/workspace/task-refresh.ts` | `web/src/workspace/task-runner.ts` uses the canonical workspace refresh API directly |
| `web/src/workspace/transport.ts` | Task-specific transports above; the generic factory had no runtime consumer |

`web/blueprints/workspace_assistant.py` is an active API module despite its
legacy name. `/workspace-assistant` is a compatibility redirect to `/`, not a
second rendered shell.

New frontend contracts must cite `web/src/` and test the generated bundle only
as a build artifact. See [ARCHITECTURE.md](ARCHITECTURE.md) for current
ownership.

## Task-flow information ownership

The workspace task card is the single user-facing projection of a running file
task. `task-runner.ts` only composes the runtime; route, plan, execution,
verification, recovery, and final-result messages are owned by the focused
`task-*-event-handlers.ts`, `task-stage-presentation.ts`, and
`task-result-presentation.ts` modules. Markdown output is rendered and
sanitized by `markdown-rendering.ts`; task modules must not probe raw
`window._waRenderMarkdown` or `window._sanitizeRenderedHtml` aliases.

Same-bundle task dependencies use TypeScript imports or injected runtime
methods. `window.WA` is reserved for inline template handlers and separately
loaded editor/workbench bundles. The task-card persistence projection is
returned by `createTaskDispatcher()` as `taskCardPersistenceStructure`; it is
not published globally. The serialized session field remains named
`test_structure` with schema `koto_ai_task_chain_test_v1` solely to read and
write existing conversation history. That historical wire name is not a test
runtime or a second presentation owner.

## File frontend conflict ownership

The active file frontend has no retained multi-owner runtime flags. The July
2026 cleanup retired six concrete conflict groups:

| Retired conflict | Canonical owner |
| --- | --- |
| `_WA_fileBrowserLoaded` written by the tree and embedded shell | `ensureFileBrowserLoaded()` in `web/src/workspace/fs-tree.ts` |
| `_docxHoverForceHiddenText` written by two toolbars | `web/src/shared/selection-runtime.ts` |
| `_docxNativeSelBottom` written by two toolbars | `web/src/shared/selection-runtime.ts` |
| `_escHtml` republished by file open | `web/src/workspace/infrastructure.ts` |
| `_WA_RUNTIME_SESSION_ID` republished during runtime initialization | `web/src/workspace/state.ts` |
| raw `window.WA` replacement from UI/task modules | `getWorkspaceApi()` and `publishWorkspaceApi()` |

`web/templates/_workspace_asset_scripts.html` may bootstrap `window.WA` once so
inline template actions have an object before the bundle executes. It must not
predeclare bundle-internal variables. The DOCX review engine registration is a
separate, intentional lazy-bundle boundary: `docx-review-engine.ts` registers
the module once and `docx-review-loader.ts` is its only loader.

The remaining large frontend debt is event markup, not competing state
ownership. The active workspace template set currently contains 432 inline
event attributes (410 in `index.html`, 16 in the selection toolbar partial, and
6 in the close-warning/color-picker partials). Migrate those by feature slice
to delegated TypeScript handlers; do not add new inline handlers or create a
second event owner during the migration.

## File-task lifecycle ownership

The active file-task lifecycle has one terminal protocol and one UI-state
projection owner. Backend producers emit `run.finished` for both successful and
failed execution, or `run.cancelled` for cancellation. The retired `run.error`
and unused `multi_target.*` branches must not be restored. Structured execution
failure details live in the failed `run.finished` payload. The Web stream
boundary enforces exactly one terminal event and ignores producer output after
that terminal event.

`app/core/agent/file_task_ui_stream.py` owns lifecycle-event to UI-state and
progress mapping. `web/file_task_stream.py` transports and persists that
projection; it must not maintain another stage/progress table. The frontend
normalizes the same terminal payload in `web/src/workspace/file-task-status.ts`.

`needs_attention`, `no_file_change`, and the workspace route alias `open_file`
are retired active-flow concepts. Session/artifact readers may translate the
first two when loading historical records, but runtime and browser task code
must emit only the canonical statuses and route names documented in
`ai_task_event_contract.md`.

Python file-task writes use the staged `TASK_TARGET_PATH` contract. Direct host
target writes and self-reported file markers are not compatibility paths: the
runtime verifies the staged file fingerprint and synchronizes it through the
canonical artifact path. Do not restore marker-only success detection.

## Panel resizing ownership

`web/src/ui/panel-layout.ts` is the only owner of workspace panel resizing. It
creates exactly two Split.js gutters for the active `#wa-left`, `#wa-canvas`,
and `#wa-ai` columns. The former `sidebarResizeHandle`, `inputResizeHandle`,
`settingsResizeHandle`, and `skillsResizeHandle` elements had no event owner
and have been removed from the templates together with their CSS.

There is no standalone two-column layout branch. Initialization validates the
single live Split.js instance, replaces stale instances or orphan gutters, and
clears an interrupted drag on window blur, touch cancellation, or page hiding.
Panel storage is optional: unavailable or malformed browser storage falls back
to the default three-column sizes without aborting workspace startup.

The older `wa_split_sizes*` keys remain only in the removal list used to clear
stale browser preferences; they are never read as layout state. Narrow-window
and high-UI-scale layouts intentionally hide Split.js gutters while the file
panel becomes a drawer. That responsive behavior is active design, not a
legacy resize path.

## Structural layout ownership

The unified application shell in `web/static/css/workspace.css` owns workspace
geometry. `#wa-workspace` is always the flex child of `#workspaceView`; do not
restore the former standalone `position:absolute` layout or an embedded-mode
reset for it.

`web/src/app/theme.ts` derives the single `koto-layout-compact` state from the
zoom-compensated layout width. Both narrow windows and high UI scale use that
same state for the file drawer, canvas, gutters, and accessibility state. Media
queries may adjust small-screen detail sizing, but must not duplicate the
structural drawer rules.

Settings and Skills are activity-rail auxiliary panels. Their shared geometry,
stacking level, scrim relationship, and visibility transitions are declared by
the unified shell selector; generic right-side panel geometry and content-push
rules are retired.

The former `workspacePanel` right-side file list is also retired. It was hidden
by the unified shell while its router callback still toggled state on the dead
element. File navigation and folder switching belong to the visible workspace
tree and its `WA` actions.
