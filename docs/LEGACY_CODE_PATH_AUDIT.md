> **Historical snapshot — not current implementation guidance.** Current ownership is documented in [ARCHITECTURE.md](ARCHITECTURE.md).

# Legacy Code Path Audit

Date: 2026-06-28

This audit tracks production code paths that still look old, compatibility-only,
or migrated-but-retained. The goal is to avoid deleting current runtime
contracts by name alone while continuing to shrink the old conversation/file
assistant overlap.

## Changes Completed In This Pass

| Area | Result | Guard |
| --- | --- | --- |
| File task chat stream | Active `web.app` call now uses `stream_file_task_chat_request`; the old `stream_legacy_file_task` compatibility alias has been removed. | `tests/unit/test_architecture_guardrails.py::test_file_task_stream_lives_outside_web_app` |
| Memory API registration | `register_memory_routes(app, get_memory_manager)` moved from the bottom of `web.app` into `web.app_blueprints.register_blueprints_deferred`. | `tests/unit/test_architecture_guardrails.py::test_memory_api_registration_stays_outside_web_app` |
| Memory runtime helpers | `get_memory_manager`, `_start_memory_extraction`, and `get_knowledge_base` now live in `web.memory_runtime`; `web.app` only re-exports the old names. | `tests/unit/test_architecture_guardrails.py::test_memory_runtime_implementation_stays_outside_web_app` |
| Task orchestrator | `TaskOrchestrator` now lives in `web.task_orchestrator`; the old `web.app.TaskOrchestrator` compatibility export has been removed. | `tests/unit/test_architecture_guardrails.py::test_task_orchestrator_implementation_stays_outside_web_app` |
| Task orchestrator runtime | Runtime proxies for client/model/settings/workspace now live in `web.task_orchestrator_runtime`, keeping `web.task_orchestrator` focused on orchestration behavior. | `tests/unit/test_architecture_guardrails.py::test_task_orchestrator_implementation_stays_outside_web_app` |
| Background file-task API | `app.api.task_routes` now calls `web.file_task_stream` directly instead of relaying through `web.runtime_context`. | `tests/unit/test_architecture_guardrails.py::test_background_file_tasks_call_the_file_task_stream_owner_directly` |
| Agent model selection | `app.core.agent.llm_provider_helpers` now uses Core model selection directly rather than reflecting through `web.runtime_context`. | `tests/unit/test_architecture_guardrails.py::test_core_llm_provider_helpers_do_not_reflect_through_web_runtime_context` |
| Agent memory tools | `MemoryToolsPlugin` now resolves the established `web.memory_runtime` owner directly instead of reflecting through `web.runtime_context`. | `tests/unit/test_architecture_guardrails.py::test_memory_tools_plugin_uses_the_memory_runtime_owner_directly` |
| Task file generation | `_execute_file_gen` now delegates to `web.task_orchestrator_filegen.execute_file_gen`, isolating document/PPT/Excel export logic from the orchestrator class. | `tests/unit/test_architecture_guardrails.py::test_task_orchestrator_filegen_lives_outside_orchestrator_class` |
| Task step executors | Painter, research, coder, and system execution now delegate to `web.task_orchestrator_steps`, leaving the orchestrator class focused on sequencing. | `tests/unit/test_architecture_guardrails.py::test_task_orchestrator_step_executors_live_outside_orchestrator_class` |
| Task PPT multi-step execution | PPT planning, quality gate, and rendering now delegate to `web.task_orchestrator_ppt.execute_ppt_multi_step`, keeping heavy PPT execution details out of the orchestrator class. | `tests/unit/test_architecture_guardrails.py::test_task_orchestrator_ppt_multi_step_lives_outside_orchestrator_class` |
| Task Web search execution | `_execute_web_search` now delegates to `web.task_orchestrator_search.execute_web_search`, keeping `WebSearcher` and async search progress details out of the orchestrator class. | `tests/unit/test_architecture_guardrails.py::test_task_orchestrator_web_search_lives_outside_orchestrator_class` |
| Task quality scoring | `_validate_quality` now delegates to `web.task_orchestrator_quality.validate_quality`, isolating Gemini scoring and runtime client access from the orchestrator class. | `tests/unit/test_architecture_guardrails.py::test_task_orchestrator_quality_scoring_lives_outside_orchestrator_class` |
| Removed native file open route | The `/api/files/open` compatibility handler has been deleted; no frontend caller remains. | `tests/unit/test_architecture_guardrails.py::test_removed_file_hub_open_endpoint_has_no_compatibility_route` |
| Retired document annotation alias | Removed non-streaming `/api/document/analyze-annotations`; current callers use the streaming annotation flow or the unified file-task endpoint. | `tests/unit/test_architecture_guardrails.py::test_retired_api_aliases_stay_removed` |
| Retired Skill toggle alias | Removed `/api/skills/<id>/enable`; `/toggle` is the single supported endpoint. | `tests/unit/test_architecture_guardrails.py::test_retired_api_aliases_stay_removed` |
| Frontend orphan assets | Removed two unbundled TS modules, an unrendered template, two unloaded stylesheets, and two unrouted static debug pages. | `tests/unit/test_frontend_button_route_contract.py::test_all_typescript_sources_are_reachable_from_a_bundle_entrypoint` |
| AI panel CSS ownership | Removed duplicate composer/session selectors from `workspace.css`; `workspace-ai-panel.css` is now the only final owner. | `tests/unit/test_workspace_ai_composer_contract.py` |
| Migrated class tests | Unit tests for `WebSearcher`, `ContextAnalyzer`, `Utils`, and `SessionManager` now import their real modules instead of `web.app`, reducing test pressure on old app compatibility exports. | `tests/unit/test_architecture_guardrails.py::test_migrated_app_class_tests_use_real_modules` |
| Migrated helper tests | Unit tests for stream interrupts, SSE sanitization, filename sanitization, proxy normalization, prompt extraction, fake Gemini responses, and interactions-only model checks now target helper modules instead of `web.app`. | `tests/unit/test_architecture_guardrails.py::test_migrated_app_class_tests_use_real_modules` |
| Chat/filegen helpers | Chat system instruction generation and FILE_GEN time parsing/context building now live in `web.chat_system_instruction` and `web.filegen_time_context`, reducing `web.app` to runtime aliases for those helpers. | `tests/unit/test_architecture_guardrails.py::test_migrated_app_class_tests_use_real_modules` |
| Monolith budget | `web/app.py` is down to about 3.5k lines and the guard budget is tightened to 3525. | `tests/unit/test_architecture_guardrails.py::test_web_app_line_budget_does_not_regress` |

## Production Compatibility Paths Still Present

| Path | Current role | Cleanup condition |
| --- | --- | --- |
| `web/blueprints/pages.py:/workspace-assistant` | Redirect-only legacy URL alias to `/`. | Remove after installer/tests/docs and old bookmarks no longer require the alias. |
| `web.memory_runtime` compatibility exports through `web.app` | Runtime implementation has moved out, but old import names still exist on `web.app`. | Remove after chat stream handlers, tests, and external imports target `web.memory_runtime` or `web.runtime_context` directly. |
| `web/app.py` chat wrappers (`chat`, `chat_stream`, `chat_with_file`) | Non-route compatibility wrappers after blueprint migration. | Remove after tests and import callers stop importing these names from `web.app`. |

## Removed Workspace Frontend Paths

The old standalone workspace frontend has now been removed. Do not restore these
files as compatibility shims:

| Removed path | Current owner |
| --- | --- |
| `web/src/workspace/ (已迁移至模块化工作区)` | `web/src/` modules bundled into `web/static/js/build/workspace-bundle.js` |
| `web/static/js/workspace-ai-*.js` | `web/src/workspace/*` TypeScript modules |
| `web/static/js/workspace-task-*.js` | `web/src/workspace/*` TypeScript modules |
| `web/templates/workspace_assistant.html` | `web/templates/index.html` |

Boundary tests should read `web/src/`, `web/templates/index.html`, and the
built bundle references instead of these removed paths.

## Retired Or Suspicious Paths To Re-check

| Path | Observation | Suggested next action |
| --- | --- | --- |
| `app/core/routing/local_model_router.py::to_legacy_tuple` | Structured decision still exposes a legacy tuple view. | Keep while SmartDispatcher or tests consume tuple format; otherwise migrate consumers to the object contract. |
| `app/core/workflow/interactive_planner.py` legacy dataclasses | Old planner compatibility data classes remain. | Confirm production callers before removing; likely tied to workflow UI compatibility. |
| `app/core/agent/task_tools.py` legacy marker text helpers | Structured sandbox results still provide marker-text compatibility. | Keep until every file-task consumer reads structured results. |
| `app/core/skills/skill_schema.py::from_legacy_dict` | Skill schema upgrades legacy dict definitions. | Keep while builtin/custom skills may still be persisted as dicts. |

## Non-issues From Keyword Scans

The scan returned many `fallback` hits that are not old code paths:

- model fallback chains in `app.core.llm` and chat handlers;
- safe write fallback copies in `app.core.agent.task_tools`;
- filesystem search fallback in file hub;
- parser/output compatibility for third-party formats.

These should not be removed as part of legacy cleanup unless a specific
replacement path exists.

## Recommended Next Cleanup Order

1. Replace `web.app` chat wrapper imports in tests with blueprint/runtime module imports.
2. Move remaining `web.app` model/client globals into explicit runtime modules.
3. Move `TaskOrchestrator._merge_results` into a small result assembly service or convert it to a pure function.
4. Revisit the `/workspace` and `/workspace-assistant` redirect aliases after installer and bookmark compatibility no longer matters.
5. Migrate the remaining tuple-based local-router tests before removing `to_legacy_tuple`.
