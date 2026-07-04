# Koto Design Cleanup Execution Inventory

Date: 2026-07-04

This inventory turns the architecture cleanup assessment into executable
batches. It should be updated after each cleanup batch, together with
`scripts/audit_code_baseline.py` output and the relevant guard tests.

## Current Baseline

Measured with:

```powershell
python scripts\audit_code_baseline.py --json
```

| Signal | Current value |
| --- | ---: |
| `web/app.py` lines | 3501 |
| `app/core/agent` top-level `.py` files | 121 |
| `app/core/agent` recursive `.py` files | 147 |
| Production TODO/FIXME count | 11 |
| Production files >= 1500 lines | 33 |
| Lines inside files >= 1500 lines | 94752 |
| Production files >= 2000 lines | 18 |
| Lines inside files >= 2000 lines | 69606 |
| `workspace-bundle.js` size | 1128117 bytes |
| `web/static/vendor` size | 6510883 bytes |

The working tree is already mid-refactor. Treat these numbers as the current
checkout baseline, not as a stable release snapshot.

## Cleanup Zones

| Zone | Main files | Current smell | Cleanup direction |
| --- | --- | --- | --- |
| File-task execution | `app/core/agent/file_task_runtime.py`, `app/core/agent/task_tools.py`, `app/core/agent/file_task_quality_gate.py` | Runtime orchestration, tool execution, classification, verification, and fallback behavior still have dense cross-calls. | Keep `FileTaskRuntime` as the owner, but move pure helpers into typed subpackages and keep tool contracts stable. |
| Agent entrypoints | `app/core/agent/unified_agent.py`, `app/core/agent/langgraph_agent.py`, `app/core/agent/legacy_loop_facade.py`, `web/services/chat_stream/agent_handler.py` | Multiple supported execution paths remain active; filename-based deletion would break current transports. | Preserve the entrypoint matrix, pass decisions forward, then retire facades only after callers and tests move. |
| Web transport and runtime context | `web/app.py`, `web/file_task_stream.py`, `web/services/chat_stream/*`, `web/runtime_context.py`, `web/runtime_services.py` | Web modules still own some core decisions and runtime singleton lookups. | Keep Flask/SSE/session mapping in web; move pure routing, generation policy, service accessors, and event normalization into narrower owners. |
| Workspace frontend | `web/src/workspace/task-runner.ts`, `web/src/workspace/task-workbench.ts`, `web/templates/index.html`, `web/static/css/workspace.css` | Task presentation, editor shell, and AI panel styles are large and easy to desynchronize. | Split by ownership: task presentation, composer, editor shell, file tree, and shared layout. Rebuild bundle after every batch. |
| Document editors | `web/tiptap-editor/koto-docx-editor.js`, `web/tiptap-editor/docx-extensions.js`, `app/core/file/parsers/docx_parser.py`, `web/document_feedback.py` | DOCX parsing, review, feedback, and editor behavior are large but user-facing. | Add behavior guards first; extract format-specific services only after visual or route tests cover the path. |
| Skills and marketplace | `app/core/skills/skill_auto_matcher.py`, `app/core/skills/builtin_skills.py`, `app/api/skill_marketplace_routes.py`, `app/api/github_skill_hub.py` | Registry, matching, marketplace API, and bundled definitions are heavy in a few files. | Separate data definitions, registry access, matching policy, and HTTP surfaces. Preserve skill JSON compatibility. |
| Packaging and assets | `koto.spec`, `build_cython.py`, `scripts/download_vendors.py`, `config/frontend_asset_budgets.json` | Already partially single-sourced; future vendor or hidden-import drift is still possible. | Keep asset budgets and vendor reference graph as the acceptance gate. |

## Large-File Hotlist

Top hotspots from the current audit:

| Path | Lines | Batch |
| --- | ---: | --- |
| `web/static/css/workspace.css` | 12652 | Frontend CSS ownership |
| `app/core/agent/task_tools.py` | 6716 | File-task tool contract |
| `app/core/agent/file_task_runtime.py` | 5854 | File-task runtime split |
| `web/static/css/style.css` | 5782 | Global style ownership |
| `app/core/file/parsers/docx_parser.py` | 4118 | DOCX parser service split |
| `web/tiptap-editor/koto-docx-editor.js` | 3607 | DOCX editor guards |
| `web/app.py` | 3501 | Runtime-context shrink |
| `web/document_feedback.py` | 3375 | Document feedback service split |
| `web/tiptap-editor/docx-extensions.js` | 3325 | DOCX extension packaging |
| `web/src/workspace/task-runner.ts` | 2696 | Task presentation split |

## Deletion Rules

Do not delete by name alone. A cleanup candidate is deletable only when all of
these are true:

1. No production import, route, template, bundled asset, or packaging hidden
   import still points to it.
2. Tests have moved to the canonical owner rather than pinning the compatibility
   path.
3. A guard test prevents the retired route, import, asset, or alias from
   returning.
4. For frontend paths, `npm --prefix web run build` has regenerated the bundle
   and a browser or contract test covers the visible behavior.

## Batch Plan

### Batch 1: Evidence And Guardrails

Status: completed.

- Extend `scripts/audit_code_baseline.py` to report large production files.
- Keep the deleted agent-loop hit list at zero.
- Keep frontend vendor reference graph and asset budgets in the audit output.
- Record this inventory as the shared cleanup map.

Validation:

```powershell
python -m pytest tests\unit\test_audit_code_baseline.py -q
python scripts\audit_code_baseline.py
```

### Batch 2: File-Task Classification Packaging

Status: completed.

Goal: reduce scattered `file_task_classification_*` modules into a package-level
surface without changing classification behavior.

Completed in this pass:

- Added `app/core/agent/file_task_classification/__init__.py` as the canonical
  import surface for classification, intent adjudication, and decision-context
  helpers.
- Moved `FileTaskRuntime` classification-related imports to the package surface
  instead of direct leaf-module imports.
- Updated architecture tests to enforce the package surface while keeping leaf
  helper implementation tests in place.

Candidate moves:

- `app/core/agent/file_task_classification_*.py`
- `app/core/agent/file_task_intent_*.py`
- `app/core/agent/file_task_decision_context.py`

Acceptance:

```powershell
python -m pytest tests\unit\test_file_task_classification_*.py -q
python -m pytest tests\unit\test_file_task_routing_decision_contract.py -q
python -m pytest tests\unit\test_ai_task_chain_architecture.py -q
```

### Batch 3: File Tool Contract Shrink

Status: completed.

Goal: make `task_tools.py` delegate more pure filesystem behavior to canonical
services while preserving marker-text and artifact contracts.

Completed in this pass:

- Added an internal `FileService` factory for `task_tools.py`.
- Changed public `copy_file()` to delegate the copy operation to
  `FileService.copy_file(..., overwrite=True)` while keeping the standard
  `copy_file` file-change payload.
- Preserved write-blocked payload mapping for permission failures.
- Made `app.core.file.register_file_tools` a lazy package export, avoiding the
  `file_service -> app.core.file.path_policy -> app.core.file.__init__ ->
  file_tools -> file_service` import cycle.

Candidate owners:

- `app/core/services/file_service.py`
- `app/core/file/path_policy.py`
- `app/core/agent/task_tools.py`

Acceptance:

```powershell
python -m pytest tests\unit\test_task_tools_file_task_contracts.py -q
python -m pytest tests\unit\test_file_tools_coverage.py -q
python -m pytest tests\integration\test_file_hub_routes.py -q
```

### Batch 4: Workspace Task Presentation Split

Status: completed.

Goal: keep process-first and report-last behavior stable while reducing the
size and overlap of task UI modules.

Completed in this pass:

- Added shared task report layout helpers in
  `web/src/workspace/task-report-layout.ts` for compact text, unique text
  extraction, stage mapping, action text, status text, and status classes.
- Moved `task-workbench.ts` to consume those helpers through explicit aliases,
  removing its local duplicate stage/status helper definitions.
- Added an architecture guard that keeps shared task presentation helpers out
  of `task-workbench.ts`.
- Rebuilt the workspace bundle after the source split.

Candidate owners:

- `web/src/workspace/task-runner.ts`
- `web/src/workspace/task-workbench.ts`
- `web/src/workspace/task-report-layout.ts`
- `web/static/css/workspace.css`

Acceptance:

```powershell
npm --prefix web run typecheck
npm --prefix web run build
python -m pytest tests\unit\test_workspace_task_presentation_architecture.py -q
python -m pytest tests\unit\test_workspace_ai_task_flow_guards.py -q
```

### Batch 5: Runtime Context Shrink

Status: completed.

Goal: reduce remaining compatibility exports and named singleton lookups from
`web.app` by moving callers to canonical runtime modules.

Completed in this pass:

- Added `web/runtime_services.py` for lazy-loaded services that do not need the
  transitional `web.app` bridge.
- Removed 16 lazy service accessors from `web/runtime_context.py`, leaving it
  focused on compatibility access to globals still owned by `web.app`.
- Moved service-style blueprints to import lazy service accessors from
  `web.runtime_services`: analytics, proactive, execution, knowledge,
  file-editor, and file-organize.
- Added architecture guards to prevent those lazy service accessors from
  flowing back into `runtime_context.py` or the service blueprints.

Candidate owners:

- `web/app.py`
- `web/runtime_context.py`
- `web/runtime_services.py`
- `web/services/chat_stream/*`
- `web/app_factory.py`

Acceptance:

```powershell
python -m pytest tests\unit\test_architecture_guardrails.py -q
python -m pytest tests\test_ai_stream.py -q --tb=short
python -m pytest tests\unit\test_web_app_coverage.py -q --tb=short
```

### Batch 6: Workspace Task-Stream Contract Split

Status: completed.

Goal: keep the workspace file-task stream on one frontend/backend contract while
splitting parser, dispatcher, status, and report-layout concerns into named
owners.

Completed in this pass:

- Added `web/src/workspace/file-task-sse.ts` as the transport-frame parser.
- Added `web/src/workspace/file-task-dispatch.ts` as the event dedupe and
  injected-handler dispatcher.
- Added `web/src/workspace/file-task-status.ts` as the single terminal-status
  normalization and copy source for workspace file-task UI.
- Added `web/src/workspace/task-report-layout.ts` as the shared process/report
  layout helper source.
- Moved `task-runner.ts`, `task-workbench.ts`, history restore, file utilities,
  and result surfaces to those shared owners.
- Removed the old chat-stream file-task adapter; file tasks execute through
  `/api/editor/ai/task-stream`, while `/api/chat/stream` now blocks legacy
  file-task execution instead of producing a second completion contract.
- Started the task terminal persistence watcher in `task-dispatcher.ts` after
  the initial partial task turn is persisted, so terminal cards still get saved
  when the final stream promise and DOM snapshot timing diverge.
- Rebuilt `web/static/js/build/workspace-bundle.js` from the TypeScript source.

Candidate owners:

- `web/file_task_stream.py`
- `web/blueprints/editor_ai.py`
- `web/src/workspace/task-runner.ts`
- `web/src/workspace/task-dispatcher.ts`
- `web/src/workspace/file-task-sse.ts`
- `web/src/workspace/file-task-dispatch.ts`
- `web/src/workspace/file-task-status.ts`
- `web/src/workspace/task-report-layout.ts`

Acceptance:

```powershell
npm --prefix web run typecheck
npm --prefix web run build
Push-Location web; npx eslint src/workspace/file-task-dispatch.ts src/workspace/task-dispatcher.ts --ext .ts; Pop-Location
python -m pytest tests\unit\test_backend_frontend_stream_contract.py -q --tb=short
python -m pytest tests\unit\test_workspace_ai_task_flow_guards.py::test_workspace_unified_assistant_uses_model_route_before_whitebox -q --tb=short
python -m pytest tests\e2e\test_workspace_ai_assistant.py -q --tb=short
python scripts\run_ai_assistant_flow_tests.py full
git diff --check
```

### Batch 7: Editor Selection Context And Workspace Accessibility

Status: completed.

Goal: keep editor-originated AI context structured and keep hidden workspace
surfaces out of the active interaction path while preserving the visible task
report order.

Completed in this pass:

- Added structured XLSX selection payloads with sheet name, A1 range, row/column
  counts, TSV text, AI text, and preview text from the Univer bridge.
- Moved the XLSX workspace editor to pin the structured payload instead of only
  plain selected text.
- Removed the PPTX legacy array-to-rich adapter and made the editor require
  structured slide data, while keeping snake_case field normalization for parsed
  PPTX payloads.
- Marked the hidden legacy workspace view with `aria-hidden` and `inert`, with
  embedded-mode code responsible for restoring/removing those attributes.
- Added the AI session clear-history surface and stable summary id.
- Kept the artifact panel before messages and live progress in both workspace
  templates so outputs remain visible above the conversational tail.
- Rebuilt the TipTap, Univer, and workspace bundles after source edits.

Candidate owners:

- `web/src/editors/xlsx-editor.ts`
- `web/univer-editor/sheets-main.js`
- `web/src/editors/pptx-editor.ts`
- `web/src/ui/selection-toolbar.ts`
- `web/templates/index.html`
- `web/templates/workspace.html`

Acceptance:

```powershell
npm --prefix web run typecheck
npm --prefix web run build
python -m pytest tests\unit\test_workspace_render_perf_guards.py -q --tb=short
python -m pytest tests\unit\test_workspace_ai_task_flow_guards.py::test_workspace_selection_context_reaches_ai_chat_and_tasks -q --tb=short
python -m pytest tests\unit\test_workspace_ai_task_flow_guards.py::test_workspace_main_view_inerts_legacy_chat_entrypoint -q --tb=short
python -m pytest tests\unit\test_ai_session_history_ui_guards.py -q --tb=short
python -m pytest tests\unit\test_docx_format_hoverbar_guard.py -q --tb=short
git diff --check
```

### Batch 8: Task Step Label Ownership Split

Status: completed.

Goal: keep task execution/rendering in `task-runner.ts` separate from static
tool labels, step titles, and plan-violation copy.

Completed in this pass:

- Added `web/src/workspace/task-step-labels.ts` as the owner for tool display
  labels, internal/read-tool classification, always-suppressed tool-finished
  names, extra step titles, and plan-violation labels.
- Moved local label tables and small text helpers out of
  `web/src/workspace/task-runner.ts`.
- Updated `task-runner.ts` to import named helpers from `task-step-labels.ts`
  while keeping stream event handling unchanged.
- Added architecture guards so label tables do not drift back into
  `task-runner.ts`.
- Rebuilt the workspace bundle from the TypeScript source.

Candidate owners:

- `web/src/workspace/task-runner.ts`
- `web/src/workspace/task-step-labels.ts`
- `web/src/workspace/task-report-layout.ts`

Acceptance:

```powershell
npm --prefix web run typecheck
npm --prefix web run build
python -m pytest tests\unit\test_workspace_task_presentation_architecture.py -q --tb=short
python -m pytest tests\unit\test_workspace_ai_task_flow_guards.py::test_workspace_file_task_steps_are_user_visible_whitebox_stages -q --tb=short
git diff --check
```

### Batch 9: Task Final Report Rendering Split

Status: completed.

Goal: keep final-answer extraction and markdown rendering separate from the
task stream event runner.

Completed in this pass:

- Added `web/src/workspace/task-final-report.ts` as the owner for terminal
  answer extraction, compact flow summaries, long-answer detection, markdown
  normalization, and readable HTML fallback rendering.
- Moved final report helpers out of `web/src/workspace/task-runner.ts` while
  keeping run-finished event handling and DOM insertion in place.
- Updated architecture guards so final-report helpers do not drift back into
  `task-runner.ts`.
- Rebuilt the workspace bundle from the TypeScript source.

Candidate owners:

- `web/src/workspace/task-runner.ts`
- `web/src/workspace/task-final-report.ts`
- `web/src/workspace/task-report-layout.ts`

Acceptance:

```powershell
npm --prefix web run typecheck
npm --prefix web run build
python -m pytest tests\unit\test_workspace_task_presentation_architecture.py -q --tb=short
python -m pytest tests\unit\test_workspace_ai_task_flow_guards.py::test_workspace_task_workbench_is_split_and_mounted -q --tb=short
python -m pytest tests\unit\test_workspace_ai_task_flow_guards.py::test_workspace_task_renderer_compacts_tool_result_details -q --tb=short
git diff --check
```

### Batch 10: Task Performance Summary Split

Status: completed.

Goal: keep performance timing aggregation and model-summary state updates out
of the task stream event runner while leaving DOM row insertion local to the
runner.

Completed in this pass:

- Added `web/src/workspace/task-performance.ts` as the owner for model-summary
  state, task performance source merging, duration formatting, encoded dataset
  updates, and model summary text generation.
- Moved timing aggregation helpers out of `web/src/workspace/task-runner.ts`.
- Changed `task-runner.ts` to call `updateTaskPerformanceDataset()` before
  writing the `data-task-performance` value and performance row.
- Changed model summary handling to call `updateModelSummaryState()` while
  keeping the existing task-row DOM update in place.
- Added architecture guards so performance helpers and model-summary state do
  not drift back into `task-runner.ts`.
- Rebuilt the workspace bundle from the TypeScript source.

Candidate owners:

- `web/src/workspace/task-runner.ts`
- `web/src/workspace/task-performance.ts`

Acceptance:

```powershell
npm --prefix web run typecheck
npm --prefix web run build
python -m pytest tests\unit\test_workspace_task_presentation_architecture.py -q --tb=short
python -m pytest tests\unit\test_workspace_ai_task_flow_guards.py::test_workspace_task_workbench_is_split_and_mounted -q --tb=short
git diff --check
```

## Stop Conditions

Pause a cleanup batch if one of these happens:

- A user-facing file task can no longer show progress, final report, or produced
  artifacts.
- A frontend bundle rebuild changes the live entrypoint without a matching
  template or browser check.
- A compatibility path still has production callers but a deletion patch tries
  to remove it.
- A broad test failure cannot be separated from unrelated dirty-worktree state.
