# Koto Architecture Stabilization Plan

Last updated: 2026-06-05

## Goal

Reduce the failure radius of the current Flask monolith without risky cleanup.
Deletion and large rewrites should happen only after import paths, packaging
hidden imports, and regression tests agree.

## Current Verified Risk

| Area | Status | Stabilization rule |
| --- | --- | --- |
| `web/app.py` | Large legacy entrypoint with global state and no direct business route decorators | Do not add new routes here; move new endpoints to blueprints |
| `web/app_blueprints.py` | Central route registry already exists | Treat this as the primary route extension point |
| `web/voice_api_enhanced.py` | Removed compatibility shim for `web.blueprints.voice` | Do not reintroduce; use `web.blueprints.voice` directly |
| `web/settings_backup.py` | Removed backup settings implementation | Do not reintroduce; use `web.settings.SettingsManager` |
| `launcher/__init__.py` | Package marker only | Keep side-effect free |
| Workflow runtime | Old `workflow_engine.py` and LangGraph runtime both in use | Migrate callers in batches with tests per workflow family |
| External planners | Retired external planner adapters have been removed | Default registry is empty |
| Legacy microphone voice stack | Removed old microphone modules and routes | Keep upload-based `/api/voice/stt` plus text-only `/api/speech/extract-actions` |

## Guardrails Added

- `tests/unit/test_architecture_guardrails.py` parses `web/app.py` without
  importing it and locks the current direct `@app.route` surface.
- The same test keeps a line-count budget on `web/app.py` so new work does not
  quietly expand the monolith.
- Removed compatibility shims are asserted absent from `koto.spec` so bundled
  builds do not pull dead modules back into the runtime surface.
- `launcher/__init__.py` no longer prints during import.
- Legacy PPT endpoints have been removed; PPT routes are served by
  `web.blueprints.ppt_api_routes`.
- Non-streaming chat and file upload chat now live in `web.blueprints.chat`.
- File-task, editor stream, chart, and skill-list endpoints now live in
  `web.blueprints.editor_ai`; `web.app` only keeps non-route compatibility
  wrappers for old imports.
- Direct production imports from `web.app` are locked to zero by
  `tests/unit/test_architecture_guardrails.py`; runtime compatibility should
  flow through `web.runtime_context` while globals are migrated to services.
- Chat routes, chat stream handlers, and file-upload chat handlers now use
  named `web.runtime_context` accessors instead of stringly typed
  `get_app_attr(...)` lookups; a guard test keeps that boundary from regressing.
- Session and settings blueprints now also use named `web.runtime_context`
  accessors for app version, API key, session manager, brain, proxy detection,
  and client factory lookups.
- `web.blueprints.editor_ai` now uses named runtime accessors for
  `SmartDispatcher` and client factory fallback; guard tests reject
  `get_app_attr(...)` in the active chat/session/settings/editor AI surfaces.
- Service blueprints for analytics, proactive features, execution, knowledge,
  file editing, and file organization now use named runtime accessors backed
  by lazy loaders instead of `call_app_factory(...)`; guard tests keep
  `web.blueprints` free of stringly typed runtime factory calls.
- `call_app_factory(...)` now has no production callers outside
  `web.runtime_context`; it remains compatibility-only while remaining lazy
  runtime globals are replaced with explicit accessors.
- `get_app_attr(...)` now has no production callers outside
  `web.runtime_context`; runtime globals are exposed through named accessors
  such as `get_create_client()` and `get_operation_history()`.
- `WebSearcher` implementation now lives in `web.web_searcher`; `web.app`
  only re-exports the class for compatibility, and the app line-count budget
  has been lowered to keep the migration from regressing.
- `ContextAnalyzer` implementation now lives in `web.context_analyzer`;
  `web.app` only re-exports the class for compatibility, and guard tests keep
  the context analysis logic out of the monolith.
- `Utils` implementation now lives in `web.utils.assistant_utils`;
  `web.runtime_context.get_utils()` resolves the utility class directly, while
  `web.app` keeps only the compatibility re-export.
- `SessionManager` implementation now lives in `web.session_manager`; `web.app`
  keeps the compatibility re-export and owns only the active `session_manager`
  instance.
- Unit tests for `WebSearcher`, `ContextAnalyzer`, `Utils`, and
  `SessionManager` now import their real modules instead of `web.app`; guard
  tests keep those migrated tests from reviving old compatibility imports.
- Unit tests for `StreamInterruptManager`, SSE sanitization, filename
  sanitization, proxy normalization, prompt extraction, fake Gemini responses,
  and interactions-only model checks now target their service/helper modules
  instead of `web.app`.
- Chat system instruction generation now lives in
  `web.chat_system_instruction`, and FILE_GEN time parsing/context generation
  now lives in `web.filegen_time_context`; `web.app` keeps only private alias
  imports for runtime compatibility.
- `LocalDispatcher` implementation now lives in `web.local_dispatcher`; `web.app`
  keeps only the compatibility import for the Ollama fallback route helper.
- The active file-task chat stream path now imports
  `stream_file_task_chat_request`; the old `stream_legacy_file_task`
  compatibility alias has been removed.
- Memory API registration now happens in `web.app_blueprints`, not at the
  bottom of `web.app`; a guard keeps `memory_api_routes` out of the monolith.
- Memory runtime helpers now live in `web.memory_runtime`; `web.app` only
  re-exports `get_memory_manager`, `_start_memory_extraction`, and
  `get_knowledge_base` for compatibility.
- `TaskOrchestrator` now lives in `web.task_orchestrator`; the old
  `web.app.TaskOrchestrator` compatibility export has been removed.
- `TaskOrchestrator` runtime proxies now live in
  `web.task_orchestrator_runtime`; the orchestrator module is reserved for
  orchestration behavior instead of `web.app` runtime lookups.
- File generation execution now lives in `web.task_orchestrator_filegen`;
  `TaskOrchestrator._execute_file_gen` remains a compatibility wrapper that
  injects the PPT multi-step runner.
- Painter, research, coder, and system subtask execution now live in
  `web.task_orchestrator_steps`; the orchestrator class keeps only thin
  compatibility wrappers for those task types.
- PPT multi-step planning, quality gate, and file rendering now live in
  `web.task_orchestrator_ppt`; the orchestrator class keeps only the
  compatibility wrapper used by file generation.
- Web-search subtask execution now lives in `web.task_orchestrator_search`;
  the orchestrator class no longer imports `WebSearcher` directly.
- Compound-task quality scoring now lives in `web.task_orchestrator_quality`;
  the orchestrator class no longer imports the Gemini client/runtime proxy.
- The removed `/api/files/open` native-open endpoint remains a deliberate 404
  compatibility boundary and is named `removed_native_open_file`; the old
  `retired_open_file` name is guarded against.
- `docs/LEGACY_CODE_PATH_AUDIT.md` records the remaining compatibility paths
  and separates real old-code candidates from normal fallback behavior.
- External file-task planner adapters have been removed; native file-task
  planning is the only path.
- Legacy microphone voice modules and routes have been removed.
- `koto.spec` no longer packages old microphone voice modules or dependencies.
- Pytest temp directories are isolated per process under `.pytest_tmp/run-<pid>`.

## Migration Order

1. Move the remaining editor/PPT/chat route handlers out of `web/app.py` into
   dedicated blueprints while leaving thin compatibility imports if needed.
2. Move shared globals such as client access, model map, workspace path, and
   settings access into a small runtime context module.
3. Continue shrinking voice-adjacent UI/docs to the supported upload-based STT
   route and remove old documentation for microphone/Vosk flows.
4. Migrate old workflow skills from `app.core.workflow_engine` to the LangGraph
   runtime family by family, keeping the old engine as a compatibility layer
   until no production caller remains.
5. Only after those checks pass, archive or delete backup/deprecated files.

## Operating Rules

- Prefer blueprints and service modules over adding more code to `web/app.py`.
- Do not re-add deleted shims or backup modules to packaging hidden imports.
- Run tests serially unless `pytest.ini` stops sharing a fixed
  `--basetemp=.pytest_tmp`.
- Any future architecture cleanup should include at least one focused guard or
  regression test before removing compatibility paths.
