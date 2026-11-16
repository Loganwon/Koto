# P2 editor-session completion — 2026-07-19

## Outcome

P2 is complete. Workspace editors no longer read or capture `window.state`.
The mutable workspace store remains owned by the workspace runtime and is
exposed to editors only through one explicitly constructed `EditorSession`.

The P2 architecture target is locked at `window_state_writes = 0`, and the
`frontend.window-state` compatibility-debt entry has been deleted because its
retirement condition is satisfied.

## Root cause removed

- Lazy editor bundles captured `window.state` during module evaluation.
- PDF actions, XLSX selection synchronization and editor-selection
  preservation read the ambient global directly.
- The frontend observer depended on the same mutable object, so deleting only
  the write would have silently broken diagnostics and editor automation.
- Editor construction had no common dependency or lifecycle boundary.

## Implemented contract

- `web/src/editors/editor-session.ts` is the sole editor-facing state boundary.
  It supplies live snapshots, the active editor, pinned selection, loading
  updates and editor mounting without publishing the store globally.
- DOCX, XLSX, PPTX, PDF, image and text editors are mounted through the same
  explicit session in `web/src/workspace/file-open.ts`.
- PDF session lookup and download behavior live in small dedicated modules;
  the PDF bundle no longer captures workspace state when it loads.
- The frontend observer consumes a read-only runtime inspection result instead
  of the mutable store.
- Selection preservation resolves the active editor through `EditorSession`
  instead of workspace infrastructure reaching into a browser global.
- P3 compatibility boundaries (`window.WA` and lazy global editor modules) are
  unchanged and remain separately tracked; P2 did not disguise them as solved.

## Governance evidence

| Gate | Result |
|---|---:|
| Production `window.state` reads/writes | 0 |
| `window_state_writes` budget | 0 / 0 |
| P2 compatibility-debt entries | 0 |
| Remaining compatibility debt | P3: 3, P5: 3 |
| Frontend global assignments | 508 (unchanged) |
| `publishWorkspaceApi` calls | 26 (unchanged) |

## Acceptance evidence

| Lane | Result |
|---|---|
| Frontend typecheck | passed |
| Frontend production build | 17 bundles passed; all bundle budgets met |
| Frontend unit tests | 49 files / 196 tests passed |
| P2 governance, editor and workspace contract regression | 200 passed |
| Broad `web_*` / `workspace_*` Python regression | 1,628 passed |
| Architecture manifest validation | passed; no P2 debt remains |

The P2 exit condition is enforced by both TypeScript behavior tests and Python
source-contract tests, so reintroducing an ambient `window.state` dependency or
raising its zero budget fails the automated gates.

## Cross-phase gate note

The all-phase ratchet currently also reports line-count overages in the P5
large-file metrics while separate PDF/PPTX changes are entering the shared
worktree. They do not affect the P2 zero-state target. Their budgets were not
raised or waived here; they remain cleanup work for the large-file phase.
