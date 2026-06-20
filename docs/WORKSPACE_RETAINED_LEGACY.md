# Workspace retained legacy map

Koto has one product entry: `/`, launched through `Koto_Start.vbs` or `Koto_Start.bat`.

Some files still keep the old `workspace_assistant` / `workspace-assistant` names because they are runtime contracts, compatibility fixtures, or migration anchors. They should not be deleted or renamed until their ownership has been moved and the tests below have been updated.

## Active Runtime

| File | Current role | Keep until |
|------|--------------|------------|
| `web/blueprints/workspace_assistant.py` | File workstation BFF. Owns `/api/v1/workspace/*`, open/save/export, temp raw files, versions, PDF operations, and workspace FS operations. | A renamed BFF module exists and all blueprint registrations/tests import the new module. |
| `web/static/css/workspace-assistant.css` | Compatibility stylesheet manifest imported by `index.html`; delegates selector ownership to `workspace.css`. | The app shell and installer tests load the new stylesheet path. |

## Compatibility Contracts

| File | Current role | Keep until |
|------|--------------|------------|
| `web/static/js/workspace-assistant.js` | Retained WA compatibility runtime and public contract reference. It still protects editor adapters, file open/save flows, CSRF fetch behavior, task dispatch contracts, and migration guards while TypeScript modules are being split out. | `web/src/` owns the full file/editor runtime and all contract tests move off the legacy file. |
| `web/templates/workspace_assistant.html` | Standalone compatibility fixture for editor/layout tests. The route `/workspace-assistant` no longer renders it; it redirects to `/`. | Tests no longer need a standalone shell fixture and the last inline WA dependencies have moved into `index.html` or bundled modules. |
| `web/blueprints/pages.py:/workspace-assistant` | Legacy URL alias. Redirects to `/` and preserves query strings. | External callers and old bookmarks no longer need compatibility. |

## Boundary Tests

| Test | What it protects |
|------|------------------|
| `tests/integration/test_workspace_routes.py::TestUnifiedWorkspaceEntry` | `/workspace-assistant` stays a redirect to `/`. |
| `tests/unit/test_workspace_ai_panel_layout_guards.py::test_workspace_has_single_unified_frontend_entry` | Unified frontend entry remains `/`; old page template is not rendered as a product route. |
| `tests/unit/test_workspace_ai_panel_layout_guards.py::test_workspace_retained_legacy_files_are_documented_as_compatibility_contracts` | Retained legacy-named files keep clear ownership notes. |
| `tests/unit/test_workspace_ai_task_flow_guards.py` | AI/task-flow contracts stay wired through the retained WA compatibility surface while migration continues. |

## Cleanup Rule

Do not remove a retained legacy-named file only because the name looks old. Remove or rename it only when:

1. The current runtime owner is named in `web/src/`, `web/templates/index.html`, or a renamed BFF module.
2. The Flask route or bundle no longer imports or serves the legacy file.
3. All tests above are updated to assert the new owner.
4. A Flask test-client check still confirms `/` returns the unified shell and `/api/v1/workspace/asset_health` is healthy.
