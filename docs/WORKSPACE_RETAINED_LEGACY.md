# Removed Legacy Workspace Frontend

Koto has one product entry: `/`, launched through `Koto_Start.vbs` or
`Koto_Start.bat`.

The old standalone workspace frontend has been removed. Do not restore these
files as compatibility shims:

| Removed path | Replacement owner |
|--------------|-------------------|
| `web/static/js/workspace-assistant.js` | `web/src/` modules bundled into `web/static/js/build/workspace-bundle.js` |
| `web/static/js/workspace-ai-task.js` | `web/src/workspace/task-runner.ts` |
| `web/static/js/workspace-ai-task-refresh.js` | `web/src/workspace/task-refresh.ts` |
| `web/static/js/workspace-ai-transport.js` | `web/src/workspace/transport.ts` |
| `web/static/js/workspace-ai-results.js` | `web/src/workspace/results.ts` |
| `web/static/js/workspace-ai-quick-actions.js` | `web/src/workspace/quick-actions.ts` |
| `web/static/js/workspace-ai-conversation.js` | `web/src/workspace/conversation.ts` |
| `web/static/js/workspace-task-dispatcher.js` | `web/src/workspace/task-dispatcher.ts` |
| `web/static/js/workspace-task-workbench.js` | `web/src/workspace/task-workbench.ts` |
| `web/templates/workspace_assistant.html` | `web/templates/index.html` |

## Still Legacy-Named

`web/blueprints/workspace_assistant.py` remains active runtime code. The module
name is legacy, but the blueprint owns `/api/v1/workspace/*`, open/save/export,
temporary raw files, versions, PDF operations, and workspace filesystem
operations for the unified `/` shell.

`/workspace-assistant` remains only as a URL redirect to `/` so old bookmarks do
not break. It must not render a second page shell.

## Boundary Tests

| Test | What it protects |
|------|------------------|
| `tests/unit/test_ai_task_chain_architecture.py::test_workspace_uses_bundled_ts_assets_without_legacy_static_entrypoints` | Unified workspace scripts load only the built TypeScript bundle. |
| `tests/unit/test_workspace_ai_panel_layout_guards.py::test_workspace_legacy_frontend_entrypoints_are_removed` | Removed legacy frontend files stay removed. |
| `tests/unit/test_workspace_ai_panel_layout_guards.py::test_workspace_has_single_unified_frontend_entry` | `/workspace-assistant` stays a redirect and does not render a standalone shell. |

## Cleanup Rule

New frontend contracts should read `web/src/`, `web/templates/index.html`, and
the built bundle manifest. Tests should not read removed `web/static/js/workspace-*`
entrypoints.
