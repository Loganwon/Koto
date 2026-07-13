# Koto architecture debt report

Baseline captured: 2026-07-12. This replaces the deleted root-level report;
the canonical location is `docs/KOTO_CODE_DEBT_REPORT.md`.

## Active debt register

| Priority | Owner and current size | Risk | Next controlled step |
| --- | --- | --- | --- |
| P0 | `app/core/agent/task_tools.py` — 4,806 lines | Tool changes have broad format impact. | Continue format-specific extraction behind stable tool contracts. |
| P0 | `app/core/agent/file_task_runtime.py` — 3,189 lines | Routing, execution, progress, and artifacts can regress together. | Keep phase helpers authoritative; add behavior tests before moving another branch. |
| P1 | `web/src/workspace/task-runner.ts` — 2,475 lines | Task rendering and interaction state remain concentrated. | Split only along rendered-flow seams with browser/contract coverage. |
| P1 | `web/app.py` — 1,894 lines | Compatibility and service assembly can hide cross-layer coupling. | Move stable factory/service seams without adding routes here. |
| P2 | `web/src/workspace/fs-tree.ts` — 1,196 lines | File tree touches selection, drag/drop, menus, and opening. | Keep one event owner and retain browser interaction coverage. |
| Watch | `app/core/file/parsers/docx_parser.py` — 657 lines | Smaller than the former monolith, but formatting regressions are costly. | Keep paragraph/table/style behavior behind focused parser tests. |

Line counts are a prioritization signal, not a release verdict. Recalculate them
when an extraction lands; do not copy historical counts from prior reports.

## Resolved ownership decisions

- The unified frontend source is `web/src/`; `workspace-bundle.js` is its build
  output. Removed `web/src/app/ (已迁移至模块化主应用)` and `workspace-assistant.js` are not
  compatibility targets.
- HTTP routes belong to `web/blueprints/*`; domain behavior belongs in
  `app/core/*`; `web/app.py` remains application assembly/compatibility only.
- Public skill reads use `SkillManager` public methods, not private registries.

## Quality gates for debt work

1. Add or update a focused regression test before changing an ownership line.
2. Run the relevant Python tests, `npm --prefix web run typecheck`, and
   `git diff --check` for the touched scope.
3. For task-flow changes, follow [ai-assistant-testing.md](ai-assistant-testing.md).
4. For packaging-impacting changes, complete [RELEASE_GATE.md](RELEASE_GATE.md).

The staged plan and historical context are in
[ARCHITECTURE_CLEANUP_ROADMAP.md](ARCHITECTURE_CLEANUP_ROADMAP.md).
