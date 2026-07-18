# Koto overall optimization execution

Started: 2026-07-16

This is the live execution ledger for the current structural optimization.
It supplements the historical roadmaps and records the active worktree rather
than assuming the 2026-07-12 inventory is still current.

## Working rules

1. Preserve unknown or user-owned files until their owner and purpose are known.
2. Retired paths are removed end to end; do not restore compatibility shims
   merely to keep old imports alive.
3. Every runtime symbol, route, global bridge, and lifecycle transition has one
   authoritative owner.
4. Each cleanup slice ends with focused tests, `git diff --check`, and a scan
   proving the retired entrypoint is no longer active.
5. Generated frontend bundles are verified from `web/src/`; they are not edited
   as an independent source tree.
6. A dirty worktree is never treated as release evidence. Final validation must
   use a clean candidate assembled from the intended source set.

## Step 1 - Worktree freeze and cleanup boundary

Status: completed

### Current tracked delta

- 234 tracked paths changed: 222 modified and 12 deleted.
- Approximate tracked diff: 7,855 insertions and 9,274 deletions.
- The current branch is behind its upstream by three commits.

### Confirmed retired paths

The following tracked paths are intentionally deleted and must not be restored:

- `app/core/memory/memory_reflector.py`
- `tests/unit/test_memory_manager.py`
- `web/audio_overview.py`
- `web/enhanced_memory_manager.py`
- `web/memory_integration.py`
- `web/memory_manager.py`
- `web/src/shared/sse-pipeline.ts`
- `web/src/shared/task-preclassify.test.ts`
- `web/src/shared/task-preclassify.ts`
- `web/src/workspace/notebook.ts`
- `web/src/workspace/task-refresh.ts`
- `web/templates/notebook_lm.html`

References that remain in architecture tests or retained-legacy documentation
are negative guards proving these paths stay deleted, not active consumers.

### Current untracked source set

These files are implementation source and must be reviewed with their owners:

- `app/core/agent/file_task_failure.py`
- `app/core/agent/file_task_financial_report_recovery.py`
- `app/core/agent/file_task_preflight_policy.py`
- `app/core/agent/task_tools_docx_table_helpers.py`
- `app/core/config/workspace_runtime.py`
- `app/core/memory/conversation_memory_extractor.py`
- `app/core/services/image_manager.py`
- `app/core/services/system_info.py`
- `web/src/bundles/frontend-observer.ts`
- `web/src/bundles/image-viewer.ts`
- `web/src/bundles/pdf-viewer.ts`
- `web/src/bundles/pptx-editor.ts`
- `web/src/bundles/xlsx-editor.ts`
- `web/src/shared/frontend-observer-loader.ts`
- `web/src/shared/selection-runtime.ts`

The associated ten untracked tests are source tests, not disposable output.
The generated frontend bundle files under `web/static/js/build/` must be
regenerated and verified from the corresponding `web/src/bundles/` entries.

### Safe noise cleanup

Root `.pytest_*.xml` files are local JUnit/debug reports. They are ignored by a
narrow root-only rule and may be deleted without affecting runtime or fixtures.

## Step 2 - Frontend entrypoint and lifecycle cleanup

Status: completed

### Retired path verification

- The deleted SSE pipeline, task pre-classifier, task-refresh module, notebook
  module/template, audio overview, and web memory bridges have no current source
  or generated-bundle consumer.
- References retained in tests, packaging scans, or retained-legacy
  documentation are negative guards or historical compatibility notes.
- `run.error` is not an active file-task terminal event. The generic transport
  `error` event is normalized through the single `run.finished` terminal
  renderer.
- `needs_attention` and `no_file_change` remain only at persisted-data
  compatibility boundaries. Current runtime and frontend status owners do not
  produce them.
- The frontend observer has one installer bundle and one idle loader. The
  workspace bundle does not contain a second observer installer.
- XLSX loading uses `KotoXlsxEditorModule`; there is no active
  `window.KotoXlsxEditor` editor owner.

### Public runtime surface reduction

`web/src/workspace/task-runner.ts` is loaded for side effects, but it previously
published 24 internal functions and state helpers through the shared workspace
global. The public surface is now limited to eight actual cross-module
contracts:

- `streamTaskFlow`
- `makeRunCard`
- `compactTaskContract`
- `decodeTaskContract`
- `restoreTaskRunCard`
- `resumePersistedFileTask`
- `syncTaskInteractionSummary`
- `processFileTaskStreamEvent`

Internal event handlers, status objects, parser helpers, and cancellation
details are no longer available as alternate global entrypoints.

### Verification

- Focused frontend/backend architecture suite: 40 passed.
- `npm --prefix web run typecheck`: passed.
- `npm --prefix web run build`: passed; all bundle budgets met.
- `git diff --check` for the slice: passed.
- Direct Playwright collection reached the workspace E2E suite, but the local
  browser fixture did not start within its timeout. This is recorded as an
  environment-level live-browser validation item for the final release pass,
  not treated as a source-test regression.

## Step 3 - Backend shim and service-owner cleanup

Status: completed

### Removed compatibility modules

The following web-layer aliases were removed after all runtime, test, startup,
and packaging consumers were migrated to their authoritative owners:

- `web/system_info.py` -> `app/core/services/system_info.py`
- `web/image_manager.py` -> `app/core/services/image_manager.py`
- `web/settings.py` -> `app/core/config/user_settings.py`
- `web/config/__init__.py` -> `web/shared.py`

The PyInstaller hidden-import list no longer preserves the deleted web aliases.
Startup diagnostics, graceful shutdown, model selection, agent executors, chat
system context, and context injection now import their Core owners directly.

### Retired status containment

`app/core/artifacts/models.py` no longer recognizes the retired
`needs_attention` status. Compatibility translation for old persisted sessions
is limited to `web/blueprints/sessions.py` and `web/file_task_stream.py`.
Current Core runtime, artifact models, and frontend status owners use only the
canonical status vocabulary.

### Architecture ratchet

- Three files were removed from the explicit Core-to-Web import debt allowlist.
- New guardrails require settings, system information, image management, and
  web configuration helpers to keep one owner and prevent the deleted aliases
  from returning.

### Verification

- Combined architecture, artifact, file-task, workspace-flow, and web-app
  coverage suite: 337 passed.
- Service-owner, startup, shutdown, provider, and migrated module suites:
  237 passed in the focused owner pass.
- Retired-import scans show no active consumer of `web.settings`,
  `web.system_info`, `web.image_manager`, or `web.config`.
- `git diff --check` for the slice: passed.

## Step 4 - File-task idempotency and failed-output containment

Status: completed

### Financial report transaction boundary

The deterministic financial-report recovery path no longer writes directly to
the requested final DOCX. It now:

1. Resolves a run-scoped hidden staging file in the target directory.
2. Writes paragraphs, the compact financial table, and both chart images only
   to that staging DOCX.
3. Holds all `file.changed` events until every required tool succeeds.
4. Atomically replaces the final target only after the complete report exists.
5. Rewrites staged change records to the requested final path before publishing
   them.

### Failed-run cleanup

If any required recovery step or the final commit fails:

- the staging DOCX is deleted;
- charts created by that failed recovery are deleted unless they existed before
  the run;
- no artifact or file change is returned as a successful output;
- no `file.changed` event is emitted for the partial report.

Existing user files are not broadly deleted on quality failure. Cleanup is
limited to run-owned staging and newly-created recovery artifacts.

### Duplicate-output protection

- New financial report target inference continues to choose a non-existing
  numbered path rather than appending to an older generated report.
- The DOCX quality gate rejects repeated Title blocks and duplicate identical
  tables.
- A retry therefore starts from a fresh target or a run-owned staging file,
  rather than continuing an incomplete generated body.

### Verification

- Full financial-report runtime suite: 27 passed.
- Failure, artifact-result, and read-only terminal suites: 28 passed.
- Success-path assertion confirms no staging path is exposed in
  `file.changed`.
- Failure-path assertion confirms the partial DOCX and newly created charts are
  removed and the final target is absent.
- `git diff --check` for the slice: passed.

## Step 5 - Guarded high-coupling extraction

Status: completed

### Extracted owner

Run-owned generated artifact transactions now live in:

- `app/core/agent/file_task_artifact_transaction.py`

This module is the single owner for:

- resolving write targets through the canonical task-tool path resolver;
- creating hidden run-scoped staging paths;
- deleting only run-owned failed artifacts while preserving pre-existing
  files;
- atomically publishing a completed staging artifact;
- rewriting staged file-change paths to the final public target.

The financial report recovery module now consumes this boundary and no longer
owns `os.replace`, staging-name construction, or generic failed-artifact
cleanup.

### Scope control

The dirty worktree makes a bulk split of `task_tools.py`,
`file_task_runtime.py`, or `task-runner.ts` unnecessarily conflict-prone.
This step therefore extracted the reusable transaction seam and added a
ratcheting owner/line-budget guard without relocating unrelated active logic.

### Verification

- Transaction, financial runtime, and task-chain architecture suite:
  46 passed.
- Architecture and terminal-failure guard suite: 76 passed.
- Dedicated transaction tests cover staging-name isolation, atomic replacement,
  preservation of pre-existing artifacts, cleanup of new failed artifacts, and
  final-path change rewriting.
- `git diff --check` for the slice: passed.

## Step 6 - Source, browser, and live-product validation

Status: completed for the current source/worktree scope

### Source and release lane

- `npm --prefix web run typecheck`: passed.
- `npm --prefix web run build`: passed; all bundle budgets met.
- Workspace bundle: approximately 508.9 KB of a 550 KB budget.
- AI assistant `release` lane: 118 passed.
- Final workspace assistant plus open-file browser slice: 17 passed.
- Targeted structural and owner suites executed during Steps 1-5 remained
  green after the final rebuild.

### Live Koto service

- `GET /api/info`: HTTP 200.
- `GET /api/health`: healthy; required blueprints, disk, and Ollama checks all
  reported `ok`.
- The original financial report and the deduplicated report both opened through
  the real `/api/v1/workspace/open_file_by_path` route with the current CSRF
  contract and returned DOCX editor payloads.
- The direct API produced approximately 622 KB of editor HTML for the original
  report and 580 KB for the deduplicated report.

### Browser regression found and fixed

The release browser lane exposed a real presentation issue: the
`image_insert_guard` recovery message was written only to transient header
state and then lost during terminal process compaction. The final task card now
persists:

- `补充图表`
- `正在将已生成图表写入 Word`

without exposing the internal tool name. The previously failing browser test
now passes, and the full release lane is green.

### Artifact state

- No `*.koto-partial*` file remains in `workspace/`.
- The original report remains preserved as historical evidence: two Title
  paragraphs and two identical tables.
- The deduplicated report contains one Title paragraph, one table, two inline
  chart images, and no duplicate table fingerprint.

### Remaining release boundary

The source/product path is structurally stable for the optimized scope, but the
repository is still a large dirty worktree and the current branch remains three
commits behind its upstream. Portable/installer packaging and clean-candidate
SHA verification should be performed only after the intended source set is
split or staged into a clean release candidate.

## Step 7 - Worktree hygiene and retired-reference closure

Status: completed for the current cleanup slice

### Safe runtime cleanup

- Removed 17 local JUnit reports and stale PID files from `.codex-runtime/`.
- Both recorded process IDs were verified stale before removal.
- Added a root-scoped `/.codex-runtime/` ignore rule so subsequent validation
  runs cannot reintroduce these files into the untracked source inventory.
- After this cleanup, every remaining untracked path is implementation source,
  a source test, documentation, or a generated bundle paired with a current
  TypeScript entrypoint.
- The proactive-feature and trigger-parameter tests no longer write SQLite
  state into `config/`; each test now receives an isolated pytest temporary
  directory, and the manual runners use an OS temporary directory.
- Seven `config/test_*.db` files and `config/skill_ratings.json` were already
  classified by `.gitignore` as runtime artifacts but remained tracked from
  the legacy layout. They have now been removed from the Git index while their
  local copies remain available to the running application and developer.

### Retired-reference closure

- Current runtime source has no consumer of the deleted system-info,
  image-manager, settings, memory, notebook, task-refresh, or review-bundle
  compatibility paths.
- Historical integration guides now import system information from
  `app.core.services.system_info`.
- The architecture stabilization guide now identifies
  `app.core.config.user_settings.SettingsManager` as the settings owner.
- The frontend reachability guard uses the six current independent entrypoints:
  DOCX review, frontend observer, image viewer, PDF viewer, PPTX editor, and
  XLSX editor. It no longer treats the deleted aggregate review bundle as a
  source root.

### Commit boundary map

The current worktree must be assembled in coherent groups, without mixing
runtime state into code commits:

1. Core owners and configuration runtime: settings, workspace runtime, memory
   extraction, system information, and image management.
2. File-task correctness: preflight, failure contract, artifact transaction,
   financial-report recovery, runtime wiring, and their focused tests.
3. Frontend ownership: independent editor/review bundles, workspace lifecycle
   modules, retired aggregate entrypoints, templates, generated bundles, and
   frontend contract tests.
4. Packaging and dependency updates: specifications, installer scripts,
   requirements, CI configuration, and their validation tests.
5. Documentation and guardrails: current architecture guidance, retained
   legacy notes, execution ledger, and negative import/asset guards.

The following tracked runtime state is explicitly excluded from all source
groups until its ownership is reviewed separately:

- RAG index metadata JSON files;
- skill rating state;
- suggestions and user-behavior databases;
- test behavior/context/dialogue/execution/notification/trigger databases.

### Verification

- Retired runtime import scan: no active residual references.
- Independent bundle mapping: all six source entrypoints are present in the
  build script and workspace asset registry.
- Retired `review.ts` and `review-bundle.js(.map)` files remain absent.
- Focused architecture, memory-owner, frontend-route, frontend-quality, and
  workspace-retirement suite: 194 passed.
- Proactive-feature and trigger-parameter runtime-isolation suite: 11 passed.

## Step 8 - Personal runtime data isolation

Status: completed

### Removed repository-owned runtime state

The following paths were already generated or mutated by normal application
use and are now removed from the Git index while remaining on the local disk:

- `config/file_rag_index/`
- `config/memory_rag_index/`
- `config/suggestions.db`
- `config/user_behavior.db`

Both SQLite owners create their directory, schema, and indexes when initialized.
The FAISS directories were already covered by `.gitignore`; their changing
document counts and timestamps confirmed that they are runtime indexes rather
than source fixtures.

### Test isolation closure

- `tests/test_smart_features.py` is now an explicitly manual demo instead of an
  accidentally collected pytest module.
- The demo runs under an OS temporary working directory, so its sample files,
  knowledge graph, behavior database, suggestions database, and report export
  do not modify the checkout.
- A new runtime-data hygiene guard prevents the ignored database/index paths or
  repository-targeting test database literals from returning.

### Verification

- Runtime database owner and proactive feature suite: 27 passed.
- The full smart-feature demo completed successfully.
- Git status before and after the demo was identical.

## Step 9 - Ignored-file and packaged-default closure

Status: completed

### Tracked-ignore debt removed

The repository no longer contains any path that is simultaneously tracked and
matched by `.gitignore`. The cleanup includes:

- coverage output;
- generated E2E screenshots;
- local skill bindings and trigger state;
- generated training samples;
- work-file-library runtime data;
- user-uploaded files.

The local bindings, triggers, training samples, work-file database, and uploads
were preserved. Only disposable coverage and screenshot output was removed from
disk. `web/uploads/.gitkeep` is now the sole tracked upload-directory entry.

### Packaged defaults separated from personal state

`skill_bindings.json`, `skill_ratings.json`, and `triggers.json` are no longer
required packaged defaults. Release checks and installer E2E expectations now
exclude them, and `koto.spec` explicitly prevents a local build from packaging
these files even when they exist in the developer's runtime config.

Fresh-runtime verification with an empty `KOTO_DB_DIR` created:

- 7 recommended triggers;
- 42 recommended skill bindings.

This proves the runtime owners can initialize a clean installation without
shipping mutable developer state.
