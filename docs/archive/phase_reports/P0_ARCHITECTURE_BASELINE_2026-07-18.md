# P0 Architecture Baseline — 2026-07-18

## Result

P0 establishes the current checkout as a ratcheting architecture baseline. It
does not claim that the debt is acceptable; it makes growth, missing ownership
and indefinite compatibility retention fail the release gate.

## Measured debt

| Metric | P0 baseline | Required target |
| --- | ---: | ---: |
| Inline script tags in `index.html` | 11 | P3: 2 |
| Inline event handlers | 406 | P3: 0 |
| Inline handlers calling `WA` | 174 | P3: 0 |
| Unique inline `WA` methods | 99 | P3: 0 |
| Frontend global assignments | 508 | Must not increase; eliminate business globals in P3 |
| `window.state` writes | 1 | P2: 0 |
| `publishWorkspaceApi` calls | 26 | P3: 0 |
| Frontend source files over 1000 lines | 11 | P5: 0 |
| Production files at least 1500 lines | 33 / 84,985 lines | Must decrease |
| Production files at least 2000 lines | 18 / 59,838 lines | P5: 0 files |

Largest current cleanup targets include:

- `web/static/css/workspace.css`: 10,620 lines
- `web/static/css/style.css`: 5,993 lines
- `app/core/agent/task_tools.py`: 4,346 lines
- `web/tiptap-editor/koto-docx-editor.js`: 3,693 lines
- `app/core/agent/file_task_runtime.py`: 3,474 lines
- `web/tiptap-editor/docx-extensions.js`: 3,318 lines
- `app/core/file/parsers/docx_rich_renderer.py`: 3,274 lines
- `web/templates/index.html`: 2,653 lines
- `web/blueprints/workspace_assistant.py`: 2,591 lines
- `web/src/editors/pdf-viewer.ts`: 2,322 lines

## Ownership and retirement truth

- 12 critical user-facing capabilities now have explicit frontend owners,
  backend owners, entry points, tests and behavioral acceptance criteria.
- Startup, model settings, DOCX review and all current PDF capabilities are
  explicitly `beta`; they cannot be represented as fully accepted features
  until their later phase gates pass.
- Seven compatibility debts have deletion conditions and deadlines: one in P2,
  three in P3 and three in P5.
- The earliest deadline is 2026-08-31 for `window.state`; an overdue entry fails
  CI rather than silently rolling forward.

## Automated gates

- `scripts/audit_code_baseline.py` measures the runtime debt and validates the
  two governance manifests.
- `tests/unit/test_audit_code_baseline.py` prevents metrics and configured
  ceilings from exceeding the P0 baseline.
- `scripts/run_release_gate.ps1` now runs the architecture governance tests as
  part of release source regressions.

## Verification

```text
143 related architecture/release/frontend contract tests passed
Python compile check passed
git diff --check passed for all P0 files
architecture over-budget metrics: 0
compatibility validation errors: 0
feature ownership validation errors: 0
```

## P0 exit decision

P0 is complete. P1 may start only with the startup capability contract and the
installed/portable local-model failure matrix defined in `desktop.startup` and
`settings.model-runtime`.
