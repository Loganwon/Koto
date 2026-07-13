# Source adoption manifest

## Purpose

This manifest records the untracked Python modules required by the current
tracked runtime, together with their owning boundary, tracked importers, and
the regression coverage that exercises the boundary.  It is intentionally an
adoption-only record: no source behaviour is changed by this change.

The importer list was derived from static imports in tracked Python files.  A
module listed as a compatibility re-export remains part of the supported
import surface even where its consumers are external or legacy callers.

## Adopted runtime modules

| Module | Owner | Tracked importer(s) | Test location |
| --- | --- | --- | --- |
| `app/api/response_routes.py` | API response routes | `web/app_blueprints.py` | `tests/unit/test_startup_risk_cleanup.py` |
| `app/core/agent/file_task_context_read.py` | File-task runtime | `app/core/agent/file_task_runtime.py` | `tests/unit/test_file_task_runtime_stepwise_architecture.py` |
| `app/core/agent/file_task_execution_loop.py` | File-task runtime | `app/core/agent/file_task_runtime.py` | `tests/unit/test_file_task_runtime_stepwise_architecture.py` |
| `app/core/agent/file_task_finalization.py` | File-task runtime | `app/core/agent/file_task_runtime.py` | `tests/unit/test_file_task_runtime_stepwise_architecture.py` |
| `app/core/agent/file_task_plan_presentation.py` | File-task runtime | `app/core/agent/file_task_runtime.py` | `tests/unit/test_file_task_runtime_stepwise_architecture.py` |
| `app/core/agent/file_task_planning.py` | File-task runtime | `app/core/agent/file_task_runtime.py` | `tests/unit/test_file_task_runtime_stepwise_architecture.py` |
| `app/core/agent/pipeline_hooks.py` | Document agent pipeline | `app/core/agent/doc_websocket_agent_executor.py` | `tests/test_agent_loop.py` |
| `app/core/agent/response_formatter.py` | Document agent pipeline | `app/core/agent/doc_websocket_agent_executor.py`; `tests/test_agent_loop.py` | `tests/test_agent_loop.py` |
| `app/core/agent/task_tools_conversion.py` | File-task tools | `app/core/agent/task_tools.py` | `tests/unit/test_god_file_refactor_guardrails.py` |
| `app/core/agent/task_tools_docx_template.py` | File-task tools | `app/core/agent/task_tools.py` | `tests/unit/test_god_file_refactor_guardrails.py` |
| `app/core/agent/task_tools_office_create.py` | File-task tools | `app/core/agent/task_tools.py` | `tests/unit/test_god_file_refactor_guardrails.py` |
| `app/core/agent/task_tools_registry.py` | File-task tools | `app/core/agent/task_tools.py` | `tests/unit/test_god_file_refactor_guardrails.py` |
| `app/core/agent/task_tools_xlsx.py` | File-task tools | `app/core/agent/task_tools.py` | `tests/unit/test_god_file_refactor_guardrails.py` |
| `app/core/brain.py` | Brain/runtime | `web/app.py` | `tests/unit/test_brain_runtime_services.py` |
| `app/core/file/parsers/docx_parser_review.py` | DOCX parser | `app/core/file/parsers/docx_parser.py` | `tests/unit/test_god_file_refactor_guardrails.py` |
| `app/core/file/parsers/docx_rich_renderer.py` | DOCX parser | `app/core/file/parsers/docx_parser.py` | `tests/unit/test_god_file_refactor_guardrails.py` |
| `app/core/llm/llm_client_compat.py` | LLM compatibility boundary | `web/app.py` | `tests/unit/test_llm_client_compat.py` |
| `app/core/llm/provider_boundary.py` | LLM boundary | `web/blueprints/settings.py`; `web/runtime_context.py`; chat-stream generation handlers | `tests/unit/test_gemini_archive_boundary.py` |
| `app/core/llm/provider_compat.py` | LLM boundary | `web/app.py`; routing, jobs, services, and chat-stream handlers | `tests/unit/test_gemini_archive_boundary.py` |
| `app/core/routing/local_dispatcher.py` | Runtime routing | `web/app.py` | `tests/unit/test_architecture_guardrails.py` |
| `scripts/write_release_manifest.py` | Release tooling | `Build_Release.ps1` release invocation | `tests/unit/test_release_manifest.py` |
| `src/startup_diagnostics.py` | Desktop startup | `launcher/entry.py`; `src/koto_app.py` | `tests/unit/test_startup_diagnostics.py` |
| `web/app_entrypoint.py` | Web startup | `web/app.py` | `tests/unit/test_startup_import_contract.py` |
| `web/chat_runtime_services.py` | Chat runtime | `web/app.py`; chat/session blueprints; chat-stream handlers | `tests/unit/test_startup_import_contract.py` |
| `web/doc_annotation.py` | Document annotation | `web/services/intent/annotation_classifier.py` | `tests/unit/test_architecture_guardrails.py` |
| `web/llm_client_compat.py` | LLM compatibility re-export | Legacy public import surface | `tests/unit/test_llm_client_compat.py` |
| `web/search_backend.py` | Web search backend | `web/web_searcher.py` | `tests/unit/test_search_backend.py` |
| `web/services/chat_stream/error_messages.py` | Chat-stream generation | `web/services/chat_stream/generate/regular_handler.py` | `tests/unit/test_web_app_runtime.py` |
| `web/services/chat_stream/generate/_provider_helpers.py` | Chat-stream generation | `web/services/chat_stream/generate/regular_handler.py` | `tests/unit/test_web_app_runtime.py` |
| `web/settings_runtime_bootstrap.py` | Settings runtime | `web/app.py` | `tests/unit/test_architecture_guardrails.py` |
| `web/settings_runtime_services.py` | Settings runtime | `web/blueprints/settings.py` | `tests/unit/test_startup_import_contract.py` |

## Adopted direct regression tests

The following untracked tests cover the adopted runtime and release boundaries:

- `tests/unit/test_brain_runtime_services.py`
- `tests/unit/test_gemini_archive_boundary.py`
- `tests/unit/test_god_file_refactor_guardrails.py`
- `tests/unit/test_launcher_entry.py`
- `tests/unit/test_llm_client_compat.py`
- `tests/unit/test_release_manifest.py`
- `tests/unit/test_search_backend.py`
- `tests/unit/test_startup_diagnostics.py`
- `tests/unit/test_startup_import_contract.py`
- `tests/unit/test_startup_risk_cleanup.py`

## Explicit exclusions

This adoption does not include untracked chat histories, workspace uploads,
screenshots, temporary files, generated assets, frontend files, or unrelated
test-only and utility files.  It does not change `.gitignore`.
