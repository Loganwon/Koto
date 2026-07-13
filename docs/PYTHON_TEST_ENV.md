# Koto test environment

Use the repository virtual environment. Do not rely on a system Python or an
Anaconda installation: tests, the local server, and packaging must use the
same `.venv` runtime.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r config\requirements.txt
npm ci --prefix web
npm ci --prefix web/univer-editor
```

Install browser support only when a lane requires it:

```powershell
.\.venv\Scripts\pip install pytest-playwright playwright
.\.venv\Scripts\python.exe -m playwright install chromium
```

## Daily checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/unit
npm --prefix web run typecheck
.\.venv\Scripts\python.exe scripts\run_ai_assistant_flow_tests.py smoke -q
```

For AI assistant lane definitions and prerequisites, use
[ai-assistant-testing.md](ai-assistant-testing.md). `smoke` is a positional
lane name; do not write `--lane smoke`.

## Before a release

Follow [RELEASE_GATE.md](RELEASE_GATE.md). It defines the required frontend,
Python, AI-flow, packaging, and installer checks.
