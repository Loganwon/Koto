# Worktree inventory and freeze

Inventory cutoff: 2026-07-12. This document covers the requested **221-path snapshot** only; files created by parallel work after the cutoff are deliberately not folded into it. No file in the snapshot was deleted or moved.

| Classification | Paths | Release disposition |
| --- | ---: | --- |
| Source and release documentation | 50 | Review and commit with their owning change set |
| Runtime data | 158 | Preserve locally; ignore |
| Temporary artifacts | 13 | Preserve now; ignore; remove only after owner approval |
| **Total** | **221** | **Frozen by this inventory** |

## Source and release documentation — 50

The following 47 Python files are implementation, compatibility, release-tool, or regression-test work. They are not ignored and should be reviewed and committed with their dependent tracked changes.

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

The three untracked documents are also source/release documentation and should be committed:

```text
docs/ENTERPRISE_FEATURES_QUICKSTART.md
docs/KOTO_CODE_DEBT_REPORT.md
docs/PYTHON_TEST_ENV.md
```

## Runtime data — 158

### Conversation history — 150

The 150 JSON files have the session-history shape used by `web/session_manager.py` (`role`, `parts`, `timestamp`, `source`, `schema_version`, and `turn_id`), including user/model turns. The active setting currently points at the root `chats/` directory, so `app/core/chats/` is a retained, misplaced/legacy runtime snapshot rather than a source package. These records may contain user prompts and model responses; they are preserved locally and ignored narrowly by `/app/core/chats/`.

The exact 150 paths are recorded in the manifest below.

### Workspace and configuration state — 8

| Path | Runtime source | Disposition |
| --- | --- | --- |
| `app/core/workspace/images/input_1783753121.jpg` | Image input persisted under the current workspace | Preserve and ignore |
| `app/core/workspace/images/input_1783753326.jpg` | Image input persisted under the current workspace | Preserve and ignore |
| `app/core/workspace/images/input_1783753646.jpg` | Image input persisted under the current workspace | Preserve and ignore |
| `app/core/workspace/images/input_1783753995.jpg` | Image input persisted under the current workspace | Preserve and ignore |
| `app/core/workspace/uploads/sample.txt` | Browser/workspace upload | Preserve and ignore |
| `app/core/workspace/uploads/test.txt` | Browser/workspace upload | Preserve and ignore |
| `config/auto_execution.db` | `web/auto_execution.py` SQLite execution store | Preserve and ignore |
| `config/user_settings.json` | User-specific settings written by settings and setup flows | Preserve and ignore |

## Temporary artifacts — 13

| Path | Likely source | Recommendation |
| --- | --- | --- |
| `collapse_state.png` | Frontend state screenshot | Preserve; remove only with owner approval |
| `expand_state.png` | Frontend state screenshot | Preserve; remove only with owner approval |
| `screenshot_before.png` | Before-change screenshot | Preserve; remove only with owner approval |
| `debug_error.txt` | Local debugging output | Preserve; remove only with owner approval |
| `frontend_test_err.txt` | Frontend test stderr capture | Preserve; remove only with owner approval |
| `safe_test_files.txt` | Local test-file selection capture | Preserve; remove only with owner approval |
| `temp_test_output.txt` | Temporary test stdout capture | Preserve; remove only with owner approval |
| `temp_test_result.txt` | Temporary test result capture | Preserve; remove only with owner approval |
| `test_stderr.txt` | Test stderr capture | Preserve; remove only with owner approval |
| `test_stdout.txt` | Test stdout capture | Preserve; remove only with owner approval |
| `unit_test_results.txt` | Unit-test result capture | Preserve; remove only with owner approval |
| `create_test.py` | Empty root-level ad-hoc debug stub | Preserve; deletion candidate, no deletion performed |
| `temp_fix4.py` | Root-level one-off fix/debug script | Preserve; deletion candidate, no deletion performed |

## The 19 non-chat, non-Python support items

These are the requested logs, screenshots, database/configuration state, and workspace artifacts. The table above identifies their origin and safe handling: eight are runtime data and eleven are temporary captures. The two debug scripts are Python paths and are classified in the policy document rather than double-counted here.

```text
app/core/workspace/images/input_1783753121.jpg
app/core/workspace/images/input_1783753326.jpg
app/core/workspace/images/input_1783753646.jpg
app/core/workspace/images/input_1783753995.jpg
app/core/workspace/uploads/sample.txt
app/core/workspace/uploads/test.txt
config/auto_execution.db
config/user_settings.json
collapse_state.png
debug_error.txt
expand_state.png
frontend_test_err.txt
safe_test_files.txt
screenshot_before.png
temp_test_output.txt
temp_test_result.txt
test_stderr.txt
test_stdout.txt
unit_test_results.txt
```

## Conversation-history manifest — 150

```text
app/core/chats/对话_20260711_1359_1783749562.json
app/core/chats/对话_20260711_1359_1783749564.json
app/core/chats/对话_20260711_1359_1783749567.json
app/core/chats/对话_20260711_1359_1783749568.json
app/core/chats/对话_20260711_1359_1783749569.json
app/core/chats/对话_20260711_1443_1783752193.json
app/core/chats/对话_20260711_1443_1783752195.json
app/core/chats/对话_20260711_1443_1783752198.json
app/core/chats/对话_20260711_1443_1783752199.json
app/core/chats/对话_20260711_1443_1783752201.json
app/core/chats/对话_20260711_1445_1783752309.json
app/core/chats/对话_20260711_1445_1783752311.json
app/core/chats/对话_20260711_1445_1783752314.json
app/core/chats/对话_20260711_1445_1783752316.json
app/core/chats/对话_20260711_1445_1783752318.json
app/core/chats/对话_20260711_1449_1783752571.json
app/core/chats/对话_20260711_1449_1783752574.json
app/core/chats/对话_20260711_1449_1783752577.json
app/core/chats/对话_20260711_1449_1783752579.json
app/core/chats/对话_20260711_1449_1783752582.json
app/core/chats/对话_20260711_1604_1783757089.json
app/core/chats/对话_20260711_1604_1783757091.json
app/core/chats/对话_20260711_1604_1783757094.json
app/core/chats/对话_20260711_1604_1783757096.json
app/core/chats/对话_20260711_1604_1783757098.json
app/core/chats/对话_20260711_1606_1783757219.json
app/core/chats/对话_20260711_1607.json
app/core/chats/对话_20260711_1607_1783757224.json
app/core/chats/对话_20260711_1607_1783757226.json
app/core/chats/对话_20260711_1607_1783757228.json
app/core/chats/对话_202607121154.json
app/core/chats/对话_20260712_0034_1783787691.json
app/core/chats/对话_20260712_0034_1783787693.json
app/core/chats/对话_20260712_0034_1783787696.json
app/core/chats/对话_20260712_0034_1783787697.json
app/core/chats/对话_20260712_0034_1783787699.json
app/core/chats/对话_20260712_0035_1783787721.json
app/core/chats/对话_20260712_0035_1783787723.json
app/core/chats/对话_20260712_0035_1783787726.json
app/core/chats/对话_20260712_0035_1783787727.json
app/core/chats/对话_20260712_0035_1783787729.json
app/core/chats/对话_20260712_0035_1783787758.json
app/core/chats/对话_20260712_0045.json
app/core/chats/对话_20260712_0220.json
app/core/chats/对话_20260712_0220_1783794059.json
app/core/chats/对话_20260712_0223.json
app/core/chats/对话_20260712_0223_1783794210.json
app/core/chats/对话_20260712_0223_1783794211.json
app/core/chats/对话_20260712_0223_1783794212.json
app/core/chats/对话_20260712_0223_1783794215.json
app/core/chats/对话_20260712_0223_1783794216.json
app/core/chats/对话_20260712_0223_1783794218.json
app/core/chats/对话_20260712_0223_1783794235.json
app/core/chats/对话_20260712_0224.json
app/core/chats/对话_20260712_0224_1783794249.json
app/core/chats/对话_20260712_0224_1783794251.json
app/core/chats/对话_20260712_0224_1783794253.json
app/core/chats/对话_20260712_0224_1783794255.json
app/core/chats/对话_20260712_0224_1783794256.json
app/core/chats/对话_20260712_0228_1783794494.json
app/core/chats/对话_20260712_0228_1783794495.json
app/core/chats/对话_20260712_0228_1783794498.json
app/core/chats/对话_20260712_0228_1783794500.json
app/core/chats/对话_20260712_0228_1783794501.json
app/core/chats/对话_20260712_0229_1783794571.json
app/core/chats/对话_20260712_0229_1783794573.json
app/core/chats/对话_20260712_0229_1783794575.json
app/core/chats/对话_20260712_0229_1783794577.json
app/core/chats/对话_20260712_0229_1783794578.json
app/core/chats/对话_20260712_0230_1783794616.json
app/core/chats/对话_20260712_0230_1783794618.json
app/core/chats/对话_20260712_0230_1783794620.json
app/core/chats/对话_20260712_0230_1783794622.json
app/core/chats/对话_20260712_0230_1783794624.json
app/core/chats/对话_20260712_0232_1783794722.json
app/core/chats/对话_20260712_0232_1783794723.json
app/core/chats/对话_20260712_0232_1783794726.json
app/core/chats/对话_20260712_0232_1783794728.json
app/core/chats/对话_20260712_0232_1783794729.json
app/core/chats/对话_20260712_0232_1783794748.json
app/core/chats/对话_20260712_0232_1783794750.json
app/core/chats/对话_20260712_0232_1783794753.json
app/core/chats/对话_20260712_0232_1783794754.json
app/core/chats/对话_20260712_0232_1783794756.json
app/core/chats/对话_20260712_0232_1783794761.json
app/core/chats/对话_20260712_0232_1783794763.json
app/core/chats/对话_20260712_0232_1783794766.json
app/core/chats/对话_20260712_0232_1783794767.json
app/core/chats/对话_20260712_0232_1783794769.json
app/core/chats/对话_20260712_0233_1783794821.json
app/core/chats/对话_20260712_0233_1783794823.json
app/core/chats/对话_20260712_0233_1783794826.json
app/core/chats/对话_20260712_0233_1783794827.json
app/core/chats/对话_20260712_0233_1783794829.json
app/core/chats/对话_20260712_0234_1783794859.json
app/core/chats/对话_20260712_0234_1783794861.json
app/core/chats/对话_20260712_0234_1783794863.json
app/core/chats/对话_20260712_0234_1783794865.json
app/core/chats/对话_20260712_0234_1783794866.json
app/core/chats/对话_20260712_0234_1783794890.json
app/core/chats/对话_20260712_0234_1783794892.json
app/core/chats/对话_20260712_0234_1783794894.json
app/core/chats/对话_20260712_0234_1783794896.json
app/core/chats/对话_20260712_0234_1783794897.json
app/core/chats/对话_20260712_0234_1783794899.json
app/core/chats/对话_20260712_0235.json
app/core/chats/对话_20260712_0235_1783794903.json
app/core/chats/对话_20260712_0235_1783794905.json
app/core/chats/对话_20260712_0235_1783794906.json
app/core/chats/对话_20260712_0235_1783794926.json
app/core/chats/对话_20260712_0235_1783794928.json
app/core/chats/对话_20260712_0235_1783794931.json
app/core/chats/对话_20260712_0235_1783794932.json
app/core/chats/对话_20260712_0235_1783794934.json
app/core/chats/对话_20260712_0236_1783794962.json
app/core/chats/对话_20260712_0236_1783794963.json
app/core/chats/对话_20260712_0236_1783794966.json
app/core/chats/对话_20260712_0236_1783794968.json
app/core/chats/对话_20260712_0236_1783794969.json
app/core/chats/对话_20260712_0242_1783795373.json
app/core/chats/对话_20260712_0242_1783795375.json
app/core/chats/对话_20260712_0242_1783795378.json
app/core/chats/对话_20260712_0242_1783795379.json
app/core/chats/对话_20260712_0243.json
app/core/chats/对话_20260712_1540_1783842022.json
app/core/chats/对话_20260712_1540_1783842024.json
app/core/chats/对话_20260712_1540_1783842027.json
app/core/chats/对话_20260712_1540_1783842028.json
app/core/chats/对话_20260712_1540_1783842030.json
app/core/chats/对话_20260712_1541_1783842089.json
app/core/chats/对话_20260712_1541_1783842091.json
app/core/chats/对话_20260712_1541_1783842094.json
app/core/chats/对话_20260712_1541_1783842095.json
app/core/chats/对话_20260712_1541_1783842097.json
app/core/chats/对话_20260712_1545_1783842347.json
app/core/chats/对话_20260712_1545_1783842348.json
app/core/chats/对话_20260712_1545_1783842351.json
app/core/chats/对话_20260712_1545_1783842353.json
app/core/chats/对话_20260712_1545_1783842355.json
app/core/chats/对话_20260712_1722_1783848148.json
app/core/chats/对话_20260712_1722_1783848150.json
app/core/chats/对话_20260712_1722_1783848154.json
app/core/chats/对话_20260712_1722_1783848156.json
app/core/chats/对话_20260712_1722_1783848158.json
app/core/chats/对话_20260712_1758_1783850323.json
app/core/chats/对话_20260712_1758_1783850325.json
app/core/chats/对话_20260712_1758_1783850329.json
app/core/chats/对话_20260712_1758_1783850331.json
app/core/chats/对话_20260712_1758_1783850332.json
app/core/chats/对话_20260712_1907.json
```
