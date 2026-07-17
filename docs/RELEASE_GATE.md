# Koto release gate

Use this checklist before creating a Windows release. The authoritative build
script is [`Build_Release.ps1`](../Build_Release.ps1); GitHub release and build
workflows apply the same categories of checks.

## 1. Clean and identify the intended change

```powershell
git status --short --branch --untracked-files=all
git diff --check
```

Do not treat a clean scoped diff as proof that an already-dirty worktree is
release-ready.

`Build_Release.ps1` refuses a dirty worktree by default. Its
`-AllowDirtyWorktree` switch exists only for local diagnostics; never publish
an artifact built with that override. The manifest records the build-start
revision, whether it started dirty, and whether the worktree changed while the
build was running. The drift check fingerprints tracked diff content and every
untracked file, so repeated edits to an already-modified file are detected. A
clean formal build fails if that state drifts.

## 2. Validate source and frontend

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/unit/test_release_packaging_guards.py tests/unit/test_architecture_guardrails.py
npm ci --prefix web
npm --prefix web run typecheck
npm --prefix web run build
npm ci --prefix web/univer-editor
npm --prefix web/univer-editor run build
```

## 3. Validate AI task flows

```powershell
.\.venv\Scripts\python.exe scripts\run_ai_assistant_flow_tests.py release -q --tb=short
```

`browser-mock` within that lane is a preflight only. For a user-visible file
task change, also run a live local smoke: open `/`, submit the real task from
the UI, observe progress, and verify the produced artifact.

## 4. Package and verify

```powershell
.\Build_Release.ps1
```

The script builds the frontend, PyInstaller application, portable package,
release manifest, and installer. Run the installer and portable E2E checks
against the generated artifacts when they are not already supplied by CI:

```powershell
tests\installer\test_installer_e2e.ps1
tests\installer\test_portable_e2e.ps1
```

If the build stops partway through, inspect `logs/` and verify ZIP, manifest,
and installer outputs individually before retrying. Do not release with
`-AllowPrebuiltFrontend`, `-AllowNoInstaller`, or `-AllowDirtyWorktree` unless
the release decision explicitly permits that exception. A dirty-worktree
artifact remains diagnostic-only even when the switch is approved.
