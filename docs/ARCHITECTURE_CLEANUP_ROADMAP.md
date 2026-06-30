# Koto Architecture Cleanup Roadmap

Last updated: 2026-06-18

## Goal

Separate Koto's conversation experience from file-work execution without a
large risky rewrite. The cleanup should reduce hidden coupling, keep current
user flows working, and make future deletions test-backed instead of
guess-based.

## Current Baseline

| Area | Current shape | Cleanup direction |
| --- | --- | --- |
| `web/app.py` | Flask assembly plus remaining runtime globals, about 3.7k lines | Keep routes out; migrate globals behind explicit services |
| `web/runtime_context.py` | Temporary accessor layer for globals still owned by `web.app` | Shrink accessor usage batch by batch |
| `web/blueprints/*` | Main route surface already moved out of `web.app` | Keep this as the extension point |
| `app/core/agent/file_task_runtime.py` | File-task orchestration plus many extracted helper modules | Stabilize contracts before further splitting |
| `app/core/file/*` | Parser/exporter split has mostly landed | Add focused regression tests and clean silent exceptions |
| `web/static/js/workspace-assistant.js` | Workspace UI monolith, about 14k lines | Extract modules behind the existing facade |
| `web/static/js/app.js` | Main app/chat monolith, about 9.3k lines | Extract shared SSE and chat/session modules |

## Architectural Boundaries

Koto should converge on these ownership lines:

- `web/app.py`: process startup, Flask app construction, top-level runtime
  compatibility only.
- `web/app_blueprints.py`: route registration and environment-gated blueprint
  loading.
- `web/blueprints/*`: request parsing and HTTP response mapping.
- `web/services/*`: web-facing orchestration that is not route-specific.
- `app/core/agent/chat_pipeline.py`: normal conversation pipeline.
- `app/core/agent/file_task_runtime.py`: file-task orchestration only.
- `app/core/file_assistant/*`: workspace file open/save/preview/filesystem
  services.
- `app/core/file/*`: document parsing, exporting, and file-format utilities.
- `app/core/skills/*`: skill registration, matching, permissions, and runner
  behavior.

## Phase Plan

### Phase 0: Guardrails and Baseline

- Keep business behavior unchanged.
- Lower the `web/app.py` line budget to the current reduced size.
- Lock direct `from web.app import ...` usage behind a small allowlist.
- Record dirty-worktree baseline before larger refactors.
- Keep route additions flowing through blueprints.

### Phase 1: Backend Boundary Cleanup

- Replace `runtime_context.get_app_attr()` call sites with explicit service
  accessors when a stable owner exists.
- Move remaining global service factories out of `web.app` into a small runtime
  service module.
- Standardize API responses through `app.api.response_utils`.
- Gate dev/training/debug blueprints by environment flags.

### Phase 2: File Task Contract Stabilization

- Treat `FileTaskRequest -> IntentPlan -> ExecutionBrief -> ToolResult ->
  ArtifactResult` as the stable execution chain.
- Keep readonly analysis and write/generate tasks explicitly separated.
- Add regression tests for DOCX annotation, PPTX edits, XLSX read/write, PDF
  page-window reads, and follow-up file tasks.
- Reduce legacy marker text only after artifact contracts cover the same cases.

### Phase 3: Frontend Module Extraction

- Extract shared SSE parsing for chat and file-task streams.
- Split workspace file tree, tab manager, editor bridge, save flow, AI task
  panel, and task result rendering.
- Keep `workspace-assistant.js` as a facade during migration.
- Add browser smoke/guard tests for each extracted global entrypoint.

### Phase 4: Legacy Removal

- Remove only code that has no production references, no packaging dependency,
  and updated tests.
- Prioritize deprecated endpoints, duplicated PPT/workspace paths, dead CSS/JS,
  and modules imported only by low-value tests.
- Update packaging hidden imports alongside every deletion.

### Phase 5: Quality Ratchet

- Tighten line budgets after each successful shrink.
- Add import guards for direct `web.app` coupling.
- Add response-contract tests for API surfaces.
- Track silent exception cleanup with focused tests around fallback behavior.

## Operating Rules

- Do not add routes to `web/app.py`.
- Do not reintroduce deleted compatibility shims.
- Prefer explicit service modules over broad runtime-context access.
- Do not delete compatibility paths until tests and packaging agree.
- Keep each cleanup batch small enough to review and bisect.
