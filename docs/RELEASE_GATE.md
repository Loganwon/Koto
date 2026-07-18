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

## 4. Configure Windows code signing

Formal tag releases require an Authenticode code-signing certificate with an
accessible private key. Import it into `Cert:\CurrentUser\My`, then build with
its SHA-1 thumbprint:

```powershell
.\Build_Release.ps1 `
  -RequireCodeSigning `
  -SigningCertificateThumbprint "<40-hex-thumbprint>"
```

The canonical pipeline signs `Koto.exe`, `LocalModelInstaller.exe`, the Inno
Setup executable, and the generated uninstaller with SHA-256 plus an RFC 3161
timestamp. It verifies every signature before producing the release manifest;
the manifest records whether signing was required, the result, signer
thumbprint, and timestamp service. An unsigned local build remains useful for
diagnostics but is not a formal publication candidate.

GitHub tag releases import the certificate from the repository secrets
`WINDOWS_CODE_SIGNING_PFX_BASE64` and `WINDOWS_CODE_SIGNING_PFX_PASSWORD`.
The PFX should be base64-encoded without being committed to the repository.
Tag builds fail before packaging if either secret is absent or invalid. Manual
workflow builds may remain unsigned and are clearly marked as non-publishable.

## 5. Package and verify

```powershell
.\Build_Release.ps1
```

The script builds the frontend, PyInstaller application, portable package,
release manifest, and installer. It also downloads Microsoft's x64 Evergreen
WebView2 standalone installer, accepts it only with a valid Microsoft
Authenticode signature, and carries it in both Windows artifacts. This lets a
clean Windows 10/11 x64 account start without Python, Node.js, a VC++
redistributable install, or a preinstalled WebView2 Runtime.

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
  -SetupExe dist\Koto_Setup_1.0.0.exe `
  -RequireCodeSigning `
  -Launch
```

The Sandbox maps the release and test scripts read-only, launches the same real
installer E2E, performs an in-place upgrade over a deliberately stale
`_internal` marker, refuses an upgrade while Koto is running, preserves a
user-data sentinel, and writes a transcript, JSON result, and desktop
screenshot to `dist/windows-sandbox-results`. The
restricted-PATH local E2E is useful compatibility evidence, but it is not a
substitute for OS-level isolation when Windows Sandbox is unavailable.
`-RequireCodeSigning` is mandatory for formal signed release evidence: the
Sandbox runner passes it through to the installer E2E, which refuses to execute
an unsigned or inconsistently signed payload. Omit it only when diagnosing an
explicitly unsigned local build.

If the build stops partway through, inspect `logs/` and verify ZIP, manifest,
and installer outputs individually before retrying. Do not release with
`-AllowPrebuiltFrontend`, `-AllowNoInstaller`, or `-AllowDirtyWorktree` unless
the release decision explicitly permits that exception. A dirty-worktree
artifact remains diagnostic-only even when the switch is approved.
