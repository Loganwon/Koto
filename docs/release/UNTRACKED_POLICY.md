# Untracked-file policy

This policy applies to the 221-path inventory cutoff in `WORKTREE_INVENTORY.md`. It does not authorize deletion. Files created by parallel work after that cutoff remain outside this frozen batch and require their own classification.

## Classification rules

1. Implementation, compatibility shims, release tools, and regression tests are reviewed and committed; they are never added to a broad ignore rule.
2. Session histories, workspace uploads/images, local databases, and user settings are personal runtime data. They are preserved locally and ignored using narrow directory/file rules.
3. One-off captures and debug stubs remain on disk and are ignored by exact name. An owner must explicitly approve any deletion.
4. A newly discovered file is classified before an ignore rule is broadened. Do not use a catch-all rule that could hide source, fixtures, or release assets.

## `.gitignore` freeze

The freeze adds only these narrow paths:

```gitignore
/app/core/chats/
/app/core/workspace/images/
/app/core/workspace/uploads/
/app/core/workspace/clipboard/history.json
config/auto_execution.db
config/user_settings.json
/collapse_state.png
/expand_state.png
/screenshot_before.png
/debug_error.txt
/frontend_test_err.txt
/safe_test_files.txt
/temp_test_output.txt
/temp_test_result.txt
/test_stderr.txt
/test_stdout.txt
/unit_test_results.txt
/create_test.py
/temp_fix4.py
```

## Post-cutoff runtime state

`app/core/workspace/clipboard/history.json` was created after the original
inventory cutoff. It is a local clipboard-history cache, not source or a
fixture, and is ignored by its exact path above. No other post-cutoff file is
classified by this policy.

## The 49 untracked Python files

### Must commit — 47

These files have direct owning references in changed application, packaging, or test surfaces. For example, the release scripts are referenced by `Build_Release.ps1`; `startup_diagnostics.py` is imported by `src/koto_app.py`; and the LLM/response modules are imported by `web/app.py`, settings, and blueprints.

```text
app/api/response_routes.py
app/core/agent/file_task_context_read.py
app/core/agent/file_task_execution_loop.py
app/core/agent/file_task_finalization.py
app/core/agent/file_task_plan_presentation.py
app/core/agent/file_task_planning.py
app/core/agent/pipeline_hooks.py
app/core/agent/response_formatter.py
app/core/agent/task_tools_conversion.py
app/core/agent/task_tools_docx_template.py
app/core/agent/task_tools_office_create.py
app/core/agent/task_tools_registry.py
app/core/agent/task_tools_xlsx.py
app/core/brain.py
app/core/file/parsers/docx_parser_review.py
app/core/file/parsers/docx_rich_renderer.py
app/core/llm/llm_client_compat.py
app/core/llm/provider_boundary.py
app/core/llm/provider_compat.py
app/core/routing/local_dispatcher.py
scripts/clean_inplace_cython_artifacts.py
scripts/write_release_manifest.py
src/startup_diagnostics.py
tests/unit/test_brain_runtime_services.py
tests/unit/test_cython_safe_file_task_paths.py
tests/unit/test_docx_pagination_stability.py
tests/unit/test_file_task_stream_compaction.py
tests/unit/test_frontend_runtime_symbol_guards.py
tests/unit/test_gemini_archive_boundary.py
tests/unit/test_god_file_refactor_guardrails.py
tests/unit/test_launcher_entry.py
tests/unit/test_llm_client_compat.py
tests/unit/test_release_manifest.py
tests/unit/test_search_backend.py
tests/unit/test_startup_diagnostics.py
tests/unit/test_startup_import_contract.py
tests/unit/test_startup_risk_cleanup.py
tests/unit/test_voice_provider_contract.py
web/app_entrypoint.py
web/chat_runtime_services.py
web/doc_annotation.py
web/llm_client_compat.py
web/search_backend.py
web/services/chat_stream/error_messages.py
web/services/chat_stream/generate/_provider_helpers.py
web/settings_runtime_bootstrap.py
web/settings_runtime_services.py
```

### Pending deletion — 2

| Path | Evidence | Required action |
| --- | --- | --- |
| `create_test.py` | Empty root-level file; no repository reference found | Keep ignored; delete only after owner approval |
| `temp_fix4.py` | Root-level one-off debug/fix script; no repository reference found | Keep ignored; delete only after owner approval |

### Pending human confirmation — 0

All remaining Python files have a clear implementation, packaging, or regression-test role in the current change set. This is an explicit empty category, not permission to delete either pending-deletion candidate.

## Release handoff

Commit the 47 Python files and the three existing release documents with their related tracked changes. Leave the 158 runtime paths and 13 temporary paths on disk; the new ignore rules keep them out of review without destroying any local evidence.
