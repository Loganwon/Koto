# PPT, Workflow, And Skill Route Matrix

Date: 2026-06-30

This matrix separates capability declarations from execution owners. Built-in
skills may influence prompt and routing, but deterministic file-producing
workflows should have one executor owner.

## PPT Routes

| Route | Current entry | Execution owner | Status | Next cleanup |
| --- | --- | --- | --- | --- |
| Generic document-generation PPT | `DocGenPlugin.create_presentation` | `app.core.services.doc_gen_service.DocGenService.generate_presentation` | Valid for structured `sections` input shared with DOCX/PDF/XLSX generation. | Keep as DocGen output path; do not route presentation planning here. |
| Agent PPT planning and generation | `PPTPlugin.generate_ppt_outline` / `PPTPlugin.generate_ppt` | `app.core.services.ppt_generation_service` facade via `app.core.services.ppt_generation_legacy_adapter` | Valid; app/core plugin no longer imports web PPT modules directly. | Move concrete planner/generator implementation behind the adapter when PPT smoke tests cover saved file shape. |
| Multi-step task PPT | `web.task_orchestrator_ppt.execute_ppt_multi_step` | `app.core.services.ppt_generation_service` facade plus quality gate | Valid for task-orchestrator file-generation flows; planner/generator calls share the same facade as `PPTPlugin`. | Move concrete planner/generator implementation behind the facade when saved file smoke tests are broad enough. |
| Single-step task PPT fallback | `web.task_orchestrator_filegen.execute_file_gen` | `app.core.services.ppt_generation_service` facade plus quality gate | Valid fallback when multi-step generation is unavailable or falls back; it no longer instantiates `web.ppt_generator` directly. Markdown outline parsing and theme selection now live in the service facade module. | Keep behavior aligned with multi-step path while concrete planner/generator migration continues. |
| Template PPT generation | `web.template_library.TemplateLibrary._generate_pptx_from_template` | `app.core.services.ppt_generation_service` facade | Valid template generator; it now receives normalized generation result metadata from the facade instead of directly instantiating `web.ppt_generator`. | Keep template generation separate from PPTX editor sessions. |
| Existing PPT editing API | `web.ppt_api_routes` and PPTX editor blueprints | `web.ppt_session_manager` plus `app.core.services.ppt_generation_service` render facade | Valid editor route, not the same as planning generation; render now goes through the same generator boundary without changing session ownership. | Keep editor session/save behavior separate until editor save/export smoke tests exist. |
| Legacy advanced PPT pipeline | `web.ppt_pipeline.PPTGenerationPipeline` | `web.ppt_master` + `web.ppt_synthesizer` | Dormant compatibility module; no production caller should import it until a migration owner and smoke test exist. | Keep isolated or retire after proving no saved-file flow depends on it. |
| Built-in PPT prompt skills | `ppt_outline`, `ppt_generator_pro`, `slide_storyteller`, `slide_data_viz` | `app.core.skills.builtin_skills` prompt injection only | Capability declaration, not a renderer. | Map to generation routes only through routing metadata, not direct execution. |

## Workflow Skill To Executor Mapping

The executable mapping owner is `app.core.workflows.skill_mapping`. Its
`WorkflowSkillMapping` rows are exposed through `WORKFLOW_SKILL_MAPPINGS`,
`get_workflow_candidates_for_skill`, `get_workflow_skill_mapping`, and
`list_workflow_skill_mappings`. Reverse lookup is exposed through
`get_skill_ids_for_workflow` and `workflow_has_skill_mapping`, and the workflow
catalog attaches `related_skill_ids` from this mapping. Built-in skills remain
prompt/capability declarations; this mapping only records eligible deterministic
executors.

| Built-in skill id | Executor id | Executor owner | Boundary |
| --- | --- | --- | --- |
| `cross_format_extractor` | `cross_format_extractor` | `app.core.workflows.registry` -> `CrossFormatExtractor` | Skill describes capability; executor owns file parsing/fill behavior. |
| `doc_smart_compare` | `doc_smart_compare` | `app.core.workflows.registry` -> `DocSmartCompare` | Skill describes intent; executor owns diff output. |
| `questionnaire_filler` | `questionnaire_filler` | `app.core.workflows.registry` -> `QuestionnaireFiller` | Skill describes RFP/questionnaire intent; executor owns workbook output. |
| `data_format_cleaner` | `data_format_cleaner` | `app.core.workflows.registry` -> `DataFormatCleaner` | Skill describes spreadsheet cleaning; executor owns code execution and workbook preview. |
| `multi_doc_synthesis` | `multi_file_synthesis_report` | `app.core.workflows.registry` -> `MultiFileSynthesisReport` | Skill is broader prompt affinity; executor owns multi-file DOCX report. |
| `spreadsheet_analyst` / `excel_data_cleaner` | `data_anomaly_report` or `data_format_cleaner` | `app.core.workflows.registry` | Prompt skills must not execute; router should pick a deterministic executor when files/intent require one. |
| `contract_reviewer` / `legal_doc_review` | `contract_clause_matrix`, `contract_diff_markup`, or `doc_ai_review` | `app.core.workflows.registry` | Legal prompts guide language; workflow selection must be explicit by user intent and files. |

## Current Code Ownership

- `app.core.workflows.catalog` owns workflow metadata exposed by
  `/api/workflow/list`, including prompt-only chat workflows.
- `app.core.workflows.registry` owns Python executor lookup.
- `app.core.workflows.skill_mapping` owns skill id to workflow executor
  candidates for duplicate workflow-like built-in skills.
- `web.blueprints.workflow_api` owns upload/download, Flask `Response`, and SSE
  transport.
- `app.core.skills.builtin_skills` owns prompt and capability declarations.
- `app.core.services.ppt_generation_service` is the transitional facade between
  `PPTPlugin`, `web.task_orchestrator_ppt`, `web.task_orchestrator_filegen`,
  `web.template_library`, `web.ppt_api_routes`, and the current
  legacy PPT adapter.
- `app.core.services.ppt_generation_legacy_adapter` is the only module that
  lazy-loads the current `web.ppt_master` / `web.ppt_generator` implementation.
- `app.core.services.ppt_generation_contract` owns pure data-shape helpers:
  slide normalization, fallback outlines, markdown outline parsing, theme
  selection, and renderer result normalization.
- PPT Markdown outline parsing and fallback theme selection are also owned by
  `app.core.services.ppt_generation_contract`, so web task executors no longer
  carry those generation rules inline.
- `web.ppt_pipeline` remains an isolated legacy module; architecture guards keep
  production code from importing it accidentally.
- `DocGenPlugin.create_presentation` and `PPTPlugin.generate_ppt` are both valid
  tool routes today, but they should not grow independent rendering rules.

## Acceptance

- Web workflow API delegates metadata lookup to `app.core.workflows.catalog`.
- Web workflow API delegates executor lookup to `app.core.workflows.registry`.
- Workflow-like built-in skills are covered by `app.core.workflows.skill_mapping`
  and every mapped executor id exists in the registry.
- `PPTPlugin` and task-orchestrator PPT generation paths depend on
  `app.core.services.ppt_generation_service`, not direct `web.ppt_master` or
  `web.ppt_generator` imports.
- Direct `web.ppt_generator` imports are limited to
  `app.core.services.ppt_generation_legacy_adapter`.
- The PPT generation contract module has no `web.ppt_*` imports; only the
  legacy adapter lazy-loads concrete web implementations.
- Production paths do not import dormant `web.ppt_pipeline`.
- Architecture guards prevent `web.blueprints.workflow_api` from growing direct
  per-workflow imports or a duplicate `_WORKFLOW_REGISTRY` again.
- Any future PPT generator consolidation must preserve:
  `DocGenPlugin.create_presentation`, `PPTPlugin.generate_ppt`, task orchestrator
  PPT generation, and PPTX editor save/export smoke paths.
