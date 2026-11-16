# Koto Architecture Governance

This document is the executable governance contract for architecture cleanup.
Planning documents describe intent; the files below decide whether architecture
debt is allowed to ship.

## Sources of truth

- `config/feature_ownership.json` maps every critical user-facing capability to
  its frontend owner, backend owner, entry point, tests, release status and
  behavioral acceptance criteria.
- `config/compatibility_debt.json` is the complete retirement ledger for known
  production compatibility boundaries. Every entry has an owner, replacement,
  deletion condition, target phase and calendar deadline.
- `config/architecture_debt_budget.json` records ratcheting numeric budgets. A
  change may reduce a metric but may never increase it.
- `scripts/audit_code_baseline.py --json` produces the current measured state.

## Merge rules

1. New compatibility code requires a ledger entry in the same change.
2. Compatibility entries without an owner, replacement, test or deletion date
   fail the architecture gate.
3. An overdue entry fails the architecture gate. Moving its deadline requires
   an explicit architecture decision, not a drive-by test update.
4. Once callers reach zero, the compatibility implementation and its ledger
   entry are deleted together.
5. Inline event handlers, global browser assignments, `window.WA` usage,
   oversized source files and total large-file debt are ratchets. Updating a
   budget upward is not an acceptable way to make CI green.
6. A feature is `stable` only when its behavioral acceptance criteria are
   exercised against the real runtime and declared in the ownership manifest.
   A missing journey or weakened numeric budget is a release failure.

## Required validation

```powershell
.venv\Scripts\python.exe scripts\audit_code_baseline.py --json
.venv\Scripts\python.exe -m pytest tests\unit\test_audit_code_baseline.py -q
```

The release gate must include the architecture test. Numeric budgets may tighten
over time, but they do not replace this contract.
