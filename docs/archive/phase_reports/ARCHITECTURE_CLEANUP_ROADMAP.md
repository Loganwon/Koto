# Koto architecture cleanup roadmap

Last verified: 2026-07-12. This roadmap describes the live source tree, not
the deleted static frontend files from earlier migrations.

## Current state

| Area | Current owner | Status |
| --- | --- | --- |
| HTTP boundaries | `web/blueprints/*` | Active; new routes belong here. |
| Web orchestration | `web/services/*`, `web/file_task_stream.py` | Active; keep request-independent logic out of routes. |
| File task lifecycle | `app/core/agent/file_task_runtime.py` and extracted phase helpers | Active; still a high-coupling target. |
| File tools | `app/core/agent/task_tools.py` and format-specific helpers | Active; still the largest domain module. |
| Workspace frontend | `web/src/workspace/*` | Active source; built by `web/src/bundles/workspace.ts`. |
| Legacy URLs and names | `web/blueprints/workspace_assistant.py` | Compatibility route/module only; no second UI shell. |

## Sequenced work

### 1. Preserve the boundaries already landed

- Keep `web/app.py` focused on app assembly and compatibility.
- Keep route parsing/HTTP mapping in blueprints.
- Keep `web/src/` as the sole frontend source and do not restore removed static
  JavaScript entrypoints.

### 2. Stabilize the largest runtime contracts

- Treat `FileTaskRequest -> plan -> execution -> artifact/result` as a tested
  contract before extracting more from `file_task_runtime.py`.
- Extract `task_tools.py` by format or capability only when callers and
  artifact contracts are covered.
- Prefer narrow, reversible moves over cross-cutting rewrites.

### 3. Finish workspace source ownership

- Keep one owner for each global `WA` bridge and DOM event family.
- Maintain source tests plus browser checks for file selection, drag/drop,
  context menus, and task rendering.
- Regenerate the frontend bundle only through the standard build gate.

### 4. Ratchet release confidence

- Add a focused test for every deleted compatibility path or moved owner.
- Run the AI flow lane appropriate to user-visible task changes.
- Run the packaging gate whenever static assets, startup, or frozen imports
  change.

See [KOTO_CODE_DEBT_REPORT.md](KOTO_CODE_DEBT_REPORT.md) for the current line
count baseline and [RELEASE_GATE.md](RELEASE_GATE.md) for required validation.
