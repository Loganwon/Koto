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
- Legacy PPT endpoints now live in `web.blueprints.ppt_legacy`.
- Non-streaming chat and file upload chat now live in `web.blueprints.chat`.
- File-task, editor stream, chart, and skill-list endpoints now live in
  `web.blueprints.editor_ai`; `web.app` only keeps non-route compatibility
  wrappers for old imports.
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
