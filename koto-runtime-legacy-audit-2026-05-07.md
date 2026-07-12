> **Historical snapshot — not current implementation guidance.** Use [ARCHITECTURE.md](ARCHITECTURE.md) and [KOTO_CODE_DEBT_REPORT.md](KOTO_CODE_DEBT_REPORT.md) for the live architecture.

# Koto Runtime And Legacy Audit

Date: 2026-05-07

## Scope

This audit answers three questions:

1. What currently controls what users can actually see and do?
2. Which routes, scripts, pages, and runtimes are still live but no longer primary?
3. Which parts are old code, dead shims, build output, or audit noise rather than the current product path?

The audit is based on four kinds of evidence:

- Runtime browser inspection of the live `http://127.0.0.1:5000/workspace-assistant` page.
- Static route and script tracing from the current source tree.
- Regression tests that explicitly assert legacy entrypoints are removed.
- Packaging/build evidence for what is shipped versus what is only source or generated output.

## 1. Runtime Truth

### 1.1 Startup Chain

The practical local desktop chain is:

- `Koto_Start.ps1` prefers `src/koto_app.py`, then `src/koto_setup.py`, then `web/app.py`.
- `koto.spec` packages `src/koto_setup.py` as the PyInstaller entrypoint.
- `src/koto_setup.py` can hand off into `src/koto_app.py`.
- `src/koto_app.py` starts the Flask backend and opens the desktop window.
- `web/app.py` is the actual backend application that registers blueprints and serves the product.

Meaning:

- `src/koto_app.py` controls desktop startup behavior.
- `web/app.py` controls the actual application behavior users feel after startup.
- `src/server.py` matters for pure service mode, not the main desktop user path.

### 1.2 Source Of Truth Versus Output

Current source-of-truth layers:

- Backend app and routes: `web/app.py`, `web/blueprints/`, `app/api/`
- Frontend page shell: `web/templates/`
- Frontend workspace runtime: `web/src/workspace/ (已迁移至模块化工作区)`, `web/static/js/workspace-ai-task.js`
- File task runtime: `app/core/agent/file_task_runtime.py`

Generated or non-source layers:

- `build/` is build and packaging output.
- `web/static/univer-dist/` is generated runtime asset output, not authoring source.
- `config/`, `chats/`, `logs/`, `uploads/`, `workspace/` are runtime state/data, not product control logic.
- `scripts/` and `src/scripts/` are dev/training utilities, not user-facing runtime.

Important audit trap:

- `build_cython.py` compiles several `app/core/*` directories into `.pyd` modules.
- In packaged or in-place compiled runs, Python can import the `.pyd` before the sibling `.py`.
- So some source files can exist and still not be the live runtime in a compiled desktop build.

## 2. Current User-Facing Control Path

### 2.1 Primary Page Path

The current primary user-facing file experience is:

- Page route: `web/blueprints/pages.py:132` -> `/workspace-assistant`
- Template: `web/templates/workspace_assistant.html`
- Loaded scripts at runtime:
  - `/static/js/workspace-ai-task.js`
  - `/static/js/workspace-assistant.js`
  - `/static/js/doc-agent-ui.js`

Browser inspection of the live page confirms:

- `window.WA` exists.
- The live page exposes `openWorkspaceFile`, `sendMessage`, `sendInlineMessage`, `streamWhiteboxTask`, `toggleSkillLibrary`, `openAudioOverview`, and `openNotebookGuide`.
- The page does not expose a live `docAgentUI` instance.

### 2.2 Frontend Control Matrix

| User-facing capability | Frontend owner | Backend owner | Current status |
| --- | --- | --- | --- |
| Open workspace page | `web/blueprints/pages.py:132` + `web/templates/workspace_assistant.html` | `web/app.py` blueprint registration | Primary |
| Workspace file tree and current workspace metadata | `web/src/workspace/ (已迁移至模块化工作区)` fetches `/api/v1/workspace/current_dir` | `web/blueprints/workspace_assistant.py` | Primary |
| Recent files and search | `web/src/workspace/ (已迁移至模块化工作区)` fetches `/api/files/recent` and `/api/files/search` | `app/api/file_hub_routes.py:237`, `app/api/file_hub_routes.py:323` | Primary |
| Open file from workspace | `window.WA.openWorkspaceFile` at `web/src/workspace/ (已迁移至模块化工作区):3102` | `web/blueprints/workspace_assistant.py:266` and `:368` | Primary |
| Editor dispatch by file type | `_mountOpenTabEditor` at `web/src/workspace/ (已迁移至模块化工作区):451` | Parsed file payload from `workspace_assistant.py` | Primary |
| DOCX editing | `_mountDocxEditor` and `_ensureTipTap` in `workspace-assistant.js` | `workspace_assistant.py` open + `docx_full` progressive fetch | Primary |
| XLSX editing | `_ensureUniverSheets` and `KotoXlsxEditor` in `workspace-assistant.js` | `workspace_assistant.py` open/save/export | Primary |
| PPTX editing | `KotoPptxEditor` in `workspace-assistant.js` | `workspace_assistant.py` parsing path plus PPTX helpers | Primary |
| PDF viewing and PDF ops | `KotoPdfViewer` in `workspace-assistant.js` | `workspace_assistant.py` PDF routes | Primary |
| Text/code editing | `KotoTextEditor` in `workspace-assistant.js` | `workspace_assistant.py` | Primary |
| Quick AI actions on selection or current content | `WA.quickAction` and `WA.sendQuickAction` in `workspace-assistant.js` | `/api/editor/ai/stream` in `web/blueprints/editor_ai.py` | Current secondary AI path |
| Whitebox file task stream | `WA.sendMessage` in `workspace-assistant.js` -> `WA.streamWhiteboxTask` in `workspace-ai-task.js:619` | `/api/editor/ai/task-stream` in `web/blueprints/editor_ai.py` -> `FileTaskRuntime` | Current primary file-task AI path |
| Save / export / auto-save / versions | `workspace-assistant.js` buttons and timers | `workspace_assistant.py` save, auto_save, versions, restore-version | Primary |
| Audio overview and notebook guide | `workspace-assistant.js` modal/drawer actions | `workspace_assistant.py` `/audio_overview` and `/notebook_guide` | Primary but auxiliary |

### 2.3 File-Type Ownership

Current editor/viewer ownership is not split across multiple page systems. It is centralized in `web/src/workspace/ (已迁移至模块化工作区)`.

- DOCX: `_mountDocxEditor` creates `new KotoDocxEditorLib.KotoTipTapEditor()` and `_ensureTipTap` loads `/static/js/tiptap-docx-bundle.js`.
- XLSX: `_ensureUniverSheets` loads `/static/univer-dist/assets/sheets-main.css` and `/static/univer-dist/assets/sheets-main.js`, then `KotoXlsxEditor` talks to `window.KotoSheetsAPI`.
- PPTX: `KotoPptxEditor` is implemented directly in `workspace-assistant.js`.
- PDF: `KotoPdfViewer` is implemented directly in `workspace-assistant.js`.
- Image: `KotoImageViewer` is implemented directly in `workspace-assistant.js`.
- Text/code: `KotoTextEditor` is implemented directly in `workspace-assistant.js`.

Conclusion:

- The current file workstation is a single-page shell with one controlling JS monolith plus one whitebox task helper script.
- The old split model of many separate editors is no longer the primary user path.

## 3. Backend Control Path

### 3.1 Registration And Routing

`web/app.py` is the real control center for live backend routing.

- `_register_blueprints_deferred()` is defined at `web/app_blueprints.py`.
- `workspace_assistant_bp` is registered through that path at `web/app_blueprints.py`.
- `_register_blueprints_deferred()` is called at `web/app_blueprints.py`.

That makes `web/app.py` the place where backend user-visible behavior is actually wired into the live app.

### 3.2 Current Backend Ownership

| Concern | Actual owner | Why it matters |
| --- | --- | --- |
| File workstation BFF | `web/blueprints/workspace_assistant.py` | Owns open, save, temp raw files, versions, PDF ops, workspace FS operations |
| File search/recent/archive | `app/api/file_hub_routes.py` | Feeds the workstation sidebar and archive flows |
| Whitebox file task AI | `web/blueprints/editor_ai.py` + `_stream_whitebox_file_task_request` at `web/file_task_stream.py` + `app/core/agent/file_task_runtime.py` | This is the current primary file-task AI runtime |
| Quick editor AI actions | `web/blueprints/editor_ai.py` | Handles selection-based translate/polish/check/summarize and other editor actions |
| Generic task ledger/progress system | `app/api/task_routes.py` | Still live infrastructure, but not the primary workstation user feel path |
| Legacy/compat agent callbacks | `app/api/agent_routes.py` | Still registered, but mostly compatibility or retirement surfaces |

### 3.3 Why `/api/editor/ai/task-stream` Is The Current Primary File AI Path

The live path is:

- `WA.sendMessage` at `workspace-assistant.js:11836`
- `WA.streamWhiteboxTask` at `workspace-ai-task.js:619`
- POST `/api/editor/ai/task-stream` at `workspace-ai-task.js:626`
- `web/blueprints/editor_ai.py` route
- `_stream_whitebox_file_task_request()` at `web/file_task_stream.py`
- `FileTaskRuntime.run()` in `app/core/agent/file_task_runtime.py`

This is the current primary AI path for file tasks because it is the only path that is both:

- Explicitly wired from the live workstation UI
- Typed around file-task request/event flow
- Able to stream structured tool progress back into the workstation UI

### 3.4 Why `/api/editor/ai/stream` Is Still Current But Secondary

Quick actions still use `/api/editor/ai/stream`.

Evidence:

- `WA.sendQuickAction` sends to `/api/editor/ai/stream` from `workspace-assistant.js:4050`.
- `_EDITOR_AI_STREAM_ACTIONS` in `web/blueprints/editor_ai.py` includes `translate`, `polish`, `summarize`, `check`, `chart`, `find_replace`, `custom_instruction`, and more.

So this route is not dead. It is just no longer the primary multi-file/file-task path.

## 4. Still Reachable But No Longer Primary

These are not the main user path, but they still exist and remain reachable:

- `web/blueprints/pages.py:62` -> `/file-network`
- `web/blueprints/pages.py:79` -> `/edit-ppt/<session_id>`
- `web/blueprints/pages.py:85` -> `/pptx-editor/<file_id>`
- `web/blueprints/pages.py:91` -> `/skills`
- `web/blueprints/pages.py:126` -> `/notebook`
- `web/blueprints/pages.py:141` -> `/doc-compare`

Classification:

- `file-network`, `skills`, `notebook`, `doc-compare` are auxiliary or utility surfaces.
- `edit-ppt` and `pptx-editor` are specialized older page-style editors that are no longer the primary workstation experience.

These are live but not the current central path users feel when using the workstation.

## 5. Legacy And Dead-Code Classification

### 5.1 High-Confidence Current Path

These are current and should not be treated as dead code:

- `web/templates/workspace_assistant.html`
- `web/src/workspace/ (已迁移至模块化工作区)`
- `web/static/js/workspace-ai-task.js`
- `web/blueprints/workspace_assistant.py`
- `web/app.py` routes `/api/editor/ai/task-stream` and `/api/editor/ai/stream`
- `app/core/agent/file_task_runtime.py`
- `app/api/file_hub_routes.py`

### 5.2 Loaded But Inert Compat Layer

`web/static/js/doc-agent-ui.js` is the clearest loaded-but-not-current example.

Facts:

- The template still loads it.
- It only auto-initializes on `DOMContentLoaded` if both `window.waSocket || window.socket` and `#wa-ai-panel` exist.
- The live workstation page currently has none of those conditions satisfied.
- Browser inspection showed:
  - `window.DocAgentUI === true`
  - `window.docAgentUI === false`
  - `window.waSocket === false`
  - `window.socket === false`
  - `#wa-ai-panel` does not exist

Judgment:

- This is not the current controlling layer.
- It is a dormant compat payload that still adds page weight and confusion.

### 5.3 Retired Stubs Still Present In Live Source

These are still in source, but their behavior is mostly retirement or compatibility behavior rather than the main path.

| Item | Evidence | Judgment |
| --- | --- | --- |
| `WA.extractTopics` | `web/src/workspace/ (已迁移至模块化工作区):11447` only shows a retirement warning | Retired stub |
| `WA.sendInlineMessage` | `web/src/workspace/ (已迁移至模块化工作区):12182` only returns a disabled message | Retired stub |
| `WA.setOutputMode` | `web/src/workspace/ (已迁移至模块化工作区):11980` hard-locks inline mode | Compat shim |
| `WA.applyAIResponse` | `web/src/workspace/ (已迁移至模块化工作区):11755` survives as a wrapper into the action bar apply path | Compat shim |
| `/api/agent/confirm` | `app/api/agent_routes.py:1382` returns HTTP 410 | Explicit retirement stub |
| `/api/agent/choice` | `app/api/agent_routes.py:1396` returns HTTP 410 | Explicit retirement stub |

These are not healthy current product logic. They are controlled leftovers.

### 5.4 Removed Legacy Entry Points Confirmed By Tests

The strongest fully removed legacy items are backed by regression tests.

Confirmed removed:

- `/api/editor/ai/skill-execute` returns 404
- `/api/editor/ai/task-execute` returns 404
- `web/univer-editor/index.html` does not exist
- `web/static/univer-dist/index.html` does not exist
- `web/univer-editor/main.js` does not exist
- `web/univer-editor/src` does not exist
- `web/blueprints/editor_docs.py` does not exist
- `web/static/tiptap-dist/` does not exist

Important nuance:

- `web/univer-editor/` still exists, but only as a support/build-source directory for the sheets runtime.
- `web/static/univer-dist/assets/sheets-main.js` and `sheets-main.css` are still required by the current workstation.

So the old standalone Univer editor is removed, but the sheets runtime support path is still alive.

### 5.5 Build And Packaging Noise

These should not be mixed into the dead-code audit as if they were current app logic:

- `build/`
- `build/cython_cache/`
- `build/temp.win-amd64-cpython-311/`
- `build/koto/`
- screenshots under `build/`
- runtime state directories such as `chats/`, `logs/`, `uploads/`, `workspace/`

These are noise for architecture ownership. They may matter operationally, but not as the current control path.

### 5.6 Developer And Training Script Noise

These are not live user-facing control logic:

- `scripts/` contains diagnostics, tests, training helpers, and maintenance utilities.
- `src/scripts/` contains a smaller packaged/training subset.

This duplication is not the main runtime path, but it is repository clutter that can mislead audits.

## 6. What Controls What

### 6.1 Frontend Ownership

- The workstation shell, left file panel, tab model, editor dispatch, AI input, save/autosave buttons, model switches, and many per-format UI behaviors are all centralized in `web/src/workspace/ (已迁移至模块化工作区)`.
- The structured whitebox task rendering and follow-up action UI are centralized in `web/static/js/workspace-ai-task.js`.
- The template `web/templates/workspace_assistant.html` decides what the live page actually loads.

### 6.2 Backend Ownership

- `web/app.py` owns global route wiring and editor AI endpoints.
- `web/blueprints/workspace_assistant.py` owns workstation file I/O and BFF-style workspace operations.
- `app/core/agent/file_task_runtime.py` owns the current whitebox file-task execution loop.
- `app/api/file_hub_routes.py` owns recent-file and search APIs used by the workstation sidebar.

### 6.3 Packaging Ownership

- `Koto_Start.ps1`, `src/koto_setup.py`, `src/koto_app.py`, and `koto.spec` own how the desktop product boots.
- `build_cython.py` and compiled `.pyd` artifacts can change which backend implementation is actually live in packaged or compiled runs.

## 7. Where The Old Shit Mountain Actually Is

This repo does not have one single dead layer. It has several different kinds of old mess.

### 7.1 `web/src/workspace/ (已迁移至模块化工作区)` Is The Main Frontend Shit Mountain

Why:

- It is the true controlling file for user-visible workstation behavior.
- It mixes shell UI, file-tree logic, API orchestration, editor dispatch, DOCX progressive loading, XLSX runtime loading, PPTX editor logic, PDF viewer logic, chart flow, autosave, versioning hooks, and AI shims in one place.
- It also still contains retired or compatibility surfaces like `extractTopics`, `sendInlineMessage`, `setOutputMode`, and `applyAIResponse`.

This is the highest-value cleanup target because current behavior and legacy residue are mixed in the same monolith.

### 7.2 `web/app.py` Is The Main Backend Shit Mountain

Why:

- It is still the real backend control center.
- It wires current editor AI routes, whitebox task streaming, and many historical compatibility layers in one large file.
- Current logic and legacy migration residue coexist here.

This is the backend equivalent of the workstation monolith.

### 7.3 `doc-agent-ui.js` Is A Dormant Legacy Payload

Why:

- It still loads on the live workstation page.
- It currently does not initialize.
- It describes a socket-driven doc-agent UI path that is not the active workstation control path.

This is not dead enough to ignore and not alive enough to trust. That is classic cleanup debt.

### 7.4 Multiple Reachable Old Pages Still Compete For Mental Ownership

Why:

- `/workspace-assistant` is the current primary path.
- `/edit-ppt`, `/pptx-editor`, `/file-network`, `/doc-compare`, `/notebook`, and `/skills` are still reachable.

Even when these pages are intentional, they fragment the answer to "where does user-visible behavior live?"

### 7.5 Source Versus Generated Runtime Assets Is Still Confusing

Why:

- The current workstation loads generated assets under `web/static/univer-dist/assets/`.
- The source/build support for sheets remains under `web/univer-editor/`.
- The old standalone editor entrypoints are removed, but the remaining source/build support directory still looks like a live product path.

This is an audit trap, not necessarily dead code, but it keeps causing wrong edits and wrong assumptions.

### 7.6 Cython Shadowing Makes Runtime Ownership Harder To See

Why:

- Some `app/core/*` source files can be shadowed by compiled `.pyd` siblings.
- A developer can read or edit `.py` and still not be changing the actual loaded runtime.

This is operationally dangerous because it makes old and current code harder to distinguish by inspection alone.

### 7.7 `scripts/` And `src/scripts/` Add Repository Noise

Why:

- They are not the product runtime.
- They duplicate some training/data-generation intent.
- They expand the repo surface that a future audit has to mentally exclude.

## 8. Cleanup Priority Recommendation

Recommended order:

1. Remove or quarantine loaded-but-inert payloads and retirement stubs that still confuse active flow ownership.
2. Split current workstation control logic away from compatibility shims inside `workspace-assistant.js`.
3. Isolate the current editor AI routes and whitebox task runtime wiring from historical compatibility logic in `web/app.py`.
4. Mark non-primary but still intentional pages as auxiliary products, not the core workstation path.
5. Keep generated output and build support explicitly separated in docs and naming.
6. Treat Cython-shadowed modules as a packaging/runtime concern in every future cleanup.

## 9. Bottom Line

If the question is "what currently controls what users can touch and feel," the answer is:

- Startup: `Koto_Start.ps1` + `src/koto_setup.py` + `src/koto_app.py`
- Backend control hub: `web/app.py`
- Workstation BFF: `web/blueprints/workspace_assistant.py`
- Live workstation UI: `web/templates/workspace_assistant.html`
- Frontend control monolith: `web/src/workspace/ (已迁移至模块化工作区)`
- Current file-task AI runtime: `web/static/js/workspace-ai-task.js` + `app/core/agent/file_task_runtime.py`

If the question is "what is old shit mountain," the answer is:

- The main workstation JS monolith
- The main Flask app monolith
- Dormant doc-agent compat payloads
- Reachable but non-primary old pages
- Source/build/output overlap around Univer and Cython
- Retirement stubs that still exist in the live tree
