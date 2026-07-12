# Koto documentation index

Last verified: 2026-07-12

This is the single entrypoint for current project documentation. Do not use an
unlinked completion report, phase guide, or legacy audit as an implementation
guide.

| Need | Current document | Canonical command or owner |
| --- | --- | --- |
| Install and start Koto | [QUICKSTART.md](QUICKSTART.md) | `start_koto.bat` / `.venv\\Scripts\\python.exe -m web.app` |
| Set up and run tests | [PYTHON_TEST_ENV.md](PYTHON_TEST_ENV.md) | `.venv` Python, `npm --prefix web run typecheck` |
| Test AI assistant flows | [ai-assistant-testing.md](ai-assistant-testing.md) | `python scripts/run_ai_assistant_flow_tests.py smoke` |
| Understand active architecture | [ARCHITECTURE.md](ARCHITECTURE.md) | `web/blueprints`, `web/services`, `app/core`, `web/src` |
| Track architecture debt | [KOTO_CODE_DEBT_REPORT.md](KOTO_CODE_DEBT_REPORT.md) | owner and line-count snapshot |
| Plan cleanup work | [ARCHITECTURE_CLEANUP_ROADMAP.md](ARCHITECTURE_CLEANUP_ROADMAP.md) | staged, test-backed changes |
| Prepare a Windows release | [RELEASE_GATE.md](RELEASE_GATE.md) | `Build_Release.ps1` and release tests |

## Documentation policy

- The root [README](../README.md) and this page are the only general entry
  indexes.
- `docs/QUICKSTART.md`, `docs/PYTHON_TEST_ENV.md`, and
  `docs/RELEASE_GATE.md` are the only current startup, testing, and release
  guides.
- Documents headed **Historical snapshot** record a past state only. They may
  mention removed files, old test counts, or retired routes and must not be
  used to make implementation decisions.
- The current frontend source is `web/src/`; generated bundles are runtime
  outputs, not source-of-truth documentation targets.
