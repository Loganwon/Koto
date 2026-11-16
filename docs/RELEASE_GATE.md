# Koto release gate

Use this checklist before creating a Windows release. The complete local entry
point is [`scripts/run_release_gate.ps1`](../scripts/run_release_gate.ps1), and
the authoritative builder remains [`Build_Release.ps1`](../Build_Release.ps1).
GitHub release and build workflows apply the same categories of checks.

Before spending time on the complete gate, collect every cheap prerequisite in
one report:

```powershell
scripts\check_release_readiness.ps1 `
  -JsonOutput logs\release_readiness.json `
  -MarkdownOutput logs\release_readiness.md
```

`block` items prevent a formal candidate, while `advisory` items are useful
hardening evidence but do not replace CI. The check never commits, deletes, or
rewrites source files. The complete gate invokes the same checker with
`-RequireFormal`, so all missing prerequisites are reported together before
frontend builds and test suites begin.

The readiness check also writes `logs/source_snapshot_plan.md` and its JSON
equivalent. Every pending path is assigned to an ownership-oriented review
batch. Unclassified paths, sensitive/runtime file extensions, secret-like
names, and large untracked files block the formal gate until a narrow policy or
an intentional source owner is recorded.

For a formal local candidate, import the public-CA code-signing certificate
into the current user's Personal certificate store, expose only its
thumbprint, and run the one-command gate from a clean commit:

```powershell
$env:KOTO_CODE_SIGNING_THUMBPRINT = "YOUR_CERTIFICATE_THUMBPRINT"
scripts\run_release_gate.ps1
```

It runs source regressions, the AI release lane, the canonical build, exact
candidate verification, installer E2E, portable E2E, Authenticode verification,
and a final hash check. It prints a release-ready conclusion only when every
stage succeeds.

## 1. Prepare one version before creating the tag

Koto uses a strict `MAJOR.MINOR.PATCH` release version. Before tagging, update
all five source metadata surfaces together: `VERSION`,
`launcher/__init__.py`, `web/package.json`, `web/package-lock.json`, and the
matching `CHANGELOG.md` section. Then run:

```powershell
.\.venv\Scripts\python.exe scripts\validate_release_version.py `
  --expected-version (Get-Content VERSION -Raw).Trim()
```

Only create `vMAJOR.MINOR.PATCH` after this validation and commit have landed.
The release workflow rejects a tag or manual version that differs from source
metadata. It never edits or pushes `VERSION` after publication.

## 2. Clean and identify the intended change

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
clean formal build fails if that state drifts. Incremental, skipped-Cython,
skipped-PyInstaller, prebuilt-frontend, missing-installer, and dirty-worktree
paths are recorded as diagnostic reasons and cannot become release-eligible.

## 3. Validate source and frontend

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/unit/test_release_packaging_guards.py tests/unit/test_architecture_guardrails.py
npm ci --prefix web
npm --prefix web run typecheck
npm --prefix web run build
npm ci --prefix web/univer-editor
npm --prefix web/univer-editor run build
```

## 4. Validate AI task flows

```powershell
.\.venv\Scripts\python.exe scripts\run_ai_assistant_flow_tests.py release -q --tb=short
```

`browser-mock` within that lane is a preflight only. For a user-visible file
task change, also run a live local smoke: open `/`, submit the real task from
the UI, observe progress, and verify the produced artifact.

## 5. Package and verify

A formal Windows candidate requires a currently valid code-signing certificate
with an accessible private key and Code Signing EKU. The build resolves the
x64 Windows SDK SignTool, signs with SHA-256, applies an RFC 3161 SHA-256
timestamp, and verifies the expected signer on `Koto.exe`,
`LocalModelInstaller.exe`, Setup, and the generated uninstaller. ZIP integrity
continues to be covered by the release manifest and `SHA256SUMS`.

```powershell
$env:KOTO_CODE_SIGNING_THUMBPRINT = "YOUR_CERTIFICATE_THUMBPRINT"
.\Build_Release.ps1
```

GitHub formal releases import the certificate only immediately before the
Windows build from the protected `KOTO_CODE_SIGNING_PFX_BASE64` and
`KOTO_CODE_SIGNING_PFX_PASSWORD` secrets, delete the temporary PFX, and remove
the imported certificate as soon as signing finishes. Missing secrets block
the release instead of emitting an unsigned public artifact.

The script builds the frontend, PyInstaller application, portable package,
release manifest, and installer. It also downloads Microsoft's x64 Evergreen
WebView2 standalone installer, accepts it only with a valid Microsoft
Authenticode signature, and carries it in both Windows artifacts. This lets a
clean Windows 10/11 x64 account start without Python, Node.js, a VC++
redistributable install, or a preinstalled WebView2 Runtime. After writing the
manifest, it verifies the exact versioned artifact set, source version,
timezone-aware build timestamp, sizes, manifest hashes, SHA256SUMS hashes,
full Git provenance, and `release_eligible` state. Diagnostic
builds finish with a yellow "不得发布" result instead of a green release result.

To re-check copied or downloaded artifacts without rebuilding:

```powershell
.\.venv\Scripts\python.exe scripts\verify_release_candidate.py `
  --version (Get-Content VERSION -Raw).Trim() `
  --dist-dir dist `
  --source-root .
```

Run the installer and portable E2E checks against the generated artifacts when
they are not already supplied by CI:

```powershell
tests\installer\test_installer_e2e.ps1
tests\installer\test_portable_e2e.ps1
```

Both tests launch the real desktop path, require the WebView window shown
callback, and remove Python/Node/Java/virtual-environment paths from the child
process. A backend-only health check is not sufficient release evidence.

For a genuinely clean Windows image, run the generated Windows Sandbox test on
Windows Pro/Enterprise with the optional Sandbox feature enabled:

```powershell
tests\installer\New-KotoReleaseSandbox.ps1 `
  -SetupExe dist\Koto_v1.0.0_Setup.exe `
  -Launch
```

The Sandbox maps the release and test scripts read-only, launches the same real
installer E2E, performs an in-place upgrade over a deliberately stale
`_internal` marker, refuses an upgrade while Koto is running, preserves a
user-data sentinel, and writes a transcript, JSON result, and desktop
screenshot to `dist/windows-sandbox-results`. The
restricted-PATH local E2E is useful compatibility evidence, but it is not a
substitute for OS-level isolation when Windows Sandbox is unavailable.

If the build stops partway through, inspect `logs/` and run the candidate
verifier before retrying. Do not publish an artifact produced with
`-Incremental`, `-SkipBuild`, `-SkipCython`, `-AllowPrebuiltFrontend`,
`-AllowNoInstaller`, or `-AllowDirtyWorktree`. These paths are diagnostic-only
and are recorded in the manifest even when the exception is intentional.
`-AllowUnsigned` is also diagnostic-only; it exists so ordinary CI and local
compatibility checks can exercise packaging without access to the release key.
