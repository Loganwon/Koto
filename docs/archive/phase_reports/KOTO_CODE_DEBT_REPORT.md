# Koto architecture debt report

Baseline refreshed: 2026-07-18. This replaces the deleted root-level report;
the canonical location is `docs/KOTO_CODE_DEBT_REPORT.md`.

## Active debt register

| Priority | Owner and current size | Risk | Next controlled step |
| --- | --- | --- | --- |
| P0 | `app/core/agent/task_tools.py` — 4,713 lines | Tool changes have broad format impact. | Continue format-specific extraction behind stable tool contracts. |
| P0 | `app/core/agent/file_task_runtime.py` — 3,460 lines | Routing, execution, progress, and artifacts can regress together. | Keep phase helpers authoritative; add behavior tests before moving another branch. |
| P1 | `web/app.py` — 1,729 lines | Compatibility and service assembly can hide cross-layer coupling. | Move stable factory/service seams without adding routes here. |
| P1 | `web/src/workspace/fs-tree.ts` — 1,413 lines | File tree touches selection, drag/drop, menus, and opening. | Split rendering from interaction ownership while retaining browser coverage. |
| P1 | `web/src/workspace/task-dispatcher.ts` — 950 lines | Route selection, task launch, persistence, and follow-up recovery still meet in one owner. | Extract terminal-turn persistence or follow-up routing behind the existing dispatcher API. |
| P2 | `web/src/workspace/task-workbench.ts` — 573 lines; `task-workbench-projection.ts` — 461 lines | Live-card DOM projection and rendering remain together, while persisted-data normalization is now isolated. | Keep the pure projection DOM-free; split the renderer only if another workbench feature would exceed the current guards. |
| P2 | `app/core/file/parsers/docx_parser.py` — 761 lines | Smaller than the former monolith, but formatting regressions are costly. | Keep paragraph/table/style behavior behind focused parser tests. |

Line counts are a prioritization signal, not a release verdict. Recalculate them
when an extraction lands; do not copy historical counts from prior reports.

## Resolved ownership decisions

- The unified frontend source is `web/src/`; `workspace-bundle.js` is its build
  output. Removed `web/src/app/ (已迁移至模块化主应用)` and `workspace-assistant.js` are not
  compatibility targets.
- HTTP routes belong to `web/blueprints/*`; domain behavior belongs in
  `app/core/*`; `web/app.py` remains application assembly/compatibility only.
- Public skill reads use `SkillManager` public methods, not private registries.
- `web/src/workspace/task-runner.ts` is now a 300-line composition root. Stage,
  result, lifecycle, persistence, recovery, and interaction behavior live in
  focused `task-*` modules and must not be folded back into the runner.
- The secondary task workbench no longer owns persisted-task parsing, status
  normalization, file projection, or internal-progress filtering. Those pure
  rules live in the DOM-free `task-workbench-projection.ts` module.

## Quality gates for debt work

1. Add or update a focused regression test before changing an ownership line.
2. Run the relevant Python tests, `npm --prefix web run typecheck`, and
   `git diff --check` for the touched scope.
3. For task-flow changes, follow [ai-assistant-testing.md](ai-assistant-testing.md).
4. For packaging-impacting changes, complete [RELEASE_GATE.md](RELEASE_GATE.md).

The staged plan and historical context are in
[ARCHITECTURE_CLEANUP_ROADMAP.md](ARCHITECTURE_CLEANUP_ROADMAP.md).
