# P1 startup decoupling completion — 2026-07-19

## Outcome

P1 is complete. Koto desktop and Flask readiness no longer depend on an API
key, Ollama, a local model file, or Ollama/model version compatibility. These
conditions now change an optional capability state and repair guidance only.

## Root causes removed

- Normal desktop startup synchronously entered the first-run provider chooser
  and could perform network key validation before creating the window.
- Desktop startup always scheduled local-router warmup, which could connect to
  Ollama and load model weights even when the user did not request AI work.
- The browser's deferred startup status check invoked real cloud and local
  inference with a 25-second timeout.
- Packaged configuration lookup could be influenced by legacy external key
  locations and did not provide an authoritative isolated path for release
  tests.
- Installer and portable E2E covered one seeded cloud configuration instead of
  failure and upgrade scenarios.

## Implemented contract

- `app/core/llm/runtime_capabilities.py` owns the thread-safe public state
  machine: `available`, `unavailable`, `misconfigured`, `incompatible`, and
  `checking`.
- `/api/startup-health` remains provider-free. `/api/capabilities` is
  configuration-only by default; `?refresh=1` performs lightweight local
  inspection without generation.
- The setup wizard is manual repair UI. A normal blank launch opens Koto and
  shows a non-blocking configuration banner.
- Local model warmup is lazy and requires the explicit
  `KOTO_PREWARM_LOCAL_ROUTER=1` opt-in.
- Frozen builds resolve writable configuration from the executable directory;
  `KOTO_DEEPSEEK_CONFIG_PATH` provides an authoritative isolated override.
- Installer and portable E2E share the same eight-scenario startup matrix.

## Acceptance evidence

| Lane | Result |
|---|---|
| Frontend typecheck | passed |
| Frontend unit tests | 47 files / 188 tests passed |
| Final release/P1 Python regression set | 216 passed |
| Architecture and release source gate | 170 passed |
| Fresh installed desktop window | passed |
| Installed eight-scenario matrix | 8/8 passed |
| In-place upgrade and user-data preservation | passed |
| Installer uninstall cleanup | passed |
| Portable ZIP desktop window | passed |
| Portable ZIP eight-scenario matrix | 8/8 passed |
| Portable temporary-directory cleanup | passed |

The generated v1.0.0 artifacts were diagnostic builds from an intentionally
dirty worktree and are not release-eligible. Their purpose was real packaged
runtime validation; a formal release candidate must still be rebuilt by the
clean-worktree release gate.
